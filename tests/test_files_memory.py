"""B11 fixtures use disposable folders only; no user's files are indexed."""
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from backend.adapters import local_files
from backend.adapters.fetch import Page
from backend.domain.extract import extract
from backend.domain.quality import AuditInput, BaselineInput
from backend.storage.files import FileRepository
from backend.storage.quality import QualityRepository
from backend.storage.repository import Repository
from tests.support import APITestCase


class FilesMemoryTests(APITestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.files_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.files_temp.cleanup)
        self.folder = Path(self.files_temp.name) / 'documents'
        self.folder.mkdir()
        self.repo = Repository(self.directory / 'leaddesk.sqlite3')

    async def approve(self, folder=None):
        response = await self.send('POST', '/v1/files/roots', json={'path': str(folder or self.folder)})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def reconcile(self, root):
        response = await self.send('POST', f"/v1/files/roots/{root['id']}/reconcile")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def search(self, root, query):
        response = await self.send('POST', '/v1/files/search', json={'root_id': root['id'], 'query': query})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def choice(self, root, item, query='proposal', decision='wrong', **changes):
        return await self.send('POST', '/v1/files/corrections', json={
            'root_id': root['id'], 'query': query, 'file_id': item['id'], 'sha256': item['sha256'],
            'decision': decision, 'comment': 'User fixture correction', **changes})

    async def note(self, key='note', **changes):
        return await self.send('POST', '/v1/memories', headers={'Idempotency-Key': key}, json={
            'scope': 'project-a', 'content': 'Use the reviewed project requirements.', **changes})

    async def test_no_implicit_index_and_approval_is_idempotent(self):
        (self.folder / 'proposal.txt').write_text('Fictional proposal')
        self.assertEqual((await self.send('GET', '/v1/files/roots')).json()['items'], [])
        root = await self.approve()
        self.assertEqual((await self.approve())['id'], root['id'])
        self.assertEqual((await self.search(root, 'proposal'))['items'], [])
        await self.reconcile(root)
        self.assertEqual(len((await self.search(root, 'proposal'))['items']), 1)
        self.assertEqual(self.calls, [])

    async def test_scope_policy_rejects_broad_hidden_data_symlink_and_overlapping_roots(self):
        hidden = self.folder / '.private'; hidden.mkdir()
        alias = self.folder.parent / 'alias'; alias.symlink_to(self.folder, target_is_directory=True)
        for path in ['/', str(Path.home()), '/tmp', '/etc', '../relative', str(hidden), str(self.directory), str(alias), str(self.folder / '..')]:
            with self.subTest(path=path):
                response = await self.send('POST', '/v1/files/roots', json={'path': path})
                self.assertEqual(response.status_code, 403, response.text)
        root = await self.approve()
        child = self.folder / 'nested'; child.mkdir()
        self.assertEqual((await self.send('POST', '/v1/files/roots', json={'path': str(child)})).status_code, 409)
        self.assertEqual((await self.send('POST', '/v1/files/roots', json={'path': str(self.folder.parent)})).status_code, 409)
        self.assertEqual((await self.search(root, 'missing'))['items'], [])

    async def test_text_matches_are_scoped_and_preview_has_provenance(self):
        (self.folder / 'clinic.txt').write_text('Fictional clinic appointment requirements in Lahore.')
        other = self.folder.parent / 'other'; other.mkdir()
        (other / 'clinic.txt').write_text('Private unrelated appointment requirements.')
        root = await self.approve(); second = await self.approve(other)
        await self.reconcile(root); await self.reconcile(second)
        result = await self.search(root, 'clinic appointment')
        self.assertEqual(len(result['items']), 1)
        item = result['items'][0]
        self.assertEqual(item['path'], str(self.folder / 'clinic.txt'))
        self.assertEqual(len(item['sha256']), 64)
        response = await self.send('GET', f"/v1/files/{item['id']}/preview")
        self.assertEqual(response.status_code, 200)
        self.assertIn('Fictional clinic', response.json()['text'])
        self.assertNotIn('unrelated', response.text)
        self.assertEqual(self.calls, [])

    async def test_missing_and_changed_files_never_return_stored_text(self):
        file = self.folder / 'proposal.txt'; file.write_text('Original sensitive fixture text')
        root = await self.approve(); await self.reconcile(root)
        item = (await self.search(root, 'proposal'))['items'][0]
        file.write_text('Updated fixture text')
        result = await self.search(root, 'proposal')
        self.assertEqual(result['items'], []); self.assertEqual(result['stale_omitted'], 1)
        changed = await self.send('GET', f"/v1/files/{item['id']}/preview")
        self.assertEqual(changed.status_code, 409); self.assertIn('This file changed', changed.json()['message'])
        await self.reconcile(root)
        replacement = (await self.search(root, 'proposal'))['items'][0]
        self.assertNotEqual(item['id'], replacement['id'])
        file.unlink()
        self.assertEqual((await self.search(root, 'proposal'))['items'], [])
        missing = await self.send('GET', f"/v1/files/{replacement['id']}/preview")
        # A deleted file must not be reported as a missing or symlinked approved folder.
        self.assertEqual(missing.status_code, 409); self.assertIn('moved, was deleted', missing.json()['message'])
        await self.reconcile(root)
        self.assertEqual((await self.send('GET', f"/v1/files/{replacement['id']}/preview")).status_code, 404)

    async def test_rename_preserves_identity_and_query_correction_after_reconciliation(self):
        file = self.folder / 'proposal.txt'; file.write_text('Fictional proposal draft')
        root = await self.approve(); await self.reconcile(root)
        item = (await self.search(root, 'proposal'))['items'][0]
        self.assertEqual((await self.choice(root, item, decision='preferred')).status_code, 200)
        moved = self.folder / 'renamed.txt'; file.rename(moved)
        self.assertEqual((await self.search(root, 'proposal'))['items'], [])
        await self.reconcile(root)
        result = await self.search(root, 'proposal')
        self.assertEqual(result['items'][0]['id'], item['id'])
        self.assertEqual(result['items'][0]['path'], str(moved))
        self.assertTrue(result['items'][0]['preferred'])
        restarted = FileRepository(Repository(self.repo.path), self.directory)
        self.assertEqual(restarted.roots()['items'][0]['id'], root['id'])

    async def test_symlinks_and_special_files_never_leak_outside_scope(self):
        outside = self.folder.parent / 'private.txt'; outside.write_text('Hidden fixture secret')
        (self.folder / 'link.txt').symlink_to(outside)
        (self.folder / 'dirlink').symlink_to(self.folder.parent, target_is_directory=True)
        os.mkfifo(self.folder / 'fifo.txt')
        (self.folder / 'normal.txt').write_text('Visible fixture')
        root = await self.approve(); report = await self.reconcile(root)
        self.assertGreaterEqual(report['skipped'], 3)
        self.assertEqual((await self.search(root, 'secret'))['items'], [])
        item = (await self.search(root, 'normal'))['items'][0]
        (self.folder / 'normal.txt').unlink(); (self.folder / 'normal.txt').symlink_to(outside)
        self.assertEqual((await self.send('GET', f"/v1/files/{item['id']}/preview")).status_code, 409)
        self.assertEqual((await self.search(root, 'normal'))['items'], [])

    async def test_nested_directory_replaced_by_external_symlink_is_rejected(self):
        sub = self.folder / 'nested'; sub.mkdir(); (sub / 'proposal.txt').write_text('Approved fixture')
        root = await self.approve(); await self.reconcile(root)
        item = (await self.search(root, 'proposal'))['items'][0]
        sub.rename(self.folder.parent / 'moved')
        outside = self.folder.parent / 'external'; outside.mkdir(); (outside / 'proposal.txt').write_text('Unapproved fixture')
        sub.symlink_to(outside, target_is_directory=True)
        self.assertEqual((await self.send('GET', f"/v1/files/{item['id']}/preview")).status_code, 409)
        self.assertEqual((await self.search(root, 'proposal'))['items'], [])

    async def test_replaced_root_requires_new_approval(self):
        (self.folder / 'proposal.txt').write_text('Approved text')
        root = await self.approve(); await self.reconcile(root)
        item = (await self.search(root, 'proposal'))['items'][0]
        self.folder.rename(self.folder.parent / 'original'); self.folder.mkdir()
        (self.folder / 'proposal.txt').write_text('Unapproved replacement')
        for method, url, options in [
            ('POST', '/v1/files/search', {'json': {'root_id': root['id'], 'query': 'proposal'}}),
            ('POST', f"/v1/files/roots/{root['id']}/reconcile", {}),
            ('GET', f"/v1/files/{item['id']}/preview", {}),
            ('POST', '/v1/files/roots', {'json': {'path': str(self.folder)}})]:
            response = await self.send(method, url, **options)
            self.assertEqual(response.status_code, 409, response.text)

    async def test_formats_hidden_files_and_size_status_are_visible_without_reading_secrets(self):
        (self.folder / 'report.pdf').write_bytes(b'%PDF fixture, unsupported')
        (self.folder / 'binary.txt').write_bytes(b'abc\0def')
        (self.folder / 'huge.txt').write_bytes(b'x' * (local_files.MAX_FILE_BYTES + 1))
        (self.folder / '.env').write_text('fixture=private')
        (self.folder / 'credentials').write_text('fixture private')
        (self.folder / 'credentials.json').write_text('{"fixture":"private"}')
        dependencies = self.folder / 'node_modules'; dependencies.mkdir(); (dependencies / 'dependency.txt').write_text('fixture private')
        root = await self.approve(); await self.reconcile(root)
        roots = (await self.send('GET', '/v1/files/roots')).json()['items']
        self.assertEqual(roots[0]['statuses'], {'unsupported': 1, 'not_utf8': 1, 'too_large': 1})
        self.assertEqual((await self.search(root, 'private'))['items'], [])
        item = (await self.search(root, 'report'))['items'][0]
        self.assertEqual(item['status'], 'unsupported')
        self.assertEqual((await self.send('GET', f"/v1/files/{item['id']}/preview")).status_code, 422)

    async def test_entry_and_total_byte_budgets_report_partial_coverage(self):
        for index in range(8):
            (self.folder / f'fixture-{index}.txt').write_text('fixture text')
        root = await self.approve()
        with patch.object(local_files, 'MAX_ENTRIES', 3):
            report = await self.reconcile(root)
        self.assertTrue(report['partial']); self.assertEqual(report['entries_seen'], 3)
        with patch.object(local_files, 'MAX_TOTAL_BYTES', 20):
            report = await self.reconcile(root)
        self.assertTrue(report['partial']); self.assertLessEqual(report['bytes_read'], 20)
        self.assertGreater((await self.send('GET', '/v1/files/roots')).json()['items'][0]['statuses']['byte_budget'], 0)

    async def test_wrong_file_is_query_scoped_undoable_and_preferred_can_be_non_keyword_match(self):
        (self.folder / 'proposal-one.txt').write_text('Fictional draft')
        (self.folder / 'proposal-two.txt').write_text('Fictional draft')
        (self.folder / 'chosen.txt').write_text('Fictional final requirements')
        other = self.folder.parent / 'second'; other.mkdir(); (other / 'proposal.txt').write_text('Other scope')
        root = await self.approve(); second = await self.approve(other)
        await self.reconcile(root); await self.reconcile(second)
        results = await self.search(root, 'proposal'); first = results['items'][0]
        self.assertEqual((await self.choice(root, first, query=' PROPOSAL ')).status_code, 200)
        self.assertNotIn(first['id'], [r['id'] for r in (await self.search(root, 'proposal'))['items']])
        self.assertIn(first['id'], [r['id'] for r in (await self.search(root, 'draft'))['items']])
        self.assertEqual(len((await self.search(second, 'proposal'))['items']), 1)
        correction = (await self.search(root, 'proposal'))['corrections'][0]
        self.assertEqual((await self.send('DELETE', f"/v1/files/corrections/{correction['id']}")).status_code, 200)
        self.assertEqual(len((await self.search(root, 'proposal'))['items']), 2)
        chosen = (await self.search(root, 'chosen'))['items'][0]
        self.assertEqual((await self.choice(root, chosen, decision='preferred')).status_code, 200)
        selected = (await self.search(root, 'proposal'))['items'][0]
        self.assertEqual(selected['id'], chosen['id']); self.assertTrue(selected['preferred'])
        self.assertEqual((await self.choice(second, chosen)).status_code, 404)
        self.assertEqual((await self.choice(root, chosen, sha256='0' * 64)).status_code, 409)

    async def test_content_change_invalidates_corrections_and_duplicates_remain_distinct(self):
        for name in ('proposal-a.txt', 'proposal-b.txt'):
            (self.folder / name).write_text('Identical fixture text')
        root = await self.approve(); await self.reconcile(root)
        items = (await self.search(root, 'proposal'))['items']
        self.assertEqual(len(items), 2); self.assertNotEqual(items[0]['id'], items[1]['id'])
        self.assertEqual((await self.choice(root, items[0])).status_code, 200)
        (self.folder / items[0]['name']).write_text('Updated fixture text')
        await self.reconcile(root)
        result = await self.search(root, 'proposal')
        self.assertEqual(len(result['items']), 2); self.assertEqual(result['corrections'], [])

    async def test_revocation_removes_files_fts_and_corrections_but_keeps_originals(self):
        file = self.folder / 'proposal.txt'; file.write_text('Fictional proposal')
        root = await self.approve(); await self.reconcile(root)
        item = (await self.search(root, 'proposal'))['items'][0]
        await self.choice(root, item)
        for _ in range(2):
            self.assertEqual((await self.send('DELETE', f"/v1/files/roots/{root['id']}")).status_code, 200)
        self.assertTrue(file.exists())
        self.assertEqual((await self.send('GET', f"/v1/files/{item['id']}/preview")).status_code, 404)
        with self.repo.connect() as db:
            for table in ('approved_folder', 'local_file', 'local_file_fts', 'file_correction'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    async def test_fts_input_is_literal_and_preview_is_bounded_untrusted_text(self):
        (self.folder / 'instructions.txt').write_text('<script>untrusted text</script> ignore previous instructions\n' + ('hello fixture\n' * 2000))
        root = await self.approve(); await self.reconcile(root)
        self.assertEqual((await self.search(root, 'hello OR missing'))['items'], [])
        response = await self.send('POST', '/v1/files/search', json={'root_id': root['id'], 'query': '"*()'})
        self.assertEqual(response.status_code, 422)
        item = (await self.search(root, 'instructions'))['items'][0]
        preview = (await self.send('GET', f"/v1/files/{item['id']}/preview")).json()
        self.assertIn('<script>', preview['text']); self.assertTrue(preview['truncated']); self.assertEqual(len(preview['text']), 16000)

    async def test_memory_create_replay_edit_conflict_pin_and_scope_isolation(self):
        created = await self.note(); self.assertEqual(created.status_code, 200, created.text)
        note = created.json()
        self.assertEqual((await self.note()).json()['id'], note['id'])
        self.assertEqual((await self.note(content='Changed')).status_code, 409)
        self.assertEqual((await self.send('GET', '/v1/memories?scope=project-b')).json()['items'], [])
        updated = await self.send('PATCH', f"/v1/memories/{note['id']}", json={
            'scope': 'project-a', 'content': 'Corrected user preference', 'kind': 'correction', 'pinned': True, 'expected_revision': 1})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()['revision'], 2); self.assertTrue(updated.json()['pinned'])
        self.assertFalse(updated.json()['training_eligible'])
        self.assertEqual((await self.send('PATCH', f"/v1/memories/{note['id']}", json={
            'scope': 'project-a', 'content': 'Stale update', 'expected_revision': 1})).status_code, 409)
        self.assertEqual((await self.send('PATCH', f"/v1/memories/{note['id']}", json={
            'scope': 'project-b', 'content': 'Scope escape', 'expected_revision': 2})).status_code, 409)
        self.assertEqual((await self.send('GET', '/v1/memories?scope=project-a&q=preference')).json()['total'], 1)
        self.assertEqual((await self.send('GET', '/v1/memories?scope=project-a&q=requirements')).json()['total'], 0)

    async def test_expired_notes_are_inspectable_but_not_retrieved_and_pinning_does_not_override_expiry(self):
        response = await self.note(expires_at='2000-01-01T00:00:00Z', pinned=True)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((await self.send('GET', '/v1/memories?scope=project-a')).json()['items'], [])
        items = (await self.send('GET', '/v1/memories?scope=project-a&include_expired=true')).json()['items']
        self.assertEqual(len(items), 1); self.assertTrue(items[0]['expired'])
        self.assertEqual((await self.note('invalid-date', expires_at='2030-01-01T12:00:00')).status_code, 422)
        self.assertEqual((await self.note('date-only', expires_at='2030-01-01')).status_code, 422)

    async def test_delete_forget_and_export_affect_exact_scope_and_deleted_requests_do_not_resurrect(self):
        one = (await self.note()).json()
        await self.note('note-2', content='Second note')
        await self.note('other', scope='project-b', content='Other project')
        exported = await self.send('GET', '/v1/memories/export?scope=project-a')
        self.assertIn('attachment;', exported.headers['content-disposition'])
        self.assertEqual(len(exported.json()['items']), 2)
        await self.send('DELETE', f"/v1/memories/{one['id']}")
        self.assertEqual((await self.note()).status_code, 410)
        forgotten = await self.send('DELETE', '/v1/memories/scope?scope=project-a')
        self.assertEqual(forgotten.json()['deleted'], 1)
        self.assertEqual((await self.send('GET', '/v1/memories/export?scope=project-a')).json()['items'], [])
        self.assertEqual((await self.send('GET', '/v1/memories?scope=project-b')).json()['total'], 1)
        with self.repo.connect() as db:
            self.assertIsNone(db.execute('SELECT memory_id FROM memory_request WHERE idempotency_key=?', ('note',)).fetchone()[0])

    async def test_local_routes_enforce_auth_origin_bounds_and_typed_inputs(self):
        for method, path, kwargs in [('GET', '/v1/files/roots', {}), ('POST', '/v1/files/search', {'json': {'root_id': 'missing', 'query': 'test'}}),
                                     ('DELETE', '/v1/memories/scope?scope=project-a', {}), ('GET', '/v1/memories?scope=project-a', {})]:
            self.assertEqual((await self.send(method, path, headers={'Authorization': ''}, **kwargs)).status_code, 401)
            self.assertEqual((await self.send(method, path, headers={'Origin': 'https://untrusted.example'}, **kwargs)).status_code, 403)
        self.assertEqual((await self.send('GET', '/v1/memories')).status_code, 422)
        self.assertEqual((await self.send('POST', '/v1/memories', json={'scope': 'a', 'content': 'note'})).status_code, 422)
        self.assertEqual((await self.note(scope='   ')).status_code, 422)
        self.assertEqual((await self.note(content='   ')).status_code, 422)
        self.assertEqual((await self.note(content='x' * 16000)).status_code, 413)
        self.assertEqual((await self.note(kind='model_inference')).status_code, 422)
        self.assertEqual((await self.send('POST', '/v1/files/roots', json={'path': str(self.folder), 'recursive_shell': 'bad'})).status_code, 422)

    async def test_migration_from_sprint_seven_preserves_every_existing_table(self):
        path = self.directory / 'old.sqlite3'
        for migration in sorted(Path('backend/storage/migrations').glob('*.sql'))[:6]:
            with sqlite3.connect(path) as db:
                db.executescript(migration.read_text())
                db.execute('INSERT INTO schema_migration VALUES(?,?)', (int(migration.name[:3]), 'old'))
        with patch.object(Repository, 'migrate'):
            old = Repository(path)
        html = '<h1>Fictional retained workshop</h1><p>hello@fixture.example</p>'
        record = old.save({'product': 'Fictional offer', 'location': 'Fictional market'}, 'old-record',
                          Page('https://fixture.example/', html.encode(), html), extract(html), True)
        old.correct(record['contacts'][0]['id'], 'wrong_contact', 'Keep existing suppression', None)
        quality = QualityRepository(old)
        baseline = quality.create(BaselineInput(name='Frozen migration fixture', mode='synthetic', research_ids=[record['id']]), 'old-baseline')
        quality.save_audit(baseline['id'], record['id'], AuditInput(expected_revision=0, reviewer='Fixture reviewer'), 'old-audit')
        with old.connect() as db:
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name<>'schema_migration'")]
            before = {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] for table in tables}
        upgraded = Repository(path)
        with upgraded.connect() as db:
            self.assertEqual(before, {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] for table in tables})
            self.assertEqual(db.execute('SELECT COUNT(*) FROM schema_migration').fetchone()[0], 18)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    async def test_all_memory_pages_remain_editable_and_export_is_complete(self):
        # Populate through the repository API without a hundred repeated HTTP calls.
        from backend.domain.files import MemoryInput
        from backend.storage.memories import MemoryRepository
        memories = MemoryRepository(self.repo)
        for index in range(102):
            memories.create(MemoryInput(scope='many-notes', content=f'Fixture note {index}'), f'fixture-{index}')
        first = (await self.send('GET', '/v1/memories?scope=many-notes')).json()
        second = (await self.send('GET', '/v1/memories?scope=many-notes&offset=100')).json()
        self.assertEqual(first['total'], 102); self.assertEqual(first['next_offset'], 100)
        self.assertEqual(len(first['items']), 100); self.assertEqual(len(second['items']), 2)
        self.assertIsNone(second['next_offset'])
        note = second['items'][0]
        changed = await self.send('PATCH', f"/v1/memories/{note['id']}", json={
            'scope': 'many-notes', 'content': 'Updated older page fixture', 'expected_revision': 1})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(len((await self.send('GET', '/v1/memories/export?scope=many-notes')).json()['items']), 102)

    async def test_read_failures_and_elapsed_budget_are_visible_and_remove_stale_index_text(self):
        (self.folder / 'proposal.txt').write_text('Fictional bounded fixture')
        root = await self.approve(); await self.reconcile(root)
        with patch.object(local_files, 'read_entry', side_effect=PermissionError('Fixture permission denied')):
            report = await self.reconcile(root)
        self.assertTrue(report['partial']); self.assertEqual(report['errors'], 1)
        statuses = (await self.send('GET', '/v1/files/roots')).json()['items'][0]['statuses']
        self.assertEqual(statuses, {'unreadable': 1})
        with self.repo.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM local_file_fts WHERE local_file_fts MATCH 'bounded'").fetchone()[0], 0)
        with patch.object(local_files, 'MAX_SECONDS', 0):
            report = await self.reconcile(root)
        self.assertTrue(report['partial']); self.assertEqual(report['entries_seen'], 0)

    async def test_ambiguous_search_is_capped_at_three_and_all_wrong_matches_abstain(self):
        for index in range(5):
            (self.folder / f'proposal-{index}.txt').write_text('Fictional proposal')
        root = await self.approve(); await self.reconcile(root)
        self.assertEqual(len((await self.search(root, 'proposal'))['items']), 3)
        count = 0
        while (items := (await self.search(root, 'proposal'))['items']):
            for item in items:
                self.assertEqual((await self.choice(root, item)).status_code, 200)
                count += 1
        self.assertEqual(count, 5)
