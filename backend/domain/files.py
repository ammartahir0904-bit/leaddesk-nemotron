"""Explicit local scopes and user-authored memory inputs."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LocalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FolderInput(LocalInput):
    path: str = Field(min_length=1, max_length=2000)


def query_key(value):
    return " ".join(value.casefold().split())


class FileSearch(LocalInput):
    root_id: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=200)

    @field_validator("query")
    @classmethod
    def normalized_query(cls, value):
        return query_key(value)


class FileCorrection(FileSearch):
    file_id: str = Field(min_length=1, max_length=100)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["wrong", "preferred"]
    comment: str = Field(min_length=1, max_length=500)


class MemoryInput(LocalInput):
    scope: str = Field(min_length=1, max_length=120)
    kind: Literal["preference", "file_alias", "project_context", "product_fact", "correction"] = "project_context"
    content: str = Field(min_length=1, max_length=4000)
    source: str = Field(default="", max_length=500)
    pinned: bool = Field(default=False, strict=True)
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def aware_expiry(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Expiry needs a timezone.")
            return value.astimezone(timezone.utc)
        return value


class MemoryEdit(MemoryInput):
    expected_revision: int = Field(ge=1, strict=True)
