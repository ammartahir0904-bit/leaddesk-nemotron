"""Bounded discovery inputs and explicit connector capabilities."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.adapters.fetch import validate_url

CONNECTOR = {
    "id": "visible_external_links_v1",
    "name": "Public page links",
    "operations": ["Read a supplied public HTML page", "Discover visible external HTTP(S) links", "Inspect bounded candidate pages"],
    "access": "Public pages only; robots policy and source access restrictions are enforced on every fetch.",
    "cost": "No paid API or model inference.",
    "coverage": "One supplied page, in source link order. Offer text does not filter or rank links. No search engine, pagination, JavaScript rendering or geographic coverage guarantee.",
    "parsing_limits": "Only anchors with visible text are considered. Image-only links and visibility controlled by external CSS are not resolved.",
    "freshness": "Retrieval times are recorded; source publication dates are unknown.",
    "identity": "A link is a candidate website, not proof of a business, branch, offer fit or buying interest.",
}
DEMO_SOURCE = "https://fictional-directory.example/"
TERMINAL = {"completed", "partial", "failed", "cancelled"}


class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    brief_id: str = Field(min_length=1, max_length=100)
    brief_revision: int = Field(ge=1, strict=True)
    source_url: str | None = Field(default=None, max_length=2048)
    synthetic: bool = Field(default=False, strict=True)
    page_budget: int = Field(default=3, ge=1, le=6, strict=True)
    candidate_limit: int = Field(default=10, ge=1, le=20, strict=True)
    time_budget_seconds: int = Field(default=120, ge=30, le=300, strict=True)
    start_paused: bool = Field(default=False, strict=True)

    @field_validator("source_url")
    @classmethod
    def public_url(cls, value):
        return validate_url(value) if value else None

    @model_validator(mode="after")
    def source_scope(self):
        if self.synthetic and self.source_url is not None:
            raise ValueError("Synthetic jobs use only the fixed fictional source; omit source_url.")
        if not self.synthetic and self.source_url is None:
            raise ValueError("A supplied public source_url is required.")
        return self


class JobControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["pause", "resume", "cancel"]
