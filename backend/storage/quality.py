"""Frozen evaluation samples, append-only audits and reproducible source reports."""
import hashlib
import json
from urllib.parse import urlsplit

from backend.adapters.hardware import profile_hardware
from backend.domain.errors import ResearchError
from backend.domain.leads import summarize
from backend.domain.quality import AuditInput, BaselineInput, factual_units, validate_audit
from backend.evaluation.quality import quality_report
from backend.settings import ROOT
from backend.storage.assessment_views import raw_record
from backend.storage.repository import Repository, now, request_hash, uid

MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024


def capture_snapshot(repository, db, research_id):
    record = repository.get_in_transaction(db, research_id)
    identity = ((record.get("assessment") or {}).get("identity") or {}).get("document") or {}
    sources = []
    for comparison in identity.get("comparisons", []):
        other = raw_record(db, comparison["research_id"])
        sources.append({"id": other["id"], "source_url": other["source_url"],
                        "synthetic": bool(other["synthetic"]), "evidence": other["evidence"]})
    return {"research": record, "lead": summarize(record), "units": factual_units(record), "comparison_sources": sources}


def source_key(url):
    parts = urlsplit(url)
    return parts.scheme.lower(), parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), parts.path or "/", parts.query


class QualityRepository:
    def __init__(self, repository: Repository):
        self.repository = repository

    def _receipt(self, db, key, digest):
        row = db.execute("SELECT * FROM quality_request WHERE idempotency_key=?", (key,)).fetchone()
        if row and row["request_hash"] != digest:
            raise ResearchError("This quality request key was already used with different inputs.", status=409)
        return row["baseline_id"] if row else None

    def create(self, payload: BaselineInput, key: str) -> dict:
        digest = request_hash({"operation": "quality_baseline", "input": payload.model_dump()})
        with self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            baseline_id = self._receipt(db, key, digest)
            if baseline_id is None:
                snapshots, seen, byte_count = [], set(), 0
                for research_id in payload.research_ids:
                    snapshot = capture_snapshot(self.repository, db, research_id)
                    if snapshot["research"]["synthetic"] != (payload.mode == "synthetic"):
                        raise ResearchError("Real and synthetic records cannot share a quality baseline.")
                    source = source_key(snapshot["research"]["source_url"])
                    if source in seen:
                        raise ResearchError("Repeated source URLs cannot inflate a baseline. Select one saved record per source URL.")
                    seen.add(source)
                    byte_count += len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8"))
                    if byte_count > MAX_SNAPSHOT_BYTES:
                        raise ResearchError("These quality snapshots exceed 16 MiB. Select fewer records; no partial baseline was saved.", status=413)
                    snapshots.append((research_id, snapshot, request_hash(snapshot)))
                code_files = ("backend/domain/extract.py", "backend/domain/leads.py", "backend/domain/quality.py", "backend/evaluation/quality.py",
                              "backend/storage/assessment_views.py", "backend/storage/quality.py", "backend/storage/repository.py")
                metadata = {
                    "schema_version": 1, "rubric_version": 1, "hardware": profile_hardware(self.repository.path.parent),
                    "model_hash": None, "model_reason": "No model invoked by this source-audit workflow; prior record generation is not benchmarked here.",
                    "configuration": {"method": "manual_saved_source_audit", "max_cases": 100,
                                      "selection": "user_selected_distinct_source_urls", "rubric_version": 1,
                                      "capture_code_sha256": request_hash({p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in code_files})},
                }
                baseline_id = uid()
                dataset_hash = request_hash([(rid, digest) for rid, _, digest in snapshots])
                db.execute("INSERT INTO quality_baseline VALUES(?,?,?,?,?,?,?)",
                           (baseline_id, payload.name, payload.mode, payload.split, now(), dataset_hash, json.dumps(metadata)))
                db.executemany("INSERT INTO quality_case VALUES(?,?,?,?,?)", [
                    (baseline_id, rid, index, digest, json.dumps(snapshot)) for index, (rid, snapshot, digest) in enumerate(snapshots)])
                db.execute("INSERT INTO quality_request VALUES(?,?,?)", (key, digest, baseline_id))
        return self.get(baseline_id)

    def recent(self) -> dict:
        with self.repository.connect() as db:
            db.execute("BEGIN")
            count = db.execute("SELECT COUNT(*) FROM quality_baseline").fetchone()[0]
            rows = db.execute("SELECT b.id,b.name,b.mode,b.split,b.created_at,b.dataset_sha256,COUNT(c.research_id) AS sample_count FROM quality_baseline b JOIN quality_case c ON c.baseline_id=b.id GROUP BY b.id ORDER BY b.created_at DESC,b.id DESC LIMIT 20").fetchall()
        return {"items": [dict(row) for row in rows], "total": count, "limit": 20}

    def get(self, baseline_id: str) -> dict:
        with self.repository.connect() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM quality_baseline WHERE id=?", (baseline_id,)).fetchone()
            if row is None:
                raise ResearchError("Quality baseline not found.", status=404)
            result = dict(row)
            result.update(json.loads(result.pop("metadata_json")))
            rows = db.execute("SELECT * FROM quality_case WHERE baseline_id=? ORDER BY ordinal", (baseline_id,)).fetchall()
            audits = {row["research_id"]: {"revision": row["revision"], "updated_at": row["created_at"],
                      "document": json.loads(row["document_json"])} for row in db.execute(
                "SELECT a.* FROM quality_audit a JOIN (SELECT research_id,MAX(revision) AS revision FROM quality_audit WHERE baseline_id=? GROUP BY research_id) latest ON latest.research_id=a.research_id AND latest.revision=a.revision WHERE a.baseline_id=?", (baseline_id, baseline_id))}
            cases = []
            for row in rows:
                snapshot = json.loads(row["snapshot_json"])
                current = capture_snapshot(self.repository, db, row["research_id"])
                cases.append({"research_id": row["research_id"], "ordinal": row["ordinal"], "snapshot_sha256": row["snapshot_sha256"],
                              "snapshot": snapshot, "source_changed_since_snapshot": request_hash(current) != row["snapshot_sha256"],
                              "audit": audits.get(row["research_id"])})
            result["cases"] = cases
            result["report"] = quality_report(cases, result["mode"])
            result["report"]["generated_at"] = now()
            result["report"]["review_set_sha256"] = request_hash([(c["research_id"], c["audit"]) for c in cases])
            return result

    def save_audit(self, baseline_id: str, research_id: str, payload: AuditInput, key: str) -> dict:
        digest = request_hash({"operation": "quality_audit", "baseline": baseline_id, "research": research_id, "input": payload.model_dump()})
        with self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cached = self._receipt(db, key, digest)
            if cached is None:
                row = db.execute("SELECT snapshot_json FROM quality_case WHERE baseline_id=? AND research_id=?", (baseline_id, research_id)).fetchone()
                if row is None:
                    raise ResearchError("Quality case not found in this baseline.", status=404)
                revision = db.execute("SELECT COALESCE(MAX(revision),0) FROM quality_audit WHERE baseline_id=? AND research_id=?", (baseline_id, research_id)).fetchone()[0]
                if payload.expected_revision != revision:
                    raise ResearchError("This audit changed. Reload the baseline before saving a new revision.", status=409)
                validate_audit(json.loads(row["snapshot_json"]), payload)
                db.execute("INSERT INTO quality_audit VALUES(?,?,?,?,?)", (baseline_id, research_id, revision + 1, now(),
                           json.dumps(payload.model_dump(exclude={"expected_revision"}))))
                db.execute("INSERT INTO quality_request VALUES(?,?,?)", (key, digest, baseline_id))
        return self.get(baseline_id)

    def history(self, baseline_id: str, research_id: str) -> dict:
        with self.repository.connect() as db:
            db.execute("BEGIN")
            if not db.execute("SELECT 1 FROM quality_case WHERE baseline_id=? AND research_id=?", (baseline_id, research_id)).fetchone():
                raise ResearchError("Quality case not found in this baseline.", status=404)
            rows = db.execute("SELECT * FROM quality_audit WHERE baseline_id=? AND research_id=? ORDER BY revision DESC LIMIT 101", (baseline_id, research_id)).fetchall()
            return {"items": [{"revision": r["revision"], "updated_at": r["created_at"], "document": json.loads(r["document_json"])} for r in rows[:100]],
                    "limited": len(rows) > 100, "limit": 100}
