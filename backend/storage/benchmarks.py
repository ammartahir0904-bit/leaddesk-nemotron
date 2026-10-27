"""Storage boundary for benchmark artefacts, independent of research records."""
import json

from backend.domain.errors import ResearchError
from backend.storage.repository import Repository, now, uid


class BenchmarkRepository:
    def __init__(self, repository: Repository):
        self.repository = repository

    def cached(self, key: str, request_hash: str) -> dict | None:
        with self.repository.connect() as db:
            row = db.execute("SELECT * FROM benchmark_run WHERE idempotency_key=?", (key,)).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise ResearchError("This benchmark request key was already used with different inputs.", status=409)
        return json.loads(row["report_json"])

    def save(self, report: dict, *, key: str | None = None, request_hash: str = "") -> dict:
        record = report | {"id": uid()}
        with self.repository.connect() as db:
            db.execute("INSERT INTO benchmark_run VALUES(?,?,?,?,?,?)",
                       (record["id"], record["kind"], now(), key, request_hash, json.dumps(record)))
        return record

    def recent(self) -> list[dict]:
        with self.repository.connect() as db:
            rows = db.execute("SELECT id,kind,created_at,report_json FROM benchmark_run ORDER BY created_at DESC LIMIT 20").fetchall()
        history = []
        for row in rows:
            report = json.loads(row["report_json"])
            history.append({"id": row["id"], "kind": row["kind"], "created_at": row["created_at"],
                            **{key: report[key] for key in ("status", "sample_count", "passed_count")}})
        return history

    def get(self, run_id: str) -> dict:
        with self.repository.connect() as db:
            row = db.execute("SELECT report_json FROM benchmark_run WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ResearchError("Benchmark report not found.", status=404)
        return json.loads(row["report_json"])
