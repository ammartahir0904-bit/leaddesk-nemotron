"""Local-only fixtures: no provider, mailbox, SMTP or calendar account calls."""
import sqlite3
import unittest
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfoNotFoundError

from pydantic import ValidationError

from backend.adapters.draft_files import calendar_file, fold_line
from backend.adapters.fetch import Page
from backend.domain.correspondence import CalendarDraft, EmailDraft, ExportReview, resolve_meeting
from backend.domain.errors import ResearchError
from backend.domain.extract import extract
from backend.storage.correspondence import CorrespondenceRepository
from backend.storage.pc_worker import PCWorkerRepository
from backend.domain.pc_worker import PairWorker, WorkerTask
from backend.storage.repository import Repository
from tests.support import APITestCase
from tests.test_assessments import identity


def calendar(**changes):
    return {'kind': 'calendar', 'title': 'Fictional planning discussion', 'description': 'User-authored fictional notes.',
            'location': 'Fictional office', 'organizer_timezone': 'Asia/Karachi', 'counterpart_timezone': 'Europe/London',
            'start_local': '2026-11-01T12:00', 'duration_minutes': 30, 'synthetic': True, **changes}


class TimezoneAndFileTests(unittest.TestCase):
    def test_both_zones_and_day_rollover_are_explicit(self):
        context = resolve_meeting(CalendarDraft(**calendar(start_local='2026-01-01T01:00', counterpart_timezone='America/New_York')))
        self.assertEqual(context['start_utc'], '2025-12-31T20:00:00+00:00')
        self.assertEqual(context['counterpart_start'], '2025-12-31T15:00:00-05:00')
        self.assertEqual(context['organizer_start'], '2026-01-01T01:00:00+05:00')
        self.assertFalse(context['invitation_sent'])

    def test_dst_gap_and_ambiguous_time_require_resolution(self):
        for start in ('2026-03-08T02:30', '2026-11-01T01:30'):
            with self.assertRaises(ValidationError):
                CalendarDraft(**calendar(organizer_timezone='America/New_York', start_local=start))
        earlier = resolve_meeting(CalendarDraft(**calendar(organizer_timezone='America/New_York', start_local='2026-11-01T01:30', fold=0)))
        later = resolve_meeting(CalendarDraft(**calendar(organizer_timezone='America/New_York', start_local='2026-11-01T01:30', fold=1)))
        self.assertEqual(earlier['start_utc'], '2026-11-01T05:30:00+00:00')
        self.assertEqual(later['start_utc'], '2026-11-01T06:30:00+00:00')

    def test_duration_is_elapsed_time_across_dst_and_fractional_offsets(self):
        context = resolve_meeting(CalendarDraft(**calendar(organizer_timezone='America/New_York', counterpart_timezone='Asia/Kathmandu',
                                                            start_local='2026-11-01T01:30', fold=0, duration_minutes=120)))
        self.assertEqual(context['organizer_end'], '2026-11-01T02:30:00-05:00')
        self.assertEqual(context['counterpart_start'], '2026-11-01T11:15:00+05:45')
        self.assertEqual((datetime.fromisoformat(context['end_utc']) - datetime.fromisoformat(context['start_utc'])).total_seconds(), 7200)

    def test_invalid_timezones_dates_types_controls_and_actions_are_rejected(self):
        for change in ({'organizer_timezone': 'Invalid/Timezone'}, {'counterpart_timezone': '../private'},
                       {'start_local': '2026-02-30T12:00'}, {'start_local': '1999-12-31T23:00'},
                       {'duration_minutes': True}, {'duration_minutes': 481}, {'fold': True}, {'send': True},
                       {'title': 'Bad\r\nATTENDEE:bad@example.com'}, {'description': '\ud800'}):
            with self.assertRaises(ValidationError):
                CalendarDraft(**calendar(**change))

    def test_mailboxes_subjects_and_plain_text_are_bounded(self):
        draft = {'kind': 'email', 'research_id': 'r', 'contact_id': 'c', 'sender': 'me@example.com', 'subject': 'Review', 'body': 'Hello'}
        for change in ({'sender': 'a@example.com,b@example.com'}, {'sender': 'Name <a@example.com>'},
                       {'sender': 'a@'}, {'sender': 'a@@b.com'}, {'sender': 'a@b..c'}, {'sender': '@example.com'},
                       {'sender': 'a@example.com\nBcc: hidden@example.com'}, {'sender': 'hello@localhost'},
                       {'subject': 'Hello\nBcc: hidden@example.com'}, {'body': '\x00secret'}, {'body': 'x' * 4001},
                       {'body': '\ud800'}, {'attachments': ['/private']}):
            with self.assertRaises((ValidationError, ValueError)):
                EmailDraft(**(draft | change))
        valid = EmailDraft(**(draft | {'subject': 'اردو review', 'body': 'اردو\n<script>literal only</script>'}))
        self.assertIn('<script>', valid.body)

    def test_ics_utf8_folding_and_text_escaping_do_not_inject_properties(self):
        document = CalendarDraft(**calendar(title='اردو,;\\' * 20, description='Literal\nBEGIN:VALARM\nATTENDEE:mailto:no@example.com'))
        draft = {'id': 'synthetic-id', 'revision': 3, 'synthetic': True, 'document': document.model_dump(),
                 'context': resolve_meeting(document) | {'title': '[SYNTHETIC DEMO] ' + document.title},
                 'created_at': '2026-10-20T00:00:00+00:00', 'updated_at': '2026-10-20T00:00:00+00:00'}
        body = calendar_file(draft)
        for line in body.split(b'\r\n'):
            self.assertLessEqual(len(line), 75)
            line.decode('utf-8')
        unfolded = body.decode().replace('\r\n ', '')
        self.assertIn('SEQUENCE:2\r\n', unfolded)
        self.assertIn('STATUS:TENTATIVE\r\n', unfolded)
        self.assertIn('TRANSP:TRANSPARENT\r\n', unfolded)
        self.assertNotIn('\r\nATTENDEE:', unfolded)
        self.assertNotIn('\r\nBEGIN:VALARM', unfolded)
        self.assertNotIn('METHOD:', unfolded)
        self.assertIn('\\,\\;\\\\', unfolded)
        self.assertEqual(fold_line('x' * 76), 'x' * 75 + '\r\n x')


