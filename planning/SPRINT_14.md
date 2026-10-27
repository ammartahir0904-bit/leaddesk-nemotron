# Sprint 14 — local candidate evaluation

Date: 20 October 2026, Asia/Karachi. First B17 slice after Sprint 13. User selected **Local evaluation first**.

## Outcome and acceptance plan

Choose one current evaluation-purpose dataset, identify an externally prepared candidate by name and artifact SHA-256, and supply one output (or explicit null abstention) for each frozen example. Compare supplied outputs and the reviewed observed-output baseline against human-reviewed expected text using exact string equality. This is output evaluation, not a ranker, model execution, training, independent holdout certification or promotion.

- Bind requests to the frozen dataset hash; reject missing, duplicate and foreign predictions. Preserve whitespace in supplied outputs. Never silently normalise labels or accept partial coverage.
- Display counts, exact-match rates, abstentions, paired gains/regressions and task/domain segments. Label imported candidate provenance unverified; development results cannot claim held-out improvement. Small synthetic samples cannot establish real-source quality.
- Persist reports with dataset/artifact/input hashes, configuration, date, evaluation-host hardware and comparison timing. Candidate inference latency/memory remain unknown.
- Authenticate routes, enforce body/history limits, transactional idempotency and deletion tombstones. Do not retain copied labels, inputs or candidate output bodies in reports. Recheck current reviews/sources; clear reports invalidated by changes and cascade dataset deletion.
- Provide a usable panel, meaningful disposable-data tests, old-table migration preservation, regression checks, build and a prepared browser acceptance flow. Record actual checks and environment limits before completion.

## Delivered

- `backend/domain/experiments.py`, `backend/evaluation/experiments.py`: strict one-output-per-example inputs, explicit null abstentions and deterministic exact-text comparison. Whitespace/case/Unicode are not normalised. Counts/rates, paired gains/regressions and task/domain segments are descriptive agreement with human-reviewed text. Any paired regression is shown even when the aggregate improves. No semantic correctness, contact quality, ranking metric, significance or independent held-out improvement is inferred.
- `backend/storage/experiments.py`, migration `011_experiments.sql`: evaluation-purpose-only datasets, frozen content/hash binding, source/permission/split freshness checks, canonical-order hash-only receipts, atomic bounded report storage and replay tombstones. Reports retain metrics, domain/task segments and supplied candidate metadata/hashes rather than copied labels, inputs or candidate outputs. They record hardware/configuration/date, evaluator hash and comparison timing; candidate inference latency/memory and verified model identity remain null.
- Dataset review invalidation immediately clears dependent report metrics through a migration trigger. Source changes are checked on comparison, replay, list, inspect and export; a refused comparison still commits discovered source invalidation. Example deletion invalidates reports; dataset deletion cascades; report deletion leaves datasets, original research and suppression intact. Downloaded/in-flight files and backups require separate management. Idempotency tombstones survive deletion. Limits: 200 reports, 2,000 lifetime write receipts, 100 examples, 1,000 characters/output, existing 16,000-byte request body and 20-item independent report paging.
- `backend/api/experiments.py`: owner-authenticated list/create/get/delete/export routes under `/v1/experiments`, existing host/origin/body/no-store policies, exact dataset hashes and rejected missing/duplicate/foreign outputs. Inputs reject unpaired Unicode surrogates; scoped escaped-JSON validation responses preserve 422 errors rather than failing while encoding malformed input. Other routes retain their existing validation handler.
- `apps/web/src/EvaluationPanel.jsx`: embedded in Learning and datasets, selected evaluation dataset in the current real/synthetic mode, asserted artifact identity, editable JSON and null-only template, comparison, paginated inspect/export/delete, stale-result rejection and retryable writes. Candidate output text is temporary and cleared after successful submission. Imported candidate identity/output provenance remains explicitly unverified. The earlier-report count covers retained reports only; deletion does not establish a fresh independent holdout.
- `tests/test_experiments.py` and `scripts/evaluation-smoke.mjs`: disposable fictional fixture coverage and a prepared browser workflow. No real reviewed dataset, actual candidate artifact or worker is selected by verification. The user's actual database is not opened or migrated; migration applies at the next normal app launch.

## Verification evidence

- Final target `.venv/bin/python -m unittest discover -s tests -q`: **294 tests pass**, no skips, in **128.313 seconds** (276 prior plus 18 evaluation cases), after the final Unicode validation fix and production build. The earlier full run also passed all 294 cases.
- Final targeted `.venv/bin/python -m unittest tests.test_experiments -q`: **18 tests pass**, no skips, in **11.815 seconds**. Includes paired positive/negative changes, per-task/domain counts, Unicode/whitespace/null/literal instruction handling, missing/foreign/duplicate outputs, malformed types/hashes/surrogates, exact reordered retries and key conflicts, retained-report counts, training refusal, development/holdout labels, restart/export/no-store stability, no copied output bodies, source/review/exclusion/deletion/late-holdout invalidation, deleted-object replay, bounds, interrupted-write rollback, mode/paging, altered manifest rejection and old-table preservation.
- Migration verification applies all ten old migrations, seeds fictional research, feedback/suppression, an included review and frozen dataset, a calendar draft, local private note, paired worker and pending task through existing repositories, then compares every old table across migration 011 and checks foreign keys. Earlier preservation tests advance only their migration-count assertion to eleven. Real user storage is not used.
- Node **24.21.0**: **15 voice + 13 screen controller checks pass**, no skips. Final Vite **8.3.1** build passes: **48 modules**, JS **416.10 kB** (**115.76 kB gzip**), CSS **30.72 kB** (**6.80 kB gzip**). Compilation does not establish browser acceptance.
- Target `.venv/bin/python -m pip check`: no broken requirements. Python compilation, browser script syntax and whitespace checks pass. No dependency/lockfile changes.
- `npm run test:e2e:evaluation` attempted under Node 24: **blocked at Chrome launch**, `setsockopt: Operation not permitted`, SIGTRAP. The script stops before reading the access key, creating a source/dataset/report, opening a page, downloading a file or running UI assertions. No browser acceptance is claimed.

## Remaining desktop and candidate acceptance

Stop any regular instance on port 8765; use a new empty disposable data directory from a normal desktop terminal:

```bash
LEADDESK_DATA_DIR="$PWD/.local/browser-check" ./launch.sh
# In a second terminal:
cd apps/web
nvm use 24.21.0
LEADDESK_TEST_TOKEN_FILE=../../.local/browser-check/access-token npm run test:e2e:evaluation
```

The prepared browser flow creates a fictional source/example/dataset, opens the evaluator, checks the null-only template, malformed JSON and foreign output rejection, loses a successful create response and retries it without duplicate reports, inspects/downloads metrics, retries a failed refresh, invalidates the source example, checks blocked exports, deletes the report and verifies original suppression plus mobile overflow/page errors. Cleanup attempts to delete downloaded files, examples and versions; synthetic research/feedback and hash-only receipts remain in disposable storage. It has not run past Chrome launch here. Separately exercise keyboard navigation, multiple pages, stale tabs, mode/dataset changes and navigation during a request.

B17 remains open. Choose an actual task/ranking schema and candidate implementation, establish artifact/config provenance and representative reviewed data, isolate an independent held-out evaluation from tuning, and measure actual candidate quality, regressions and resource use before judging improvement. Human labels and text agreement alone cannot certify factual correctness. No training or promotion is authorised by this evaluation-only slice. B18 packaging is the next ordered milestone after these gates. Prior live-source quality, file search, speech/capture, reviewed-data, two-PC and email/calendar-client acceptance remain open.
