"""B10 source-audit safety. Every page and judgement here is fictional test data."""
import copy
import asyncio
import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.adapters.fetch import Page
from backend.domain.extract import extract
from backend.domain.quality import AuditInput, factual_units
from backend.evaluation.quality import proportion, quality_report
from backend.evaluation.quality_demo import build_quality_demo
from backend.storage.quality import QualityRepository
from backend.storage.repository import Repository
from tests.support import APITestCase, TOKEN
from tests.test_assessments import SOURCE, analysis, identity, quote


def known(refs, outcome='pass'):
    return {'outcome': outcome, 'evidence_ids': refs[:1], 'reason': 'Fictional rubric judgement for this test only.'}


def complete_audit(case, **changes):
    snapshot = case['snapshot']
    lead = snapshot['lead']
    identity_doc = snapshot['research']['assessment']['identity']['document']
    return {'expected_revision': case['audit']['revision'] if case['audit'] else 0, 'reviewer': 'Fictional test reviewer',
            'identity': known(identity_doc['business_name']['evidence_ids']),
            'relevance': known([snapshot['research']['evidence'][0]['id']]),
            'contacts': [{'target_id': c['id'], **known(c['evidence_ids'])} for c in lead['contacts']],
            'claims': [{'target_id': unit['id'], **known(unit['evidence_ids'])} for unit in snapshot['units']],
            'issue_tags': ['positive_fit'], **changes}


