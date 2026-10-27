"""Immutable brief revisions with atomic edits and exact request replay."""
import json

from backend.domain.briefs import invalidate_reviews_after_input_change
from backend.domain.errors import ResearchError
from backend.storage.repository import Repository, now, uid


class BriefRepository:
    def __init__(self, repository: Repository):
        self.repository = repository

    @staticmethod
    def _get(db, brief_id: str, revision: int | None = None) -> dict:
        brief = db.execute("SELECT * FROM product_brief WHERE id=?", (brief_id,)).fetchone()
        if brief is None:
            raise ResearchError("Product brief not found.", status=404)
        version = revision if revision is not None else brief["current_revision"]
        row = db.execute("SELECT * FROM brief_revision WHERE brief_id=? AND revision=?", (brief_id, version)).fetchone()
        if row is None:
            raise ResearchError("Product brief revision not found.", status=404)
        return {"id": brief_id, "revision": version, "created_at": brief["created_at"],
                "updated_at": row["created_at"], "document": json.loads(row["document_json"])}

    def get(self, brief_id: str, revision: int | None = None) -> dict:
        with self.repository.connect() as db:
            return self._get(db, brief_id, revision)

    def recent(self) -> list[dict]:
        with self.repository.connect() as db:
            rows = db.execute("SELECT id FROM product_brief ORDER BY updated_at DESC LIMIT 50").fetchall()
            return [self._get(db, row["id"]) for row in rows]

    def history(self, brief_id: str) -> list[dict]:
        with self.repository.connect() as db:
            self._get(db, brief_id)
            versions = db.execute("SELECT revision FROM brief_revision WHERE brief_id=? ORDER BY revision DESC", (brief_id,)).fetchall()
            return [self._get(db, brief_id, row["revision"]) for row in versions]

    def _cached(self, db, key: str, digest: str) -> dict | None:
        row = db.execute("SELECT * FROM brief_request WHERE idempotency_key=?", (key,)).fetchone()
        if row is None:
            return None
        if row["request_hash"] != digest:
            raise ResearchError("This brief request key was already used with different inputs.", status=409)
        return self._get(db, row["brief_id"], row["revision"])

    def create(self, document: dict, key: str, digest: str) -> dict:
        with self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cached = self._cached(db, key, digest)
            if cached:
                return cached
            brief_id, timestamp = uid(), now()
            db.execute("INSERT INTO product_brief VALUES(?,1,?,?)", (brief_id, timestamp, timestamp))
            db.execute("INSERT INTO brief_revision VALUES(?,1,?,?)", (brief_id, json.dumps(document), timestamp))
            db.execute("INSERT INTO brief_request VALUES(?,?,?,1)", (key, digest, brief_id))
            return self._get(db, brief_id)

    def update(self, brief_id: str, expected_revision: int, document: dict, key: str, digest: str) -> dict:
        with self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cached = self._cached(db, key, digest)
            if cached:
                return cached
            current = self._get(db, brief_id)
            if current["revision"] != expected_revision:
                raise ResearchError("This brief changed in another tab. Reopen the latest revision before saving.", status=409)
            document = invalidate_reviews_after_input_change(document, current["document"])
            revision, timestamp = expected_revision + 1, now()
            db.execute("INSERT INTO brief_revision VALUES(?,?,?,?)", (brief_id, revision, json.dumps(document), timestamp))
            db.execute("UPDATE product_brief SET current_revision=?,updated_at=? WHERE id=?", (revision, timestamp, brief_id))
            db.execute("INSERT INTO brief_request VALUES(?,?,?,?)", (key, digest, brief_id, revision))
            return self._get(db, brief_id, revision)
