"""B08 review safety and persistence, using only invented source excerpts."""
import asyncio
import copy
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.adapters.fetch import Page
from backend.domain.assessments import contains_quote
from backend.domain.briefs import OfferInput, rules_draft
from backend.domain.extract import extract
from backend.domain.jobs import JobInput
from backend.storage.briefs import BriefRepository
from backend.storage.jobs import JobRepository
from backend.storage.repository import Repository
from tests.support import APITestCase

SOURCE = ('<h1>Synthetic North Workshop</h1><p>North reception: +1 202-555-0148</p>'
          '<p>Directory support: help@directory.example</p>'
          '<p>Address: North, Lahore.</p><p>We count stock manually each Friday.</p>'
          '<p>We use an online booking calendar.</p>')


def quote(record, wording):
    evidence = next(e for e in record['evidence'] if contains_quote(e['excerpt'], wording))
    return {'value': wording, 'evidence_ids': [evidence['id']]}


def identity(record, **changes):
    return {'expected_revision': 0, 'decision': 'source_attributed', 'source_role': 'business',
            'business_name': quote(record, record['canonical_name']), **changes}


def analysis(record, **changes):
    return {'expected_revision': 0, 'fit': 'review',
            'observations': [quote(record, 'We count stock manually each Friday.')],
            'need_hypothesis': 'A stock review may help; ask whether manual counting causes difficulty.',
            'offer_relevance': 'The scheduling offer might help coordinate reviews; this needs checking.',
            'alternative_explanations': ['Manual counting may already work well.'],
            'missing_checks': ['Ask about current workflow, need and interest.'], **changes}


