"""B09 dashboard/export regression cases using invented pages and local SQLite."""
import csv
import io
import json
import unittest
from unittest.mock import patch

from backend.adapters.fetch import Page
from backend.domain.extract import extract
from backend.domain.lead_export import safe_cell
from backend.domain.leads import LeadFilters, LeadPage
from backend.domain.assessments import IdentityReview
from backend.storage.assessments import AssessmentRepository
from backend.storage.leads import LeadRepository
from backend.storage.repository import Repository
from tests.support import APITestCase, TOKEN
from tests.test_assessments import SOURCE, analysis, identity, quote


class LeadTests(APITestCase):
    async def make_record(self, key='first', url='https://synthetic.example/', html=SOURCE, **context):
        with patch('tests.support.HTML', html):
            response = await self.research(key, url, **context)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def review(self, record, payload, kind='identity', key='review'):
        route = 'identity-review' if kind == 'identity' else 'need-analysis'
        response = await self.send('POST', f"/v1/research/{record['id']}/{route}", json=payload,
                                   headers={'Idempotency-Key': key})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def leads(self, **filters):
        response = await self.send('GET', '/v1/leads', params=filters)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def exported(self, **filters):
        response = await self.send('GET', '/v1/leads/export', params=filters)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertIn('attachment;', response.headers['content-disposition'])
        self.assertNotIn(TOKEN, response.text)
        return response

    async def test_auth_origin_and_query_validation(self):
        for path in ('/v1/leads', '/v1/leads/export'):
            self.assertEqual((await self.send('GET', path, headers={'Authorization': ''})).status_code, 401)
            self.assertEqual((await self.send('GET', path, headers={'Origin': 'https://evil.example'})).status_code, 403)
        for params in ({'mode': 'all'}, {'limit': 0}, {'limit': 51}, {'offset': -1}, {'offset': 201},
                       {'identity': 'verified'}, {'contact': 'confirmed'}, {'fit': 'guaranteed'},
                       {'analysis': 'verified'}, {'review': 'approved'}, {'q': 'x' * 201}, {'unknown': 'yes'}):
            self.assertEqual((await self.send('GET', '/v1/leads', params=params)).status_code, 422, params)
        for params in ({'format': 'html'}, {'offset': 20}, {'limit': 5}):
            self.assertEqual((await self.send('GET', '/v1/leads/export', params=params)).status_code, 422)

    async def test_empty_results_and_downloads_have_schema(self):
        page = await self.leads()
        self.assertEqual(page['items'], [])
        self.assertEqual(page['coverage']['matched'], 0)
        self.assertIsNone(page['next_offset'])
        document = (await self.exported()).json()
        self.assertEqual(document['records'], [])
        self.assertEqual(document['schema_version'], '1')
        self.assertFalse(document['synthetic'])
        response = await self.exported(format='csv')
        self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'))
        rows = csv.DictReader(io.StringIO(response.text.lstrip('\ufeff')))
        self.assertIn('contact_effective_state', rows.fieldnames)
        self.assertEqual(list(rows), [])

    async def test_real_and_synthetic_records_and_exports_stay_separate(self):
        real = await self.make_record()
        demo = (await self.send('POST', '/v1/demo', headers={'Idempotency-Key': 'demo'})).json()
        self.assertEqual([r['id'] for r in (await self.leads())['items']], [real['id']])
        self.assertEqual([r['id'] for r in (await self.leads(mode='synthetic'))['items']], [demo['id']])
        exported = (await self.exported(mode='synthetic')).json()
        self.assertTrue(exported['synthetic'])
        self.assertTrue(exported['records'][0]['lead']['synthetic'])
        self.assertNotIn(real['id'], json.dumps(exported))
        self.assertFalse((await self.exported()).json()['synthetic'])
        self.assertEqual(self.calls, ['https://synthetic.example/'])

    async def test_search_accepts_arbitrary_offers_and_locations_and_literal_text(self):
        record = await self.make_record(product='Custom irrigation audits', location='Multan')
        for text in ('IRRIGATION', 'multan', 'North', '555-0148', 'synthetic.example'):
            self.assertEqual((await self.leads(q=text))['items'][0]['id'], record['id'])
        for text in ('unrelated offer', '%', "' OR 1=1 --"):
            self.assertEqual((await self.leads(q=text))['items'], [])
        item = (await self.leads())['items'][0]
        self.assertIsNone(item['business_name'])
        self.assertIsNone(item['address'])
        self.assertEqual(item['target_geography'], 'Multan')
        self.assertEqual(item['intent_state'], 'unknown')
        self.assertIsNone(item['budget'])
        self.assertFalse(item['outreach_approved'])

    async def test_identity_and_contact_filters_are_independent(self):
        record = await self.make_record()
        self.assertEqual(len((await self.leads(identity='unresolved', contact='extracted'))['items']), 1)
        record = await self.review(record, identity(record))
        self.assertEqual((await self.leads(identity='source_attributed', contact='attributed'))['items'], [])
        phone = next(c for c in record['contacts'] if c['type'] == 'phone')
        record = await self.review(record, identity(record, expected_revision=1, branch=quote(record, 'North'),
            contact_reviews=[{'contact_id': phone['id'], 'decision': 'attributed', 'evidence_ids': phone['evidence_ids']}]), key='contacts')
        lead = (await self.leads(contact='attributed'))['items'][0]
        self.assertEqual(lead['branch'], 'North')
        self.assertEqual(next(c for c in lead['contacts'] if c['id'] == phone['id'])['effective_state'], 'attributed')
        self.assertEqual(lead['review_state'], 'needs_review')
        self.assertIn('reachability', (await self.leads())['scope'])

    async def test_disputed_identity_excludes_contacts_without_faking_suppression(self):
        record = await self.make_record()
        await self.review(record, identity(record, decision='disputed'))
        lead = (await self.leads(identity='disputed', contact='excluded', review='excluded'))['items'][0]
        self.assertTrue(all(c['excluded'] for c in lead['contacts']))
        self.assertTrue(all(not c['suppressed'] for c in lead['contacts']))
        self.assertTrue(all(c['attribution_state'] == 'extracted' for c in lead['contacts']))
        self.assertEqual((await self.leads(contact='extracted'))['items'], [])
        self.assertEqual((await self.leads(contact='attributed'))['items'], [])
        exported = (await self.exported()).json()['records'][0]
        self.assertTrue(all(c['review_blocked'] for c in exported['research']['contacts']))
        self.assertTrue(all(c['excluded'] for c in exported['lead']['contacts']))

    async def test_geography_and_offer_exclusions_override_contact_availability(self):
        record = await self.make_record()
        await self.review(record, identity(record, geography='outside_target', address=quote(record, 'Lahore')))
        lead = (await self.leads(review='excluded'))['items'][0]
        self.assertTrue(all(c['excluded'] for c in lead['contacts']))
        self.assertEqual(lead['effective_fit'], 'not_a_fit')
        await self.review(record, identity(record, expected_revision=1, exclusions='excluded',
                                          exclusion_reason='Reviewer excludes this fictional segment.'), key='exclude')
        lead = (await self.leads(review='excluded'))['items'][0]
        self.assertIn('fictional segment', lead['exclusion_reasons'][0])

    async def test_contacts_missing_and_current_not_fit_are_explicit(self):
        record = await self.make_record(html='<h1>Fictional no-contact branch</h1>')
        lead = (await self.leads(contact='none'))['items'][0]
        self.assertEqual(lead['contacts'], [])
        rows = list(csv.DictReader(io.StringIO((await self.exported(format='csv')).text.lstrip('\ufeff'))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['contact_raw_value'], '')
        self.assertEqual(rows[0]['research_id'], record['id'])
        record = await self.make_record('other', 'https://other.example/')
        await self.review(record, analysis(record, fit='not_a_fit'), kind='analysis')
        lead = (await self.leads(fit='not_a_fit', review='excluded'))['items'][0]
        self.assertTrue(all(c['excluded'] for c in lead['contacts']))

    async def test_contact_corrections_update_existing_and_future_exports(self):
        first = await self.make_record()
        second = await self.make_record('second')
        other = await self.make_record('other', 'https://other.example/')
        cid = first['contacts'][0]['id']
        await self.send('POST', '/v1/feedback', json={'contact_id': cid, 'category': 'wrong_branch',
            'expected_value': 'Unverified proposed correction', 'comment': 'Fictional branch mismatch'})
        third = await self.make_record('third')
        document = (await self.exported(contact='excluded')).json()
        self.assertEqual({r['lead']['id'] for r in document['records']}, {first['id'], second['id'], third['id']})
        self.assertNotIn(other['id'], [r['lead']['id'] for r in document['records']])
        for item in document['records']:
            corrected = next(c for c in item['lead']['contacts'] if c['raw_value'] == first['contacts'][0]['raw_value'])
            self.assertTrue(corrected['excluded'])
            self.assertTrue(corrected['suppressed'])
            self.assertEqual(corrected['effective_state'], 'excluded')
        audit = next(r['research'] for r in document['records'] if r['lead']['id'] == first['id'])
        self.assertEqual(audit['feedback'][0]['expected_value'], 'Unverified proposed correction')
        self.assertNotIn('Unverified proposed correction', [c['raw_value'] for c in audit['contacts']])

    async def test_stale_possible_fit_is_preserved_and_removed_from_fit_filter(self):
        record = await self.make_record()
        record = await self.review(record, identity(record, geography='matches', address=quote(record, 'Lahore'),
            exclusions='clear', exclusion_reason='Reviewed offer exclusions against fictional source.'))
        record = await self.review(record, analysis(record, fit='possible_fit',
            existing_solution_status='source_described', existing_solutions=[quote(record, 'online booking calendar')],
            replacement_reason='Check if stock scheduling remains a gap.'), kind='analysis', key='analysis')
        self.assertEqual((await self.leads(fit='possible_fit', analysis='current'))['coverage']['matched'], 1)
        await self.send('POST', '/v1/feedback', json={'contact_id': record['contacts'][0]['id'], 'category': 'stale'})
        self.assertEqual((await self.leads(fit='possible_fit'))['items'], [])
        lead = (await self.leads(analysis='needs_review', fit='review'))['items'][0]
        self.assertEqual(lead['saved_fit'], 'possible_fit')
        self.assertEqual(lead['effective_fit'], 'review')
        self.assertIn('Recheck', lead['next_action'])
        item = (await self.exported()).json()['records'][0]
        self.assertEqual(item['research']['assessment']['analysis']['document']['fit'], 'possible_fit')
        self.assertEqual(len(item['assessment_history']), 2)

    async def test_source_reviewed_label_still_has_unknown_interest_and_budget(self):
        record = await self.make_record()
        record = await self.review(record, identity(record, geography='matches', address=quote(record, 'Lahore'),
            exclusions='clear', exclusion_reason='Checked', contact_reviews=[{'contact_id': c['id'],
                'decision': 'attributed', 'evidence_ids': c['evidence_ids']} for c in record['contacts']]))
        await self.review(record, analysis(record, fit='possible_fit', existing_solution_status='source_described',
            existing_solutions=[quote(record, 'online booking calendar')], replacement_reason='Check stock review gaps.'),
            kind='analysis', key='analysis')
        lead = (await self.leads(review='source_reviewed'))['items'][0]
        self.assertEqual(lead['intent_state'], 'unknown')
        self.assertIsNone(lead['budget'])
        self.assertTrue(all(not c['outreach_approved'] and c['reachability'] == 'unknown' for c in lead['contacts']))

    async def test_exports_include_foreign_comparison_evidence_and_history(self):
        record = await self.make_record()
        other = await self.make_record('other', 'https://synthetic.example/branch')
        comparison = {'research_id': other['id'], 'decision': 'different_branch',
            'local_evidence_ids': [record['evidence'][0]['id']], 'other_evidence_ids': [other['evidence'][0]['id']],
            'reason': 'Synthetic reviewer comparison.'}
        await self.review(record, identity(record, comparisons=[comparison]))
        # A later revision removes the explicit comparison; history retains its evidence.
        await self.review(record, identity(record, expected_revision=1), key='revision-two')
        item = (await self.exported(q='synthetic.example/')).json()['records']
        item = next(item for item in item if item['lead']['id'] == record['id'])
        self.assertEqual(len(item['assessment_history']), 2)
        self.assertFalse(item['history_limited'])
        self.assertEqual(item['comparison_sources'][0]['id'], other['id'])
        ids = {e['id'] for e in item['comparison_sources'][0]['evidence']}
        self.assertTrue(set(comparison['other_evidence_ids']) <= ids)

    async def test_changed_comparison_removes_effective_attribution_from_filters(self):
        first = await self.make_record()
        second = await self.make_record('other', 'https://synthetic.example/south', SOURCE.replace('North', 'South'))
        comparison = {'research_id': second['id'], 'decision': 'different_branch',
            'local_evidence_ids': quote(first, 'North')['evidence_ids'],
            'other_evidence_ids': quote(second, 'South')['evidence_ids'], 'reason': 'Separate fictional branch names.'}
        phone = next(c for c in first['contacts'] if c['type'] == 'phone')
        first = await self.review(first, identity(first, comparisons=[comparison], branch=quote(first, 'North'),
            contact_reviews=[{'contact_id': phone['id'], 'decision': 'attributed', 'evidence_ids': phone['evidence_ids']}]))
        self.assertEqual((await self.leads(contact='attributed'))['items'][0]['id'], first['id'])
        await self.review(first, analysis(first), kind='analysis', key='analysis')
        await self.review(second, {'expected_revision': 0, 'decision': 'disputed'}, key='other-change')
        self.assertEqual((await self.leads(contact='attributed'))['items'], [])
        stale = (await self.leads(analysis='needs_review'))['items'][0]
        self.assertEqual(stale['identity_status'], 'unresolved')
        self.assertEqual(next(c for c in stale['contacts'] if c['id'] == phone['id'])['effective_state'], 'extracted')
        self.assertEqual((await self.leads())['coverage']['matched'], 2)

    async def test_export_size_limit_fails_explicitly_without_partial_download(self):
        await self.make_record()
        with patch('backend.storage.leads.MAX_EXPORT_BYTES', 10):
            for format in ('json', 'csv'):
                response = await self.send('GET', '/v1/leads/export', params={'format': format})
                self.assertEqual(response.status_code, 413)
                self.assertIn('Narrow', response.json()['message'])
                self.assertNotIn('content-disposition', response.headers)
        self.assertEqual(len((await self.exported()).json()['records']), 1)

    async def test_export_reports_history_limit_and_keeps_current_review(self):
        record = await self.make_record()
        repo = Repository(self.directory / 'leaddesk.sqlite3')
        assessments = AssessmentRepository(repo)
        for revision in range(101):
            assessments.save(record['id'], 'identity', IdentityReview(**identity(record, expected_revision=revision)), f'revision-{revision}')
        item = (await self.exported()).json()['records'][0]
        self.assertTrue(item['history_limited'])
        self.assertEqual(item['history_limit'], 100)
        self.assertEqual(len(item['assessment_history']), 100)
        self.assertEqual(item['assessment_history'][0]['revision'], 101)
        self.assertEqual(item['research']['assessment']['identity']['revision'], 101)

    async def test_queued_discovery_results_export_with_frozen_brief_and_own_contacts(self):
        response = await self.send('POST', '/v1/briefs', headers={'Idempotency-Key': 'brief'},
            json={'offer': 'Fictional stock review', 'target_geography': 'Synthetic market'})
        self.assertEqual(response.status_code, 200, response.text)
        brief = response.json()
        response = await self.send('POST', '/v1/jobs', headers={'Idempotency-Key': 'job'},
            json={'brief_id': brief['id'], 'brief_revision': brief['revision'], 'synthetic': True})
        self.assertEqual(response.status_code, 202, response.text)
        for _ in range(3):
            self.app.state.workflow_worker.run_once()
        page = await self.leads(mode='synthetic')
        self.assertEqual(page['coverage']['matched'], 2)
        document = (await self.exported(mode='synthetic')).json()
        for item in document['records']:
            self.assertEqual(item['research']['product_brief'], brief)
            self.assertEqual(item['lead']['product'], 'Fictional stock review')
            self.assertTrue(item['lead']['synthetic'])
            self.assertEqual(item['lead']['identity_status'], 'unresolved')
            self.assertTrue(all(c['effective_state'] == 'extracted' for c in item['lead']['contacts']))
            self.assertNotIn('operator@fictional-directory', ' '.join(c['raw_value'] for c in item['lead']['contacts']))
        self.assertEqual(self.calls, [])

    async def test_pagination_is_deterministic_and_export_covers_all_pages(self):
        repo = Repository(self.directory / 'leaddesk.sqlite3')
        page = Page('https://fictional.example/', SOURCE.encode(), SOURCE)
        records = [repo.save({'product': 'Irrigation', 'location': 'Any town'}, f'r-{i}', page, extract(SOURCE)) for i in range(25)]
        with repo.connect() as db:
            db.execute("UPDATE campaign SET created_at='2026-10-19T00:00:00+00:00'")
        first = await self.leads(limit=20)
        second = await self.leads(offset=first['next_offset'], limit=20)
        ids = [r['id'] for r in first['items'] + second['items']]
        self.assertEqual(ids, sorted((r['id'] for r in records), reverse=True))
        self.assertIsNone(second['next_offset'])
        self.assertEqual(len((await self.exported()).json()['records']), 25)
        self.assertEqual(len(list(csv.DictReader(io.StringIO((await self.exported(format='csv')).text.lstrip('\ufeff'))))), 50)

    async def test_csv_escapes_formulas_quotes_commas_newlines_and_keeps_evidence(self):
        offer = '  =HYPERLINK("https://fictional.example", "demo")\nSecond line'
        record = await self.make_record(product=offer, location='@fictional-market',
            html=SOURCE.replace('Synthetic North Workshop', '=Fictional Formula Heading'))
        document = (await self.exported()).json()
        self.assertEqual(document['records'][0]['research']['product'], offer.strip())
        response = await self.exported(format='csv')
        rows = list(csv.DictReader(io.StringIO(response.text.lstrip('\ufeff'))))
        self.assertEqual(len(rows), len(record['contacts']))
        self.assertTrue(all(row['product'].startswith("'=") for row in rows))
        self.assertTrue(all(row['source_heading'].startswith("'=") for row in rows))
        self.assertTrue(all(row['target_geography'].startswith("'@") for row in rows))
        phone = next(row for row in rows if row['contact_type'] == 'phone')
        self.assertTrue(phone['contact_raw_value'].startswith("'+"))
        self.assertEqual(phone['contact_last_checked_at'], record['contacts'][0]['last_checked_at'])
        self.assertTrue(json.loads(phone['contact_evidence_json'])[0]['content_hash'])
        audit = json.loads(phone['research_audit_json'])
        self.assertEqual(audit['research']['product'], offer.strip())
        self.assertEqual(audit['research']['evidence'], record['evidence'])
        self.assertEqual(sum(bool(row['research_audit_json']) for row in rows), 1)
        self.assertTrue(all(row['intent_state'] == 'unknown' and row['budget'] == '' for row in rows))

    async def test_export_is_read_only_and_survives_reopening_database(self):
        record = await self.make_record()
        await self.review(record, identity(record))
        repo = Repository(self.directory / 'leaddesk.sqlite3')
        with repo.connect() as db:
            before = list(db.iterdump())
        document = (await self.exported()).json()
        await self.exported(format='csv')
        with repo.connect() as db:
            self.assertEqual(before, list(db.iterdump()))
        reopened = LeadRepository(Repository(repo.path)).export(LeadFilters())
        self.assertEqual(document['records'], reopened['records'])
        self.assertEqual(self.calls, ['https://synthetic.example/'])

    async def test_scope_limit_is_explicit_for_filters_and_both_exports(self):
        repo = Repository(self.directory / 'leaddesk.sqlite3')
        page = Page('https://fictional.example/', b'<h1>Fictional</h1>', '<h1>Fictional</h1>')
        with repo.connect() as db:
            for index in range(201):
                rid = repo.save_in_transaction(db, {'product': 'Offer', 'location': 'Town'}, f'row-{index}', page, extract(page.html))
                db.execute('UPDATE campaign SET created_at=? WHERE id=?', (f'2026-10-19T00:{index // 60:02}:{index % 60:02}+00:00', rid))
        data = await self.leads()
        self.assertEqual(data['coverage']['total_in_mode'], 201)
        self.assertEqual(data['coverage']['scanned'], 200)
        self.assertTrue(data['coverage']['scan_limited'])
        document = (await self.exported()).json()
        self.assertEqual(len(document['records']), 200)
        self.assertTrue(document['coverage']['scan_limited'])
        rows = list(csv.DictReader(io.StringIO((await self.exported(format='csv')).text.lstrip('\ufeff'))))
        self.assertEqual(len(rows), 200)
        self.assertTrue(all(row['coverage_limited'] == 'True' and row['coverage_total_in_mode'] == '201' for row in rows))

    async def test_export_snapshot_cannot_mix_a_concurrent_correction(self):
        first = await self.make_record()
        second = await self.make_record('second')
        repo = Repository(self.directory / 'leaddesk.sqlite3')
        original = repo.get_in_transaction
        corrected = False

        def read_then_correct(db, research_id):
            nonlocal corrected
            record = original(db, research_id)
            if not corrected:
                corrected = True
                repo.correct(first['contacts'][0]['id'], 'wrong_contact', 'Concurrent fictional correction', None)
            return record

        with patch.object(repo, 'get_in_transaction', side_effect=read_then_correct):
            snapshot = LeadRepository(repo).export(LeadFilters())
        self.assertEqual({r['lead']['id'] for r in snapshot['records']}, {first['id'], second['id']})
        self.assertTrue(all(not c['suppressed'] for r in snapshot['records'] for c in r['lead']['contacts']))
        later = LeadRepository(repo).page(LeadPage())
        self.assertTrue(all(any(c['suppressed'] for c in r['contacts']) for r in later['items']))


class SpreadsheetSafetyTests(unittest.TestCase):
    def test_formula_prefixes_and_hidden_control_characters(self):
        for value in ('=1+1', '+123', '-1', '@SUM(A1)', '  =1+1', '\t=1+1', '\r=1+1', '\n+1', '\ufeff=1+1'):
            self.assertEqual(safe_cell(value), "'" + value)
        for value in ('Ordinary text', '0123', 'text, "quoted"\nnext line', '{"value":"=1+1"}'):
            self.assertEqual(safe_cell(value), value)
