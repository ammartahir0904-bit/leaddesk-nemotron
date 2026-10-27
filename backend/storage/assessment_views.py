"""Read-only comparisons and effective review states, with bounded local scope."""
import hashlib
import json
from urllib.parse import urlsplit

from backend.domain.assessments import normalized
from backend.domain.errors import ResearchError


def state_of(raw):
    return json.loads(raw) if raw else {}


def raw_record(db, research_id: str) -> dict:
    row = db.execute("SELECT c.id,c.synthetic,c.assessment_json,b.id AS business_id,b.canonical_name,b.source_url FROM campaign c JOIN business b ON b.campaign_id=c.id WHERE c.id=?", (research_id,)).fetchone()
    if row is None:
        raise ResearchError("Comparison research record not found.", status=404)
    record = dict(row)
    record["state"] = state_of(record.pop("assessment_json"))
    record["evidence"] = [dict(e) for e in db.execute("SELECT * FROM evidence WHERE business_id=?", (record["business_id"],))]
    record["contacts"] = [dict(c) for c in db.execute("SELECT * FROM contact WHERE business_id=?", (record["business_id"],))]
    return record


def identity_signature(db, research_id: str) -> dict:
    row = db.execute("SELECT assessment_json FROM campaign WHERE id=?", (research_id,)).fetchone()
    state = state_of(row[0]) if row else {}
    flags = [list(r) for r in db.execute("SELECT c.id,c.suppressed FROM contact c JOIN business b ON b.id=c.business_id WHERE b.campaign_id=? ORDER BY c.id", (research_id,))]
    return {"revision": state.get("identity", {}).get("revision", 0), "contact_flags": flags}


def related_records(db, record: dict) -> dict:
    rows = db.execute("SELECT c.id,c.synthetic,b.canonical_name,b.source_url,b.id AS business_id FROM campaign c JOIN business b ON b.campaign_id=c.id WHERE c.id<>? AND c.synthetic=? ORDER BY c.created_at DESC LIMIT 201", (record["id"], int(record["synthetic"]))).fetchall()
    local_keys = {(c["type"], c["normalised_value"]) for c in record["contacts"]}
    matches, seen, duplicates = [], {record["source_url"]}, 0
    total_required = 0
    for row in rows[:200]:
        if row["source_url"] in seen:
            duplicates += 1
            continue
        seen.add(row["source_url"])
        keys = {(c[0], c[1]) for c in db.execute("SELECT type,normalised_value FROM contact WHERE business_id=?", (row["business_id"],))}
        same_host = urlsplit(row["source_url"]).hostname == urlsplit(record["source_url"]).hostname
        shared_contact = bool(local_keys & keys)
        same_name = bool(record["canonical_name"] and row["canonical_name"] and normalized(record["canonical_name"]) == normalized(row["canonical_name"]))
        if not (same_host or shared_contact or same_name):
            continue
        reasons = (["Shared host with a different page"] if same_host else []) + (["Shared contact value"] if shared_contact else []) + (["Same source heading"] if same_name else [])
        required = same_host or shared_contact
        total_required += int(required)
        if len(matches) < 20:
            other = raw_record(db, row["id"])
            matches.append({"id": row["id"], "source_url": row["source_url"], "name": row["canonical_name"],
                            "reasons": reasons, "requires_comparison": required, "evidence": other["evidence"],
                            "identity_signature": identity_signature(db, row["id"])})
    return {"records": matches, "scan_limited": len(rows) > 200,
            "required_overflow": total_required > sum(m["requires_comparison"] for m in matches),
            "duplicate_pages_skipped": duplicates,
            "scope": "Up to 200 recent records, 20 related source pages; same-page repeats and synthetic/live records are kept separate. Signals are comparison hints, not identity proof."}


