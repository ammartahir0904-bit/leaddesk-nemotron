CREATE TABLE learning_example (
 id TEXT PRIMARY KEY,
 source_key TEXT NOT NULL UNIQUE,
 source_ref_json TEXT NOT NULL,
 source_hash TEXT NOT NULL,
 revision INTEGER NOT NULL CHECK(revision>=1),
 decision TEXT NOT NULL CHECK(decision IN ('include','exclude')),
 mode TEXT NOT NULL CHECK(mode IN ('live','synthetic')),
 payload_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE learning_version (
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 purpose TEXT NOT NULL CHECK(purpose IN ('evaluation','training')),
 split TEXT NOT NULL CHECK(split IN ('development','holdout')),
 mode TEXT NOT NULL CHECK(mode IN ('live','synthetic')),
 created_at TEXT NOT NULL,
 dataset_sha256 TEXT NOT NULL,
 sample_count INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('ready','invalidated'))
);
CREATE TABLE learning_member (
 version_id TEXT NOT NULL REFERENCES learning_version(id) ON DELETE CASCADE,
 example_id TEXT NOT NULL REFERENCES learning_example(id) ON DELETE CASCADE,
 revision INTEGER NOT NULL,
 example_sha256 TEXT NOT NULL,
 payload_json TEXT,
 PRIMARY KEY(version_id,example_id)
);
CREATE TABLE learning_request (
 idempotency_key TEXT PRIMARY KEY,
 request_hash TEXT NOT NULL,
 example_id TEXT REFERENCES learning_example(id) ON DELETE SET NULL,
 version_id TEXT REFERENCES learning_version(id) ON DELETE SET NULL
);
-- Exposure reservations contain hashes only and survive dataset deletion.
CREATE TABLE learning_split (
 token TEXT PRIMARY KEY,
 split TEXT NOT NULL CHECK(split IN ('development','holdout'))
);
CREATE INDEX learning_example_date ON learning_example(updated_at DESC,id);
CREATE INDEX learning_version_date ON learning_version(created_at DESC,id);
