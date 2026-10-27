from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from backend.domain.errors import ResearchError
from backend.domain.files import FileSearch, MemoryInput
from backend.domain.voice import MAX_AUDIO_BYTES, ReviewedCommand, VoiceCommand, prepare_command


def voice_router(voice, files, memories, authenticate):
    router = APIRouter(prefix="/v1/voice", dependencies=[Depends(authenticate)])

    @router.get("/status")
    def status():
        return voice.adapter.status()

    @router.put("/transcriptions/{job_id}")
    async def transcribe(job_id: UUID, request: Request, language: Literal["auto", "en", "ur"] = "auto"):
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != "audio/wav":
            raise ResearchError("Upload audio/wav with mono 16-bit PCM at 16 kHz.", status=415)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_AUDIO_BYTES:
                raise ResearchError("Recording exceeds the 1 MB upload limit.", status=413)
            body.extend(chunk)
        return JSONResponse(voice.submit(str(job_id), bytes(body), language), status_code=202)

    @router.get("/transcriptions/{job_id}")
    def progress(job_id: UUID):
        return voice.get(str(job_id))

    @router.delete("/transcriptions/{job_id}")
    def cancel(job_id: UUID):
        return voice.cancel(str(job_id))

    @router.post("/commands/prepare")
    def prepare(payload: VoiceCommand):
        plan = prepare_command(payload)
        operation = plan["operation"]
        if operation["kind"] == "search_files" and not any(root["id"] == operation["root_id"] for root in files.roots()["items"]):
            raise ResearchError("Choose a currently approved folder.", status=404)
        return plan

    @router.post("/commands/execute")
    def execute(payload: ReviewedCommand, idempotency_key: str = Header(min_length=1, max_length=100)):
        plan = prepare_command(payload)
        if plan["plan_hash"] != payload.expected_plan_hash:
            raise ResearchError("The command or scope changed. Prepare and review it again.", status=409)
        operation = plan["operation"]
        if operation["kind"] == "search_files":
            result = files.search(FileSearch(root_id=operation["root_id"], query=operation["query"]))
            summary = f"Found {len(result['items'])} current file choices in the selected folder."
        elif operation["kind"] == "search_memories":
            result = memories.list(operation["scope"], operation["query"], limit=3)
            summary = f"Found {result['total']} matching active notes in {operation['scope']}; showing up to three."
        else:
            result = memories.create(MemoryInput(**operation["note"]), idempotency_key)
            summary = f"Saved your reviewed note in {operation['note']['scope']}."
        return {"kind": operation["kind"], "summary": summary, "result": result, "plan_hash": plan["plan_hash"]}

    return router
