from fastapi import APIRouter, Depends, Header

from backend.domain.errors import ResearchError
from backend.domain.pc_worker import CompleteTask, FailTask, LeaseInput, PairWorker, WorkerTask


def pc_worker_router(workers, authenticate):
    router = APIRouter()

    def worker_token(authorization: str = Header(default='')):
        if not authorization.startswith('Bearer ') or not 32 <= len(authorization[7:]) <= 100:
            raise ResearchError('Worker authentication required.', status=401)
        return authorization[7:]

    @router.get('/v1/pc-workers', dependencies=[Depends(authenticate)])
    def overview():
        return workers.overview()

    @router.post('/v1/pc-workers', dependencies=[Depends(authenticate)])
    def pair(payload: PairWorker, idempotency_key: str = Header(min_length=1, max_length=100)):
        return workers.pair(payload, idempotency_key)

    @router.post('/v1/pc-workers/{worker_id}/revoke', dependencies=[Depends(authenticate)])
    def revoke(worker_id: str):
        return workers.revoke(worker_id)

    @router.post('/v1/pc-tasks', dependencies=[Depends(authenticate)], status_code=202)
    def enqueue(payload: WorkerTask, idempotency_key: str = Header(min_length=1, max_length=100)):
        return workers.create(payload, idempotency_key)

    @router.get('/v1/pc-tasks/{task_id}', dependencies=[Depends(authenticate)])
    def get_task(task_id: str):
        return workers.get(task_id)

    @router.post('/v1/pc-tasks/{task_id}/cancel', dependencies=[Depends(authenticate)])
    def cancel(task_id: str):
        return workers.cancel(task_id)

    @router.post('/v1/pc-worker/claim')
    def claim(token: str = Depends(worker_token), idempotency_key: str = Header(min_length=1, max_length=100)):
        return workers.claim(token, idempotency_key)

    @router.post('/v1/pc-worker/tasks/{task_id}/heartbeat')
    def heartbeat(task_id: str, payload: LeaseInput, token: str = Depends(worker_token)):
        return workers.heartbeat(token, task_id, payload.lease_token)

    @router.post('/v1/pc-worker/tasks/{task_id}/complete')
    def complete(task_id: str, payload: CompleteTask, token: str = Depends(worker_token)):
        return workers.complete(token, task_id, payload)

    @router.post('/v1/pc-worker/tasks/{task_id}/fail')
    def fail(task_id: str, payload: FailTask, token: str = Depends(worker_token)):
        return workers.fail(token, task_id, payload)

    return router
