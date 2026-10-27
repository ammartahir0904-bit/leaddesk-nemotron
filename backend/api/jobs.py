"""Authenticated queue API. Enqueue returns before any page is fetched."""
from fastapi import APIRouter, Depends, Header

from backend.domain.jobs import CONNECTOR, JobControl, JobInput
from backend.storage.jobs import JobRepository
from backend.workflows.worker import WorkflowWorker


def job_router(jobs: JobRepository, worker: WorkflowWorker, authenticate) -> APIRouter:
    router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])

    @router.get("/discovery/connectors")
    def connectors():
        return [CONNECTOR]

    @router.get("/jobs")
    def recent_jobs():
        return jobs.recent()

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str):
        return jobs.get(job_id)

    @router.post("/jobs", status_code=202)
    def create_job(payload: JobInput, idempotency_key: str = Header(min_length=1, max_length=100)):
        job = jobs.create(payload, idempotency_key)
        worker.wake()
        return job

    @router.post("/jobs/{job_id}/control")
    def control_job(job_id: str, payload: JobControl, idempotency_key: str = Header(min_length=1, max_length=100)):
        job = jobs.control(job_id, payload.action, idempotency_key)
        worker.wake()
        return job

    return router
