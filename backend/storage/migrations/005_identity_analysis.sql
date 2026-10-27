ALTER TABLE campaign ADD COLUMN assessment_json TEXT;
CREATE TABLE assessment_revision (
 id TEXT PRIMARY KEY,
 campaign_id TEXT NOT NULL REFERENCES campaign(id),
 kind TEXT NOT NULL CHECK(kind IN ('identity','analysis')),
 revision INTEGER NOT NULL CHECK(revision>=1),
 document_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(campaign_id,kind,revision)
);
CREATE TRIGGER assessment_revision_immutable BEFORE UPDATE ON assessment_revision
BEGIN SELECT RAISE(ABORT,'Assessment revisions are immutable'); END;
CREATE TRIGGER assessment_revision_no_delete BEFORE DELETE ON assessment_revision
BEGIN SELECT RAISE(ABORT,'Assessment revisions are immutable'); END;
CREATE TABLE assessment_evidence (
 revision_id TEXT NOT NULL REFERENCES assessment_revision(id),
 evidence_id TEXT NOT NULL REFERENCES evidence(id),
 PRIMARY KEY(revision_id,evidence_id)
);
CREATE TRIGGER assessment_evidence_immutable BEFORE UPDATE ON assessment_evidence
BEGIN SELECT RAISE(ABORT,'Assessment evidence links are immutable'); END;
CREATE TRIGGER assessment_evidence_no_delete BEFORE DELETE ON assessment_evidence
BEGIN SELECT RAISE(ABORT,'Assessment evidence links are immutable'); END;
CREATE TABLE assessment_request (
 idempotency_key TEXT PRIMARY KEY,
 request_hash TEXT NOT NULL,
 campaign_id TEXT NOT NULL REFERENCES campaign(id)
);
CREATE INDEX assessment_history ON assessment_revision(campaign_id,kind,revision DESC);
