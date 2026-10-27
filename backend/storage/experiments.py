"""Transactional local comparisons bound to live reviewed-dataset eligibility."""
import json
import hashlib
import time
import tracemalloc
from pathlib import Path

from backend.adapters.hardware import profile_hardware
from backend.domain.errors import ResearchError
from backend.domain.experiments import Prediction
from backend.evaluation.experiments import compare
from backend.evaluation import contact_ranker, experiments as comparison_module
from backend.storage.learning import LearningRepository
from backend.storage.repository import now, request_hash, uid

MAX_EXPERIMENTS = 200
MAX_RECEIPTS = 2000


class ExperimentRepository:
    def __init__(self, repository):
        self.repository = repository
        self.learning = LearningRepository(repository)

    def _dataset(self, db, dataset_id):
        row = db.execute('SELECT * FROM learning_version WHERE id=?', (dataset_id,)).fetchone()
        if row is None:
            raise ResearchError('Dataset version not found.', status=404)
        dataset = dict(row)
        self.learning._sync_version(db, dataset, self.learning._protected(db))
        return dataset

    @staticmethod
    def _view(row):
        item = dict(row)
        body = item.pop('report_json')
        item['report'] = json.loads(body) if body is not None else None
        return item

    def _get(self, db, experiment_id):
        row = db.execute('SELECT * FROM evaluation_experiment WHERE id=?', (experiment_id,)).fetchone()
        if row is None:
            raise ResearchError('Evaluation report not found.', status=404)
        self._dataset(db, row['dataset_id'])
        return self._view(db.execute('SELECT * FROM evaluation_experiment WHERE id=?', (experiment_id,)).fetchone())

    def _receipt(self, db, key, digest):
        receipt = db.execute('SELECT * FROM evaluation_request WHERE idempotency_key=?', (key,)).fetchone()
        if receipt:
            if receipt['request_hash'] != digest:
                raise ResearchError('This evaluation request key has different inputs.', status=409)
            if receipt['experiment_id'] is None:
                raise ResearchError('This evaluation report or its dataset was deleted.', status=410)
        return receipt

    def _examples(self, db, dataset, dataset_sha256):
        if dataset['purpose'] != 'evaluation':
            raise ResearchError('Choose an evaluation-purpose dataset; training datasets are not test sets.', status=409)
        if dataset['dataset_sha256'] != dataset_sha256:
            raise ResearchError('The frozen dataset hash does not match.', status=409)
        members = db.execute('SELECT payload_json FROM learning_member WHERE version_id=? ORDER BY example_id', (dataset['id'],)).fetchall()
        examples = [json.loads(row[0]) for row in members]
        if request_hash(examples) != dataset_sha256:
            raise ResearchError('Dataset content hash does not match its frozen manifest.', status=409)
        if db.execute('SELECT COUNT(*) FROM evaluation_experiment').fetchone()[0] >= MAX_EXPERIMENTS:
            raise ResearchError('Evaluation report limit reached (200). Delete unused reports.', status=429)
        if db.execute('SELECT COUNT(*) FROM evaluation_request').fetchone()[0] >= MAX_RECEIPTS:
            raise ResearchError('Lifetime evaluation request limit reached (2000).', status=429)
        return examples

    def _store(self, db, dataset, examples, predictions, key, digest, candidate_name, artifact_sha256, configuration, candidate=None):
        start = time.perf_counter()
        report = compare(examples, predictions, executed=candidate is not None)
        report.update(comparison_ms=(time.perf_counter() - start) * 1000,
                      schema_version=1, mode=dataset['mode'], split=dataset['split'],
                      evaluator_sha256=hashlib.sha256(Path(comparison_module.__file__).read_bytes()).hexdigest(),
                      hardware=profile_hardware(self.repository.path.parent), model_hash=None, configuration=configuration,
                      candidate_inference_ms=None, candidate_peak_memory_bytes=None, candidate_provenance='imported_unverified',
                      training_executed=False, prior_retained_dataset_reports=db.execute(
                          'SELECT COUNT(*) FROM evaluation_experiment WHERE dataset_id=?', (dataset['id'],)).fetchone()[0])
        if candidate:
            report.update(candidate)
        rows = sorted(({'example_id': p.example_id, 'output': p.output} for p in predictions), key=lambda item: item['example_id'])
        experiment_id = uid()
        db.execute('INSERT INTO evaluation_experiment VALUES(?,?,?,?,?,?,?,?,?)',
                   (experiment_id, dataset['id'], dataset['dataset_sha256'], candidate_name,
                    artifact_sha256, request_hash(rows), now(), 'ready', json.dumps(report)))
        db.execute('INSERT INTO evaluation_request VALUES(?,?,?)', (key, digest, experiment_id))
        return self._get(db, experiment_id)

    def create(self, payload, key):
        # Canonicalise prediction order: network retries must not depend on JSON array order.
        inputs = payload.model_dump()
        inputs['predictions'] = sorted(inputs['predictions'], key=lambda item: item['example_id'])
        digest = request_hash(inputs)
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            receipt = self._receipt(db, key, digest)
            if receipt:
                return self._get(db, receipt['experiment_id'])
            dataset = self._dataset(db, payload.dataset_id)
            # Commit freshness invalidation even when this new comparison is refused.
            invalid = dataset['status'] != 'ready'
            if not invalid:
                examples = self._examples(db, dataset, payload.dataset_sha256)
                if {e['id'] for e in examples} != {p.example_id for p in payload.predictions}:
                    raise ResearchError('Supply exactly one output or null abstention for every frozen example.', status=422)
                configuration = {'method': 'imported_outputs_exact_text_v1', 'normalization': 'none',
                                 'baseline': 'reviewed_observed_output', 'candidate_execution': 'not_executed'}
                result = self._store(db, dataset, examples, payload.predictions, key, digest,
                                     payload.candidate_name, payload.artifact_sha256, configuration)
        if invalid:
            raise ResearchError('Dataset was invalidated. Review current sources and freeze a new version.', status=409)
        return result

    def run_builtin(self, payload, key):
        """Execute the bundled deterministic candidate on frozen inputs, never on labels."""
        digest = request_hash({'operation': 'builtin_candidate', 'input': payload.model_dump()})
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            receipt = self._receipt(db, key, digest)
            if receipt:
                return self._get(db, receipt['experiment_id'])
            dataset = self._dataset(db, payload.dataset_id)
            invalid = dataset['status'] != 'ready'
            if not invalid:
                examples = self._examples(db, dataset, payload.dataset_sha256)
                configuration = contact_ranker.configuration() | {
                    'method': 'builtin_candidate_exact_text_v1', 'normalization': 'none', 'baseline': 'reviewed_observed_output',
                    'candidate_execution': 'executed_locally_builtin', 'abstention_output': payload.abstention_output}
                artifact = hashlib.sha256(Path(contact_ranker.__file__).read_bytes() + json.dumps(
                    configuration, sort_keys=True).encode()).hexdigest()
                # Project frozen examples so the candidate cannot read observed or expected outputs.
                views = [{'id': e['id'], 'task': e['provenance']['task'], 'input_text': e['review']['input_text'],
                          'domain_group': e['provenance']['domain_group']} for e in examples]
                tracemalloc.start()
                start = time.perf_counter()
                try:
                    decisions = [(view['id'], *contact_ranker.predict(view)) for view in views]
                    elapsed = (time.perf_counter() - start) * 1000
                    peak = tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
                predictions = [Prediction(example_id=ident, output=output if output is not None else payload.abstention_output)
                               for ident, output, _ in decisions]
                counts = {}
                for _, _, code in decisions:
                    counts[code] = counts.get(code, 0) + 1
                candidate = {'candidate_inference_ms': elapsed, 'candidate_peak_memory_bytes': peak,
                             'candidate_provenance': 'builtin_executed_locally', 'candidate_artifact_sha256': artifact,
                             'candidate_decisions': dict(sorted(counts.items())),
                             'candidate_memory_method': 'python_tracemalloc_peak_during_inference'}
                result = self._store(db, dataset, examples, predictions, key, digest,
                                     'Built-in contact ranker v1', artifact, configuration, candidate)
        if invalid:
            raise ResearchError('Dataset was invalidated. Review current sources and freeze a new version.', status=409)
        return result

    def get(self, experiment_id):
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            return self._get(db, experiment_id)

    def list(self, mode, offset):
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            query = '''FROM evaluation_experiment e JOIN learning_version v ON v.id=e.dataset_id WHERE v.mode=?'''
            total = db.execute('SELECT COUNT(*) ' + query, (mode,)).fetchone()[0]
            ids = [row[0] for row in db.execute('SELECT e.id ' + query + ' ORDER BY e.created_at DESC,e.id DESC LIMIT 20 OFFSET ?', (mode, offset))]
            items = [self._get(db, experiment_id) for experiment_id in ids]
        return {'items': items, 'total': total, 'offset': offset, 'limit': 20,
                'next_offset': offset + 20 if offset + 20 < total else None}

    def delete(self, experiment_id):
        with self.repository.connect() as db:
            db.execute('DELETE FROM evaluation_experiment WHERE id=?', (experiment_id,))
        return {'deleted': True, 'dataset_preserved': True}
