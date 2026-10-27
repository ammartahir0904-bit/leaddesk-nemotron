CREATE TABLE prospect_enrichment (
 search_id TEXT NOT NULL REFERENCES prospect_search(id) ON DELETE CASCADE,
 candidate_id TEXT NOT NULL,
 result_json TEXT NOT NULL,
 enriched_at TEXT NOT NULL,
 PRIMARY KEY(search_id,candidate_id)
);