def identity_blockers(db, record: dict, identity: dict | None, related: dict) -> list[str]:
    if identity is None:
        return ["Business and branch identity have not been reviewed."]
    doc = identity["document"]
    reasons = []
    if doc["decision"] != "source_attributed":
        reasons.append("Identity is disputed or unresolved.")
    if doc["source_role"] not in {"business", "shared_brand"}:
        reasons.append("The source has not been reviewed as a business page.")
    comparisons = {c["research_id"]: c for c in doc["comparisons"]}
    for other in related["records"]:
        review = comparisons.get(other["id"])
        if other["requires_comparison"] and (review is None or review["decision"] == "unresolved"):
            reasons.append("A shared-domain/contact comparison remains unresolved.")
        if review and review["decision"] != "unresolved":
            if identity.get("comparison_signatures", {}).get(other["id"]) != other["identity_signature"]:
                reasons.append("A compared record changed; review its identity/contact comparison again.")
    related_ids = {r["id"] for r in related["records"]}
    for other_id, review in comparisons.items():
        if other_id not in related_ids and review["decision"] != "unresolved":
            if identity.get("comparison_signatures", {}).get(other_id) != identity_signature(db, other_id):
                reasons.append("A compared record changed; review its identity/contact comparison again.")
    if related["required_overflow"] or related["scan_limited"]:
        reasons.append("The bounded comparison scan cannot cover all local records; identity needs further review.")
    return list(dict.fromkeys(reasons))


def dependency_hash(db, record: dict, identity: dict | None, related: dict) -> str:
    value = {"identity_revision": identity["revision"] if identity else 0,
             "contacts": sorted((c["id"], bool(c["suppressed"])) for c in record["contacts"]),
             "related": [(r["id"], r["identity_signature"]) for r in related["records"]],
             "comparisons": [(c["research_id"], identity_signature(db, c["research_id"]))
                             for c in identity["document"]["comparisons"]] if identity else [],
             "scan_limited": related["scan_limited"], "required_overflow": related["required_overflow"]}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def decorate_record(db, record: dict, state: dict) -> dict:
    identity = state.get("identity")
    analysis = state.get("analysis")
    related = related_records(db, record)
    blockers = identity_blockers(db, record, identity, related)
    current_hash = dependency_hash(db, record, identity, related)
    disputed_evidence = {eid for c in record["contacts"] if c["suppressed"] for eid in c["evidence_ids"]}
    reasons = []
    if analysis:
        if analysis["dependency_hash"] != current_hash:
            reasons.append("Identity, related records or contact corrections changed after this analysis.")
        if set(analysis["evidence_ids"]) & disputed_evidence:
            reasons.append("Analysis cites evidence attached to a disputed contact.")
    record["assessment"] = {"identity": identity, "analysis": analysis, "identity_blockers": blockers,
                            "analysis_state": "needs_review" if reasons else "current" if analysis else "not_reviewed",
                            "analysis_review_reasons": reasons, "related_scope": related["scope"],
                            "intent_state": "unknown", "budget": None,
                            "scope": "Source-reviewed judgements and hypotheses; no corroboration, reachability, buying interest or outreach approval is established."}
    if identity:
        doc = identity["document"]
        record["identity_status"] = "disputed" if doc["decision"] == "disputed" else "unresolved" if blockers else "source_attributed"
        reviews = {c["contact_id"]: c for c in doc["contact_reviews"]}
        for contact in record["contacts"]:
            contact["review_blocked"] = doc["decision"] == "disputed"
            review = reviews.get(contact["id"])
            if not contact["suppressed"] and not blockers and review and review["decision"] == "attributed":
                contact["attribution_state"] = "attributed"
                contact["attribution_reviewed_at"] = identity["updated_at"]
        record["unknowns"]["official_business_identity"] = "Source identity has a manual review; official ownership and independent corroboration are not established."
        if doc["address"] or doc["service_area"]:
            record["unknowns"]["business_location"] = "Cited source location text is saved in the review; geographic matching remains a reviewer judgement, not an independently verified address."
    if analysis:
        record["unknowns"]["product_fit"] = "A reviewed inference is available; revisit it if identity, contacts or evidence change."
    return record