class QualityTests(APITestCase):
    async def make_case(self, index=1, *, synthetic=True, reviewed=True, offer='Inventory support', geography='Lahore', url=None, html=None):
        html = html or SOURCE.replace('Synthetic North Workshop', f'Fictional Workshop {index}').replace(
            '+1 202-555-0148', f'+1 202-555-{100 + index:04}').replace('help@directory.example', f'hello@fictional-{index}.example').replace('Lahore', geography)
        url = url or f'https://fictional-{index}.example/'
        repo = Repository(self.directory / 'leaddesk.sqlite3')
        record = repo.save({'product': offer, 'location': geography}, f'research-{index}', Page(url, html.encode(), html), extract(html), synthetic)
        if reviewed:
            payload = identity(record, address=quote(record, geography), geography='matches', exclusions='clear',
                exclusion_reason='Fictional source checked for this test.', contact_reviews=[
                    {'contact_id': c['id'], 'decision': 'attributed', 'evidence_ids': c['evidence_ids']} for c in record['contacts']])
            response = await self.send('POST', f"/v1/research/{record['id']}/identity-review", json=payload, headers={'Idempotency-Key': f'identity-{index}'})
            self.assertEqual(response.status_code, 200, response.text)
            record = response.json()
            if 'We count stock manually each Friday.' in html:
                response = await self.send('POST', f"/v1/research/{record['id']}/need-analysis", json=analysis(record,
                    fit='possible_fit', existing_solution_status='source_described', existing_solutions=[quote(record, 'online booking calendar')],
                    replacement_reason='A fictional test hypothesis, not real buying need.'), headers={'Idempotency-Key': f'analysis-{index}'})
                self.assertEqual(response.status_code, 200, response.text)
                record = response.json()
        return record

    async def create_baseline(self, records, *, mode='synthetic', key='baseline', name='Fictional quality baseline', **extra):
        response = await self.send('POST', '/v1/quality/baselines', json={
            'name': name, 'mode': mode, 'research_ids': [r['id'] for r in records], **extra}, headers={'Idempotency-Key': key})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def audit(self, baseline, payload, *, index=0, key='audit', status=200):
        case = baseline['cases'][index]
        response = await self.send('POST', f"/v1/quality/baselines/{baseline['id']}/cases/{case['research_id']}/audit",
                                   json=payload, headers={'Idempotency-Key': key})
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    async def reload(self, baseline):
        response = await self.send('GET', f"/v1/quality/baselines/{baseline['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_auth_origin_missing_records_and_input_bounds(self):
        paths = [('GET', '/v1/quality/baselines'), ('POST', '/v1/quality/baselines'),
                 ('GET', '/v1/quality/baselines/missing'), ('GET', '/v1/quality/baselines/missing/export'),
                 ('POST', '/v1/quality/baselines/missing/cases/missing/audit'), ('GET', '/v1/quality/baselines/missing/cases/missing/history')]
        for method, path in paths:
            self.assertEqual((await self.send(method, path, json={}, headers={'Authorization': ''})).status_code, 401)
            self.assertEqual((await self.send(method, path, json={}, headers={'Origin': 'https://evil.example'})).status_code, 403)
        self.assertEqual((await self.send('GET', '/v1/quality/baselines/missing')).status_code, 404)
        self.assertEqual((await self.send('GET', '/v1/quality/baselines/missing/cases/missing/history')).status_code, 404)
        for payload in ({'name': 'ab', 'mode': 'live', 'research_ids': ['x']}, {'name': 'Test', 'mode': 'all', 'research_ids': ['x']},
                        {'name': 'Test', 'mode': 'live', 'research_ids': []}, {'name': 'Test', 'mode': 'live', 'research_ids': ['x'] * 101},
                        {'name': 'Test', 'mode': 'live', 'research_ids': ['x', 'x']}, {'name': 'Test', 'mode': 'live', 'research_ids': ['x'], 'split': 'training'},
                        {'name': 'Test', 'mode': 'live', 'research_ids': ['x'], 'auto_score': True}):
            self.assertEqual((await self.send('POST', '/v1/quality/baselines', json=payload, headers={'Idempotency-Key': 'invalid'})).status_code, 422)
        valid = {'name': 'Test', 'mode': 'live', 'research_ids': ['missing']}
        self.assertEqual((await self.send('POST', '/v1/quality/baselines', json=valid)).status_code, 422)
        self.assertEqual((await self.send('POST', '/v1/quality/baselines', json=valid, headers={'Idempotency-Key': 'missing'})).status_code, 404)

    async def test_six_segments_start_unreviewed_and_keep_metadata(self):
        records = []
        for index, (offer, geo) in enumerate((offer, geo) for offer in ('Appointment support', 'Stock planning', 'Tender alerts') for geo in ('Lahore', 'Karachi')):
            records.append(await self.make_case(index + 1, offer=offer, geography=geo))
        baseline = await self.create_baseline(records, split='holdout')
        self.assertEqual(len(baseline['report']['segments']), 6)
        self.assertEqual(baseline['report']['requirements']['offer_labels'], 3)
        self.assertEqual(baseline['report']['requirements']['geography_labels'], 2)
        self.assertEqual(baseline['report']['requirements']['real_fully_reviewed_cases'], 0)
        self.assertEqual(baseline['report']['overall']['fully_reviewed_cases'], 0)
        self.assertEqual(baseline['report']['release_readiness'], 'not_established')
        self.assertEqual(baseline['split'], 'holdout')
        self.assertIsNone(baseline['model_hash'])
        self.assertIn('cpu', baseline['hardware'])
        self.assertEqual(len(baseline['dataset_sha256']), 64)
        self.assertEqual(len(baseline['configuration']['capture_code_sha256']), 64)
        self.assertEqual([case['research_id'] for case in baseline['cases']], [r['id'] for r in records])
        for segment in baseline['report']['segments']:
            self.assertIsNone(segment['identity_accuracy']['rate'])
            self.assertEqual(segment['identity_accuracy']['unreviewed'], 1)
            self.assertEqual(segment['factual_reference_coverage']['rate'], 1)
            self.assertIsNone(segment['audited_evidence_support']['rate'])
            self.assertIsNone(segment['precision_at_20']['rate'])
        self.assertEqual(self.calls, [])

    async def test_mixed_modes_repeated_source_urls_and_partial_capture_roll_back(self):
        synthetic = await self.make_case()
        live = await self.make_case(2, synthetic=False)
        for ids, mode in (([synthetic['id'], live['id']], 'synthetic'), ([synthetic['id'], live['id']], 'live'), ([synthetic['id'], 'missing'], 'synthetic')):
            response = await self.send('POST', '/v1/quality/baselines', json={'name': 'Mixed test', 'mode': mode, 'research_ids': ids}, headers={'Idempotency-Key': 'mixed'})
            self.assertIn(response.status_code, (422, 404))
        repeat = await self.make_case(3, reviewed=False, url=synthetic['source_url'])
        response = await self.send('POST', '/v1/quality/baselines', json={'name': 'Repeat test', 'mode': 'synthetic',
            'research_ids': [synthetic['id'], repeat['id']]}, headers={'Idempotency-Key': 'repeat'})
        self.assertEqual(response.status_code, 422)
        with Repository(self.directory / 'leaddesk.sqlite3').connect() as db:
            for table in ('quality_baseline', 'quality_case', 'quality_request'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)

    async def test_capture_remains_frozen_after_contact_correction(self):
        record = await self.make_case()
        baseline = await self.create_baseline([record])
        await self.send('POST', '/v1/feedback', json={'contact_id': record['contacts'][0]['id'], 'category': 'wrong_branch'})
        changed = await self.reload(baseline)
        self.assertEqual(changed['dataset_sha256'], baseline['dataset_sha256'])
        self.assertEqual(changed['cases'][0]['snapshot'], baseline['cases'][0]['snapshot'])
        self.assertTrue(changed['cases'][0]['source_changed_since_snapshot'])
        self.assertEqual(changed['report']['overall']['changed_since_snapshot'], 1)
        self.assertFalse(changed['cases'][0]['snapshot']['lead']['contacts'][0]['suppressed'])
        self.assertEqual(changed['cases'][0]['snapshot']['lead']['saved_fit'], 'possible_fit')

    async def test_complete_audit_reports_small_sample_uncertainty_without_certification(self):
        record = await self.make_case()
        baseline = await self.create_baseline([record])
        saved = await self.audit(baseline, complete_audit(baseline['cases'][0]))
        report = saved['report']['overall']
        self.assertEqual(report['identity_accuracy']['passed'], 1)
        self.assertEqual(report['identity_accuracy']['reviewed'], 1)
        self.assertEqual(report['identity_accuracy']['gate_status'], 'observed_target_met')
        self.assertLess(report['identity_accuracy']['wilson_95'][0], .3)
        self.assertEqual(report['contact_attribution_precision']['reviewed'], len(record['contacts']))
        self.assertEqual(report['fully_reviewed_cases'], 1)
        self.assertEqual(saved['report']['requirements']['real_fully_reviewed_cases'], 0)
        self.assertEqual(saved['report']['release_readiness'], 'not_established')
        self.assertNotEqual(saved['report']['review_set_sha256'], baseline['report']['review_set_sha256'])
        current = (await self.send('GET', f"/v1/research/{record['id']}")).json()
        self.assertEqual(current, record)
        self.assertIsNone(current['assessment']['budget'])
        self.assertEqual(current['assessment']['intent_state'], 'unknown')

    async def test_unknown_and_partial_audits_never_become_correct(self):
        record = await self.make_case()
        baseline = await self.create_baseline([record])
        unknown = await self.audit(baseline, {'expected_revision': 0, 'reviewer': 'Fictional reviewer'})
        metric = unknown['report']['overall']['identity_accuracy']
        self.assertIsNone(metric['rate'])
        self.assertEqual(metric['unknown'], 1)
        self.assertEqual(metric['passed'], 0)
        self.assertEqual(metric['unreviewed'], 0)
        self.assertEqual(unknown['report']['overall']['fully_reviewed_cases'], 0)
        payload = complete_audit(unknown['cases'][0])
        payload['claims'] = payload['claims'][:1]
        partial = await self.audit(unknown, payload, key='partial')
        support = partial['report']['overall']['audited_evidence_support']
        self.assertEqual(support['reviewed'], 1)
        self.assertGreater(support['unreviewed'], 0)
        self.assertEqual(support['gate_status'], 'incomplete')
        self.assertEqual(partial['report']['overall']['fully_reviewed_cases'], 0)

    async def test_failing_audit_is_visible_by_segment_and_error_flag(self):
        record = await self.make_case()
        baseline = await self.create_baseline([record])
        payload = complete_audit(baseline['cases'][0], issue_tags=['wrong_branch', 'directory_operator'])
        payload['contacts'][0]['outcome'] = 'fail'
        payload['claims'][0]['outcome'] = 'fail'
        payload['relevance']['outcome'] = 'fail'
        saved = await self.audit(baseline, payload)
        segment = saved['report']['segments'][0]
        self.assertEqual(segment['contact_attribution_precision']['failed'], 1)
        self.assertEqual(segment['contact_attribution_precision']['gate_status'], 'below_target')
        self.assertEqual(segment['audited_evidence_support']['failed'], 1)
        self.assertEqual(segment['reviewed_relevance_rate']['rate'], 0)
        self.assertEqual(segment['reviewer_issue_tags'], {'wrong_branch': 1, 'directory_operator': 1})

    async def test_audit_rejects_foreign_targets_citations_and_missing_reasons(self):
        first = await self.make_case()
        other = await self.make_case(2)
        baseline = await self.create_baseline([first])
        valid = complete_audit(baseline['cases'][0])
        cases = []
        for field in ('identity', 'relevance'):
            bad = copy.deepcopy(valid); bad[field]['evidence_ids'] = [other['evidence'][0]['id']]; cases.append(bad)
            bad = copy.deepcopy(valid); bad[field]['reason'] = ''; cases.append(bad)
        bad = copy.deepcopy(valid); bad['contacts'][0]['target_id'] = other['contacts'][0]['id']; cases.append(bad)
        bad = copy.deepcopy(valid); bad['contacts'][0]['evidence_ids'] = first['contacts'][1]['evidence_ids']; cases.append(bad)
        bad = copy.deepcopy(valid); bad['claims'][0]['target_id'] = 'invented-claim'; cases.append(bad)
        bad = copy.deepcopy(valid); bad['claims'][0]['evidence_ids'] = first['contacts'][0]['evidence_ids']; cases.append(bad)
        bad = copy.deepcopy(valid); bad['contacts'].append(bad['contacts'][0]); cases.append(bad)
        bad = copy.deepcopy(valid); bad['claims'].append(bad['claims'][0]); cases.append(bad)
        bad = copy.deepcopy(valid); bad['expected_revision'] = True; cases.append(bad)
        bad = copy.deepcopy(valid); bad['issue_tags'] = ['invented']; cases.append(bad)
        bad = copy.deepcopy(valid); bad['issue_tags'] = ['wrong_phone', 'wrong_phone']; cases.append(bad)
        bad = copy.deepcopy(valid); bad['identity']['evidence_ids'] *= 2; cases.append(bad)
        for index, payload in enumerate(cases):
            await self.audit(baseline, payload, key=f'bad-{index}', status=422)
        self.assertIsNone((await self.reload(baseline))['cases'][0]['audit'])

    async def test_unresolved_identity_and_extracted_contacts_are_abstentions(self):
        record = await self.make_case(reviewed=False)
        baseline = await self.create_baseline([record])
        report = baseline['report']['overall']
        self.assertEqual(report['identity_abstentions'], 1)
        self.assertEqual(report['contact_abstentions_or_exclusions'], len(record['contacts']))
        self.assertEqual(report['contact_attribution_precision']['eligible'], 0)
        self.assertIsNone(report['identity_accuracy']['rate'])
        await self.audit(baseline, {'expected_revision': 0, 'reviewer': 'Fictional reviewer', 'identity': known([record['evidence'][0]['id']])}, status=422)

    async def test_audit_retries_revisions_conflicts_and_old_replay(self):
        record = await self.make_case()
        baseline = await self.create_baseline([record])
        replay = await self.create_baseline([record])
        self.assertEqual(replay['id'], baseline['id'])
        payload = complete_audit(baseline['cases'][0])
        first = await self.audit(baseline, payload)
        repeat = await self.audit(baseline, payload)
        self.assertEqual(repeat['cases'][0]['audit']['revision'], 1)
        await self.audit(baseline, payload | {'notes': 'Conflicting key reuse'}, status=409)
        await self.audit(baseline, payload, key='stale', status=409)
        second = await self.audit(first, complete_audit(first['cases'][0], reviewer='Another fictional reviewer'), key='second')
        replay = await self.audit(baseline, payload)
        self.assertEqual(replay['cases'][0]['audit'], second['cases'][0]['audit'])
        await self.audit(second, complete_audit(second['cases'][0]), key='baseline', status=409)
        response = await self.send('POST', '/v1/quality/baselines', json={'name': 'Different name', 'mode': 'synthetic', 'research_ids': [record['id']]}, headers={'Idempotency-Key': 'baseline'})
        self.assertEqual(response.status_code, 409)

    async def test_concurrent_reviewers_cannot_overwrite_the_same_revision(self):
        record = await self.make_case()
        baseline = await self.create_baseline([record])
        path = f"/v1/quality/baselines/{baseline['id']}/cases/{record['id']}/audit"
        first = complete_audit(baseline['cases'][0])
        second = complete_audit(baseline['cases'][0], reviewer='Another fictional reviewer')
        responses = await asyncio.gather(
            self.send('POST', path, json=first, headers={'Idempotency-Key': 'first-reviewer'}),
            self.send('POST', path, json=second, headers={'Idempotency-Key': 'second-reviewer'}))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        self.assertEqual((await self.reload(baseline))['cases'][0]['audit']['revision'], 1)

    async def test_revisions_do_not_inflate_samples_and_history_limit_is_visible(self):
        record = await self.make_case()
        baseline = await self.create_baseline([record])
        quality = QualityRepository(Repository(self.directory / 'leaddesk.sqlite3'))
        for revision in range(101):
            quality.save_audit(baseline['id'], record['id'], AuditInput(expected_revision=revision, reviewer='Fictional revision test'), f'revision-{revision}')
        history = quality.history(baseline['id'], record['id'])
        self.assertEqual(len(history['items']), 100)
        self.assertTrue(history['limited'])
        self.assertEqual(history['items'][0]['revision'], 101)
        self.assertEqual(quality.get(baseline['id'])['report']['overall']['sample_count'], 1)
        self.assertEqual(quality.get(baseline['id'])['dataset_sha256'], baseline['dataset_sha256'])

    async def test_suppressed_contacts_before_capture_never_enter_attribution_precision(self):
        record = await self.make_case()
        cid = record['contacts'][0]['id']
        await self.send('POST', '/v1/feedback', json={'contact_id': cid, 'category': 'wrong_contact'})
        baseline = await self.create_baseline([record])
        self.assertEqual(baseline['report']['overall']['contact_attribution_precision']['eligible'], len(record['contacts']) - 1)
        payload = complete_audit(baseline['cases'][0])
        next(v for v in payload['contacts'] if v['target_id'] == cid)['outcome'] = 'fail'
        saved = await self.audit(baseline, payload)
        self.assertEqual(saved['report']['overall']['contact_attribution_precision']['failed'], 0)
        self.assertEqual(saved['report']['overall']['contact_abstentions_or_exclusions'], 1)

    async def test_fictional_demo_covers_segments_errors_unknowns_and_abstention(self):
        report = build_quality_demo(Repository(self.directory / 'disposable-demo.sqlite3'))
        self.assertTrue(report['demonstration']['fictional'])
        self.assertEqual(report['mode'], 'synthetic')
        self.assertEqual(len(report['cases']), 6)
        self.assertEqual(len(report['report']['segments']), 6)
        self.assertTrue(all(c['snapshot']['research']['synthetic'] for c in report['cases']))
        self.assertEqual(report['report']['requirements']['real_fully_reviewed_cases'], 0)
        self.assertEqual(report['report']['overall']['identity_abstentions'], 1)
        self.assertGreater(report['report']['overall']['contact_attribution_precision']['failed'], 0)
        self.assertEqual(report['report']['overall']['reviewed_relevance_rate']['unknown'], 2)
        self.assertEqual(report['report']['release_readiness'], 'not_established')
        self.assertTrue(all(g['status'] == 'not_measured' for g in report['report']['other_release_gates']))
        self.assertEqual(self.calls, [])

    async def test_history_restart_immutability_and_export_contents(self):
        record = await self.make_case()
        baseline = await self.create_baseline([record])
        baseline = await self.audit(baseline, complete_audit(baseline['cases'][0]))
        endpoint = f"/v1/quality/baselines/{baseline['id']}/cases/{record['id']}/history"
        history = (await self.send('GET', endpoint)).json()
        self.assertEqual(history['items'][0]['revision'], 1)
        self.assertFalse(history['limited'])
        response = await self.send('GET', f"/v1/quality/baselines/{baseline['id']}/export")
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment;', response.headers['content-disposition'])
        self.assertIn('synthetic', response.headers['content-disposition'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn(TOKEN, response.text)
        exported = response.json()
        self.assertEqual(exported['cases'], baseline['cases'])
        self.assertEqual(exported['report']['segments'], baseline['report']['segments'])
        restarted = QualityRepository(Repository(self.directory / 'leaddesk.sqlite3')).get(baseline['id'])
        self.assertEqual(restarted['cases'], baseline['cases'])
        repo = Repository(self.directory / 'leaddesk.sqlite3')
        with repo.connect() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            for table in ('quality_baseline', 'quality_case', 'quality_audit'):
                for sql in (f'UPDATE {table} SET baseline_id=baseline_id' if table != 'quality_baseline' else f'UPDATE {table} SET name=name', f'DELETE FROM {table}'):
                    with self.assertRaises(sqlite3.IntegrityError):
                        db.execute(sql)

    async def test_snapshot_and_export_size_limits_are_explicit(self):
        record = await self.make_case()
        with patch('backend.storage.quality.MAX_SNAPSHOT_BYTES', 1):
            response = await self.send('POST', '/v1/quality/baselines', json={'name': 'Oversize test', 'mode': 'synthetic', 'research_ids': [record['id']]}, headers={'Idempotency-Key': 'oversize'})
        self.assertEqual(response.status_code, 413)
        self.assertEqual((await self.send('GET', '/v1/quality/baselines')).json()['total'], 0)
        baseline = await self.create_baseline([record])
        with patch('backend.api.quality.MAX_SNAPSHOT_BYTES', 1):
            response = await self.send('GET', f"/v1/quality/baselines/{baseline['id']}/export")
        self.assertEqual(response.status_code, 413)
        self.assertNotIn('content-disposition', response.headers)

    async def test_foreign_comparison_evidence_is_frozen_with_the_case(self):
        first = await self.make_case()
        second = await self.make_case(2, reviewed=False, url='https://fictional-1.example/south')
        payload = identity(first, expected_revision=1, comparisons=[{'research_id': second['id'], 'decision': 'different_branch',
            'local_evidence_ids': [first['evidence'][0]['id']], 'other_evidence_ids': [second['evidence'][0]['id']],
            'reason': 'Fictional branch comparison for this test.'}])
        response = await self.send('POST', f"/v1/research/{first['id']}/identity-review", json=payload, headers={'Idempotency-Key': 'compare'})
        self.assertEqual(response.status_code, 200, response.text)
        baseline = await self.create_baseline([response.json()])
        sources = baseline['cases'][0]['snapshot']['comparison_sources']
        self.assertEqual(sources[0]['id'], second['id'])
        self.assertEqual(sources[0]['evidence'], second['evidence'])
        audit = complete_audit(baseline['cases'][0])
        audit['identity']['evidence_ids'] = [second['evidence'][0]['id']]
        await self.audit(baseline, audit, status=422)
        audit['identity']['evidence_ids'].append(first['evidence'][0]['id'])
        saved = await self.audit(baseline, audit, key='scoped-comparison')
        self.assertEqual(saved['cases'][0]['audit']['revision'], 1)

    async def test_audits_allow_large_bounded_forms_without_relaxing_other_routes(self):
        html = '<h1>Fictional email workshop</h1><p>Address: Lahore.</p>' + ''.join(f'<p>Contact: team-{i}@fictional.example</p>' for i in range(50))
        record = await self.make_case(html=html)
        baseline = await self.create_baseline([record])
        payload = complete_audit(baseline['cases'][0])
        for verdict in [payload['identity'], payload['relevance'], *payload['contacts'], *payload['claims']]:
            verdict['reason'] = ('Fictional explanation. ' * 18)[:390]
        self.assertGreater(len(json.dumps(payload)), 16000)
        self.assertLess(len(json.dumps(payload)), 128 * 1024)
        await self.audit(baseline, payload)
        path = f"/v1/quality/baselines/{baseline['id']}/cases/{record['id']}/audit"
        self.assertEqual((await self.send('POST', path, json={'notes': 'x' * (128 * 1024)})).status_code, 413)
        self.assertEqual((await self.send('POST', '/v1/quality/baselines', json={'name': 'x' * 16000})).status_code, 413)

    async def test_migration_from_sprint_six_preserves_existing_data(self):
        path = self.directory / 'sprint-six.sqlite3'
        for migration in sorted(Path('backend/storage/migrations').glob('*.sql'))[:5]:
            with sqlite3.connect(path) as db:
                db.executescript(migration.read_text())
                db.execute('INSERT INTO schema_migration VALUES(?,?)', (int(migration.name[:3]), 'old'))
        with patch.object(Repository, 'migrate'):
            old = Repository(path)
        html = '<h1>Fictional saved business</h1><p>hello@fictional.example</p>'
        record = old.save({'product': 'Original offer', 'location': 'Original town'}, 'old', Page('https://old.example/', html.encode(), html), extract(html), True)
        corrected = old.correct(record['contacts'][0]['id'], 'wrong_contact', 'Original feedback', None)
        with old.connect() as db:
            tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name<>'schema_migration' ORDER BY name")]
            before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table}')] for table in tables}
        upgraded = Repository(path)
        self.assertEqual(upgraded.get(record['id']), corrected)
        with upgraded.connect() as db:
            self.assertEqual(before, {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table}')] for table in tables})
            self.assertEqual(db.execute('SELECT COUNT(*) FROM schema_migration').fetchone()[0], 18)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])


class QualityStatisticsTests(unittest.TestCase):
    def test_inferred_claims_are_not_mislabelled_as_factual_audit_units(self):
        record = {'claims': [{'id': 'fact', 'value': 'Published source name', 'evidence_id': 'e1', 'inference_flag': 0},
                             {'id': 'inference', 'value': 'Might buy', 'evidence_id': 'e1', 'inference_flag': 1}], 'contacts': [], 'assessment': None}
        self.assertEqual([unit['id'] for unit in factual_units(record)], ['claim:fact'])

    def test_wilson_intervals_unknowns_and_gate_statuses(self):
        empty = proportion([], .95)
        self.assertIsNone(empty['rate'])
        self.assertIsNone(empty['wilson_95'])
        one = proportion(['pass'], .95)
        self.assertAlmostEqual(one['wilson_95'][0], .2065493144)
        self.assertAlmostEqual(one['wilson_95'][1], 1)
        twenty = proportion(['pass'] * 20, .95)
        self.assertAlmostEqual(twenty['wilson_95'][0], .8388748419)
        failed = proportion(['fail'] * 20, .95)
        self.assertAlmostEqual(failed['wilson_95'][1], .1611251581)
        self.assertEqual(failed['gate_status'], 'below_target')
        mixed = proportion(['pass', 'fail', 'unknown', 'unreviewed'], .95)
        self.assertEqual(mixed['rate'], .5)
        self.assertEqual(mixed['reviewed'], 2)
        self.assertEqual(mixed['unknown'], 1)
        self.assertEqual(mixed['unreviewed'], 1)
        self.assertEqual(mixed['gate_status'], 'incomplete')

    def test_reference_presence_is_separate_from_human_support(self):
        record = {'evidence': [{'id': 'e1'}]}
        case = {'snapshot': {'research': record, 'comparison_sources': [], 'lead': {
            'product': 'Any offer', 'target_geography': 'Any town', 'identity_status': 'unresolved', 'contacts': []},
            'units': [{'id': 'claim:1', 'evidence_ids': ['missing']}, {'id': 'claim:2', 'evidence_ids': []}]}, 'audit': None}
        report = quality_report([case], 'synthetic')
        self.assertEqual(report['overall']['factual_reference_coverage']['failed'], 2)
        self.assertIsNone(report['overall']['audited_evidence_support']['rate'])
        self.assertEqual(report['overall']['fully_reviewed_cases'], 0)
        self.assertEqual(report['release_readiness'], 'not_established')
