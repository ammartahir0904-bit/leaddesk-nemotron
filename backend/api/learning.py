import json
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import Response

from backend.domain.errors import ResearchError
from backend.domain.learning import DatasetInput, ExampleReview
from backend.storage.learning import MAX_EXPORT_BYTES


def learning_router(learning, authenticate):
    router = APIRouter(prefix='/v1/learning', dependencies=[Depends(authenticate)])

    @router.get('/sources')
    def sources(mode: Literal['live', 'synthetic'] = 'live', offset: int = Query(default=0, ge=0, le=100000)):
        return learning.sources(mode, offset)

    @router.get('/examples')
    def examples(mode: Literal['live', 'synthetic'] = 'live', offset: int = Query(default=0, ge=0, le=100000)):
        return learning.examples(mode, offset)

    @router.post('/examples')
    def review(payload: ExampleReview, idempotency_key: str = Header(min_length=1, max_length=100)):
        return learning.review(payload, idempotency_key)

    @router.delete('/examples/{example_id}')
    def delete_example(example_id: str):
        return learning.delete_example(example_id)

    @router.get('/versions')
    def versions(offset: int = Query(default=0, ge=0, le=100000)):
        return learning.versions(offset)

    @router.post('/versions')
    def create_version(payload: DatasetInput, idempotency_key: str = Header(min_length=1, max_length=100)):
        return learning.create_version(payload, idempotency_key)

    @router.get('/versions/{version_id}')
    def get_version(version_id: str):
        return learning.version(version_id)

    @router.get('/versions/{version_id}/export')
    def export_version(version_id: str):
        result = learning.version(version_id)
        if result['status'] != 'ready':
            raise ResearchError('This version was invalidated by a review, permission, source or deletion change. Create a new reviewed version.', status=409)
        body = json.dumps(result, ensure_ascii=False).encode('utf-8')
        if len(body) > MAX_EXPORT_BYTES:
            raise ResearchError('Dataset exceeds the 2 MiB export limit.', status=413)
        return Response(body, media_type='application/json', headers={
            'Content-Disposition': f'attachment; filename="leaddesk-dataset-{result["mode"]}-{result["id"]}.json"'})

    @router.delete('/versions/{version_id}')
    def delete_version(version_id: str):
        return learning.delete_version(version_id)

    return router
