"""Dashboard filters and conservative, evidence-preserving lead summaries."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LeadFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mode: Literal["live", "synthetic"] = "live"
    q: str = Field(default="", max_length=200)
    identity: Literal["all", "unresolved", "source_attributed", "disputed"] = "all"
    contact: Literal["all", "attributed", "extracted", "excluded", "none"] = "all"
    analysis: Literal["all", "not_reviewed", "current", "needs_review"] = "all"
    fit: Literal["all", "unknown", "review", "possible_fit", "not_a_fit"] = "all"
    review: Literal["all", "needs_review", "excluded", "source_reviewed"] = "all"


class LeadPage(LeadFilters):
    offset: int = Field(default=0, ge=0, le=200)
    limit: int = Field(default=20, ge=1, le=50)


class LeadExport(LeadFilters):
    format: Literal["json", "csv"] = "json"


def summarize(record: dict) -> dict:
    assessment = record.get("assessment") or {}
    identity = assessment.get("identity") or {}
    identity_doc = identity.get("document") or {}
    analysis = assessment.get("analysis") or {}
    analysis_doc = analysis.get("document") or {}
    analysis_state = assessment.get("analysis_state", "not_reviewed")
    saved_fit = analysis_doc.get("fit", "unknown")
    effective_fit = saved_fit if analysis_state == "current" else "review" if analysis else "unknown"
    reasons = list(assessment.get("identity_blockers", []))
    if not identity:
        reasons.append("Business and branch identity have not been reviewed.")
    reasons += assessment.get("analysis_review_reasons", [])
    exclusions = []
    if record["identity_status"] == "disputed":
        exclusions.append("Business identity is disputed.")
    if identity_doc.get("geography") == "outside_target":
        exclusions.append("Reviewed source location is outside the target geography.")
    if identity_doc.get("exclusions") == "excluded":
        exclusions.append(identity_doc["exclusion_reason"])
    if effective_fit == "not_a_fit":
        exclusions.append("Current reviewer judgement is not a fit.")
    if exclusions:
        effective_fit = "not_a_fit" if record["identity_status"] != "disputed" else "review"
    evidence = {e["id"]: e for e in record["evidence"]}
    contacts = []
    for contact in record["contacts"]:
        excluded = bool(contact["suppressed"] or contact.get("review_blocked") or exclusions)
        contacts.append(contact | {
            "excluded": excluded,
            "effective_state": "excluded" if excluded else contact["attribution_state"],
            "exclusion_reasons": (["Contact correction suppresses this value on this host."] if contact["suppressed"] else []) + exclusions,
            "evidence": [evidence[eid] for eid in contact["evidence_ids"]],
            "reachability": "unknown", "outreach_approved": False,
        })
    if contacts and all(c["excluded"] for c in contacts) and not exclusions:
        exclusions.append("All extracted contacts are excluded by corrections or identity review.")
    if not analysis:
        reasons.append("Need and offer relevance have not been reviewed.")
    if effective_fit in {"unknown", "review"} and analysis:
        reasons.append("Offer fit requires further review.")
    if not contacts:
        reasons.append("No public contact was extracted from this page.")
    elif any(c["effective_state"] == "extracted" for c in contacts):
        reasons.append("One or more contact ownership reviews remain incomplete.")
    review_state = "excluded" if exclusions else "needs_review" if reasons else "source_reviewed"
    if exclusions:
        next_action = "Review the exclusion reasons before considering this prospect."
    elif analysis_state == "needs_review":
        next_action = "Recheck saved analysis against the changed identity, comparisons or corrections."
    elif record["identity_status"] != "source_attributed":
        next_action = "Review business and branch identity against the saved source evidence."
    elif not contacts:
        next_action = "Inspect a permitted public contact page."
    elif not analysis or effective_fit in {"review", "unknown"}:
        next_action = "Review need, offer relevance and existing alternatives."
    elif any(c["effective_state"] == "extracted" for c in contacts):
        next_action = "Review each contact's source and branch attribution."
    else:
        next_action = "Independently check source freshness, contact ownership and need; interest and budget remain unknown."
    quoted = lambda field: (identity_doc.get(field) or {}).get("value")
    return {
        "id": record["id"], "synthetic": record["synthetic"], "created_at": record["created_at"],
        "source_url": record["source_url"], "source_heading": record["canonical_name"],
        "business_name": quoted("business_name"), "branch": quoted("branch"),
        "address": quoted("address"), "service_area": quoted("service_area"),
        "identity_status": record["identity_status"], "identity_reviewed_at": identity.get("updated_at"),
        "product": record["product"], "target_geography": record["geography"],
        "contacts": contacts, "analysis_state": analysis_state, "saved_fit": saved_fit,
        "effective_fit": effective_fit, "analysis_reviewed_at": analysis.get("updated_at"),
        "need_hypothesis": analysis_doc.get("need_hypothesis") or None,
        "analysis_interpretation": analysis_doc.get("interpretation", "No need analysis has been reviewed."),
        "review_state": review_state, "review_reasons": list(dict.fromkeys(reasons)),
        "exclusion_reasons": exclusions, "next_action": next_action,
        "intent_state": "unknown", "budget": None,
        "budget_reason": "No documented prospect interaction establishes a budget.",
        "outreach_approved": False,
    }


def matches(lead: dict, filters: LeadFilters) -> bool:
    search = " ".join(str(lead.get(field) or "") for field in (
        "source_heading", "business_name", "branch", "address", "service_area", "source_url", "product", "target_geography"))
    search += " " + " ".join(c["raw_value"] for c in lead["contacts"])
    if filters.q.casefold() not in search.casefold():
        return False
    for selected, field in ((filters.identity, "identity_status"), (filters.analysis, "analysis_state"),
                            (filters.fit, "effective_fit"), (filters.review, "review_state")):
        if selected != "all" and selected != lead[field]:
            return False
    if filters.contact == "none":
        return not lead["contacts"]
    return filters.contact == "all" or any(c["effective_state"] == filters.contact for c in lead["contacts"])
