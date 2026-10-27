import json

from fastapi import APIRouter, Depends, Header
from fastapi.responses import Response

from backend.domain.errors import ResearchError
from backend.domain.quality import AuditInput, BaselineInput
from backend.storage.quality import MAX_SNAPSHOT_BYTES, QualityRepository


def quality_router(quality: QualityRepository, authenticate) -> APIRouter:
    router = APIRouter(prefix="/v1/quality/baselines", dependencies=[Depends(authenticate)])

    @router.get("")
    def recent():
        return quality.recent()

    @router.post("")
    def create(payload: BaselineInput, idempotency_key: str = Header(min_length=1, max_length=100)):
        return quality.create(payload, idempotency_key)

    @router.get("/{baseline_id}")
    def get(baseline_id: str):
        return quality.get(baseline_id)

    @router.get("/{baseline_id}/export")
    def export(baseline_id: str):
        document = quality.get(baseline_id)
        body = json.dumps(document, ensure_ascii=False).encode("utf-8")
        if len(body) > MAX_SNAPSHOT_BYTES:
            raise ResearchError("This quality export exceeds 16 MiB. Create a baseline with fewer records; no partial file was created.", status=413)
        return Response(body, media_type="application/json", headers={
            "Content-Disposition": f'attachment; filename="leaddesk-quality-{document["mode"]}-{document["id"]}.json"'})

    @router.post("/{baseline_id}/cases/{research_id}/audit")
    def audit(baseline_id: str, research_id: str, payload: AuditInput, idempotency_key: str = Header(min_length=1, max_length=100)):
        return quality.save_audit(baseline_id, research_id, payload, idempotency_key)

    @router.get("/{baseline_id}/cases/{research_id}/history")
    def history(baseline_id: str, research_id: str):
        return quality.history(baseline_id, research_id)

    return router