class AssessmentTests(APITestCase):
    async def make_record(self, key='first', url='https://synthetic.example/', html=SOURCE):
        with patch('tests.support.HTML', html):
            response = await self.research(key, url)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def review(self, record, payload, kind='identity', key='review', status=200):
        route = 'identity-review' if kind == 'identity' else 'need-analysis'
        response = await self.send('POST', f"/v1/research/{record['id']}/{route}", json=payload,
                                   headers={'Idempotency-Key': key})
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    async def get_record(self, record):
        return (await self.send('GET', f"/v1/research/{record['id']}")).json()

    async def test_review_routes_auth_origin_missing_records_and_keys(self):
        for method, suffix in [('GET', 'related'), ('GET', 'assessments/history'),
                               ('POST', 'identity-review'), ('POST', 'need-analysis')]:
            path = f'/v1/research/missing/{suffix}'
            self.assertEqual((await self.send(method, path, json={}, headers={'Authorization': ''})).status_code, 401)
            self.assertEqual((await self.send(method, path, json={}, headers={'Origin': 'https://evil.example'})).status_code, 403)
        for suffix in ('related', 'assessments/history'):
            self.assertEqual((await self.send('GET', f'/v1/research/missing/{suffix}')).status_code, 404)
        record = await self.make_record()
        self.assertEqual((await self.send('POST', f"/v1/research/{record['id']}/identity-review",
                                         json=identity(record))).status_code, 422)

    async def test_identity_and_contact_attribution_are_separate(self):
        record = await self.make_record()
        reviewed = await self.review(record, identity(record))
        self.assertEqual(reviewed['identity_status'], 'source_attributed')
        self.assertTrue(all(c['attribution_state'] == 'extracted' for c in reviewed['contacts']))
        self.assertEqual(reviewed['canonical_name'], record['canonical_name'])
        self.assertEqual(reviewed['assessment']['intent_state'], 'unknown')
        self.assertIsNone(reviewed['assessment']['budget'])
        self.assertIn('separately', reviewed['unknowns']['business_location'])

    async def test_quotes_require_matching_local_evidence_in_every_reference(self):
        record = await self.make_record()
        other = await self.make_record('other', 'https://other.example/')
        cases = [
            {'value': 'Invented business', 'evidence_ids': [record['evidence'][0]['id']]},
            {'value': record['canonical_name'], 'evidence_ids': ['missing']},
            quote(other, other['canonical_name']),
            {'value': record['canonical_name'], 'evidence_ids': [record['evidence'][0]['id'], quote(record, 'Lahore')['evidence_ids'][0]]},
        ]
        for index, value in enumerate(cases):
            await self.review(record, identity(record, business_name=value), key=f'bad-{index}', status=422)
        self.assertEqual((await self.get_record(record))['assessment'], None)

    async def test_directory_agency_and_shared_brand_constraints(self):
        record = await self.make_record()
        for role in ('directory', 'agency', 'unknown', 'shared_brand'):
            await self.review(record, identity(record, source_role=role), key=role, status=422)
        reviewed = await self.review(record, identity(record, source_role='shared_brand', branch=quote(record, 'North')))
        self.assertEqual(reviewed['identity_status'], 'source_attributed')

    async def test_geography_and_exclusion_judgements_need_support(self):
        record = await self.make_record()
        await self.review(record, identity(record, geography='matches'), key='geo', status=422)
        await self.review(record, identity(record, exclusions='clear'), key='excluded', status=422)
        reviewed = await self.review(record, identity(record, geography='matches', address=quote(record, 'Lahore'),
                                                     exclusions='clear', exclusion_reason='Reviewed offer exclusions against source.'))
        self.assertEqual(reviewed['geography'], 'Target city')
        self.assertEqual(reviewed['assessment']['identity']['document']['address']['value'], 'Lahore')

    async def test_contact_requires_own_excerpt_and_explicit_branch(self):
        record = await self.make_record()
        phone = next(c for c in record['contacts'] if c['type'] == 'phone')
        email = next(c for c in record['contacts'] if c['type'] == 'email')
        decision = {'contact_id': phone['id'], 'decision': 'attributed', 'evidence_ids': email['evidence_ids']}
        await self.review(record, identity(record, contact_reviews=[decision]), key='wrong', status=422)
        await self.review(record, identity(record, branch=quote(record, 'North'), contact_reviews=[{
            'contact_id': email['id'], 'decision': 'attributed', 'evidence_ids': email['evidence_ids']}]), key='email', status=422)
        decision['evidence_ids'] = phone['evidence_ids']
        reviewed = await self.review(record, identity(record, branch=quote(record, 'North'), contact_reviews=[decision]))
        self.assertEqual(next(c for c in reviewed['contacts'] if c['id'] == phone['id'])['attribution_state'], 'attributed')
        self.assertEqual(next(c for c in reviewed['contacts'] if c['id'] == email['id'])['attribution_state'], 'extracted')
        self.assertIn('reachability', reviewed['assessment']['scope'])

    async def test_branch_word_boundary_and_cross_record_contact_rejected(self):
        record = await self.make_record(html=SOURCE.replace('North reception:', 'Northumberland reception:'))
        phone = next(c for c in record['contacts'] if c['type'] == 'phone')
        await self.review(record, identity(record, branch=quote(record, 'North'), contact_reviews=[{
            'contact_id': phone['id'], 'decision': 'attributed', 'evidence_ids': phone['evidence_ids']}]), status=422)
        other = await self.make_record('other', 'https://other.example/')
        await self.review(record, identity(record, contact_reviews=[{
            'contact_id': other['contacts'][0]['id'], 'decision': 'unreviewed'}]), key='foreign', status=422)

    async def test_disputed_identity_excludes_only_its_record_and_is_revisable(self):
        first = await self.make_record()
        repeat = await self.make_record('repeat')
        disputed = await self.review(first, {'expected_revision': 0, 'decision': 'disputed', 'source_role': 'directory'})
        self.assertTrue(all(c['review_blocked'] and not c['suppressed'] for c in disputed['contacts']))
        self.assertTrue(all(not c.get('review_blocked') and not c['suppressed'] for c in (await self.get_record(repeat))['contacts']))
        resolved = await self.review(first, identity(first, expected_revision=1), key='resolve')
        self.assertTrue(all(not c['review_blocked'] for c in resolved['contacts']))
        self.assertEqual(resolved['identity_status'], 'source_attributed')

    async def test_suppression_cannot_be_overridden_by_review(self):
        record = await self.make_record()
        contact = record['contacts'][0]
        corrected = await self.send('POST', '/v1/feedback', json={'contact_id': contact['id'], 'category': 'wrong_business'})
        self.assertEqual(corrected.status_code, 200)
        await self.review(record, identity(record, contact_reviews=[{'contact_id': contact['id'],
            'decision': 'attributed', 'evidence_ids': contact['evidence_ids']}]), status=409)

    async def test_shared_host_requires_cited_comparison_and_never_merges(self):
        first = await self.make_record()
        second = await self.make_record('south', 'https://synthetic.example/south', SOURCE.replace('North', 'South'))
        related = (await self.send('GET', f"/v1/research/{first['id']}/related")).json()
        self.assertEqual([r['id'] for r in related['records']], [second['id']])
        unresolved = await self.review(first, identity(first))
        self.assertEqual(unresolved['identity_status'], 'unresolved')
        comparison = {'research_id': second['id'], 'decision': 'different_branch', 'reason': 'Distinct source branch names.',
                      'local_evidence_ids': quote(first, 'North')['evidence_ids'],
                      'other_evidence_ids': quote(second, 'South')['evidence_ids']}
        invalid = copy.deepcopy(comparison); invalid['other_evidence_ids'] = []
        await self.review(first, identity(first, expected_revision=1, comparisons=[invalid]), key='bad', status=422)
        resolved = await self.review(first, identity(first, expected_revision=1, comparisons=[comparison]), key='resolve')
        self.assertEqual(resolved['identity_status'], 'source_attributed')
        self.assertNotEqual(first['business_id'], second['business_id'])
        self.assertEqual(len((await self.send('GET', '/v1/research')).json()), 2)
        await self.review(first, analysis(first), kind='analysis', key='analysis')
        await self.review(second, {'expected_revision': 0, 'decision': 'disputed'}, key='other-change')
        changed = await self.get_record(first)
        self.assertEqual(changed['identity_status'], 'unresolved')
        self.assertEqual(changed['assessment']['analysis_state'], 'needs_review')

    async def test_same_name_only_is_hint_and_repeat_page_is_skipped(self):
        first = await self.make_record()
        unique = SOURCE.replace('+1 202-555-0148', '+1 202-555-0199').replace('help@directory.example', 'other@another.example')
        await self.make_record('other', 'https://different.example/', unique)
        await self.make_record('repeat')
        related = (await self.send('GET', f"/v1/research/{first['id']}/related")).json()
        self.assertEqual(len(related['records']), 1)
        self.assertFalse(related['records'][0]['requires_comparison'])
        self.assertEqual(related['duplicate_pages_skipped'], 1)
        self.assertEqual((await self.review(first, identity(first)))['identity_status'], 'source_attributed')

    async def test_comparisons_scope_both_sides_and_synthetic_data(self):
        first = await self.make_record()
        other = await self.make_record('other', 'https://other.example/')
        comparison = {'research_id': other['id'], 'decision': 'different_business', 'reason': 'Reviewed both sources.',
                      'local_evidence_ids': [first['evidence'][0]['id']], 'other_evidence_ids': [first['evidence'][0]['id']]}
        await self.review(first, identity(first, comparisons=[comparison]), status=422)
        demo = (await self.send('POST', '/v1/demo', headers={'Idempotency-Key': 'demo'})).json()
        comparison.update(research_id=demo['id'], other_evidence_ids=[demo['evidence'][0]['id']])
        await self.review(first, identity(first, comparisons=[comparison]), key='synthetic', status=422)

    async def test_analysis_keeps_inferences_and_unknown_budget_separate(self):
        record = await self.make_record()
        reviewed = await self.review(record, analysis(record), kind='analysis')
        saved = reviewed['assessment']['analysis']['document']
        self.assertEqual(saved['intent_state'], 'unknown'); self.assertIsNone(saved['budget'])
        self.assertIn('inferences', saved['interpretation'])
        self.assertEqual(reviewed['assessment']['analysis_state'], 'current')
        for field, value in [('budget', 1000), ('intent_state', 'interested'), ('verified', True)]:
            await self.review(record, analysis(record, **{field: value}), kind='analysis', key=field, status=422)

    async def test_analysis_requires_alternatives_missing_checks_and_grounded_quotes(self):
        record = await self.make_record()
        for index, change in enumerate([{'alternative_explanations': []}, {'missing_checks': []},
                                       {'existing_solution_status': 'not_described_in_selected_excerpts'}]):
            await self.review(record, analysis(record, **change), kind='analysis', key=str(index), status=422)
        invented = quote(record, 'We count stock manually each Friday.'); invented['value'] = 'They need software urgently.'
        await self.review(record, analysis(record, observations=[invented]), kind='analysis', status=422)

    async def test_possible_fit_needs_reviewed_identity_geography_exclusions_and_alternatives(self):
        record = await self.make_record()
        payload = analysis(record, fit='possible_fit', existing_solution_status='not_described_in_selected_excerpts',
                           checked_evidence_ids=quote(record, 'We count stock manually each Friday.')['evidence_ids'])
        await self.review(record, payload, kind='analysis', key='no-identity', status=409)
        await self.review(record, identity(record))
        await self.review(record, payload, kind='analysis', key='no-geo', status=409)
        await self.review(record, identity(record, expected_revision=1, geography='matches', address=quote(record, 'Lahore'),
                          exclusions='clear', exclusion_reason='No listed exclusion applies to this cited source.'), key='full-identity')
        await self.review(record, payload | {'existing_solution_status': 'not_checked'}, kind='analysis', key='unchecked', status=422)
        saved = await self.review(record, payload, kind='analysis', key='possible')
        self.assertEqual(saved['assessment']['analysis']['document']['fit'], 'possible_fit')
        self.assertIsNone(saved['assessment']['budget'])

    async def test_existing_solution_requires_citation_and_change_reason_for_possible_fit(self):
        record = await self.make_record()
        payload = analysis(record, existing_solution_status='source_described')
        await self.review(record, payload, kind='analysis', status=422)
        payload['existing_solutions'] = [quote(record, 'online booking calendar')]
        saved = await self.review(record, payload, kind='analysis', key='solution')
        self.assertEqual(saved['assessment']['analysis']['document']['existing_solution_status'], 'source_described')
        await self.review(record, payload | {'expected_revision': 1, 'fit': 'possible_fit'}, kind='analysis', key='replace', status=422)

    async def test_analysis_stales_on_identity_and_related_changes(self):
        record = await self.make_record()
        first = await self.review(record, analysis(record), kind='analysis')
        await self.review(record, identity(record), key='identity')
        self.assertEqual((await self.get_record(record))['assessment']['analysis_state'], 'needs_review')
        await self.review(record, analysis(record, expected_revision=1), kind='analysis', key='refresh')
        await self.make_record('related', 'https://synthetic.example/another')
        stale = await self.get_record(record)
        self.assertEqual(stale['assessment']['analysis_state'], 'needs_review')
        self.assertEqual(stale['assessment']['analysis']['document'], first['assessment']['analysis']['document'])

    async def test_contact_correction_stales_analysis_and_rejects_disputed_evidence(self):
        record = await self.make_record()
        phone = next(c for c in record['contacts'] if c['type'] == 'phone')
        payload = analysis(record, observations=[quote(record, 'North reception:')])
        await self.review(record, payload, kind='analysis')
        response = await self.send('POST', '/v1/feedback', json={'contact_id': phone['id'], 'category': 'wrong_branch'})
        stale = response.json()['assessment']
        self.assertEqual(stale['analysis_state'], 'needs_review')
        self.assertTrue(any('disputed contact' in reason for reason in stale['analysis_review_reasons']))
        await self.review(record, payload | {'expected_revision': 1}, kind='analysis', key='bad-refresh', status=409)
        await self.review(record, analysis(record, expected_revision=1), kind='analysis', key='uncontested')
        self.assertEqual((await self.get_record(record))['assessment']['analysis_state'], 'current')

    async def test_revision_conflicts_idempotency_and_old_replay_return_current_state(self):
        record = await self.make_record()
        original = identity(record)
        await self.review(record, original)
        await self.review(record, original, key='stale', status=409)
        await self.review(record, original | {'notes': 'Changed'}, status=409)
        await self.review(record, {'expected_revision': 1, 'decision': 'disputed'}, key='new')
        replay = await self.review(record, original)
        self.assertEqual(replay['identity_status'], 'disputed')
        self.assertEqual(replay['assessment']['identity']['revision'], 2)
        self.assertEqual(len((await self.send('GET', f"/v1/research/{record['id']}/assessments/history")).json()), 2)

    async def test_concurrent_reviews_cannot_overwrite_the_same_revision(self):
        record = await self.make_record()
        responses = await asyncio.gather(*(self.send('POST', f"/v1/research/{record['id']}/identity-review",
            json=identity(record, notes=key), headers={'Idempotency-Key': key}) for key in ('one', 'two')))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        self.assertEqual((await self.get_record(record))['assessment']['identity']['revision'], 1)

    async def test_large_local_comparison_scope_stays_bounded_and_explicit(self):
        record = await self.make_record()
        repository = Repository(self.directory / 'leaddesk.sqlite3')
        extracted = extract(SOURCE)
        with repository.connect() as db:
            for index in range(201):
                page = Page(f'https://related-{index}.example/', SOURCE.encode(), SOURCE)
                repository.save_in_transaction(db, {'product': 'Offer', 'location': 'Market'}, f'bulk-{index}', page, extracted)
        related = (await self.send('GET', f"/v1/research/{record['id']}/related")).json()
        self.assertEqual(len(related['records']), 20)
        self.assertTrue(related['scan_limited']); self.assertTrue(related['required_overflow'])
        reviewed = await self.review(record, identity(record))
        self.assertEqual(reviewed['identity_status'], 'unresolved')
        self.assertTrue(any('bounded' in reason for reason in reviewed['assessment']['identity_blockers']))

    async def test_history_evidence_and_review_survive_restart_and_are_immutable(self):
        record = await self.make_record()
        saved = await self.review(record, identity(record))
        repository = Repository(self.directory / 'leaddesk.sqlite3')
        self.assertEqual(repository.get(record['id']), saved)
        with repository.connect() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM assessment_evidence').fetchone()[0], 1)
            for statement in ('UPDATE assessment_revision SET revision=99', 'DELETE FROM assessment_revision',
                              "UPDATE assessment_evidence SET evidence_id='missing'", 'DELETE FROM assessment_evidence'):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(statement)

    async def test_upgrade_preserves_sprint_four_records_brief_snapshot_and_paused_job(self):
        path = self.directory / 'sprint-four.sqlite3'
        for migration in sorted(Path('backend/storage/migrations').glob('*.sql'))[:4]:
            with sqlite3.connect(path) as db:
                db.executescript(migration.read_text())
                db.execute('INSERT INTO schema_migration VALUES(?,?)', (int(migration.name[:3]), 'old'))
        with patch.object(Repository, 'migrate'):
            old = Repository(path)
        brief = BriefRepository(old).create(rules_draft(OfferInput(offer='Original offer', target_geography='Original market')), 'brief', 'digest')
        # Old pages retain only their original contact/name excerpts.
        extracted = extract(SOURCE); extracted.source_excerpts = []
        page = Page('https://original.example/', SOURCE.encode(), SOURCE)
        record = old.save({'product': 'Original offer', 'location': 'Original market'}, 'old', page, extracted, brief_snapshot=brief)
        corrected = old.correct(record['contacts'][0]['id'], 'wrong_branch', 'Existing feedback', None)
        jobs = JobRepository(old)
        payload = JobInput(brief_id=brief['id'], brief_revision=1, synthetic=True, start_paused=True)
        job = jobs.create(payload, 'job')
        upgraded = Repository(path)
        self.assertEqual(upgraded.get(record['id']), corrected)
        self.assertEqual(JobRepository(upgraded).get(job['id']), job)
        self.assertEqual(BriefRepository(upgraded).get(brief['id']), brief)
        self.assertFalse(any(e['extraction_method'] == 'visible_text_context_v1' for e in upgraded.get(record['id'])['evidence']))
        with upgraded.connect() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM schema_migration').fetchone()[0], 18)


class AssessmentExtractionTests(unittest.TestCase):
    def test_quotes_normalize_whitespace_case_and_respect_word_boundaries(self):
        self.assertTrue(contains_quote('NORTH\n reception', 'North reception'))
        self.assertFalse(contains_quote('Northumberland reception', 'North'))
        self.assertFalse(contains_quote('notnorth', 'north'))

    def test_visible_context_has_strict_count_size_and_hidden_content_limits(self):
        html = '<h1>Source name</h1><script>private script</script><p hidden>private hidden</p>'
        html += ''.join(f'<p>Visible paragraph {i} ' + 'x' * 500 + '</p>' for i in range(20))
        extracted = extract(html)
        self.assertEqual(len(extracted.source_excerpts), 12)
        self.assertTrue(all(len(e) <= 400 for e in extracted.source_excerpts))
        self.assertFalse(any('private' in e for e in extracted.source_excerpts))
