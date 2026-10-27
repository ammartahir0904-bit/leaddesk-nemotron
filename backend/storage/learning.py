"""Reviewed examples, frozen local datasets, leakage guards and deletion propagation."""
import json
from types import SimpleNamespace
from urllib.parse import urlsplit

from backend.domain.errors import ResearchError
from backend.domain.learning import ExampleSelection, LearningSource, domain_group
from backend.domain.quality import snapshot_evidence
from backend.storage.quality import capture_snapshot
from backend.storage.repository import now, request_hash, uid

MAX_EXPORT_BYTES = 2 * 1024 * 1024
SOURCE_QUERY = """
 SELECT 'feedback' AS kind,f.id AS id,NULL AS research_id,NULL AS unit_type,NULL AS target_id,
        f.created_at AS stamp,ca.synthetic AS synthetic
 FROM feedback f JOIN contact c ON c.id=f.contact_id JOIN business b ON b.id=c.business_id JOIN campaign ca ON ca.id=b.campaign_id
 UNION ALL
 SELECT 'quality_audit',a.baseline_id,a.research_id,'contacts',json_extract(v.value,'$.target_id'),a.created_at,
        json_extract(q.snapshot_json,'$.research.synthetic')
 FROM quality_audit a JOIN quality_case q ON q.baseline_id=a.baseline_id AND q.research_id=a.research_id
 JOIN json_each(a.document_json,'$.contacts') v
 WHERE json_extract(v.value,'$.outcome') IN ('pass','fail') AND NOT EXISTS
 (SELECT 1 FROM quality_audit newer WHERE newer.baseline_id=a.baseline_id AND newer.research_id=a.research_id AND newer.revision>a.revision)
 UNION ALL
 SELECT 'quality_audit',a.baseline_id,a.research_id,'claims',json_extract(v.value,'$.target_id'),a.created_at,
        json_extract(q.snapshot_json,'$.research.synthetic')
 FROM quality_audit a JOIN quality_case q ON q.baseline_id=a.baseline_id AND q.research_id=a.research_id
 JOIN json_each(a.document_json,'$.claims') v
 WHERE json_extract(v.value,'$.outcome') IN ('pass','fail') AND NOT EXISTS
 (SELECT 1 FROM quality_audit newer WHERE newer.baseline_id=a.baseline_id AND newer.research_id=a.research_id AND newer.revision>a.revision)
"""


def source_tokens(sources):
    tokens = set()
    for source in sources:
        tokens.add(request_hash({'domain': domain_group(source['source_url'])}))
        tokens.update(request_hash({'page': evidence['content_hash']}) for evidence in source['evidence'])
    return tokens


def business_token(review):
    group = ' '.join(review.get('business_group', '').casefold().split())
    return request_hash({'reviewed_business_group': group}) if group else None


