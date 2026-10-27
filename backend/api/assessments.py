from fastapi import APIRouter, Depends, Header

from backend.domain.assessments import IdentityReview, NeedAnalysis
from backend.storage.assessments import AssessmentRepository


def assessment_router(assessments: AssessmentRepository, authenticate) -> APIRouter:
    router = APIRouter(prefix="/v1/research", dependencies=[Depends(authenticate)])

    @router.get("/{research_id}/related")
    def related(research_id: str):
        return assessments.related(research_id)

    @router.get("/{research_id}/assessments/history")
    def history(research_id: str):
        return assessments.history(research_id)

    @router.post("/{research_id}/identity-review")
    def review_identity(research_id: str, payload: IdentityReview, idempotency_key: str = Header(min_length=1, max_length=100)):
        return assessments.save(research_id, "identity", payload, idempotency_key)

    @router.post("/{research_id}/need-analysis")
    def review_need(research_id: str, payload: NeedAnalysis, idempotency_key: str = Header(min_length=1, max_length=100)):
        return assessments.save(research_id, "analysis", payload, idempotency_key)

    return router
