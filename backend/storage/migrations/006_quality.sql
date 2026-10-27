CREATE TABLE quality_baseline (
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 mode TEXT NOT NULL CHECK(mode IN ('live','synthetic')),
 split TEXT NOT NULL CHECK(split IN ('development','holdout')),
 created_at TEXT NOT NULL,
 dataset_sha256 TEXT NOT NULL,
 metadata_json TEXT NOT NULL
);
CREATE TABLE quality_case (
 baseline_id TEXT NOT NULL REFERENCES quality_baseline(id),
 research_id TEXT NOT NULL REFERENCES campaign(id),
 ordinal INTEGER NOT NULL,
 snapshot_sha256 TEXT NOT NULL,
 snapshot_json TEXT NOT NULL,
 PRIMARY KEY(baseline_id,research_id),
 UNIQUE(baseline_id,ordinal)
);
CREATE TABLE quality_audit (
 baseline_id TEXT NOT NULL,
 research_id TEXT NOT NULL,
 revision INTEGER NOT NULL CHECK(revision>=1),
 created_at TEXT NOT NULL,
 document_json TEXT NOT NULL,
 PRIMARY KEY(baseline_id,research_id,revision),
 FOREIGN KEY(baseline_id,research_id) REFERENCES quality_case(baseline_id,research_id)
);
CREATE TABLE quality_request (
 idempotency_key TEXT PRIMARY KEY,
 request_hash TEXT NOT NULL,
 baseline_id TEXT NOT NULL REFERENCES quality_baseline(id)
);
CREATE INDEX quality_by_date ON quality_baseline(created_at DESC,id DESC);
CREATE TRIGGER quality_baseline_immutable BEFORE UPDATE ON quality_baseline BEGIN SELECT RAISE(ABORT,'Baseline metadata is immutable'); END;
CREATE TRIGGER quality_baseline_no_delete BEFORE DELETE ON quality_baseline BEGIN SELECT RAISE(ABORT,'Baseline metadata is immutable'); END;
CREATE TRIGGER quality_case_immutable BEFORE UPDATE ON quality_case BEGIN SELECT RAISE(ABORT,'Quality snapshots are immutable'); END;
CREATE TRIGGER quality_case_no_delete BEFORE DELETE ON quality_case BEGIN SELECT RAISE(ABORT,'Quality snapshots are immutable'); END;
CREATE TRIGGER quality_audit_immutable BEFORE UPDATE ON quality_audit BEGIN SELECT RAISE(ABORT,'Quality audit revisions are immutable'); END;
CREATE TRIGGER quality_audit_no_delete BEFORE DELETE ON quality_audit BEGIN SELECT RAISE(ABORT,'Quality audit revisions are immutable'); END;
