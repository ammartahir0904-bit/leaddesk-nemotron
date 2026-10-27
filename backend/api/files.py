import json

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import Response

from backend.domain.files import FileCorrection, FileSearch, FolderInput, MemoryEdit, MemoryInput


def files_router(files, memories, authenticate):
    router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])

    @router.get("/files/roots")
    def roots():
        return files.roots()

    @router.post("/files/roots")
    def approve(payload: FolderInput):
        return files.approve(payload.path)

    @router.delete("/files/roots/{root_id}")
    def revoke(root_id: str):
        return files.revoke(root_id)

    @router.post("/files/roots/{root_id}/reconcile")
    def reconcile(root_id: str):
        return files.reconcile(root_id)

    @router.post("/files/search")
    def search(payload: FileSearch):
        return files.search(payload)

    @router.get("/files/{file_id}/preview")
    def preview(file_id: str):
        return files.preview(file_id)

    @router.post("/files/corrections")
    def correct(payload: FileCorrection):
        return files.correct(payload)

    @router.delete("/files/corrections/{correction_id}")
    def undo(correction_id: str):
        return files.undo(correction_id)

    @router.get("/memories")
    def list_memories(scope: str = Query(min_length=1, max_length=120), q: str = Query(default="", max_length=200), include_expired: bool = False,
                      offset: int = Query(default=0, ge=0, le=1000)):
        return memories.list(scope, q, include_expired, offset=offset)

    @router.get("/memories/export")
    def export(scope: str = Query(min_length=1, max_length=120)):
        body = json.dumps(memories.list(scope, include_expired=True, limit=1000), ensure_ascii=False)
        return Response(body, media_type="application/json", headers={"Content-Disposition": 'attachment; filename="leaddesk-memories.json"'})

    @router.post("/memories")
    def create(payload: MemoryInput, idempotency_key: str = Header(min_length=1, max_length=100)):
        return memories.create(payload, idempotency_key)

    @router.patch("/memories/{memory_id}")
    def update(memory_id: str, payload: MemoryEdit):
        return memories.update(memory_id, payload)

    @router.delete("/memories/scope")
    def forget(scope: str = Query(min_length=1, max_length=120)):
        return memories.forget(scope)

    @router.delete("/memories/{memory_id}")
    def delete(memory_id: str):
        return memories.delete(memory_id)

    return router
