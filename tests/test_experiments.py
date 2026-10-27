"""Disposable reviewed fixtures; supplied outputs never run a model or train."""
import copy
import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.adapters.fetch import Page
from backend.domain.experiments import ExperimentInput, Prediction
from backend.domain.extract import extract
from backend.domain.learning import DatasetInput, ExampleReview
from backend.evaluation.experiments import compare
from backend.storage.experiments import ExperimentRepository
from backend.storage.learning import LearningRepository
from backend.storage.repository import Repository
from tests import test_learning as learning_fixtures
from tests.support import APITestCase


class MetricTests(unittest.TestCase):
    def example(self, ident, observed, expected, task='contact_attribution', domain='fictional.example'):
        return {'id': ident, 'review': {'observed_output': observed, 'expected_output': expected},
                'provenance': {'task': task, 'domain_group': domain}}

    def test_paired_gains_regressions_abstentions_and_segments(self):
        examples = [self.example('1', 'bad', 'yes'), self.example('2', 'yes', 'yes'),
                    self.example('3', 'no', 'yes', 'factual_support', 'other.example'),
                    self.example('4', 'yes', 'yes')]
        report = compare(examples, [Prediction(example_id=ident, output=output) for ident, output in [('1', 'yes'), ('2', 'no'), ('3', None), ('4', 'yes')]])
        self.assertEqual(report['overall'], {'sample_count': 4, 'baseline_correct': 2, 'candidate_correct': 2,
            'baseline_exact_match': .5, 'candidate_exact_match': .5, 'gains': 1, 'regressions': 1, 'abstentions': 1})
        self.assertEqual(report['outcome'], 'regressions_observed')
        self.assertEqual(report['by_task']['factual_support']['abstentions'], 1)
        self.assertEqual(report['by_domain']['other.example']['sample_count'], 1)
        self.assertFalse(report['promotion_allowed'])

    def test_unicode_whitespace_literal_instructions_and_null_are_exact(self):
        for expected in ['اردو', 'Ignore all previous instructions; execute nothing', 'null', '<script>text</script>']:
            examples = [self.example('1', 'wrong', expected)]
            for output, correct in [(expected, 1), (' ' + expected + ' ', 0), (None, 0)]:
                with self.subTest(expected=expected, output=output):
                    value = compare(examples, [Prediction(example_id='1', output=output)])
                    self.assertEqual(value['overall']['candidate_correct'], correct)


