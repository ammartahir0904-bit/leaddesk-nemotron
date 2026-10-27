# Operations, privacy and reliability

## Default deployment
Single-user local installation, loopback-bound authenticated backend, selected folders, on-demand microphone/screen, cloud spend zero. Keep model downloads separate from application updates. Optional workers are explicitly paired and revocable.

## Resource controls
Per-job page, byte, time and inference budgets; per-source rate limits; global concurrency limits; cancellation checks between steps. Pause noninteractive work under memory pressure. Backpressure limits queue growth and disk cache usage. User sees partial completion and why work stopped.

## Audit and observability
Record task ID, tool, timestamps, outcome, model/config versions, evidence IDs and policy decision. Redact credentials, raw voice and sensitive screen text from logs. Store error classes rather than dumping entire pages or emails. Metrics should answer: Where did a wrong number enter? Which claim lacked support? Why was the job slow?

## Retention and deletion
Configurable retention for public evidence excerpts, logs, feedback and caches. Default screenshot/audio persistence is off. Keep the minimum excerpts needed for review and respect source restrictions. User can clear a campaign, project memory or file index. Deletion propagates to derived indexes and future training datasets; backup expiry is documented. Export sensitive records only on request.

## Secrets and boundaries
Use OS keyring or a suitable secret store. Never put credentials in Git, model prompts, datasets or exports. Treat documents and pages as untrusted. Parser timeouts, file size limits and isolated execution protect local workflows. Model tools have explicit allowlists and path/domain restrictions.

## Backups and updates
Use SQLite's supported backup mechanism rather than copying an actively changing database carelessly. Back up database, user settings and model registry metadata; model weights can usually be re-downloaded if version/licence allows. Test restore before claiming backup support. Run migrations with a backup and rollback/recovery plan. Signed/reviewed update packaging is a distribution milestone, not implemented in this blueprint.

## Failure policy
No source → unknown/partial result. Model unavailable → deterministic extraction still works. PC offline → queue or approved local fallback. Voice unavailable → text input. Screen denied → user-assisted context. Provider quota exhausted → pause and explain. Training regression → keep/restore baseline. Uncertain send → reconcile before retry.

## Later hosted multi-user version
Introduce user/tenant isolation, role-based access, scoped retrieval, audit separation, encryption/retention policy and jurisdiction-specific review before onboarding others. Do not simply expose the personal desktop agent publicly. This is a separate engineering gate.