class CorrespondenceAPITests(APITestCase):
    async def create(self, document=None, key='create'):
        response = await self.send('POST', '/v1/correspondence/drafts', json=document or calendar(), headers={'Idempotency-Key': key})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def approve(self, draft, key='review', **changes):
        payload = {'expected_revision': draft['revision'], 'context_hash': draft['context_hash'], 'reviewer': 'Fictional reviewer',
                   'note': 'Inspected this local file only.', 'confirmed': True, **changes}
        response = await self.send('POST', f"/v1/correspondence/drafts/{draft['id']}/review", json=payload, headers={'Idempotency-Key': key})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def download(self, draft):
        return await self.send('GET', f"/v1/correspondence/drafts/{draft['id']}/export", params={
            'revision': draft['revision'], 'context_hash': draft['context_hash']})

    async def email(self, reviewed=True):
        repo = Repository(self.directory / 'leaddesk.sqlite3')
        html = '<h1>Fictional Workshop</h1><p>Office: hello@fictional.example</p>'
        record = repo.save({'product': 'Fictional offer', 'location': 'Fictional city'}, 'fictional-record',
                          Page('https://fictional.example/', html.encode(), html), extract(html), synthetic=True)
        contact = record['contacts'][0]
        if reviewed:
            payload = identity(record, contact_reviews=[{'contact_id': contact['id'], 'decision': 'attributed', 'evidence_ids': contact['evidence_ids']}])
            response = await self.send('POST', f"/v1/research/{record['id']}/identity-review", json=payload, headers={'Idempotency-Key': 'identity'})
            self.assertEqual(response.status_code, 200, response.text)
        draft = await self.create({'kind': 'email', 'research_id': record['id'], 'contact_id': contact['id'], 'sender': 'author@example.com',
                                   'subject': 'Fictional اردو discussion', 'body': 'Fictional body.\n<script>untrusted literal</script>'})
        return draft, record, contact

    async def test_calendar_review_export_stable_bytes_uid_and_no_provider_state(self):
        draft = await self.create()
        self.assertEqual((await self.download(draft)).status_code, 409)
        reviewed = await self.approve(draft)
        self.assertTrue(reviewed['can_export'])
        response = await self.download(reviewed)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertIn('.ics', response.headers['content-disposition'])
        self.assertIn(b'DTSTART:20261101T070000Z\r\n', response.content)
        self.assertIn(f"UID:{draft['id']}@leaddesk.local".encode(), response.content)
        self.assertEqual(response.content, (await self.download(reviewed)).content)
        self.assertEqual(reviewed['delivery_state'], 'local_file_only')
        self.assertFalse(reviewed['provider_connected'])
        self.assertEqual(self.calls, [])

    async def test_email_file_is_plain_draft_with_exact_recipient_and_no_hidden_headers(self):
        draft, record, contact = await self.email()
        reviewed = await self.approve(draft)
        response = await self.download(reviewed)
        self.assertEqual(response.status_code, 200, response.text)
        parsed = BytesParser(policy=policy.default).parsebytes(response.content)
        self.assertEqual(str(parsed['To']), contact['normalised_value'])
        self.assertEqual(str(parsed['From']), 'author@example.com')
        self.assertTrue(str(parsed['Subject']).startswith('[SYNTHETIC DEMO]'))
        self.assertIn('اردو', str(parsed['Subject']))
        self.assertEqual(str(parsed['X-Unsent']), '1')
        self.assertIsNone(parsed['Bcc'])
        self.assertEqual(parsed.get_content_type(), 'text/plain')
        self.assertIn('<script>untrusted literal</script>', parsed.get_content())
        self.assertNotIn(record['source_url'].encode(), response.content)
        self.assertEqual(response.content, (await self.download(reviewed)).content)

    async def test_malformed_sender_returns_validation_error_without_creating_drafts(self):
        draft, record, contact = await self.email()
        for sender in ('a@', 'a@@b.com', '@example.com', 'a@b..c', '.a@example.com'):
            response = await self.send('POST', '/v1/correspondence/drafts', json=draft['document'] | {'sender': sender}, headers={'Idempotency-Key': 'malformed'})
            self.assertEqual(response.status_code, 422)
        self.assertEqual((await self.send('GET', '/v1/correspondence/drafts', params={'mode': 'synthetic'})).json()['total'], 1)

    async def test_unattributed_suppressed_disputed_and_missing_contacts_cannot_export(self):
        draft, record, contact = await self.email(reviewed=False)
        self.assertEqual(draft['review_state'], 'blocked')
        payload = {'expected_revision': 1, 'context_hash': draft['context_hash'], 'reviewer': 'Reviewer', 'note': 'Local', 'confirmed': True}
        response = await self.send('POST', f"/v1/correspondence/drafts/{draft['id']}/review", json=payload, headers={'Idempotency-Key': 'blocked'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual((await self.download(draft)).status_code, 409)
        bad = await self.send('POST', '/v1/correspondence/drafts', json=draft['document'] | {'contact_id': 'unrelated'}, headers={'Idempotency-Key': 'other'})
        self.assertEqual(bad.status_code, 409)

    async def test_correction_immediately_invalidates_prior_export_and_review_replay(self):
        draft, record, contact = await self.email()
        reviewed = await self.approve(draft)
        await self.send('POST', '/v1/feedback', json={'contact_id': contact['id'], 'category': 'wrong_branch', 'comment': 'Fictional correction'})
        self.assertEqual((await self.download(reviewed)).status_code, 409)
        current = (await self.send('GET', f"/v1/correspondence/drafts/{draft['id']}")).json()
        self.assertFalse(current['can_export'])
        self.assertNotEqual(current['context_hash'], draft['context_hash'])
        replay = await self.approve(draft)
        self.assertFalse(replay['can_export'])
        self.assertTrue(any('suppressed' in reason for reason in current['context']['blockers']))
        self.assertTrue(Repository(self.directory / 'leaddesk.sqlite3').get(record['id'])['contacts'][0]['suppressed'])

    async def test_identity_change_requires_current_context_review(self):
        draft, record, contact = await self.email()
        reviewed = await self.approve(draft)
        # A new source review changes the approval's context even if it keeps
        # attribution; stale tabs cannot approve the new source on an old hash.
        payload = identity(record, expected_revision=1, contact_reviews=[{
            'contact_id': contact['id'], 'decision': 'attributed', 'evidence_ids': contact['evidence_ids']}], notes='Reviewed again')
        response = await self.send('POST', f"/v1/research/{record['id']}/identity-review", json=payload, headers={'Idempotency-Key': 'identity-again'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual((await self.download(reviewed)).status_code, 409)
        current = (await self.send('GET', f"/v1/correspondence/drafts/{draft['id']}")).json()
        self.assertEqual(current['review_state'], 'needs_review')
        fresh = await self.approve(current, key='fresh-review')
        self.assertEqual((await self.download(fresh)).status_code, 200)

    async def test_disputed_identity_and_new_related_source_block_prior_export(self):
        draft, record, contact = await self.email()
        reviewed = await self.approve(draft)
        repo = Repository(self.directory / 'leaddesk.sqlite3')
        html = '<h1>Fictional related branch</h1><p>hello@fictional.example</p>'
        repo.save({'product': 'Fictional offer', 'location': 'Fictional city'}, 'related',
                  Page('https://fictional.example/branch', html.encode(), html), extract(html), True)
        current = (await self.send('GET', f"/v1/correspondence/drafts/{draft['id']}")).json()
        self.assertEqual(current['review_state'], 'blocked')
        self.assertEqual((await self.download(reviewed)).status_code, 409)
        payload = identity(record, expected_revision=1, decision='disputed')
        response = await self.send('POST', f"/v1/research/{record['id']}/identity-review", json=payload, headers={'Idempotency-Key': 'disputed'})
        self.assertEqual(response.status_code, 200)
        current = (await self.send('GET', f"/v1/correspondence/drafts/{draft['id']}")).json()
        self.assertEqual(current['context']['identity_status'], 'disputed')
        self.assertFalse(current['can_export'])

    async def test_missing_research_context_is_blocked_without_deleting_user_text(self):
        draft, record, contact = await self.email()
        await self.approve(draft)
        store = CorrespondenceRepository(Repository(self.directory / 'leaddesk.sqlite3'))
        with patch.object(store.repository, 'get_in_transaction', side_effect=ResearchError('Source missing', status=404)):
            missing = store.get(draft['id'])
        self.assertEqual(missing['review_state'], 'blocked')
        self.assertEqual(missing['document']['body'], draft['document']['body'])
        self.assertFalse(missing['can_export'])

    async def test_edit_conflict_resets_approval_and_advances_calendar_sequence(self):
        draft = await self.create()
        approved = await self.approve(draft)
        payload = {'expected_revision': 1, 'document': calendar(title='Changed fictional meeting')}
        response = await self.send('PATCH', f"/v1/correspondence/drafts/{draft['id']}", json=payload, headers={'Idempotency-Key': 'edit'})
        self.assertEqual(response.status_code, 200)
        changed = response.json()
        self.assertEqual(changed['revision'], 2)
        self.assertFalse(changed['can_export'])
        self.assertEqual((await self.download(approved)).status_code, 409)
        old_review = await self.approve(draft)  # Does not reapply review to revision 2.
        self.assertFalse(old_review['can_export'])
        stale = await self.send('PATCH', f"/v1/correspondence/drafts/{draft['id']}", json=payload, headers={'Idempotency-Key': 'stale-edit'})
        self.assertEqual(stale.status_code, 409)
        changed = await self.approve(changed, key='review-2')
        file = await self.download(changed)
        self.assertIn(b'SEQUENCE:1\r\n', file.content)
        self.assertIn(f"UID:{draft['id']}@leaddesk.local".encode(), file.content)

    async def test_idempotent_create_edit_review_and_deleted_replay_tombstones(self):
        draft = await self.create()
        self.assertEqual((await self.create())['id'], draft['id'])
        conflict = await self.send('POST', '/v1/correspondence/drafts', json=calendar(title='Different'), headers={'Idempotency-Key': 'create'})
        self.assertEqual(conflict.status_code, 409)
        approved = await self.approve(draft)
        await self.send('DELETE', f"/v1/correspondence/drafts/{draft['id']}")
        self.assertEqual((await self.send('GET', f"/v1/correspondence/drafts/{draft['id']}")).status_code, 404)
        self.assertEqual((await self.download(approved)).status_code, 404)
        for path, payload, key in [('/v1/correspondence/drafts', calendar(), 'create'),
            (f"/v1/correspondence/drafts/{draft['id']}/review", {'expected_revision': 1, 'context_hash': draft['context_hash'], 'reviewer': 'Fictional reviewer', 'note': 'Inspected this local file only.', 'confirmed': True}, 'review')]:
            self.assertEqual((await self.send('POST', path, json=payload, headers={'Idempotency-Key': key})).status_code, 409)
        with Repository(self.directory / 'leaddesk.sqlite3').connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM correspondence_draft').fetchone()[0], 0)
            self.assertNotIn('Fictional planning discussion', str([tuple(r) for r in db.execute('SELECT * FROM correspondence_request')]))

    async def test_deleted_contact_blocks_export_but_keeps_draft_deletable(self):
        draft, record, contact = await self.email()
        reviewed = await self.approve(draft)
        repo = Repository(self.directory / 'leaddesk.sqlite3')
        with repo.connect() as db:
            db.execute('DELETE FROM contact_evidence WHERE contact_id=?', (contact['id'],))
            db.execute('DELETE FROM contact WHERE id=?', (contact['id'],))
        self.assertEqual((await self.download(reviewed)).status_code, 409)
        current = (await self.send('GET', f"/v1/correspondence/drafts/{draft['id']}")).json()
        self.assertEqual(current['review_state'], 'blocked')
        self.assertEqual((await self.send('DELETE', f"/v1/correspondence/drafts/{draft['id']}")).status_code, 200)

    async def test_deleted_draft_does_not_change_source_suppression_or_other_features(self):
        draft, record, contact = await self.email()
        repo = Repository(self.directory / 'leaddesk.sqlite3')
        repo.correct(contact['id'], 'wrong_contact', 'Preserve correction', None)
        before = repo.get(record['id'])
        await self.send('DELETE', f"/v1/correspondence/drafts/{draft['id']}")
        self.assertEqual(repo.get(record['id']), before)

    async def test_paging_and_real_synthetic_separation_cover_every_draft_and_source(self):
        store = CorrespondenceRepository(Repository(self.directory / 'leaddesk.sqlite3'))
        for index in range(22):
            store.save(CalendarDraft(**calendar(title=f'Fictional {index}')), f'calendar-{index}')
        store.save(CalendarDraft(**calendar(synthetic=False, title='Personal planning')), 'personal')
        seen = []
        for offset in (0, 20):
            response = (await self.send('GET', '/v1/correspondence/drafts', params={'mode': 'synthetic', 'offset': offset})).json()
            seen.extend(item['id'] for item in response['items'])
        self.assertEqual(len(set(seen)), 22)
        self.assertEqual(len((await self.send('GET', '/v1/correspondence/drafts')).json()['items']), 1)
        for index in range(22):
            html = f'<h1>Fictional {index}</h1><p>team@fictional{index}.example</p>'
            store.repository.save({'product': 'Fictional', 'location': 'Synthetic city'}, f'source-{index}',
                Page(f'https://fictional{index}.example/', html.encode(), html), extract(html), True)
        sources = []
        for offset in (0, 20):
            response = (await self.send('GET', '/v1/correspondence/sources', params={'mode': 'synthetic', 'offset': offset})).json()
            sources.extend(item['id'] for item in response['items'])
        self.assertEqual(len(set(sources)), 22)
        self.assertEqual((await self.send('GET', '/v1/correspondence/sources')).json()['items'], [])

    async def test_restart_preserves_reviews_and_repeat_download(self):
        draft = await self.approve(await self.create())
        old = (await self.download(draft)).content
        restarted = CorrespondenceRepository(Repository(self.directory / 'leaddesk.sqlite3'))
        current = restarted.get(draft['id'])
        self.assertTrue(current['can_export'])
        self.assertEqual(restarted.export(draft['id'], draft['revision'], draft['context_hash'])[1], old)

    async def test_auth_origin_body_review_scope_and_strict_action_input(self):
        for method, path, payload in [('GET', '/v1/correspondence/drafts', None), ('GET', '/v1/correspondence/sources', None),
            ('POST', '/v1/correspondence/drafts', calendar()), ('GET', '/v1/correspondence/drafts/missing', None),
            ('DELETE', '/v1/correspondence/drafts/missing', None)]:
            self.assertEqual((await self.send(method, path, json=payload, headers={'Authorization': ''})).status_code, 401)
        self.assertEqual((await self.send('POST', '/v1/correspondence/drafts', json=calendar(), headers={'Origin': 'https://evil.example', 'Idempotency-Key': 'evil'})).status_code, 403)
        self.assertEqual((await self.send('POST', '/v1/correspondence/drafts', content='x' * 16001, headers={'Idempotency-Key': 'large'})).status_code, 413)
        for change in ({'kind': 'send_email'}, {'send': True}, {'duration_minutes': True}, {'attendees': ['hidden@example.com']}):
            response = await self.send('POST', '/v1/correspondence/drafts', json=calendar(**change), headers={'Idempotency-Key': 'invalid'})
            self.assertEqual(response.status_code, 422)
        draft = await self.create()
        base = {'expected_revision': 1, 'context_hash': draft['context_hash'], 'reviewer': 'Reviewer', 'note': 'Local only', 'confirmed': True}
        for change in ({'confirmed': False}, {'confirmed': 1}, {'expected_revision': True}, {'scope': 'send'}):
            response = await self.send('POST', f"/v1/correspondence/drafts/{draft['id']}/review", json=base | change, headers={'Idempotency-Key': 'invalid-review'})
            self.assertEqual(response.status_code, 422)
        stale = await self.send('POST', f"/v1/correspondence/drafts/{draft['id']}/review", json=base | {'context_hash': '0' * 64}, headers={'Idempotency-Key': 'stale-review'})
        self.assertEqual(stale.status_code, 409)

    async def test_failed_receipt_or_oversized_export_rolls_back_without_partial_write(self):
        draft = await self.create()
        store = CorrespondenceRepository(Repository(self.directory / 'leaddesk.sqlite3'))
        values = ExportReview(expected_revision=1, context_hash=draft['context_hash'], reviewer='Reviewer', note='Local', confirmed=True)
        with patch.object(store, '_save_receipt', side_effect=RuntimeError('Synthetic interruption')):
            with self.assertRaises(RuntimeError):
                store.review(draft['id'], values, 'interrupted')
        self.assertFalse(store.get(draft['id'])['can_export'])
        reviewed = await self.approve(draft)
        with patch('backend.storage.correspondence.MAX_EXPORT_BYTES', 10):
            with self.assertRaises(ResearchError) as error:
                store.export(draft['id'], reviewed['revision'], reviewed['context_hash'])
            self.assertEqual(error.exception.status, 413)
        self.assertEqual((await self.download(reviewed)).status_code, 200)

    async def test_unavailable_timezone_after_review_blocks_without_losing_draft(self):
        draft = await self.approve(await self.create())
        store = CorrespondenceRepository(Repository(self.directory / 'leaddesk.sqlite3'))
        with patch('backend.domain.correspondence.ZoneInfo', side_effect=ZoneInfoNotFoundError('Synthetic unavailable zone')):
            current = store.get(draft['id'])
        self.assertEqual(current['review_state'], 'blocked')
        self.assertFalse(current['can_export'])
        self.assertEqual(current['document']['title'], draft['document']['title'])

    async def test_migration_preserves_every_sprint_twelve_table(self):
        path = self.directory / 'sprint-12.sqlite3'
        for migration in sorted(Path('backend/storage/migrations').glob('*.sql'))[:9]:
            with sqlite3.connect(path) as db:
                db.executescript(migration.read_text())
                db.execute('INSERT INTO schema_migration VALUES(?,?)', (int(migration.name[:3]), 'fixture'))
        with patch.object(Repository, 'migrate'):
            old = Repository(path)
        html = '<h1>Fictional preserved record</h1><p>hello@preserved.example</p>'
        record = old.save({'product': 'Fictional offer', 'location': 'Fictional city'}, 'old-research',
            Page('https://preserved.example/', html.encode(), html), extract(html), True)
        old.correct(record['contacts'][0]['id'], 'wrong_branch', 'Preserve suppression', None)
        workers = PCWorkerRepository(old)
        worker = workers.pair(PairWorker(name='Fictional preserved worker'), 'old-pair')['worker']
        workers.create(WorkerTask(worker_id=worker['id'], kind='synthetic_parser_benchmark'), 'old-task')
        with old.connect() as db:
            db.execute("INSERT INTO local_memory VALUES('private-note','scope','project_context','Preserve private note','fixture',0,NULL,'old','old',1)")
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name<>'schema_migration'")]
            before = {name: [tuple(r) for r in db.execute(f'SELECT * FROM "{name}"')] for name in tables}
        upgraded = Repository(path)
        with upgraded.connect() as db:
            self.assertEqual(before, {name: [tuple(r) for r in db.execute(f'SELECT * FROM "{name}"')] for name in tables})
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM schema_migration').fetchone()[0], 18)
