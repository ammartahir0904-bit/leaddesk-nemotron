from typing import Literal

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import Response

from backend.domain.correspondence import DraftEdit, DraftInput, ExportReview


def correspondence_router(drafts, authenticate):
    router = APIRouter(prefix='/v1/correspondence', dependencies=[Depends(authenticate)])

    @router.get('/sources')
    def sources(mode: Literal['live', 'synthetic'] = 'live', offset: int = Query(default=0, ge=0, le=100000)):
        return drafts.sources(mode, offset)

    @router.get('/drafts')
    def list_drafts(mode: Literal['live', 'synthetic'] = 'live', offset: int = Query(default=0, ge=0, le=100000)):
        return drafts.list(mode, offset)

    @router.post('/drafts')
    def create(payload: DraftInput, idempotency_key: str = Header(min_length=1, max_length=100)):
        return drafts.save(payload, idempotency_key)

    @router.get('/drafts/{draft_id}')
    def get(draft_id: str):
        return drafts.get(draft_id)

    @router.patch('/drafts/{draft_id}')
    def edit(draft_id: str, payload: DraftEdit, idempotency_key: str = Header(min_length=1, max_length=100)):
        return drafts.save(payload.document, idempotency_key, draft_id, payload.expected_revision)

    @router.post('/drafts/{draft_id}/review')
    def review(draft_id: str, payload: ExportReview, idempotency_key: str = Header(min_length=1, max_length=100)):
        return drafts.review(draft_id, payload, idempotency_key)

    @router.get('/drafts/{draft_id}/export')
    def export(draft_id: str, revision: int = Query(ge=1), context_hash: str = Query(pattern=r'^[a-f0-9]{64}$')):
        kind, body = drafts.export(draft_id, revision, context_hash)
        extension, media = ('eml', 'message/rfc822') if kind == 'email' else ('ics', 'text/calendar')
        return Response(body, media_type=media, headers={'Content-Disposition': f'attachment; filename="leaddesk-{draft_id}.{extension}"'})

    @router.delete('/drafts/{draft_id}')
    def delete(draft_id: str):
        return drafts.delete(draft_id)

    return router
