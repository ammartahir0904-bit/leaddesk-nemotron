# Sprint 12 — optional paired PC benchmark worker

Date: 20 October 2026, Asia/Karachi. Implementation scope: the first B15 vertical slice after Sprint 11. Earlier desktop/live-source acceptance gates remain open and do not establish release readiness.

## Outcome and scope

Explicitly pair a worker, download its scoped credential, queue a synthetic parser benchmark for that worker, inspect its reported measurements, cancel work and revoke pairing. The coordinator owns SQLite. A separate opt-in CLI polls through a user-established SSH loopback tunnel; the application continues to bind only to loopback. No tunnel, public listener, cloud service, model download or inference is automatically enabled.

Only the bundled synthetic parser benchmark is allowed (2–20 rounds). Job inputs contain no research records, documents, file paths, notes, screenshots or audio. Reports are worker assertions, separately stored and labelled; they do not promote models, establish real-source quality or replace local benchmark results.

## Acceptance plan

- Worker tokens cannot access owner APIs or another worker's tasks; owner keys cannot authenticate as workers. Tokens are hashed at rest and pairing secrets are returned only once.
- Explicit per-worker queueing, bounded queue/history, strict inputs/results and immutable task scope. Unknown job kinds and arbitrary commands/URLs are rejected.
- Persisted leases, heartbeats, bounded attempts, expiry recovery after disconnect/restart, stale-result rejection, replay-safe completion and cancellation/revocation that beat late results. No automatic local/cloud fallback.
- CLI uses loopback only, no redirects/proxies, private credential files, bounded responses/timeouts and a single execution slot. Exact executor/fixture hashes are checked before executing and accepting results.
- Dashboard pairing, credential download/forget, queue/status/results, cancellation/revocation, retry and small-window flow; prepare a disposable-data browser check.
- Existing data preservation through additive migration, targeted failure tests, full Python regression suite, existing JS checks and frontend build. Record actual results and desktop/two-machine limits below after validation.

## Delivered

- `backend/domain/pc_worker.py`, `backend/api/pc_worker.py`: strict synthetic-only protocol, separate owner/worker authentication, one-time scoped pairing credentials and task lease tokens. Worker credentials cannot access owner data; owner access keys cannot claim work. Inputs reject unknown kinds/commands/paths/URLs, booleans as counts, non-finite measurements and dates without a timezone.
- `backend/storage/pc_worker.py`, migration `009_pc_worker.sql`: coordinator-owned pairings, immutable assigned task scope, hash-only secrets, transactional queue/receipts/results, one active PC task, 60-second leases, heartbeats capped at 120 seconds/attempt and at most three attempts. Claim replay recovers the same valid lease; old claims never take a later task. Exact completion/failure replays are accepted, conflicts and stale/replaced/cancelled/revoked submissions are rejected. Revoking a worker cancels its pending tasks and leaves reports intact.
- Reports bind the assigned round count, fixture hash, executor-source/lockfile hash, known case IDs and check totals. Failed checks remain visible. Reports carry explicit unverified-worker provenance, fictional-fixture status and null model hash, separately from local benchmark and research storage. Hash matching establishes protocol consistency, not attestation of an honest worker or installed dependencies.
- `backend/workflows/pc_client.py`, `pc_executor.py`, `scripts/pc_worker.py`: opt-in polling CLI through manually established SSH loopback forwarding, no proxy/redirect inheritance, owned mode-600 regular credential files, bounded responses/HTTP timeouts and a fixed benchmark subprocess with a 30-second timeout. Lost claim/completion responses can retry without duplicate execution/acceptance; an in-memory result survives transient transport errors. A stopped process can recompute only after lease expiry. No public listener, networking setup, model/runtime download, arbitrary command, remote research or automatic fallback is introduced.
- `apps/web/src/WorkersPanel.jsx`/CSS: pairing/download/forget, explicit computer/round selection, offline/recently-seen/revoked states, manual refresh, queued/running/terminal tasks, cancellation, confirmed revocation, labelled measurements and request retry. Credentials are not stored in browser storage; downloaded files require separate management. Hard limits are documented: 50 lifetime pairings, 500 task records, 20 pending tasks and 12,000 bytes/report. History deletion and extended remote capabilities are future work.
- `tests/test_pc_worker.py`: disposable SQLite, in-process ASGI, injected disconnects and actual fixed executor subprocess checks. `scripts/workers-smoke.mjs` prepares a fictional browser workflow using simulated worker requests and locally measured synthetic results; it is not a remote PC test.

