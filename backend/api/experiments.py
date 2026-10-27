import json
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import Response

from backend.domain.errors import ResearchError
from backend.domain.experiments import BuiltinRunInput, ExperimentInput


def experiments_router(experiments, authenticate):
    router = APIRouter(prefix='/v1/experiments', dependencies=[Depends(authenticate)])

    @router.get('')
    def reports(mode: Literal['live', 'synthetic'] = 'live', offset: int = Query(default=0, ge=0, le=100000)):
        return experiments.list(mode, offset)

    @router.post('')
    def create(payload: ExperimentInput, idempotency_key: str = Header(min_length=1, max_length=100)):
        return experiments.create(payload, idempotency_key)

    @router.post('/builtin')
    def builtin(payload: BuiltinRunInput, idempotency_key: str = Header(min_length=1, max_length=100)):
        return experiments.run_builtin(payload, idempotency_key)

    @router.get('/{experiment_id}')
    def get(experiment_id: str):
        return experiments.get(experiment_id)

    @router.get('/{experiment_id}/export')
    def export(experiment_id: str):
        result = experiments.get(experiment_id)
        if result['status'] != 'ready':
            raise ResearchError('This report was invalidated by a dataset/source change.', status=409)
        return Response(json.dumps(result, ensure_ascii=False), media_type='application/json', headers={
            'Content-Disposition': f'attachment; filename="leaddesk-evaluation-{result["id"]}.json"'})

    @router.delete('/{experiment_id}')
    def delete(experiment_id: str):
        return experiments.delete(experiment_id)

    return router
