CREATE TABLE pc_worker (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    last_seen_at REAL,
    revoked_at REAL
);
CREATE TABLE pc_task (
    id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL REFERENCES pc_worker(id),
    rounds INTEGER NOT NULL CHECK(rounds BETWEEN 2 AND 20),
    executor_hash TEXT NOT NULL,
    fixture_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed','cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    lease_until REAL,
    lease_started_at REAL,
    lease_hash TEXT,
    claim_key TEXT,
    result_json TEXT,
    result_hash TEXT,
    error_code TEXT
);
CREATE INDEX pc_task_queue ON pc_task(worker_id,status,created_at);
CREATE TABLE pc_request (
    operation TEXT NOT NULL,
    request_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    object_id TEXT NOT NULL,
    PRIMARY KEY(operation,request_key)
);
CREATE TABLE pc_claim (
    worker_id TEXT NOT NULL REFERENCES pc_worker(id),
    request_key TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES pc_task(id),
    attempt INTEGER NOT NULL,
    PRIMARY KEY(worker_id,request_key)
);
CREATE TRIGGER pc_task_scope_immutable BEFORE UPDATE OF worker_id,rounds,executor_hash,fixture_hash ON pc_task
BEGIN SELECT RAISE(ABORT,'PC task scope is immutable'); END;