## Verification evidence

- Final target `.venv/bin/python -m unittest discover -s tests -q`: **252 tests pass**, no skips, in **92.669 seconds** (229 previous plus 23 PC-worker cases). The targeted 23-case suite also passes. Coverage includes owner/worker/other-worker isolation, no automatic pairing, one-time credentials/hash-only storage, task allowlisting, exact claim/completion/failure replay, lost responses without duplicate execution, offline queueing, expiry/restart/retry limits, bounded heartbeat extension, cancellation/revocation precedence, invalid/oversized/mismatched reports and atomic rollback, immutable scope, queue limits, credential permissions/symlinks, redirects/oversized responses, executor mismatch, actual fixed benchmark subprocess and old-table preservation.
- Migration verification creates an eight-migration fixture, seeds research/feedback/suppression, applies migration 009, compares **every** old table before/after and checks foreign keys. Existing earlier migration-preservation tests also pass with their migration-count assertion advanced to nine. All use disposable databases; the user's data is not opened by this validation.
- Node **24.21.0**: **15 voice + 13 screen controller tests pass**, no skips. The shell initially selected Node 20, which rejected the existing `--test-isolation=none` option before executing tests; selecting the repository's pinned installed Node 24 resolved it. No dependency change was needed.
- Final Node 24 / Vite **8.3.1** production build passes: **45 modules**, JS **392.87 kB** (**110.54 kB gzip**), CSS **29.22 kB** (**6.61 kB gzip**). This establishes compilation, not UI acceptance.
- Target `.venv/bin/python -m pip check`: no broken requirements. Python compilation, worker CLI `--help`, browser-script syntax, staged/unstaged whitespace checks pass. Python validation uses this checkout's own environment.
- `npm run test:e2e:workers` attempted under Node 24: **blocked at Chrome launch**, `setsockopt: Operation not permitted`, SIGTRAP. It stopped before reading a key/credential, opening a page, creating a worker/task or running browser assertions. No workaround or real SSH connection was attempted.
- The subprocess test executes the bundled benchmark locally with two rounds / ten fictional checks and verifies ten passes, executor/fixture hashes and positive process RSS. These are local fixture checks on this laptop, not worker-network measurements or evidence of an improved model. Worker reports include hardware/date/configuration, exact source/fixture hashes and null model identity via their task envelope; no model is invoked.

## Desktop and two-computer acceptance

The coordinator's actual data has not been migrated or paired by these checks. The additive migration applies at the next app launch. No actual PC connection, SSH configuration or external account was enabled.

For the browser workflow, stop any regular instance on port 8765, then start an empty disposable instance from the repository root:

```bash
LEADDESK_DATA_DIR="$PWD/.local/browser-check" ./launch.sh
# In another terminal:
cd apps/web
nvm use 24.21.0
LEADDESK_TEST_TOKEN_FILE=../../.local/browser-check/access-token npm run test:e2e:workers
```

The prepared browser check pairs one fictional computer, downloads/forgets its credential, queues/cancels work offline, queues again, simulates claim/completion with local synthetic metrics, inspects labelled results, retries a failed refresh, revokes the worker and checks revoked access, page errors and mobile overflow. It leaves pairing/task history in the disposable instance and revokes pairing during cleanup where possible. It has not run past Chrome launch here. Separately exercise keyboard navigation, navigation during pairing, lost pairing/queue responses and multiple tabs.

For real B15 acceptance, use two deliberately selected Ubuntu computers with matching checkouts/dependencies and the README's privately configured SSH tunnel. Pair/download privately, chmod the credential to 600, start the CLI only on the selected PC, and confirm its own hardware/config/date/result rather than the laptop's. Disconnect SSH while idle and during a task/result submission; work must remain queued or recover after expiry, with bounded attempts and stale results rejected. Restart coordinator/client separately, test credential isolation, revoke/cancel during work and verify no research/private data leaves the coordinator. Confirm the forwarded port is loopback-only. Actual SSH transport, hardware provenance, network latency/reconnect and cross-machine compatibility remain unverified.

Prior B10 representative real-source quality, B11 file-search, B12 microphone/model/language and B13 capture permissions plus B14 real reviewed datasets/browser acceptance remain open. B15 remote inference and task types beyond this synthetic benchmark remain future slices. The next ordered backlog item is B16, requiring a chosen email/calendar provider and explicit action scope before any account connection or messaging.
