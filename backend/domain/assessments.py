"""Evidence-backed review inputs; user judgements never become source facts."""
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.domain.errors import ResearchError

EvidenceId = Annotated[str, Field(min_length=1, max_length=100)]
Note = Annotated[str, Field(min_length=1, max_length=400)]


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceQuote(ReviewModel):
    value: str = Field(min_length=1, max_length=300)
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=4)


class ContactReview(ReviewModel):
    contact_id: str = Field(min_length=1, max_length=100)
    decision: Literal["unreviewed", "attributed"] = "unreviewed"
    evidence_ids: list[EvidenceId] = Field(default_factory=list, max_length=5)


class Comparison(ReviewModel):
    research_id: str = Field(min_length=1, max_length=100)
    decision: Literal["unresolved", "different_business", "different_branch", "same_business_branch"] = "unresolved"
    local_evidence_ids: list[EvidenceId] = Field(default_factory=list, max_length=4)
    other_evidence_ids: list[EvidenceId] = Field(default_factory=list, max_length=4)
    reason: str = Field(default="", max_length=400)

    @model_validator(mode="after")
    def grounded_judgement(self):
        if self.decision != "unresolved" and (not self.local_evidence_ids or not self.other_evidence_ids or not self.reason):
            raise ValueError("A comparison judgement needs evidence from both records and a reason.")
        return self


class IdentityReview(ReviewModel):
    expected_revision: int = Field(ge=0, strict=True)
    decision: Literal["unresolved", "source_attributed", "disputed"] = "unresolved"
    source_role: Literal["unknown", "business", "shared_brand", "directory", "agency"] = "unknown"
    business_name: SourceQuote | None = None
    branch: SourceQuote | None = None
    address: SourceQuote | None = None
    service_area: SourceQuote | None = None
    geography: Literal["unknown", "matches", "outside_target"] = "unknown"
    exclusions: Literal["not_checked", "clear", "excluded"] = "not_checked"
    exclusion_reason: str = Field(default="", max_length=400)
    contact_reviews: list[ContactReview] = Field(default_factory=list, max_length=50)
    comparisons: list[Comparison] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def distinct_review_scopes(self):
        if len({c.contact_id for c in self.contact_reviews}) != len(self.contact_reviews):
            raise ValueError("A contact can only appear once in a review.")
        if len({c.research_id for c in self.comparisons}) != len(self.comparisons):
            raise ValueError("A related record can only appear once in a review.")
        if self.decision == "source_attributed":
            if self.source_role not in {"business", "shared_brand"} or self.business_name is None:
                raise ValueError("Source attribution requires a reviewed business source and cited business name.")
            if self.source_role == "shared_brand" and self.branch is None:
                raise ValueError("A shared brand page needs explicit branch evidence.")
        if self.geography != "unknown" and self.address is None and self.service_area is None:
            raise ValueError("A geography judgement requires cited address or service-area text.")
        if self.exclusions != "not_checked" and not self.exclusion_reason:
            raise ValueError("Record why the offer's exclusions are clear or apply.")
        return self


class NeedAnalysis(ReviewModel):
    expected_revision: int = Field(ge=0, strict=True)
    fit: Literal["unknown", "review", "possible_fit", "not_a_fit"] = "review"
    observations: list[SourceQuote] = Field(default_factory=list, max_length=5)
    need_hypothesis: str = Field(default="", max_length=600)
    offer_relevance: str = Field(default="", max_length=600)
    existing_solution_status: Literal["not_checked", "not_described_in_selected_excerpts", "source_described"] = "not_checked"
    existing_solutions: list[SourceQuote] = Field(default_factory=list, max_length=3)
    checked_evidence_ids: list[EvidenceId] = Field(default_factory=list, max_length=8)
    replacement_reason: str = Field(default="", max_length=400)
    alternative_explanations: list[Note] = Field(min_length=1, max_length=5)
    missing_checks: list[Note] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def alternatives_are_scoped(self):
        if self.existing_solution_status == "source_described":
            if not self.existing_solutions:
                raise ValueError("Cite the solution described by the source.")
        elif self.existing_solutions:
            raise ValueError("Source solution quotes require source_described status.")
        if self.existing_solution_status == "not_described_in_selected_excerpts" and not self.checked_evidence_ids:
            raise ValueError("Select the excerpts actually checked for existing solutions.")
        if self.fit == "possible_fit":
            if not self.observations or not self.need_hypothesis or not self.offer_relevance:
                raise ValueError("Possible fit needs source observations plus explicit need/relevance hypotheses.")
            if self.existing_solution_status == "not_checked":
                raise ValueError("Check existing alternatives before assessing possible fit.")
            if self.existing_solution_status == "source_described" and not self.replacement_reason:
                raise ValueError("Explain why investigating a change may help despite the existing solution.")
        return self


def normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def contains_quote(excerpt: str, value: str) -> bool:
    needle = normalized(value)
    haystack = normalized(excerpt)
    pattern = (r"(?<!\w)" if needle[0].isalnum() else "") + re.escape(needle) + (r"(?!\w)" if needle[-1].isalnum() else "")
    return bool(re.search(pattern, haystack))


def require_evidence(ids: list[str], evidence: dict) -> set[str]:
    unknown = set(ids) - evidence.keys()
    if unknown:
        raise ResearchError("A cited evidence ID is missing or belongs to another research record.")
    return set(ids)


def validate_quote(quote: SourceQuote, evidence: dict) -> set[str]:
    refs = require_evidence(quote.evidence_ids, evidence)
    if any(not contains_quote(evidence[eid]["excerpt"], quote.value) for eid in refs):
        raise ResearchError("A source quote must occur in every cited excerpt. Keep interpretations in the hypothesis fields.")
    return refs
