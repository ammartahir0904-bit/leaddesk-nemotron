"""User-assisted screen text and deterministic local actions; never image storage."""
import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import Field, field_validator, model_validator

from backend.domain.errors import ResearchError
from backend.domain.files import FileSearch, LocalInput, MemoryInput


class ScreenFrame(LocalInput):
    captured_at: datetime
    surface: Literal["window", "monitor", "browser", "unknown"]
    width: int = Field(ge=1, le=16384, strict=True)
    height: int = Field(ge=1, le=16384, strict=True)

    @field_validator("captured_at")
    @classmethod
    def aware_timestamp(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Capture time needs a timezone.")
        return value.astimezone(timezone.utc)


class ScreenContext(LocalInput):
    text: str = Field(min_length=1, max_length=4000)
    source: str = Field(min_length=1, max_length=160)
    frame: ScreenFrame | None = None


class ScreenCommand(LocalInput):
    context: ScreenContext
    action: Literal["search_files", "search_memories", "save_note"]
    query: str | None = Field(default=None, min_length=1, max_length=200)
    root_id: str | None = Field(default=None, min_length=1, max_length=100)
    scope: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def explicit_scope(self):
        if self.action == "search_files":
            if not self.root_id or not self.query or self.scope is not None:
                raise ValueError("File search needs keywords and an approved folder only.")
        elif self.action == "search_memories":
            if not self.scope or not self.query or self.root_id is not None:
                raise ValueError("Memory search needs keywords and an exact memory scope only.")
        elif not self.scope or self.query is not None or self.root_id is not None:
            raise ValueError("Saving context needs an exact memory scope only.")
        return self


class ReviewedScreenCommand(ScreenCommand):
    expected_plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def prepare_screen_command(payload):
    context = payload.context
    if payload.action == "search_files":
        search = FileSearch(root_id=payload.root_id, query=payload.query)
        operation = {"kind": "search_files", **search.model_dump()}
        risk, summary = "read_only", f"Search the selected approved folder for: {search.query}"
    elif payload.action == "search_memories":
        operation = {"kind": "search_memories", "scope": payload.scope, "query": payload.query}
        risk, summary = "read_only", f"Search active notes in {payload.scope} for: {payload.query}"
    else:
        source = f"User-assisted context; source label: {context.source}"
        if context.frame:
            frame = context.frame
            source += (f"; client-reported capture: {frame.captured_at.isoformat()}; {frame.surface}; "
                       f"full selected surface (0,0,{frame.width},{frame.height})")
        note = MemoryInput(scope=payload.scope, content=context.text, source=source)
        operation = {"kind": "save_note", "note": note.model_dump(mode="json")}
        risk, summary = "writes_memory", f"Save the reviewed context text in {payload.scope}."
    plan = {"context": context.model_dump(mode="json"), "operation": operation, "risk": risk, "summary": summary,
            "text_origin": "user_assisted", "image_included": False}
    return plan | {"plan_hash": hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()}


def require_screen_plan(payload):
    plan = prepare_screen_command(payload)
    if plan["plan_hash"] != payload.expected_plan_hash:
        raise ResearchError("The context, action or scope changed. Prepare and review it again.", status=409)
    return plan
