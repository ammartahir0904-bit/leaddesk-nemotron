CREATE TABLE benchmark_run (
 id TEXT PRIMARY KEY,
 kind TEXT NOT NULL CHECK(kind IN ('parser','local_model')),
 created_at TEXT NOT NULL,
 idempotency_key TEXT UNIQUE,
 request_hash TEXT NOT NULL,
 report_json TEXT NOT NULL
);
CREATE INDEX benchmark_by_date ON benchmark_run(created_at DESC);