class LearningRepository:
    def __init__(self, repository):
        self.repository = repository

    def _protected(self, db):
        # Extract only URLs/hashes rather than loading entire frozen datasets.
        rows = db.execute("""
          SELECT json_extract(c.snapshot_json,'$.research.source_url') AS url,json_extract(e.value,'$.content_hash') AS hash
          FROM quality_case c JOIN quality_baseline b ON b.id=c.baseline_id JOIN json_each(c.snapshot_json,'$.research.evidence') e WHERE b.split='holdout'
          UNION
          SELECT json_extract(s.value,'$.source_url'),json_extract(e.value,'$.content_hash')
          FROM quality_case c JOIN quality_baseline b ON b.id=c.baseline_id
          JOIN json_each(c.snapshot_json,'$.comparison_sources') s JOIN json_each(s.value,'$.evidence') e WHERE b.split='holdout'
        """)
        tokens = {row[0] for row in db.execute("SELECT token FROM learning_split WHERE split='holdout'")}
        for row in rows:
            tokens.add(request_hash({'domain': domain_group(row['url'])}))
            tokens.add(request_hash({'page': row['hash']}))
        return tokens

    def _source(self, db, ref, protected):
        key = request_hash(ref.model_dump())
        stale = False
        if ref.kind == 'feedback':
            row = db.execute("""SELECT f.*,c.raw_value,c.normalised_value,c.suppressed,b.campaign_id FROM feedback f
                JOIN contact c ON c.id=f.contact_id JOIN business b ON b.id=c.business_id WHERE f.id=?""", (ref.id,)).fetchone()
            if row is None:
                raise ResearchError('Feedback source not found.', status=404)
            record = self.repository.get_in_transaction(db, row['campaign_id'])
            contact = next(c for c in record['contacts'] if c['id'] == row['contact_id'])
            evidence = [e for e in record['evidence'] if e['id'] in contact['evidence_ids']][:4]
            latest = db.execute('SELECT id FROM feedback WHERE contact_id=? ORDER BY created_at DESC,id DESC LIMIT 1', (row['contact_id'],)).fetchone()[0]
            stale = latest != ref.id
            details = dict(row) | {'latest_feedback_id': latest}
            observed, task = row['raw_value'], 'contact_attribution'
            suggestion = row['expected_value'] or ''
            verdict, reason = 'disputed', row['comment']
            sources, source_revision = [record], 1
        else:
            row = db.execute("""SELECT q.snapshot_json,q.snapshot_sha256,b.split,a.document_json,a.revision FROM quality_case q
                JOIN quality_baseline b ON b.id=q.baseline_id JOIN quality_audit a ON a.baseline_id=q.baseline_id AND a.research_id=q.research_id
                WHERE q.baseline_id=? AND q.research_id=? ORDER BY a.revision DESC LIMIT 1""", (ref.id, ref.research_id)).fetchone()
            if row is None:
                raise ResearchError('Audited quality source not found.', status=404)
            snapshot = json.loads(row['snapshot_json'])
            audit = json.loads(row['document_json'])
            item = next((v for v in audit[ref.unit_type] if v['target_id'] == ref.target_id and v['outcome'] != 'unknown'), None)
            if item is None:
                raise ResearchError('This quality target has no current pass/fail audit.', status=409)
            record = snapshot['research']
            targets = snapshot['lead']['contacts'] if ref.unit_type == 'contacts' else snapshot['units']
            target = next(t for t in targets if t['id'] == ref.target_id)
            evidence_map = snapshot_evidence(snapshot)
            evidence = [evidence_map[eid] for eid in item['evidence_ids']]
            observed = target['raw_value'] if ref.unit_type == 'contacts' else target['value']
            task = 'contact_attribution' if ref.unit_type == 'contacts' else 'factual_support'
            current_hash = request_hash(capture_snapshot(self.repository, db, ref.research_id))
            stale = current_hash != row['snapshot_sha256']
            details = {'audit': item, 'audit_revision': row['revision'], 'snapshot_sha256': row['snapshot_sha256'], 'current_sha256': current_hash}
            sources, source_revision = [record, *snapshot['comparison_sources']], row['revision']
            verdict, reason, suggestion = item['outcome'], item['reason'], ''
        tokens = source_tokens(sources)
        fingerprint = request_hash({'task': task, 'observed': ' '.join(observed.casefold().split()),
                                    'pages': sorted({e['content_hash'] for e in evidence})})
        tokens.add(request_hash({'target': fingerprint}))
        value = {'key': key, 'ref': ref.model_dump(), 'source_revision': source_revision, 'research_id': record['id'],
                 'mode': 'synthetic' if record['synthetic'] else 'live', 'task': task, 'source_url': record['source_url'],
                 'source_origin': f"{urlsplit(record['source_url']).scheme}://{urlsplit(record['source_url']).hostname}",
                 'domain_group': domain_group(record['source_url']), 'observed_output': observed, 'suggested_correction_unverified': suggestion,
                 'source_verdict': verdict, 'source_reason': reason, 'evidence': evidence, 'details': details,
                 'fingerprint': fingerprint, 'split_tokens': sorted(tokens)}
        value['source_hash'] = request_hash(value)
        value['stale'] = stale
        value['held_out'] = bool(tokens & protected)
        return value

    @staticmethod
    def _example(row):
        result = dict(row)
        result['source'] = json.loads(result.pop('source_ref_json'))
        result['review'] = json.loads(result.pop('payload_json'))
        return result

    def sources(self, mode, offset):
        with self.repository.connect() as db:
            db.execute('BEGIN')
            protected = self._protected(db)
            where = f'SELECT * FROM ({SOURCE_QUERY}) WHERE synthetic=?'
            total = db.execute(f'SELECT COUNT(*) FROM ({where})', (mode == 'synthetic',)).fetchone()[0]
            rows = db.execute(where + ' ORDER BY stamp DESC,kind,id,research_id,unit_type,target_id LIMIT 20 OFFSET ?', (mode == 'synthetic', offset)).fetchall()
            items = []
            for row in rows:
                ref = LearningSource(**{key: row[key] for key in ('kind', 'id', 'research_id', 'unit_type', 'target_id')})
                item = self._source(db, ref, protected)
                review = db.execute('SELECT * FROM learning_example WHERE source_key=?', (item['key'],)).fetchone()
                item['example'] = self._example(review) if review else None
                if item['example']:
                    item['held_out'] = item['held_out'] or business_token(item['example']['review']) in protected
                items.append(item)
            counts = {row['decision']: row['count'] for row in db.execute('SELECT decision,COUNT(*) AS count FROM learning_example WHERE mode=? GROUP BY decision', (mode,))}
        return {'items': items, 'total': total, 'offset': offset, 'limit': 20, 'next_offset': offset + 20 if offset + 20 < total else None,
                'review_counts': {'include': counts.get('include', 0), 'exclude': counts.get('exclude', 0)}, 'training_enabled': False}

    @staticmethod
    def _receipt(db, key, digest):
        row = db.execute('SELECT * FROM learning_request WHERE idempotency_key=?', (key,)).fetchone()
        if row and row['request_hash'] != digest:
            raise ResearchError('This learning request key was used with different inputs.', status=409)
        if row and not (row['example_id'] or row['version_id']):
            raise ResearchError('The learning material for this request was deleted.', status=410)
        return row

    @staticmethod
    def _invalidate(db, example_id):
        ids = [row[0] for row in db.execute('SELECT version_id FROM learning_member WHERE example_id=?', (example_id,))]
        for version_id in ids:
            db.execute("UPDATE learning_version SET status='invalidated' WHERE id=?", (version_id,))
            db.execute('UPDATE learning_member SET payload_json=NULL WHERE version_id=?', (version_id,))

    def review(self, payload, key):
        digest = request_hash({'operation': 'review_example', 'input': payload.model_dump()})
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            receipt = self._receipt(db, key, digest)
            if receipt:
                row = db.execute('SELECT * FROM learning_example WHERE id=?', (receipt['example_id'],)).fetchone()
                if row is None or row['source_hash'] != payload.expected_source_hash or row['revision'] != payload.expected_revision + 1:
                    raise ResearchError('This saved review was subsequently changed. Reload it.', status=409)
                return self._example(row)
            protected = self._protected(db)
            source = self._source(db, payload.source, protected)
            if source['source_hash'] != payload.expected_source_hash:
                raise ResearchError('This feedback or audit changed. Reload it before review.', status=409)
            previous = db.execute('SELECT * FROM learning_example WHERE source_key=?', (source['key'],)).fetchone()
            if payload.expected_revision != (previous['revision'] if previous else 0):
                raise ResearchError('This learning review changed. Reload before saving.', status=409)
            if payload.decision == 'include':
                if source['stale']:
                    raise ResearchError('This source is superseded or its frozen predictions changed. Refresh the source review first.', status=409)
                if set(payload.evidence_ids) - {e['id'] for e in source['evidence']}:
                    raise ResearchError('Citations must belong to the selected feedback/audited target.')
                if (source['held_out'] or business_token(payload.model_dump()) in protected) and payload.use_scope == 'local_training':
                    raise ResearchError('Held-out sources are reserved for evaluation.', status=409)
            if previous is None and db.execute('SELECT COUNT(*) FROM learning_example').fetchone()[0] >= 2000:
                raise ResearchError('Learning review limit reached (2000). Delete unused examples.', status=429)
            example_id = previous['id'] if previous else uid()
            self._invalidate(db, example_id)
            review = payload.model_dump(exclude={'source', 'expected_revision', 'expected_source_hash'})
            if payload.decision == 'exclude':
                review.update(input_text='', observed_output='', expected_output='', evidence_ids=[], permission_basis='', business_group='', redaction_confirmed=False, use_scope='local_evaluation')
            stamp = now()
            db.execute('''INSERT INTO learning_example VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_key) DO UPDATE SET
                source_hash=excluded.source_hash,revision=excluded.revision,decision=excluded.decision,payload_json=excluded.payload_json,updated_at=excluded.updated_at''',
                (example_id, source['key'], json.dumps(payload.source.model_dump()), source['source_hash'], payload.expected_revision + 1,
                 payload.decision, source['mode'], json.dumps(review), previous['created_at'] if previous else stamp, stamp))
            db.execute('INSERT INTO learning_request VALUES(?,?,?,NULL)', (key, digest, example_id))
            return self._example(db.execute('SELECT * FROM learning_example WHERE id=?', (example_id,)).fetchone())

    def examples(self, mode, offset):
        with self.repository.connect() as db:
            db.execute('BEGIN')
            protected = self._protected(db)
            rows = db.execute('SELECT * FROM learning_example WHERE mode=? ORDER BY updated_at DESC,id DESC LIMIT 20 OFFSET ?', (mode, offset)).fetchall()
            total = db.execute('SELECT COUNT(*) FROM learning_example WHERE mode=?', (mode,)).fetchone()[0]
            items = []
            for row in rows:
                item = self._example(row)
                try:
                    source = self._source(db, LearningSource(**item['source']), protected)
                    item['current'] = source['source_hash'] == row['source_hash'] and not source['stale']
                    item['held_out'] = source['held_out'] or business_token(item['review']) in protected
                except ResearchError:
                    item['current'], item['held_out'] = False, False
                items.append(item)
        return {'items': items, 'total': total, 'offset': offset, 'limit': 20, 'next_offset': offset + 20 if offset + 20 < total else None}

    def delete_example(self, example_id):
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._invalidate(db, example_id)
            db.execute('DELETE FROM learning_example WHERE id=?', (example_id,))
        return {'deleted': True, 'source_feedback_preserved': True}

    def _selected(self, db, selection, payload, protected):
        row = db.execute('SELECT * FROM learning_example WHERE id=?', (selection.id,)).fetchone()
        if row is None:
            raise ResearchError('Selected example not found.', status=404)
        item = self._example(row)
        if item['revision'] != selection.revision or item['decision'] != 'include':
            raise ResearchError('Select the current revision of an included example.', status=409)
        source = self._source(db, LearningSource(**item['source']), protected)
        if business_token(item['review']):
            source['split_tokens'].append(business_token(item['review']))
            source['held_out'] = source['held_out'] or bool(set(source['split_tokens']) & protected)
        if source['source_hash'] != row['source_hash'] or source['stale']:
            raise ResearchError('A selected source changed. Review it again.', status=409)
        if item['mode'] != payload.mode:
            raise ResearchError('Real and synthetic examples cannot share a dataset.')
        if payload.purpose == 'training' and item['review']['use_scope'] != 'local_training':
            raise ResearchError('Training needs explicit local-training permission for every example.', status=403)
        if source['held_out'] and payload.split != 'holdout':
            raise ResearchError('A selected source is reserved by a quality holdout.', status=409)
        for token in source['split_tokens']:
            reserved = db.execute('SELECT split FROM learning_split WHERE token=?', (token,)).fetchone()
            if reserved and reserved['split'] != payload.split:
                raise ResearchError('A domain, copied source page or target has already been reserved for the other split.', status=409)
        origin = {'source': item['source'], 'source_hash': source['source_hash'], 'source_revision': source['source_revision'],
                  'source_origin': source['source_origin'], 'domain_group': source['domain_group'], 'task': source['task'],
                  'source_verdict': source['source_verdict'], 'label_origin': 'explicit_human_review',
                  'evidence': [{'id': e['id'], 'content_hash': e['content_hash'], 'retrieved_at': e['retrieved_at']} for e in source['evidence'] if e['id'] in item['review']['evidence_ids']]}
        frozen = {'id': item['id'], 'revision': item['revision'], 'mode': item['mode'], 'reviewed_at': item['updated_at'], 'review': item['review'], 'provenance': origin}
        return frozen, source

    def create_version(self, payload, key):
        digest = request_hash({'operation': 'dataset_version', 'input': payload.model_dump()})
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            receipt = self._receipt(db, key, digest)
            if receipt:
                version_id = receipt['version_id']
            else:
                if db.execute('SELECT COUNT(*) FROM learning_version').fetchone()[0] >= 200:
                    raise ResearchError('Dataset version limit reached (200). Delete unused versions.', status=429)
                protected, frozen, tokens, targets, texts = self._protected(db), [], set(), set(), set()
                for selection in sorted(payload.examples, key=lambda item: item.id):
                    item, source = self._selected(db, selection, payload, protected)
                    text_key = request_hash([' '.join(item['review'][field].casefold().split()) for field in ('input_text', 'observed_output', 'expected_output')])
                    if source['fingerprint'] in targets or text_key in texts:
                        raise ResearchError('Duplicate source targets or reviewed examples cannot inflate a dataset.')
                    targets.add(source['fingerprint']); texts.add(text_key)
                    frozen.append(item); tokens.update(source['split_tokens'])
                if len(json.dumps(frozen, ensure_ascii=False).encode()) > MAX_EXPORT_BYTES - 8192:
                    raise ResearchError('Dataset exceeds the 2 MiB limit. Select fewer examples.', status=413)
                version_id = uid()
                db.execute('INSERT INTO learning_version VALUES(?,?,?,?,?,?,?,?,?)',
                           (version_id, payload.name, payload.purpose, payload.split, payload.mode, now(), request_hash(frozen), len(frozen), 'ready'))
                db.executemany('INSERT INTO learning_member VALUES(?,?,?,?,?)', [(version_id, item['id'], item['revision'], request_hash(item), json.dumps(item)) for item in frozen])
                db.executemany('INSERT OR IGNORE INTO learning_split VALUES(?,?)', [(token, payload.split) for token in tokens])
                db.execute('INSERT INTO learning_request VALUES(?,?,NULL,?)', (key, digest, version_id))
        return self.version(version_id)

    def _sync_version(self, db, version, protected):
        if version['status'] == 'invalidated':
            return
        rows = db.execute('SELECT example_id,revision,payload_json FROM learning_member WHERE version_id=? ORDER BY example_id', (version['id'],)).fetchall()
        valid = len(rows) == version['sample_count'] and all(row['payload_json'] is not None for row in rows)
        if valid:
            for row in rows:
                try:
                    self._selected(db, ExampleSelection(id=row['example_id'], revision=row['revision']), SimpleNamespace(**version), protected)
                except ResearchError:
                    valid = False
                    break
        if not valid:
            db.execute("UPDATE learning_version SET status='invalidated' WHERE id=?", (version['id'],))
            db.execute('UPDATE learning_member SET payload_json=NULL WHERE version_id=?', (version['id'],))
            version['status'] = 'invalidated'

    def version(self, version_id):
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM learning_version WHERE id=?', (version_id,)).fetchone()
            if row is None:
                raise ResearchError('Dataset version not found.', status=404)
            result = dict(row)
            self._sync_version(db, result, self._protected(db))
            result['examples'] = [json.loads(row[0]) for row in db.execute('SELECT payload_json FROM learning_member WHERE version_id=? AND payload_json IS NOT NULL ORDER BY example_id', (version_id,))]
            result.update(schema_version=1, training_executed=False, model_hash=None, configuration={'method': 'human_reviewed_local_dataset_v1', 'domain_grouping': 'last_two_dns_labels_conservative'})
        return result

    def versions(self, offset):
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            total = db.execute('SELECT COUNT(*) FROM learning_version').fetchone()[0]
            rows = [dict(row) for row in db.execute('SELECT * FROM learning_version ORDER BY created_at DESC,id DESC LIMIT 20 OFFSET ?', (offset,))]
            protected = self._protected(db)
            for row in rows:
                self._sync_version(db, row, protected)
        return {'items': rows, 'total': total, 'offset': offset, 'limit': 20, 'next_offset': offset + 20 if offset + 20 < total else None}

    def delete_version(self, version_id):
        with self.repository.connect() as db:
            db.execute('DELETE FROM learning_version WHERE id=?', (version_id,))
        return {'deleted': True}
