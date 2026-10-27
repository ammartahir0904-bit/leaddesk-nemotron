"""Stateless reviewed text tools. Screenshot bytes never enter these routes."""
from fastapi import APIRouter, Depends, Header

from backend.domain.errors import ResearchError
from backend.domain.files import FileSearch, MemoryInput
from backend.domain.screen import ReviewedScreenCommand, ScreenCommand, prepare_screen_command, require_screen_plan


def screen_router(files, memories, authenticate):
    router = APIRouter(prefix="/v1/screen", dependencies=[Depends(authenticate)])

    def current_folder(plan):
        operation = plan["operation"]
        if operation["kind"] == "search_files" and not any(root["id"] == operation["root_id"] for root in files.roots()["items"]):
            raise ResearchError("Choose a currently approved folder.", status=404)
        return plan

    @router.post("/commands/prepare")
    def prepare(payload: ScreenCommand):
        return current_folder(prepare_screen_command(payload))

    @router.post("/commands/execute")
    def execute(payload: ReviewedScreenCommand, idempotency_key: str = Header(min_length=1, max_length=100)):
        plan = current_folder(require_screen_plan(payload))
        operation = plan["operation"]
        if operation["kind"] == "search_files":
            result = files.search(FileSearch(root_id=operation["root_id"], query=operation["query"]))
            summary = f"Found {len(result['items'])} current file choices in the selected folder."
        elif operation["kind"] == "search_memories":
            result = memories.list(operation["scope"], operation["query"], limit=3)
            summary = f"Found {result['total']} matching active notes in {operation['scope']}; showing up to three."
        else:
            result = memories.create(MemoryInput(**operation["note"]), idempotency_key)
            summary = f"Saved your reviewed context in {operation['note']['scope']}."
        return {"kind": operation["kind"], "summary": summary, "result": result, "plan_hash": plan["plan_hash"]}

    return router
