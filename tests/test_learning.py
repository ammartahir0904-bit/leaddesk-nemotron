"""Fictional reviewed data only; no training, download, live source or model."""
import copy
import sqlite3
from pathlib import Path
from unittest.mock import patch

from backend.adapters.fetch import Page
from backend.domain.extract import extract
from backend.storage.repository import Repository, request_hash
from tests.support import APITestCase


class LearningTests(APITestCase):
    async def record(self, index=1, *, synthetic=True, url=None, html=None):
        html = html or f'<h1>Fictional Workshop {index}</h1><p>Reception: hello@case{index}.example</p>'
        return Repository(self.directory / 'leaddesk.sqlite3').save({'product': 'Any fictional offer', 'location': 'Fictional town'}, f'case-{index}',
            Page(url or f'https://case{index}.example/', html.encode(), html), extract(html), synthetic)

    async def feedback_source(self, record=None, **record_options):
        record = record or await self.record(**record_options)
        response = await self.send('POST', '/v1/feedback', json={'contact_id': record['contacts'][0]['id'], 'category': 'wrong_contact', 'comment': 'Fictional ownership mismatch'})
        self.assertEqual(response.status_code, 200, response.text)
        fid = response.json()['feedback'][0]['id']
        mode = 'synthetic' if record['synthetic'] else 'live'
        sources = (await self.send('GET', f'/v1/learning/sources?mode={mode}')).json()
        return next(source for source in sources['items'] if source['ref']['id'] == fid)

    async def quality_source(self, record, *, split='development', key='quality', unit_type='contacts', outcome='fail'):
        response = await self.send('POST', '/v1/quality/baselines', json={'name': 'Fictional audited sample', 'mode': 'synthetic' if record['synthetic'] else 'live', 'split': split, 'research_ids': [record['id']]}, headers={'Idempotency-Key': key})
        self.assertEqual(response.status_code, 200, response.text)
        baseline = response.json()
        target = baseline['cases'][0]['snapshot']['lead']['contacts'][0] if unit_type == 'contacts' else baseline['cases'][0]['snapshot']['units'][0]
        audit = {'expected_revision': 0, 'reviewer': 'Fictional source auditor', unit_type: [{'target_id': target['id'], 'outcome': outcome, 'evidence_ids': target['evidence_ids'], 'reason': 'Fictional cited judgement'}]}
        response = await self.send('POST', f"/v1/quality/baselines/{baseline['id']}/cases/{record['id']}/audit", json=audit, headers={'Idempotency-Key': f'{key}-audit'})
        self.assertEqual(response.status_code, 200, response.text)
        mode = 'synthetic' if record['synthetic'] else 'live'
        sources = (await self.send('GET', f'/v1/learning/sources?mode={mode}')).json()
        return next((item for item in sources['items'] if item['ref']['id'] == baseline['id']), None), baseline, audit

    def review_payload(self, source, **changes):
        return {'source': copy.deepcopy(source['ref']), 'expected_source_hash': source['source_hash'], 'expected_revision': source['example']['revision'] if source.get('example') else 0,
                'decision': 'include', 'reviewer': 'Fictional reviewer', 'reason': 'Fictional evidence checked',
                'input_text': source['evidence'][0]['excerpt'][:2000], 'observed_output': source['observed_output'],
                'expected_output': 'Abstain from unsupported ownership attribution.', 'evidence_ids': [source['evidence'][0]['id']],
                'redaction_confirmed': True, 'permission_basis': 'Synthetic fixtures authored for this test', 'use_scope': 'local_evaluation', **changes}

    async def review(self, source, key='review', **changes):
        response = await self.send('POST', '/v1/learning/examples', json=self.review_payload(source, **changes), headers={'Idempotency-Key': key})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def version_payload(self, items, **changes):
        return {'name': 'Fictional dataset', 'mode': 'synthetic', 'purpose': 'evaluation', 'split': 'development',
                'examples': [{'id': e['id'], 'revision': e['revision']} for e in items], **changes}

    async def version(self, examples, key='version', **changes):
        response = await self.send('POST', '/v1/learning/versions', json=self.version_payload(examples, **changes), headers={'Idempotency-Key': key})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_manual_review_and_reproducible_version_export_are_idempotent(self):
        source = await self.feedback_source()
        self.assertIsNone(source['example'])
        self.assertEqual((await self.send('GET', '/v1/learning/examples?mode=synthetic')).json()['total'], 0)
        example = await self.review(source)
        self.assertEqual((await self.review(source))['id'], example['id'])
        dataset = await self.version([example])
        self.assertEqual((await self.version([example]))['id'], dataset['id'])
        self.assertEqual(dataset['dataset_sha256'], request_hash(dataset['examples']))
        self.assertEqual(dataset['status'], 'ready')
        self.assertFalse(dataset['training_executed'])
        self.assertIsNone(dataset['model_hash'])
        response = await self.send('GET', f"/v1/learning/versions/{dataset['id']}/export")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), dataset)
        self.assertIn('attachment;', response.headers['content-disposition'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn('details', dataset['examples'][0]['provenance'])
        self.assertEqual(self.calls, [])

    async def test_inclusion_needs_permissions_redaction_citations_and_human_outputs(self):
        source = await self.feedback_source()
        for field, value in [('redaction_confirmed', False), ('redaction_confirmed', 'true'), ('permission_basis', ''), ('input_text', ''),
                             ('expected_output', ''), ('evidence_ids', []), ('observed_output', ''), ('reviewer', ''), ('expected_revision', True), ('training_now', True)]:
            response = await self.send('POST', '/v1/learning/examples', json=self.review_payload(source, **{field: value}), headers={'Idempotency-Key': 'invalid'})
            self.assertEqual(response.status_code, 422, response.text)
        other = await self.record(2)
        response = await self.send('POST', '/v1/learning/examples', json=self.review_payload(source, evidence_ids=[other['evidence'][0]['id']]), headers={'Idempotency-Key': 'wrong-evidence'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual((await self.send('GET', '/v1/learning/examples?mode=synthetic')).json()['total'], 0)

    async def test_private_sources_and_obvious_credentials_are_rejected(self):
        source = await self.feedback_source()
        for kind in ('memory', 'screen', 'voice', 'file', 'model_label'):
            payload = self.review_payload(source); payload['source']['kind'] = kind
            self.assertEqual((await self.send('POST', '/v1/learning/examples', json=payload, headers={'Idempotency-Key': kind})).status_code, 422)
        for text in ('password=fixture-secret', 'Authorization: Bearer fixture', '-----BEGIN PRIVATE KEY-----'):
            self.assertEqual((await self.send('POST', '/v1/learning/examples', json=self.review_payload(source, input_text=text), headers={'Idempotency-Key': 'secret'})).status_code, 422)
        example = await self.review(source, expected_output='نامعلوم <script>fixture()</script>')
        self.assertEqual(example['review']['expected_output'], 'نامعلوم <script>fixture()</script>')

    async def test_training_permission_and_modes_are_enforced(self):
        source = await self.feedback_source()
        example = await self.review(source)
        response = await self.send('POST', '/v1/learning/versions', json=self.version_payload([example], purpose='training'), headers={'Idempotency-Key': 'train-denied'})
        self.assertEqual(response.status_code, 403)
        response = await self.send('POST', '/v1/learning/versions', json=self.version_payload([example], mode='live'), headers={'Idempotency-Key': 'mixed'})
        self.assertEqual(response.status_code, 422)
        training = await self.review(source, key='consent', expected_revision=1, use_scope='local_training')
        dataset = await self.version([training], purpose='training')
        self.assertFalse(dataset['training_executed'])
        self.assertEqual(dataset['purpose'], 'training')

    async def test_revisions_conflicts_and_revocation_invalidate_and_scrub_all_copies(self):
        source = await self.feedback_source()
        example = await self.review(source, use_scope='local_training', input_text='Unique reviewed private fixture')
        first = await self.version([example], purpose='training')
        second = await self.version([example], key='version-2')
        response = await self.send('POST', '/v1/learning/examples', json=self.review_payload(source), headers={'Idempotency-Key': 'stale-review'})
        self.assertEqual(response.status_code, 409)
        revised = await self.review(source, key='revoke', expected_revision=1, input_text='Corrected and redacted fixture', use_scope='local_evaluation')
        for dataset in (first, second):
            response = await self.send('GET', f"/v1/learning/versions/{dataset['id']}")
            self.assertEqual(response.json()['status'], 'invalidated')
            self.assertEqual(response.json()['examples'], [])
            self.assertEqual((await self.send('GET', f"/v1/learning/versions/{dataset['id']}/export")).status_code, 409)
        with Repository(self.directory / 'leaddesk.sqlite3').connect() as db:
            self.assertNotIn('Unique reviewed private fixture', '\n'.join(db.iterdump()))
        stale = await self.send('POST', '/v1/learning/versions', json=self.version_payload([example]), headers={'Idempotency-Key': 'stale-version'})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual((await self.version([revised], key='new-version'))['status'], 'ready')

    async def test_deleting_examples_and_versions_preserves_suppression_and_blocks_replay(self):
        source = await self.feedback_source()
        example = await self.review(source, input_text='Disposable reviewed fixture')
        dataset = await self.version([example])
        await self.send('DELETE', f"/v1/learning/examples/{example['id']}")
        self.assertEqual((await self.send('GET', f"/v1/learning/versions/{dataset['id']}")).json()['examples'], [])
        replay = await self.send('POST', '/v1/learning/examples', json=self.review_payload(source, input_text='Disposable reviewed fixture'), headers={'Idempotency-Key': 'review'})
        self.assertEqual(replay.status_code, 410)
        record = (await self.send('GET', f"/v1/research/{source['research_id']}")).json()
        self.assertTrue(record['contacts'][0]['suppressed'])
        self.assertEqual(len(record['feedback']), 1)
        await self.send('DELETE', f"/v1/learning/versions/{dataset['id']}")
        self.assertEqual((await self.send('GET', f"/v1/learning/versions/{dataset['id']}")).status_code, 404)
        replay = await self.send('POST', '/v1/learning/versions', json=self.version_payload([example]), headers={'Idempotency-Key': 'version'})
        self.assertEqual(replay.status_code, 410)
        with Repository(self.directory / 'leaddesk.sqlite3').connect() as db:
            self.assertNotIn('Disposable reviewed fixture', '\n'.join(db.iterdump()))

    async def test_exclusion_clears_material_and_cannot_be_frozen(self):
        source = await self.feedback_source()
        example = await self.review(source)
        dataset = await self.version([example])
        excluded = await self.review(source, key='exclude', expected_revision=1, decision='exclude')
        self.assertEqual(excluded['review']['input_text'], '')
        self.assertEqual(excluded['review']['evidence_ids'], [])
        self.assertEqual((await self.send('GET', f"/v1/learning/versions/{dataset['id']}/export")).status_code, 409)
        response = await self.send('POST', '/v1/learning/versions', json=self.version_payload([excluded]), headers={'Idempotency-Key': 'excluded'})
        self.assertEqual(response.status_code, 409)

    async def test_quality_known_units_only_and_changed_audit_block_old_exports(self):
        record = await self.record()
        source, baseline, audit = await self.quality_source(record, unit_type='claims')
        self.assertEqual(source['task'], 'factual_support')
        example = await self.review(source)
        dataset = await self.version([example])
        audit['expected_revision'] = 1; audit['claims'][0] = {'target_id': audit['claims'][0]['target_id'], 'outcome': 'unknown'}
        response = await self.send('POST', f"/v1/quality/baselines/{baseline['id']}/cases/{record['id']}/audit", json=audit, headers={'Idempotency-Key': 'unknown-audit'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((await self.send('GET', '/v1/learning/sources?mode=synthetic')).json()['total'], 0)
        self.assertEqual((await self.send('GET', f"/v1/learning/versions/{dataset['id']}/export")).status_code, 409)

    async def test_stale_quality_predictions_and_superseded_feedback_need_new_review(self):
        record = await self.record()
        quality, baseline, audit = await self.quality_source(record)
        example = await self.review(quality)
        dataset = await self.version([example])
        source = await self.feedback_source(record)
        response = await self.send('POST', '/v1/learning/examples', json=self.review_payload(quality, expected_revision=1), headers={'Idempotency-Key': 'changed-source'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual((await self.send('GET', f"/v1/learning/versions/{dataset['id']}/export")).status_code, 409)
        reviewed = await self.review(source, key='feedback-example')
        await self.send('POST', '/v1/feedback', json={'contact_id': record['contacts'][0]['id'], 'category': 'wrong_branch', 'comment': 'Newer fictional branch correction'})
        response = await self.send('POST', '/v1/learning/versions', json=self.version_payload([reviewed]), headers={'Idempotency-Key': 'old-feedback'})
        self.assertEqual(response.status_code, 409)

    async def test_holdout_quality_never_enters_development_or_training(self):
        record = await self.record()
        source, _, _ = await self.quality_source(record, split='holdout')
        self.assertTrue(source['held_out'])
        response = await self.send('POST', '/v1/learning/examples', json=self.review_payload(source, use_scope='local_training'), headers={'Idempotency-Key': 'forbidden-training'})
        self.assertEqual(response.status_code, 409)
        example = await self.review(source)
        response = await self.send('POST', '/v1/learning/versions', json=self.version_payload([example]), headers={'Idempotency-Key': 'forbidden-development'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual((await self.version([example], split='holdout'))['status'], 'ready')

    async def test_late_quality_holdout_invalidates_existing_development_version(self):
        record = await self.record()
        example = await self.review(await self.feedback_source(record))
        dataset = await self.version([example])
        await self.quality_source(record, split='holdout')
        self.assertEqual((await self.send('GET', f"/v1/learning/versions/{dataset['id']}/export")).status_code, 409)

    async def test_domain_and_copied_page_reservations_survive_version_deletion(self):
        one = await self.record(1, url='https://north.fixture.example/')
        first = await self.review(await self.feedback_source(one), key='one')
        dataset = await self.version([first])
        await self.send('DELETE', f"/v1/learning/versions/{dataset['id']}")
        two = await self.record(2, url='https://south.fixture.example/')
        second = await self.review(await self.feedback_source(two), key='two')
        response = await self.send('POST', '/v1/learning/versions', json=self.version_payload([second], split='holdout'), headers={'Idempotency-Key': 'domain-leak'})
        self.assertEqual(response.status_code, 409)
        three = await self.record(3, url='https://unrelated.example/', html='<h1>Fictional Workshop 1</h1><p>Reception: hello@case1.example</p>')
        third = await self.review(await self.feedback_source(three), key='three')
        response = await self.send('POST', '/v1/learning/versions', json=self.version_payload([third], split='holdout'), headers={'Idempotency-Key': 'copy-leak'})
        self.assertEqual(response.status_code, 409)

    async def test_duplicate_targets_across_feedback_and_audit_are_not_counted_twice(self):
        record = await self.record()
        feedback = await self.feedback_source(record)
        quality, _, _ = await self.quality_source(record)
        first = await self.review(feedback, key='feedback')
        second = await self.review(quality, key='quality-review', expected_output='Different authored wording does not avoid deduplication.')
        response = await self.send('POST', '/v1/learning/versions', json=self.version_payload([first, second]), headers={'Idempotency-Key': 'duplicate-target'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual((await self.send('GET', '/v1/learning/versions')).json()['total'], 0)

    async def test_atomic_failure_and_idempotency_key_conflicts(self):
        source = await self.feedback_source()
        example = await self.review(source)
        payload = self.version_payload([example]); payload['examples'].append({'id': 'missing', 'revision': 1})
        response = await self.send('POST', '/v1/learning/versions', json=payload, headers={'Idempotency-Key': 'atomic'})
        self.assertEqual(response.status_code, 404)
        self.assertEqual((await self.send('GET', '/v1/learning/versions')).json()['total'], 0)
        with Repository(self.directory / 'leaddesk.sqlite3').connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM learning_split').fetchone()[0], 0)
        response = await self.send('POST', '/v1/learning/examples', json=self.review_payload(source, expected_output='Changed'), headers={'Idempotency-Key': 'review'})
        self.assertEqual(response.status_code, 409)
        await self.version([example])
        response = await self.send('POST', '/v1/learning/versions', json=self.version_payload([example], name='Changed name'), headers={'Idempotency-Key': 'version'})
        self.assertEqual(response.status_code, 409)

    async def test_auth_origin_bounds_missing_objects_and_typed_input(self):
        for method, path in [('GET', '/v1/learning/sources'), ('GET', '/v1/learning/examples'), ('POST', '/v1/learning/examples'),
                             ('GET', '/v1/learning/versions'), ('POST', '/v1/learning/versions'), ('DELETE', '/v1/learning/examples/missing'),
                             ('GET', '/v1/learning/versions/missing/export'), ('DELETE', '/v1/learning/versions/missing')]:
            self.assertEqual((await self.send(method, path, headers={'Authorization': ''})).status_code, 401)
            self.assertEqual((await self.send(method, path, headers={'Origin': 'https://external.example'})).status_code, 403)
        self.assertEqual((await self.send('GET', '/v1/learning/sources?mode=screen')).status_code, 422)
        self.assertEqual((await self.send('GET', '/v1/learning/examples?offset=-1')).status_code, 422)
        self.assertEqual((await self.send('GET', '/v1/learning/versions/missing')).status_code, 404)
        self.assertEqual((await self.send('POST', '/v1/learning/examples', content=b'x' * 16001)).status_code, 413)
        source = await self.feedback_source()
        self.assertEqual((await self.send('POST', '/v1/learning/examples', json=self.review_payload(source))).status_code, 422)
        example = await self.review(source)
        for changes in ({'split': 'holdout', 'purpose': 'training'}, {'examples': []}, {'examples': [{'id': example['id'], 'revision': 1}] * 2}, {'mode': 'all'}, {'train_now': True}):
            response = await self.send('POST', '/v1/learning/versions', json=self.version_payload([example], **changes), headers={'Idempotency-Key': 'invalid'})
            self.assertEqual(response.status_code, 422)

    async def test_migration_preserves_all_sprint_ten_data(self):
        path = self.directory / 'pre-learning.sqlite3'
        for migration in sorted(Path('backend/storage/migrations').glob('*.sql'))[:7]:
            with sqlite3.connect(path) as db:
                db.executescript(migration.read_text())
                db.execute('INSERT INTO schema_migration VALUES(?,?)', (int(migration.name[:3]), 'fixture'))
        with patch.object(Repository, 'migrate'):
            old = Repository(path)
        html = '<h1>Fictional preserved business</h1><p>hello@preserved.example</p>'
        saved = old.save({'product': 'Preserved offer', 'location': 'Preserved location'}, 'preserved', Page('https://preserved.example/', html.encode(), html), extract(html), True)
        old.correct(saved['contacts'][0]['id'], 'wrong_contact', 'Preserve this suppression', None)
        with old.connect() as db:
            db.execute("INSERT INTO local_memory VALUES('note','scope','project_context','Preserve private note','fixture',0,NULL,'old','old',1)")
            tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name<>'schema_migration'")]
            before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table}')] for table in tables}
        upgraded = Repository(path)
        with upgraded.connect() as db:
            self.assertEqual(before, {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table}')] for table in tables})
            self.assertEqual(db.execute('SELECT COUNT(*) FROM schema_migration').fetchone()[0], 18)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    async def test_unreviewed_comments_url_queries_and_suggestions_never_enter_exports(self):
        record = await self.record(url='https://privacy.example/contact?token=fictional-query-secret')
        source = await self.feedback_source(record)
        with Repository(self.directory / 'leaddesk.sqlite3').connect() as db:
            db.execute('UPDATE feedback SET comment=?,expected_value=? WHERE id=?', ('Unreviewed private comment', 'Unverified replacement', source['ref']['id']))
        source = (await self.send('GET', '/v1/learning/sources?mode=synthetic')).json()['items'][0]
        example = await self.review(source, input_text='Reviewed redacted excerpt')
        dataset = await self.version([example])
        exported = (await self.send('GET', f"/v1/learning/versions/{dataset['id']}/export")).text
        for value in ('fictional-query-secret', 'Unreviewed private comment', 'Unverified replacement'):
            self.assertNotIn(value, exported)
        self.assertEqual(dataset['examples'][0]['provenance']['source_origin'], 'https://privacy.example')

    async def test_deleted_source_invalidates_version_and_example_eligibility(self):
        source = await self.feedback_source()
        example = await self.review(source)
        dataset = await self.version([example])
        with Repository(self.directory / 'leaddesk.sqlite3').connect() as db:
            db.execute('DELETE FROM feedback WHERE id=?', (source['ref']['id'],))
        self.assertFalse((await self.send('GET', '/v1/learning/examples?mode=synthetic')).json()['items'][0]['current'])
        self.assertEqual((await self.send('GET', f"/v1/learning/versions/{dataset['id']}/export")).status_code, 409)

    async def test_size_failure_rolls_back_reservations_members_and_receipt(self):
        source = await self.feedback_source()
        example = await self.review(source)
        with patch('backend.storage.learning.MAX_EXPORT_BYTES', 8192):
            response = await self.send('POST', '/v1/learning/versions', json=self.version_payload([example]), headers={'Idempotency-Key': 'size-limit'})
        self.assertEqual(response.status_code, 413)
        with Repository(self.directory / 'leaddesk.sqlite3').connect() as db:
            for table in ('learning_version', 'learning_member', 'learning_split'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)
            self.assertIsNone(db.execute('SELECT * FROM learning_request WHERE idempotency_key=?', ('size-limit',)).fetchone())

    async def test_pagination_keeps_every_source_example_and_version_accessible(self):
        from backend.domain.learning import DatasetInput, ExampleReview
        from backend.storage.learning import LearningRepository
        repository = Repository(self.directory / 'leaddesk.sqlite3')
        learning = LearningRepository(repository)
        for index in range(21):
            record = await self.record(index + 1)
            repository.correct(record['contacts'][0]['id'], 'wrong_contact', 'Fictional paginated correction', None)
            source = learning.sources('synthetic', 0)['items'][0]
            example = learning.review(ExampleReview(**self.review_payload(source)), f'page-review-{index}')
            learning.create_version(DatasetInput(**self.version_payload([example])), f'page-version-{index}')
        for route in ('sources?mode=synthetic&', 'examples?mode=synthetic&', 'versions?'):
            first = (await self.send('GET', f'/v1/learning/{route}offset=0')).json()
            second = (await self.send('GET', f'/v1/learning/{route}offset=20')).json()
            self.assertEqual(first['total'], 21)
            self.assertEqual(len(first['items']), 20)
            self.assertEqual(first['next_offset'], 20)
            self.assertEqual(len(second['items']), 1)
            self.assertIsNone(second['next_offset'])
            identity = 'key' if route.startswith('sources') else 'id'
            self.assertFalse({item[identity] for item in first['items']} & {item[identity] for item in second['items']})

    async def test_reviewed_business_group_prevents_cross_domain_split_leakage(self):
        one = await self.review(await self.feedback_source(), business_group='Fictional shared business')
        await self.version([one])
        two = await self.review(await self.feedback_source(index=2), key='review-2', business_group='  FICTIONAL shared  business ')
        response = await self.send('POST', '/v1/learning/versions', json=self.version_payload([two], split='holdout'), headers={'Idempotency-Key': 'shared-group'})
        self.assertEqual(response.status_code, 409)
