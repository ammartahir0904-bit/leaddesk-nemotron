-- AI market-problem summaries per search. Proposals over deterministic counts; replaced on each run.
CREATE TABLE prospect_market (
 search_id TEXT PRIMARY KEY REFERENCES prospect_search(id) ON DELETE CASCADE,
 result_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