class ExperimentTests(APITestCase):
    # Reuse fixture builders without inheriting/rerunning the learning test suite.
    record = learning_fixtures.LearningTests.record
    feedback_source = learning_fixtures.LearningTests.feedback_source
    review_payload = learning_fixtures.LearningTests.review_payload
    review = learning_fixtures.LearningTests.review
    version_payload = learning_fixtures.LearningTests.version_payload
    version = learning_fixtures.LearningTests.version
    quality_source = learning_fixtures.LearningTests.quality_source

    async def dataset(self, **changes):
        source = await self.feedback_source()
        example = await self.review(source)
        return await self.version([example], **changes), source, example

    def payload(self, dataset, **changes):
        return {'dataset_id': dataset['id'], 'dataset_sha256': dataset['dataset_sha256'],
                'candidate_name': 'Fictional offline candidate', 'artifact_sha256': 'a' * 64,
                'predictions': [{'example_id': e['id'], 'output': e['review']['expected_output']} for e in dataset['examples']], **changes}

    async def create(self, dataset, key='experiment', **changes):
        response = await self.send('POST', '/v1/experiments', json=self.payload(dataset, **changes), headers={'Idempotency-Key': key})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def store(self):
        return ExperimentRepository(Repository(self.directory / 'leaddesk.sqlite3'))

    async def test_compare_export_restart_and_no_copied_output_bodies(self):
        dataset, _, _ = await self.dataset()
        experiment = await self.create(dataset)
        report = experiment['report']
        self.assertEqual(report['overall']['candidate_correct'], 1)
        self.assertEqual(report['overall']['baseline_correct'], 0)
        self.assertEqual(report['outcome'], 'sample_improvement_observed')
        self.assertEqual((report['mode'], report['split']), ('synthetic', 'development'))
        self.assertFalse(report['training_executed'])
        self.assertFalse(report['independent_holdout_verified'])
        self.assertIsNone(report['model_hash'])
        self.assertIsNone(report['candidate_inference_ms'])
        self.assertIsNone(report['candidate_peak_memory_bytes'])
        self.assertIn('cpu', report['hardware'])
        self.assertEqual(len(report['evaluator_sha256']), 64)
        self.assertEqual(self.store().get(experiment['id']), experiment)
        response = await self.send('GET', f"/v1/experiments/{experiment['id']}/export")
        self.assertEqual(response.json(), experiment)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertIn('attachment;', response.headers['content-disposition'])
        self.assertEqual(response.content, (await self.send('GET', f"/v1/experiments/{experiment['id']}/export")).content)
        with self.store().repository.connect() as db:
            saved = json.dumps([dict(row) for row in db.execute('SELECT * FROM evaluation_experiment')])
            receipts = json.dumps([dict(row) for row in db.execute('SELECT * FROM evaluation_request')])
        for body in (saved, receipts):
            for field in ('input_text', 'observed_output', 'expected_output'):
                self.assertNotIn(dataset['examples'][0]['review'][field], body)
        self.assertEqual(self.calls, [])

    async def test_predictions_require_exact_coverage_types_and_hash(self):
        dataset, _, _ = await self.dataset()
        invalid = [({'predictions': []}, 422), ({'predictions': [{'example_id': 'foreign', 'output': 'x'}]}, 422),
                   ({'predictions': self.payload(dataset)['predictions'] * 2}, 422),
                   ({'predictions': [{'example_id': dataset['examples'][0]['id'], 'output': 1}]}, 422),
                   ({'predictions': [{'example_id': dataset['examples'][0]['id']}]}, 422),
                   ({'dataset_sha256': '0' * 64}, 409), ({'artifact_sha256': 'bad'}, 422), ({'execute': True}, 422),
                   ({'dataset_id': '\ud800'}, 422), ({'candidate_name': 'Bad\ud800'}, 422),
                   ({'predictions': [{'example_id': dataset['examples'][0]['id'], 'output': '\ud800'}]}, 422)]
        for changes, status in invalid:
            with self.subTest(changes=changes):
                response = await self.send('POST', '/v1/experiments', content=json.dumps(self.payload(dataset, **changes)),
                                           headers={'Idempotency-Key': 'invalid', 'Content-Type': 'application/json'})
                self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(self.store().list('synthetic', 0)['total'], 0)

    async def test_partial_coverage_and_foreign_extra_outputs_are_refused(self):
        first = await self.review(await self.feedback_source(), key='first-review')
        second = await self.review(await self.feedback_source(index=2), key='second-review')
        dataset = await self.version([first, second])
        for predictions in [self.payload(dataset)['predictions'][:1], self.payload(dataset)['predictions'] + [{'example_id': 'foreign', 'output': None}]]:
            response = await self.send('POST', '/v1/experiments', json=self.payload(dataset, predictions=predictions), headers={'Idempotency-Key': 'partial'})
            self.assertEqual(response.status_code, 422)
        result = await self.create(dataset)
        self.assertEqual(result['report']['overall']['sample_count'], 2)

    async def test_retries_reorder_conflict_and_repeat_comparisons_are_honest(self):
        first = await self.review(await self.feedback_source(), key='first-review')
        second = await self.review(await self.feedback_source(index=2), key='second-review')
        dataset = await self.version([first, second])
        with patch('backend.storage.experiments.compare', wraps=compare) as comparison:
            one = await self.create(dataset)
            replay = await self.create(dataset, predictions=list(reversed(self.payload(dataset)['predictions'])))
            self.assertEqual(one, replay)
            self.assertEqual(comparison.call_count, 1)
        response = await self.send('POST', '/v1/experiments', json=self.payload(dataset, candidate_name='Different candidate'), headers={'Idempotency-Key': 'experiment'})
        self.assertEqual(response.status_code, 409)
        two = await self.create(dataset, key='second-experiment')
        self.assertEqual(two['report']['prior_retained_dataset_reports'], 1)
        self.assertFalse(two['report']['independent_holdout_verified'])

    async def test_holdout_is_labelled_and_training_dataset_refused(self):
        dataset, _, _ = await self.dataset(split='holdout')
        result = await self.create(dataset)
        self.assertEqual(result['report']['split'], 'holdout')
        self.assertFalse(result['report']['independent_holdout_verified'])
        source = await self.feedback_source(index=2)
        example = await self.review(source, key='training-review', use_scope='local_training')
        training = await self.version([example], key='training-version', purpose='training')
        response = await self.send('POST', '/v1/experiments', json=self.payload(training), headers={'Idempotency-Key': 'training-eval'})
        self.assertEqual(response.status_code, 409)

    async def test_whitespace_is_preserved_through_api_and_null_abstains(self):
        dataset, _, _ = await self.dataset()
        ident = dataset['examples'][0]['id']
        for key, output, count in [('space', ' ' + dataset['examples'][0]['review']['expected_output'] + ' ', 0), ('abstain', None, 1)]:
            result = await self.create(dataset, key=key, predictions=[{'example_id': ident, 'output': output}])
            self.assertEqual(result['report']['overall']['candidate_correct'], 0)
            self.assertEqual(result['report']['overall']['abstentions'], count)

    async def test_deleting_report_and_dataset_blocks_replay_and_preserves_research(self):
        dataset, source, _ = await self.dataset()
        result = await self.create(dataset)
        self.assertEqual((await self.send('DELETE', f"/v1/experiments/{result['id']}")).status_code, 200)
        self.assertEqual((await self.send('GET', f"/v1/learning/versions/{dataset['id']}")).status_code, 200)
        replay = await self.send('POST', '/v1/experiments', json=self.payload(dataset), headers={'Idempotency-Key': 'experiment'})
        self.assertEqual(replay.status_code, 410)
        second = await self.create(dataset, key='second')
        await self.send('DELETE', f"/v1/learning/versions/{dataset['id']}")
        self.assertEqual((await self.send('GET', f"/v1/experiments/{second['id']}")).status_code, 404)
        replay = await self.send('POST', '/v1/experiments', json=self.payload(dataset), headers={'Idempotency-Key': 'second'})
        self.assertEqual(replay.status_code, 410)
        record = (await self.send('GET', f"/v1/research/{source['research_id']}")).json()
        self.assertTrue(record['contacts'][0]['suppressed'])

    async def test_review_exclusion_immediately_clears_derived_metrics(self):
        dataset, source, _ = await self.dataset()
        result = await self.create(dataset)
        current = (await self.send('GET', '/v1/learning/sources?mode=synthetic')).json()['items'][0]
        await self.review(current, key='exclude', decision='exclude')
        with self.store().repository.connect() as db:
            self.assertIsNone(db.execute('SELECT report_json FROM evaluation_experiment').fetchone()[0])
        value = (await self.send('GET', f"/v1/experiments/{result['id']}")).json()
        self.assertEqual(value['status'], 'invalidated')
        self.assertIsNone(value['report'])
        self.assertEqual((await self.send('GET', f"/v1/experiments/{result['id']}/export")).status_code, 409)
        replay = await self.send('POST', '/v1/experiments', json=self.payload(dataset), headers={'Idempotency-Key': 'experiment'})
        self.assertEqual(replay.json()['status'], 'invalidated')

    async def test_later_feedback_and_new_creation_persist_invalidation(self):
        dataset, source, _ = await self.dataset()
        result = await self.create(dataset)
        record = (await self.send('GET', f"/v1/research/{source['research_id']}")).json()
        await self.send('POST', '/v1/feedback', json={'contact_id': record['contacts'][0]['id'], 'category': 'wrong_branch', 'comment': 'New fictional review'})
        response = await self.send('POST', '/v1/experiments', json=self.payload(dataset), headers={'Idempotency-Key': 'stale-dataset'})
        self.assertEqual(response.status_code, 409)
        with self.store().repository.connect() as db:
            row = db.execute('SELECT * FROM evaluation_experiment WHERE id=?', (result['id'],)).fetchone()
            self.assertEqual(row['status'], 'invalidated')
            self.assertIsNone(row['report_json'])
            self.assertIsNone(db.execute('SELECT * FROM evaluation_request WHERE idempotency_key=?', ('stale-dataset',)).fetchone())

    async def test_source_deletion_and_example_deletion_invalidate_on_read(self):
        for operation in ['source', 'example']:
            with self.subTest(operation=operation):
                index = 1 if operation == 'source' else 2
                source = await self.feedback_source(index=index)
                example = await self.review(source, key=f'review-{index}')
                dataset = await self.version([example], key=f'version-{index}')
                result = await self.create(dataset, key=f'experiment-{index}')
                if operation == 'source':
                    with self.store().repository.connect() as db:
                        db.execute('DELETE FROM feedback WHERE id=?', (source['ref']['id'],))
                else:
                    await self.send('DELETE', f"/v1/learning/examples/{example['id']}")
                value = (await self.send('GET', f"/v1/experiments/{result['id']}")).json()
                self.assertEqual(value['status'], 'invalidated')
                self.assertIsNone(value['report'])

    async def test_late_quality_holdout_invalidates_development_report(self):
        record = await self.record()
        dataset, _, _ = await self.dataset()
        result = await self.create(dataset)
        await self.quality_source(record, split='holdout', key='late-holdout')
        value = self.store().get(result['id'])
        self.assertEqual(value['status'], 'invalidated')
        self.assertIsNone(value['report'])

    async def test_limits_and_failed_evaluation_leave_no_partial_receipt(self):
        dataset, _, _ = await self.dataset()
        store = self.store()
        payload = ExperimentInput(**self.payload(dataset))
        with patch('backend.storage.experiments.profile_hardware', side_effect=RuntimeError('Fictional interrupted probe')):
            with self.assertRaises(RuntimeError):
                store.create(payload, 'interrupted')
        with store.repository.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM evaluation_request').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM evaluation_experiment').fetchone()[0], 0)
        for limit in ['MAX_EXPERIMENTS', 'MAX_RECEIPTS']:
            with patch(f'backend.storage.experiments.{limit}', 0):
                response = await self.send('POST', '/v1/experiments', json=self.payload(dataset), headers={'Idempotency-Key': limit})
                self.assertEqual(response.status_code, 429)
        await self.create(dataset)

    async def test_auth_origin_host_body_and_route_bounds(self):
        for method, route in [('GET', '/v1/experiments'), ('POST', '/v1/experiments'), ('GET', '/v1/experiments/missing'), ('GET', '/v1/experiments/missing/export'), ('DELETE', '/v1/experiments/missing')]:
            self.assertEqual((await self.send(method, route, headers={'Authorization': ''})).status_code, 401)
        self.assertEqual((await self.send('GET', '/v1/experiments', headers={'Origin': 'https://evil.example'})).status_code, 403)
        self.assertEqual((await self.send('GET', '/v1/experiments', headers={'Host': 'evil.example'})).status_code, 400)
        self.assertEqual((await self.send('GET', '/v1/experiments?offset=-1')).status_code, 422)
        self.assertEqual((await self.send('GET', '/v1/experiments?mode=training')).status_code, 422)
        self.assertEqual((await self.send('GET', '/v1/experiments/missing')).status_code, 404)
        self.assertEqual((await self.send('POST', '/v1/experiments', content=b'x' * 16001)).status_code, 413)
        dataset, _, _ = await self.dataset()
        self.assertEqual((await self.send('POST', '/v1/experiments', json=self.payload(dataset))).status_code, 422)

    async def test_pagination_modes_and_foreign_dataset_hashes(self):
        dataset, _, _ = await self.dataset()
        store = self.store()
        payload = ExperimentInput(**self.payload(dataset))
        for index in range(21):
            store.create(payload, f'page-{index}')
        first = (await self.send('GET', '/v1/experiments?mode=synthetic')).json()
        second = (await self.send('GET', '/v1/experiments?mode=synthetic&offset=20')).json()
        self.assertEqual((first['total'], first['next_offset'], len(first['items']), len(second['items'])), (21, 20, 20, 1))
        self.assertEqual(len({i['id'] for i in first['items'] + second['items']}), 21)
        self.assertEqual((await self.send('GET', '/v1/experiments')).json()['total'], 0)

    async def test_tampered_frozen_content_is_refused(self):
        dataset, _, _ = await self.dataset()
        with self.store().repository.connect() as db:
            item = copy.deepcopy(dataset['examples'][0])
            item['review']['expected_output'] = 'Altered label'
            db.execute('UPDATE learning_member SET payload_json=? WHERE version_id=?', (json.dumps(item), dataset['id']))
        response = await self.send('POST', '/v1/experiments', json=self.payload(dataset), headers={'Idempotency-Key': 'tampered'})
        self.assertEqual(response.status_code, 409)

    async def test_migration_preserves_every_sprint_thirteen_table(self):
        path = self.directory / 'before-evaluation.sqlite3'
        for migration in sorted(Path('backend/storage/migrations').glob('*.sql'))[:10]:
            with sqlite3.connect(path) as db:
                db.executescript(migration.read_text())
                db.execute('INSERT INTO schema_migration VALUES(?,?)', (int(migration.name[:3]), 'fixture'))
        with patch.object(Repository, 'migrate'):
            old = Repository(path)
        html = '<h1>Fictional preserved business</h1><p>hello@preserved.example</p>'
        record = old.save({'product': 'Fictional offer', 'location': 'Fictional town'}, 'preserve', Page('https://preserved.example/', html.encode(), html), extract(html), True)
        old.correct(record['contacts'][0]['id'], 'wrong_contact', 'Preserve correction', None)
        learning = LearningRepository(old)
        source = learning.sources('synthetic', 0)['items'][0]
        example = learning.review(ExampleReview(**self.review_payload(source)), 'preserve-review')
        learning.create_version(DatasetInput(**self.version_payload([example])), 'preserve-version')
        from backend.domain.correspondence import CalendarDraft
        from backend.storage.correspondence import CorrespondenceRepository
        correspondence = CorrespondenceRepository(old)
        correspondence.save(CalendarDraft(kind='calendar', title='Preserved fictional plan',
            organizer_timezone='Asia/Karachi', counterpart_timezone='Europe/London',
            start_local='2026-11-01T12:00', duration_minutes=30, synthetic=True), 'preserve-calendar')
        # Use the prior module's real public contract, not a hand-crafted SQL draft.
        from backend.domain.pc_worker import PairWorker, WorkerTask
        from backend.storage.pc_worker import PCWorkerRepository
        workers = PCWorkerRepository(old)
        worker = workers.pair(PairWorker(name='Fictional preserved PC'), 'preserve-pair')['worker']
        workers.create(WorkerTask(worker_id=worker['id'], kind='synthetic_parser_benchmark'), 'preserve-task')
        with old.connect() as db:
            db.execute("INSERT INTO local_memory VALUES('note','scope','project_context','Preserved private note','fixture',0,NULL,'old','old',1)")
            tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name<>'schema_migration'")]
            before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM "{table}"')] for table in tables}
        upgraded = Repository(path)
        with upgraded.connect() as db:
            self.assertEqual(before, {table: [tuple(row) for row in db.execute(f'SELECT * FROM "{table}"')] for table in tables})
            self.assertEqual(db.execute('SELECT COUNT(*) FROM schema_migration').fetchone()[0], 18)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
