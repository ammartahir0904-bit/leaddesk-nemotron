CREATE TABLE correspondence_draft (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('email','calendar')),
    synthetic INTEGER NOT NULL CHECK(synthetic IN (0,1)),
    document_json TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision>=1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reviewed_revision INTEGER,
    reviewed_context_hash TEXT,
    reviewer TEXT,
    review_note TEXT,
    reviewed_at TEXT
);
CREATE INDEX correspondence_by_mode ON correspondence_draft(synthetic,updated_at DESC,id);
CREATE TABLE correspondence_request (
    operation TEXT NOT NULL,
    request_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    draft_id TEXT NOT NULL,
    PRIMARY KEY(operation,request_key)
);
CREATE TRIGGER correspondence_kind_immutable BEFORE UPDATE OF kind ON correspondence_draft
BEGIN SELECT RAISE(ABORT,'Draft kind is immutable'); END;
