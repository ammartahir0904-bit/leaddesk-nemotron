CREATE TABLE product_brief (
 id TEXT PRIMARY KEY,
 current_revision INTEGER NOT NULL CHECK(current_revision >= 1),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE brief_revision (
 brief_id TEXT NOT NULL REFERENCES product_brief(id),
 revision INTEGER NOT NULL CHECK(revision >= 1),
 document_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 PRIMARY KEY(brief_id, revision)
);
CREATE TRIGGER brief_revision_immutable BEFORE UPDATE ON brief_revision
BEGIN SELECT RAISE(ABORT,'Brief revisions are immutable'); END;
CREATE TABLE brief_request (
 idempotency_key TEXT PRIMARY KEY,
 request_hash TEXT NOT NULL,
 brief_id TEXT NOT NULL,
 revision INTEGER NOT NULL,
 FOREIGN KEY(brief_id, revision) REFERENCES brief_revision(brief_id, revision)
);
CREATE INDEX briefs_by_date ON product_brief(updated_at DESC);
ALTER TABLE campaign ADD COLUMN brief_snapshot_json TEXT;
CREATE TRIGGER research_brief_snapshot_immutable BEFORE UPDATE OF brief_snapshot_json ON campaign
WHEN OLD.brief_snapshot_json IS NOT NULL
BEGIN SELECT RAISE(ABORT,'Research brief snapshots are immutable'); END;
