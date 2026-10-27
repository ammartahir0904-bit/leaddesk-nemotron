CREATE TABLE prospect_search (
 id TEXT PRIMARY KEY,
 idempotency_key TEXT NOT NULL UNIQUE,
 request_hash TEXT NOT NULL,
 created_at TEXT NOT NULL,
 input_json TEXT NOT NULL,
 result_json TEXT NOT NULL
);
CREATE INDEX prospect_search_date ON prospect_search(created_at DESC,id);
-- Nominatim's policy asks clients to cache geocoding results.
CREATE TABLE geocode_cache (
 query TEXT PRIMARY KEY,
 result_json TEXT NOT NULL,
 fetched_at TEXT NOT NULL
);
CREATE TABLE prospect_check (
 search_id TEXT NOT NULL REFERENCES prospect_search(id) ON DELETE CASCADE,
 candidate_id TEXT NOT NULL,
 research_id TEXT NOT NULL,
 result_json TEXT NOT NULL,
 checked_at TEXT NOT NULL,
 PRIMARY KEY(search_id,candidate_id)
);
