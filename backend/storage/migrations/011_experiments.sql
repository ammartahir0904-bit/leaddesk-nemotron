CREATE TABLE evaluation_experiment (
 id TEXT PRIMARY KEY,
 dataset_id TEXT NOT NULL REFERENCES learning_version(id) ON DELETE CASCADE,
 dataset_sha256 TEXT NOT NULL,
 candidate_name TEXT NOT NULL,
 artifact_sha256 TEXT NOT NULL,
 predictions_sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('ready','invalidated')),
 report_json TEXT
);
CREATE TABLE evaluation_request (
 idempotency_key TEXT PRIMARY KEY,
 request_hash TEXT NOT NULL,
 experiment_id TEXT REFERENCES evaluation_experiment(id) ON DELETE SET NULL
);
CREATE INDEX evaluation_experiment_date ON evaluation_experiment(created_at DESC,id);
-- Clear derived reports immediately when a review invalidates its dataset.
CREATE TRIGGER evaluation_invalidation AFTER UPDATE OF status ON learning_version
WHEN NEW.status='invalidated'
BEGIN
 UPDATE evaluation_experiment SET status='invalidated',report_json=NULL WHERE dataset_id=NEW.id;
END;
