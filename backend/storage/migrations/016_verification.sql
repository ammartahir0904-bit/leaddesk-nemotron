-- Contact verification per prospect: numbering-plan checks, source corroboration and optional mailbox checks.
CREATE TABLE prospect_verification (
 search_id TEXT NOT NULL REFERENCES prospect_search(id) ON DELETE CASCADE,
 candidate_id TEXT NOT NULL,
 result_json TEXT NOT NULL,
 verified_at TEXT NOT NULL,
 PRIMARY KEY (search_id, candidate_id)
);
