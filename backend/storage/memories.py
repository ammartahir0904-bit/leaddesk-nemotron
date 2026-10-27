"""Scoped user-authored notes. No inference or automatic training ingestion."""
from datetime import datetime, timezone
from backend.domain.errors import ResearchError
from backend.storage.repository import now, request_hash, uid


class MemoryRepository:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def public(row):
        item = dict(row)
        item["pinned"] = bool(item["pinned"])
        item["expired"] = bool(item["expires_at"] and datetime.fromisoformat(item["expires_at"]) <= datetime.now(timezone.utc))
        item["provenance"] = "user_authored"
        item["sensitivity"] = "private"
        item["training_eligible"] = False
        return item

    def list(self, scope, query="", include_expired=False, limit=100, offset=0):
        with self.repository.connect() as db:
            rows = list(db.execute("SELECT * FROM local_memory WHERE scope=? ORDER BY pinned DESC,updated_at DESC,id", (scope,)))
            items = [self.public(row) for row in rows]
            items = [item for item in items if (include_expired or not item["expired"]) and query.casefold() in item["content"].casefold()]
            total = len(items)
            return {"items": items[offset:offset + limit], "total": total, "limit": limit, "scope": scope, "offset": offset,
                    "next_offset": offset + limit if offset + limit < total else None}

    def create(self, payload, key):
        values = payload.model_dump(mode="json")
        digest = request_hash(values)
        with self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cached = db.execute("SELECT * FROM memory_request WHERE idempotency_key=?", (key,)).fetchone()
            if cached:
                if cached["request_hash"] != digest:
                    raise ResearchError("This request key was used with different memory inputs.", status=409)
                if not cached["memory_id"]:
                    raise ResearchError("That memory was deleted. Use a new request for a new note.", status=410)
                return self.public(db.execute("SELECT * FROM local_memory WHERE id=?", (cached["memory_id"],)).fetchone())
            if db.execute("SELECT COUNT(*) FROM local_memory").fetchone()[0] >= 1000:
                raise ResearchError("Memory limit reached (1000 notes). Delete unused notes first.", status=429)
            memory_id, stamp = uid(), now()
            db.execute("INSERT INTO local_memory VALUES(?,?,?,?,?,?,?,?,?,?)", (memory_id, values["scope"], values["kind"], values["content"], values["source"], values["pinned"], values["expires_at"], stamp, stamp, 1))
            db.execute("INSERT INTO memory_request VALUES(?,?,?)", (key, digest, memory_id))
            return self.public(db.execute("SELECT * FROM local_memory WHERE id=?", (memory_id,)).fetchone())

    def update(self, memory_id, payload):
        values = payload.model_dump(mode="json")
        with self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM local_memory WHERE id=?", (memory_id,)).fetchone()
            if row is None:
                raise ResearchError("Memory not found.", status=404)
            if row["revision"] != payload.expected_revision:
                raise ResearchError("This note changed in another tab. Reload before editing.", status=409)
            if row["scope"] != values["scope"]:
                raise ResearchError("A note's scope cannot change. Copy it into a new scoped note instead.", status=409)
            db.execute("""UPDATE local_memory SET kind=?,content=?,source=?,pinned=?,expires_at=?,updated_at=?,revision=revision+1 WHERE id=?""",
                       (values["kind"], values["content"], values["source"], values["pinned"], values["expires_at"], now(), memory_id))
            return self.public(db.execute("SELECT * FROM local_memory WHERE id=?", (memory_id,)).fetchone())

    def delete(self, memory_id):
        with self.repository.connect() as db:
            db.execute("DELETE FROM local_memory WHERE id=?", (memory_id,))
        return {"deleted": True}

    def forget(self, scope):
        with self.repository.connect() as db:
            count = db.execute("DELETE FROM local_memory WHERE scope=?", (scope,)).rowcount
        return {"deleted": count, "scope": scope}
