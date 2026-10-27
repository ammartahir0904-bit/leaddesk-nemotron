-- Sprint 24: corrections that change results, rules learned from them (owner-approved), and message reviews.
-- business_key identifies a business across searches: its map id (node/…, way/…, overture/…), else folded name + city.
CREATE TABLE contact_correction (
 id TEXT PRIMARY KEY,
 business_key TEXT NOT NULL,
 business_name TEXT NOT NULL,
 type TEXT NOT NULL CHECK (type IN ('phone', 'email')),
 value TEXT NOT NULL,
 value_key TEXT NOT NULL,
 verdict TEXT NOT NULL CHECK (verdict IN ('wrong', 'correct', 'added')),
 reason TEXT NOT NULL CHECK (reason IN ('not_theirs', 'disconnected', 'fake', 'temporary', 'confirmed', 'added')),
 source_hosts TEXT NOT NULL DEFAULT '[]',
 search_id TEXT,
 created_at TEXT NOT NULL,
 UNIQUE (business_key, type, value_key)
);
CREATE INDEX contact_correction_value ON contact_correction(type, value_key);
CREATE TABLE blocked_value (
 kind TEXT NOT NULL CHECK (kind IN ('phone', 'email', 'email_domain')),
 value_key TEXT NOT NULL,
 reason TEXT NOT NULL,
 correction_id TEXT,
 created_at TEXT NOT NULL,
 PRIMARY KEY (kind, value_key)
);
CREATE TABLE page_feedback (
 business_key TEXT NOT NULL,
 url TEXT NOT NULL,
 verdict TEXT NOT NULL CHECK (verdict IN ('yes', 'no')),
 created_at TEXT NOT NULL,
 PRIMARY KEY (business_key, url)
);
CREATE TABLE feature_override (
 business_key TEXT NOT NULL,
 feature TEXT NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('has', 'missing')),
 note TEXT NOT NULL DEFAULT '',
 trade TEXT,
 detected_state TEXT,
 created_at TEXT NOT NULL,
 PRIMARY KEY (business_key, feature)
);
CREATE TABLE message_review (
 search_id TEXT NOT NULL,
 candidate_id TEXT NOT NULL,
 action TEXT NOT NULL CHECK (action IN ('approved', 'edited', 'rejected')),
 problem TEXT CHECK (problem IN ('wrong_fact', 'wrong_business', 'too_generic', 'tone') OR problem IS NULL),
 text TEXT,
 template_message TEXT NOT NULL,
 ai_used INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL,
 PRIMARY KEY (search_id, candidate_id)
);
CREATE TABLE learned_rule (
 id TEXT PRIMARY KEY,
 kind TEXT NOT NULL CHECK (kind IN ('block_email_domain', 'distrust_source_host', 'detector_off', 'block_phone')),
 value TEXT NOT NULL,
 description TEXT NOT NULL,
 status TEXT NOT NULL CHECK (status IN ('active', 'off')),
 evidence_json TEXT NOT NULL,
 preview_json TEXT NOT NULL,
 approved_at TEXT NOT NULL,
 changed_at TEXT NOT NULL,
 UNIQUE (kind, value)
);
