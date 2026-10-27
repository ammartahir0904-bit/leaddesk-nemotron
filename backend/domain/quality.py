"""Human audit inputs and the factual units in a frozen research snapshot."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.domain.errors import ResearchError

Id = Annotated[str, Field(min_length=1, max_length=100)]
ISSUE_TAGS = ("positive_fit", "no_need", "existing_solution", "closed_branch", "copied_listing",
              "same_name", "wrong_phone", "wrong_branch", "directory_operator", "missing_evidence", "other")


class QualityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BaselineInput(QualityModel):
    name: str = Field(min_length=3, max_length=120)
    mode: Literal["live", "synthetic"]
    split: Literal["development", "holdout"] = "development"
    research_ids: list[Id] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_records(self):
        if len(set(self.research_ids)) != len(self.research_ids):
            raise ValueError("Select each research record only once.")
        return self


class Verdict(QualityModel):
    outcome: Literal["pass", "fail", "unknown"] = "unknown"
    evidence_ids: list[Id] = Field(default_factory=list, max_length=4)
    reason: str = Field(default="", max_length=400)

    @model_validator(mode="after")
    def explain_known_outcomes(self):
        if self.outcome != "unknown" and (not self.evidence_ids or not self.reason):
            raise ValueError("Pass/fail judgements require saved evidence and a reason.")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("Select each evidence ID only once.")
        return self


class UnitVerdict(Verdict):
    target_id: Id


class AuditInput(QualityModel):
    expected_revision: int = Field(ge=0, strict=True)
    reviewer: str = Field(min_length=2, max_length=80)
    identity: Verdict = Field(default_factory=Verdict)
    relevance: Verdict = Field(default_factory=Verdict)
    contacts: list[UnitVerdict] = Field(default_factory=list, max_length=50)
    claims: list[UnitVerdict] = Field(default_factory=list, max_length=70)
    issue_tags: list[Literal["positive_fit", "no_need", "existing_solution", "closed_branch", "copied_listing",
                             "same_name", "wrong_phone", "wrong_branch", "directory_operator", "missing_evidence", "other"]] = Field(default_factory=list, max_length=11)
    notes: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def unique_targets(self):
        for values in (self.contacts, self.claims):
            if len({v.target_id for v in values}) != len(values):
                raise ValueError("Each audit target can be reviewed only once per revision.")
        if len(set(self.issue_tags)) != len(self.issue_tags):
            raise ValueError("Select each issue tag only once.")
        return self


def factual_units(record: dict) -> list[dict]:
    """Publication/quoted facts only: no inferred need, fit, budget or interest."""
    units = [{"id": f"claim:{c['id']}", "label": "Source heading", "value": c["value"],
              "evidence_ids": [c["evidence_id"]]} for c in record["claims"] if not c.get("inference_flag")]
    units += [{"id": f"contact:{c['id']}", "label": "Source publishes contact (ownership separate)",
               "value": c["raw_value"], "evidence_ids": c["evidence_ids"]} for c in record["contacts"]]
    assessment = record.get("assessment") or {}
    identity = (assessment.get("identity") or {}).get("document") or {}
    for field in ("business_name", "branch", "address", "service_area"):
        if identity.get(field):
            units.append({"id": f"identity:{field}", "label": f"Quoted {field.replace('_', ' ')}", **identity[field]})
    analysis = (assessment.get("analysis") or {}).get("document") or {}
    for field in ("observations", "existing_solutions"):
        for index, quote in enumerate(analysis.get(field, [])):
            units.append({"id": f"{field}:{index}", "label": field.replace("_", " "), **quote})
    return units


def snapshot_evidence(snapshot: dict) -> dict:
    return {e["id"]: e for source in [snapshot["research"], *snapshot["comparison_sources"]] for e in source["evidence"]}


def validate_audit(snapshot: dict, audit: AuditInput):
    evidence = snapshot_evidence(snapshot)
    contacts = {c["id"]: c for c in snapshot["lead"]["contacts"]}
    units = {u["id"]: u for u in snapshot["units"]}
    for verdict in [audit.identity, audit.relevance, *audit.contacts, *audit.claims]:
        if set(verdict.evidence_ids) - evidence.keys():
            raise ResearchError("Audit citations must belong to this frozen case or its saved comparison sources.")
    if audit.identity.outcome != "unknown" and snapshot["lead"]["identity_status"] != "source_attributed":
        raise ResearchError("This case has no source-attributed identity prediction. Leave its identity audit unknown.")
    if audit.identity.outcome != "unknown":
        identity = snapshot["research"]["assessment"]["identity"]["document"]
        if not set(identity["business_name"]["evidence_ids"]).intersection(audit.identity.evidence_ids):
            raise ResearchError("Identity audits must cite the captured business-name evidence; comparison evidence may be added separately.")
    for verdict, targets in [(v, contacts) for v in audit.contacts] + [(v, units) for v in audit.claims]:
        if verdict.target_id not in targets:
            raise ResearchError("An audited contact or factual unit is missing or belongs to another case.")
        refs = set(targets[verdict.target_id]["evidence_ids"])
        if verdict.outcome != "unknown" and refs and not refs.intersection(verdict.evidence_ids):
            raise ResearchError("A contact/factual audit must cite at least one of that target's own saved excerpts.")
        if verdict.outcome == "pass" and not refs:
            raise ResearchError("A factual unit without saved references cannot receive a supported judgement.")
