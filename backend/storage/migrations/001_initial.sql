CREATE TABLE IF NOT EXISTS schema_migration(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE campaign(
 id TEXT PRIMARY KEY, product TEXT NOT NULL, geography TEXT NOT NULL,
 created_at TEXT NOT NULL, synthetic INTEGER NOT NULL CHECK(synthetic IN (0,1))
);
CREATE TABLE business(
 id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaign(id),
 canonical_name TEXT, source_url TEXT NOT NULL, identity_status TEXT NOT NULL DEFAULT 'unresolved'
);
CREATE TABLE evidence(
 id TEXT PRIMARY KEY, business_id TEXT NOT NULL REFERENCES business(id), source_url TEXT NOT NULL,
 retrieved_at TEXT NOT NULL, content_hash TEXT NOT NULL, excerpt TEXT NOT NULL,
 extraction_method TEXT NOT NULL DEFAULT 'visible_html_v1'
);
CREATE TABLE claim(
 id TEXT PRIMARY KEY, business_id TEXT NOT NULL REFERENCES business(id), predicate TEXT NOT NULL,
 value TEXT NOT NULL, evidence_id TEXT NOT NULL REFERENCES evidence(id), inference_flag INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE contact(
 id TEXT PRIMARY KEY, business_id TEXT NOT NULL REFERENCES business(id), type TEXT NOT NULL,
 raw_value TEXT NOT NULL, normalised_value TEXT NOT NULL,
 attribution_state TEXT NOT NULL DEFAULT 'extracted', suppressed INTEGER NOT NULL DEFAULT 0,
 last_checked_at TEXT NOT NULL,
 UNIQUE(business_id, type, normalised_value)
);
CREATE TABLE contact_evidence(
 contact_id TEXT NOT NULL REFERENCES contact(id), evidence_id TEXT NOT NULL REFERENCES evidence(id),
 PRIMARY KEY(contact_id,evidence_id)
);
CREATE TABLE feedback(
 id TEXT PRIMARY KEY, contact_id TEXT NOT NULL REFERENCES contact(id), category TEXT NOT NULL,
 comment TEXT NOT NULL, expected_value TEXT, created_at TEXT NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE suppression(
 id TEXT PRIMARY KEY, source_host TEXT NOT NULL, type TEXT NOT NULL, normalised_value TEXT NOT NULL,
 reason TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(source_host,type,normalised_value)
);
CREATE TABLE research_request(
 idempotency_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL, campaign_id TEXT NOT NULL REFERENCES campaign(id)
);
CREATE INDEX contacts_by_business ON contact(business_id);
CREATE INDEX evidence_by_business ON evidence(business_id);
CREATE TRIGGER evidence_immutable BEFORE UPDATE ON evidence
BEGIN SELECT RAISE(ABORT,'Evidence is immutable'); END;
