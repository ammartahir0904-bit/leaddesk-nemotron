"""Atomic manual assessments with immutable revisions and scoped evidence links."""
import json

from backend.domain.assessments import IdentityReview, NeedAnalysis, contains_quote, require_evidence, validate_quote
from backend.domain.errors import ResearchError
from backend.storage.assessment_views import dependency_hash, identity_blockers, identity_signature, raw_record, related_records, state_of
from backend.storage.repository import Repository, now, request_hash, uid


class AssessmentRepository:
    def __init__(self, repository: Repository):
        self.repository = repository

    def related(self, research_id: str) -> dict:
        with self.repository.connect() as db:
            return related_records(db, raw_record(db, research_id))

    def history(self, research_id: str) -> list[dict]:
        with self.repository.connect() as db:
            raw_record(db, research_id)
            rows = db.execute("SELECT * FROM assessment_revision WHERE campaign_id=? ORDER BY created_at DESC LIMIT 100", (research_id,)).fetchall()
        return [{"id": r["id"], "kind": r["kind"], "revision": r["revision"], "created_at": r["created_at"],
                 "review": json.loads(r["document_json"])} for r in rows]

    def _identity(self, db, record: dict, payload: IdentityReview) -> tuple[dict, set[str]]:
        evidence = {e["id"]: e for e in record["evidence"]}
        refs = set()
        for field in (payload.business_name, payload.branch, payload.address, payload.service_area):
            if field:
                refs |= validate_quote(field, evidence)
        signatures = {}
        for comparison in payload.comparisons:
            if comparison.research_id == record["id"]:
                raise ResearchError("Compare a different research record.")
            other = raw_record(db, comparison.research_id)
            if bool(other["synthetic"]) != bool(record["synthetic"]):
                raise ResearchError("Synthetic and real records cannot be linked by an identity review.")
            refs |= require_evidence(comparison.local_evidence_ids, evidence)
            refs |= require_evidence(comparison.other_evidence_ids, {e["id"]: e for e in other["evidence"]})
            signatures[other["id"]] = identity_signature(db, other["id"])
        review = {"document": payload.model_dump(exclude={"expected_revision"}), "comparison_signatures": signatures}
        related = related_records(db, record)
        blockers = identity_blockers(db, record, review, related)
        contacts = {c["id"]: c for c in record["contacts"]}
        for decision in payload.contact_reviews:
            contact = contacts.get(decision.contact_id)
            if contact is None:
                raise ResearchError("A reviewed contact belongs to another record or does not exist.")
            refs |= require_evidence(decision.evidence_ids, evidence)
            if decision.decision != "attributed":
                continue
            if contact["suppressed"] or blockers:
                raise ResearchError("Resolve identity/contact disputes and comparisons before attributing this contact.", status=409)
            supporting = set(decision.evidence_ids) & set(contact["evidence_ids"])
            if not supporting:
                raise ResearchError("Contact attribution must cite that contact's own source excerpt.")
            if payload.branch and not any(contains_quote(evidence[eid]["excerpt"], payload.branch.value) for eid in supporting):
                raise ResearchError("Contact evidence does not explicitly identify this branch. Keep its attribution unreviewed.")
        return review, refs

    def _analysis(self, db, record: dict, state: dict, payload: NeedAnalysis) -> tuple[dict, set[str]]:
        evidence = {e["id"]: e for e in record["evidence"]}
        refs = require_evidence(payload.checked_evidence_ids, evidence)
        for quote in [*payload.observations, *payload.existing_solutions]:
            refs |= validate_quote(quote, evidence)
        disputed = {eid for c in record["contacts"] if c["suppressed"] for eid in c["evidence_ids"]}
        if refs & disputed:
            raise ResearchError("Disputed-contact evidence cannot support this analysis. Select uncontested source excerpts.", status=409)
        identity = state.get("identity")
        related = related_records(db, record)
        blockers = identity_blockers(db, record, identity, related)
        if payload.fit == "possible_fit":
            if blockers or identity["document"]["geography"] != "matches" or identity["document"]["exclusions"] != "clear":
                raise ResearchError("Possible fit requires reviewed identity/comparisons, cited matching geography and checked exclusions.", status=409)
        document = payload.model_dump(exclude={"expected_revision"}) | {
            "intent_state": "unknown", "budget": None, "budget_reason": "No documented prospect interaction establishes a budget.",
            "interpretation": "Need, offer relevance, fit and alternative explanations are reviewer inferences, not observed business facts.",
            "source_scope": "Selected excerpts from saved research; absence of a solution here is not proof that no solution exists.",
        }
        return {"document": document, "dependency_hash": dependency_hash(db, record, identity, related),
                "evidence_ids": sorted(refs)}, refs

    def save(self, research_id: str, kind: str, payload: IdentityReview | NeedAnalysis, key: str) -> dict:
        digest = request_hash({"research_id": research_id, "kind": kind, "input": payload.model_dump()})
        with self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cached = db.execute("SELECT * FROM assessment_request WHERE idempotency_key=?", (key,)).fetchone()
            if cached:
                if cached["request_hash"] != digest:
                    raise ResearchError("This review key was already used with different inputs.", status=409)
            else:
                record = self.repository.get(research_id)
                row = db.execute("SELECT assessment_json FROM campaign WHERE id=?", (research_id,)).fetchone()
                state = state_of(row[0])
                revision = state.get(kind, {}).get("revision", 0)
                if revision != payload.expected_revision:
                    raise ResearchError("This assessment changed. Reload the saved record before submitting a new review.", status=409)
                review, refs = self._identity(db, record, payload) if kind == "identity" else self._analysis(db, record, state, payload)
                review = review | {"revision": revision + 1, "updated_at": now(), "method": "manual_review"}
                revision_id = uid()
                db.execute("INSERT INTO assessment_revision VALUES(?,?,?,?,?,?)",
                           (revision_id, research_id, kind, revision + 1, json.dumps(review), review["updated_at"]))
                db.executemany("INSERT INTO assessment_evidence VALUES(?,?)", [(revision_id, eid) for eid in refs])
                state[kind] = review
                db.execute("UPDATE campaign SET assessment_json=? WHERE id=?", (json.dumps(state), research_id))
                if kind == "identity":
                    db.execute("UPDATE business SET identity_status=? WHERE campaign_id=?", (payload.decision, research_id))
                db.execute("INSERT INTO assessment_request VALUES(?,?,?)", (key, digest, research_id))
        return self.repository.get(research_id)
