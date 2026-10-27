"""Local drafts with revision/context-bound review and guarded file exports."""
import json

from pydantic import TypeAdapter

from backend.adapters.draft_files import calendar_file, email_file
from backend.domain.correspondence import DraftInput, EmailDraft, mailbox, resolve_meeting
from backend.domain.errors import ResearchError
from backend.storage.assessment_views import identity_signature
from backend.storage.repository import now, request_hash, uid

PAGE_SIZE = 20
MAX_EXPORT_BYTES = 64000


class CorrespondenceRepository:
    def __init__(self, repository):
        self.repository = repository

    def _context(self, db, document):
        if document.kind == 'calendar':
            return resolve_meeting(document) | {
                'title': ('[SYNTHETIC DEMO] ' if document.synthetic else '') + document.title,
                'synthetic': document.synthetic, 'blockers': []}
        try:
            record = self.repository.get_in_transaction(db, document.research_id)
        except ResearchError as error:
            if error.status != 404:
                raise
            return {'recipient': None, 'subject': document.subject, 'blockers': ['The source research was deleted.']}
        contact = next((c for c in record['contacts'] if c['id'] == document.contact_id and c['type'] == 'email'), None)
        blockers = []
        if not contact:
            blockers.append('The selected email contact is missing or belongs to another record.')
        else:
            if contact['suppressed']:
                blockers.append('This source contact is suppressed by a correction.')
            if contact['attribution_state'] != 'attributed' or contact.get('review_blocked'):
                blockers.append('Review this email contact’s source attribution in the original research first.')
            try:
                mailbox(contact['normalised_value'])
            except ValueError:
                blockers.append('The source email is not supported as a single plain mailbox.')
        if record['identity_status'] != 'source_attributed':
            blockers.append('Business identity or related-source comparisons need review.')
        assessment = record.get('assessment') or {}
        if (assessment.get('identity') or {}).get('document', {}).get('exclusions') == 'excluded':
            blockers.append('The reviewed offer exclusions apply to this record.')
        own_evidence = set(contact['evidence_ids']) if contact else set()
        return {'recipient': contact['normalised_value'] if contact else None,
                'subject': ('[SYNTHETIC DEMO] ' if record['synthetic'] else '') + document.subject,
                'source_url': record['source_url'], 'source_name': record['canonical_name'],
                'synthetic': record['synthetic'], 'identity_status': record['identity_status'],
                'identity_signature': identity_signature(db, record['id']),
                'contact_state': contact['attribution_state'] if contact else 'missing',
                'source_evidence': [{'id': e['id'], 'excerpt': e['excerpt'], 'content_hash': e['content_hash'],
                                     'retrieved_at': e['retrieved_at']} for e in record['evidence'] if e['id'] in own_evidence],
                'blockers': blockers, 'reachability': 'unconfirmed', 'intent': 'unknown', 'sent': False}

    @staticmethod
    def _row(db, draft_id):
        row = db.execute('SELECT * FROM correspondence_draft WHERE id=?', (draft_id,)).fetchone()
        if row is None:
            raise ResearchError('Local draft not found. It may have been deleted.', status=404)
        return row

    def _view(self, db, row):
        values = json.loads(row['document_json'])
        try:
            document = TypeAdapter(DraftInput).validate_python(values)
            context = self._context(db, document)
        except ValueError:
            context = {'blockers': ['Timezone rules changed or are unavailable. Edit and save the draft again.']}
        context_hash = request_hash({'revision': row['revision'], 'document': values, 'context': context})
        reviewed = row['reviewed_revision'] == row['revision'] and row['reviewed_context_hash'] == context_hash
        state = 'blocked' if context['blockers'] else 'reviewed' if reviewed else 'needs_review' if row['reviewed_at'] else 'draft'
        return {k: row[k] for k in ('id', 'kind', 'revision', 'created_at', 'updated_at', 'reviewer', 'review_note', 'reviewed_at')} | {
            'synthetic': bool(row['synthetic']), 'document': values, 'context': context,
            'context_hash': context_hash, 'review_state': state, 'can_export': reviewed and not context['blockers'],
            'delivery_state': 'local_file_only', 'provider_connected': False}

    def get(self, draft_id):
        with self.repository.connect() as db:
            db.execute('BEGIN')
            return self._view(db, self._row(db, draft_id))

    def list(self, mode, offset):
        with self.repository.connect() as db:
            db.execute('BEGIN')
            count = db.execute('SELECT COUNT(*) FROM correspondence_draft WHERE synthetic=?', (mode == 'synthetic',)).fetchone()[0]
            rows = db.execute('SELECT * FROM correspondence_draft WHERE synthetic=? ORDER BY updated_at DESC,id LIMIT ? OFFSET ?',
                              (mode == 'synthetic', PAGE_SIZE, offset)).fetchall()
            items = []
            for row in rows:
                view = self._view(db, row)
                items.append({k: view[k] for k in ('id', 'kind', 'revision', 'synthetic', 'review_state', 'updated_at')} | {
                    'title': view['context'].get('subject', view['context'].get('title', view['document'].get('title', 'Local draft')))})
            return {'items': items, 'total': count, 'offset': offset, 'next_offset': offset + PAGE_SIZE if offset + PAGE_SIZE < count else None}

    def sources(self, mode, offset):
        with self.repository.connect() as db:
            db.execute('BEGIN')
            condition = "c.synthetic=? AND EXISTS(SELECT 1 FROM business b JOIN contact t ON t.business_id=b.id WHERE b.campaign_id=c.id AND t.type='email')"
            total = db.execute(f'SELECT COUNT(*) FROM campaign c WHERE {condition}', (mode == 'synthetic',)).fetchone()[0]
            ids = [r[0] for r in db.execute(f'SELECT c.id FROM campaign c WHERE {condition} ORDER BY c.created_at DESC,c.id LIMIT ? OFFSET ?',
                                          (mode == 'synthetic', PAGE_SIZE, offset))]
            items = []
            for identity in ids:
                record = self.repository.get_in_transaction(db, identity)
                items.append({'id': identity, 'name': record['canonical_name'], 'source_url': record['source_url'],
                              'synthetic': record['synthetic'], 'emails': [
                                  {k: c[k] for k in ('id', 'normalised_value', 'attribution_state', 'suppressed')}
                                  for c in record['contacts'] if c['type'] == 'email']})
            return {'items': items, 'total': total, 'offset': offset, 'next_offset': offset + PAGE_SIZE if offset + PAGE_SIZE < total else None}

    @staticmethod
    def _receipt(db, operation, key, payload):
        previous = db.execute('SELECT * FROM correspondence_request WHERE operation=? AND request_key=?', (operation, key)).fetchone()
        if previous:
            if previous['request_hash'] != request_hash(payload):
                raise ResearchError('This request key was already used with different inputs.', status=409)
            if not db.execute('SELECT 1 FROM correspondence_draft WHERE id=?', (previous['draft_id'],)).fetchone():
                raise ResearchError('This draft was deleted; request replay cannot restore it.', status=409)
        return previous['draft_id'] if previous else None

    @staticmethod
    def _save_receipt(db, operation, key, payload, draft_id):
        if db.execute('SELECT COUNT(*) FROM correspondence_request').fetchone()[0] >= 10000:
            raise ResearchError('The local draft request-history limit was reached.', status=429)
        db.execute('INSERT INTO correspondence_request VALUES(?,?,?,?)', (operation, key, request_hash(payload), draft_id))

    def save(self, document, key, draft_id=None, expected_revision=None):
        operation = 'edit' if draft_id else 'create'
        payload = {'id': draft_id, 'revision': expected_revision, 'document': document.model_dump()}
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = self._receipt(db, operation, key, payload)
            if previous:
                return self._view(db, self._row(db, previous))
            context = self._context(db, document)
            if isinstance(document, EmailDraft) and ('synthetic' not in context or context.get('recipient') is None):
                raise ResearchError('Select an email contact from an existing source record.', status=409)
            timestamp = now()
            if draft_id:
                row = self._row(db, draft_id)
                if row['revision'] != expected_revision or row['kind'] != document.kind:
                    raise ResearchError('This draft changed or its kind does not match. Reopen it before editing.', status=409)
                db.execute('''UPDATE correspondence_draft SET synthetic=?,document_json=?,revision=revision+1,updated_at=?,
                              reviewed_revision=NULL,reviewed_context_hash=NULL,reviewer=NULL,review_note=NULL,reviewed_at=NULL WHERE id=?''',
                           (context['synthetic'], json.dumps(document.model_dump()), timestamp, draft_id))
            else:
                if db.execute('SELECT COUNT(*) FROM correspondence_draft').fetchone()[0] >= 500:
                    raise ResearchError('The 500-draft limit was reached. Delete an unused draft first.', status=429)
                draft_id = uid()
                db.execute('INSERT INTO correspondence_draft(id,kind,synthetic,document_json,revision,created_at,updated_at) VALUES(?,?,?,?,1,?,?)',
                           (draft_id, document.kind, context['synthetic'], json.dumps(document.model_dump()), timestamp, timestamp))
            self._save_receipt(db, operation, key, payload, draft_id)
            return self._view(db, self._row(db, draft_id))

    def review(self, draft_id, payload, key):
        values = {'id': draft_id, **payload.model_dump()}
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = self._receipt(db, 'review', key, values)
            if previous:
                return self._view(db, self._row(db, previous))
            current = self._view(db, self._row(db, draft_id))
            if current['revision'] != payload.expected_revision or current['context_hash'] != payload.context_hash:
                raise ResearchError('Draft or source context changed. Reopen and review the current version.', status=409)
            if current['context']['blockers']:
                raise ResearchError('Resolve the displayed source/time blockers before approving this export.', status=409)
            db.execute('UPDATE correspondence_draft SET reviewed_revision=?,reviewed_context_hash=?,reviewer=?,review_note=?,reviewed_at=? WHERE id=?',
                       (current['revision'], current['context_hash'], payload.reviewer, payload.note, now(), draft_id))
            self._save_receipt(db, 'review', key, values, draft_id)
            return self._view(db, self._row(db, draft_id))

    def export(self, draft_id, revision, context_hash):
        with self.repository.connect() as db:
            # Recheck source suppression and review in one consistent snapshot.
            db.execute('BEGIN')
            draft = self._view(db, self._row(db, draft_id))
            if not draft['can_export'] or draft['revision'] != revision or draft['context_hash'] != context_hash:
                raise ResearchError('Export approval is missing or stale. Reopen and review this draft.', status=409)
            body = email_file(draft) if draft['kind'] == 'email' else calendar_file(draft)
            if len(body) > MAX_EXPORT_BYTES:
                raise ResearchError('The local draft file exceeds its export limit.', status=413)
            return draft['kind'], body

    def delete(self, draft_id):
        with self.repository.connect() as db:
            db.execute('DELETE FROM correspondence_draft WHERE id=?', (draft_id,))
        return {'deleted': True, 'id': draft_id}
