-- Sprint 23: "Is this them?" answers for web findings, the features the user delivers per search,
-- and standalone website analyses (a URL the user entered, read and compared with their offer).
CREATE TABLE web_feedback (
 search_id TEXT NOT NULL REFERENCES prospect_search(id) ON DELETE CASCADE,
 candidate_id TEXT NOT NULL,
 url TEXT NOT NULL,
 verdict TEXT NOT NULL CHECK (verdict IN ('yes', 'no')),
 created_at TEXT NOT NULL,
 PRIMARY KEY (search_id, candidate_id, url)
);
CREATE TABLE offer_pack (
 search_id TEXT PRIMARY KEY REFERENCES prospect_search(id) ON DELETE CASCADE,
 features_json TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE site_analysis (
 id TEXT PRIMARY KEY,
 idempotency_key TEXT NOT NULL UNIQUE,
 request_hash TEXT NOT NULL,
 created_at TEXT NOT NULL,
 input_json TEXT NOT NULL,
 result_json TEXT NOT NULL
);
