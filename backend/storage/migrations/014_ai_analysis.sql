CREATE TABLE ai_setting (
 key TEXT PRIMARY KEY,
 value_json TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
-- AI answers are proposals; the user's verdict is the reviewed label for later learning.
CREATE TABLE prospect_ai (
 search_id TEXT NOT NULL REFERENCES prospect_search(id) ON DELETE CASCADE,
 candidate_id TEXT NOT NULL,
 result_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 verdict TEXT CHECK(verdict IN ('agree','disagree')),
 verdict_note TEXT,
 verdict_at TEXT,
 PRIMARY KEY(search_id,candidate_id)
);
