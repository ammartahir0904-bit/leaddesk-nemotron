CREATE TABLE workflow_job (
 id TEXT PRIMARY KEY,
 idempotency_key TEXT NOT NULL UNIQUE,
 request_hash TEXT NOT NULL,
 input_json TEXT NOT NULL,
 brief_json TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('queued','running','paused','retry_wait','completed','partial','failed','cancelled')),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 pause_requested INTEGER NOT NULL DEFAULT 0 CHECK(pause_requested IN (0,1)),
 cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
 page_attempts INTEGER NOT NULL DEFAULT 0,
 active_seconds REAL NOT NULL DEFAULT 0,
 lease_owner TEXT,
 lease_until REAL,
 heartbeat_at REAL,
 step_started_at REAL,
 next_attempt_at REAL NOT NULL DEFAULT 0,
 stop_reason TEXT,
 discovery_json TEXT
);
CREATE TABLE workflow_step (
 job_id TEXT NOT NULL REFERENCES workflow_job(id),
 ordinal INTEGER NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('source','candidate')),
 url TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','running','completed','failed')),
 attempts INTEGER NOT NULL DEFAULT 0,
 research_id TEXT REFERENCES campaign(id),
 error TEXT,
 candidate_json TEXT,
 PRIMARY KEY(job_id,ordinal)
);
CREATE TABLE workflow_control (
 idempotency_key TEXT PRIMARY KEY,
 request_hash TEXT NOT NULL,
 job_id TEXT NOT NULL REFERENCES workflow_job(id)
);
CREATE TABLE workflow_event (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 job_id TEXT NOT NULL REFERENCES workflow_job(id),
 created_at TEXT NOT NULL,
 kind TEXT NOT NULL,
 message TEXT NOT NULL
);
CREATE INDEX workflow_by_status ON workflow_job(status,next_attempt_at,created_at);
CREATE INDEX workflow_events_by_job ON workflow_event(job_id,id);
CREATE TRIGGER workflow_scope_immutable BEFORE UPDATE OF input_json,brief_json ON workflow_job
BEGIN SELECT RAISE(ABORT,'Queued scopes and brief snapshots are immutable'); END;
CREATE TRIGGER workflow_source_immutable BEFORE UPDATE OF discovery_json ON workflow_job
WHEN OLD.discovery_json IS NOT NULL
BEGIN SELECT RAISE(ABORT,'Discovery source evidence is immutable'); END;
CREATE TRIGGER workflow_link_immutable BEFORE UPDATE OF candidate_json ON workflow_step
WHEN OLD.candidate_json IS NOT NULL
BEGIN SELECT RAISE(ABORT,'Discovery link evidence is immutable'); END;
CREATE TRIGGER workflow_page_scope_immutable BEFORE UPDATE OF job_id,ordinal,kind,url ON workflow_step
BEGIN SELECT RAISE(ABORT,'Queued page scopes are immutable'); END;
