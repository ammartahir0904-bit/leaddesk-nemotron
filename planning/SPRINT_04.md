# Sprint 4 — bounded discovery and a persistent research queue

Date: 19 October 2026, Asia/Karachi. B07's first connector and queue slice is implemented and tested with synthetic sources/in-process API execution. Browser interaction and live-source acceptance remain unverified.

## User outcome

Select a saved product brief, supply a public directory/association page, set a bounded scope and queue research. The connector retains visible external text links and inspects candidate pages inside that scope. Pause/resume, cancellation, retry timing, per-page outcomes, source evidence, saved research and coverage gaps are visible in Research queue.

There is no search-engine account, paid connector, model inference or automatic buyer qualification. Source links remain candidate websites. Geography, exclusions, identity, branch, fit, intent and budget require later review; the connector does not filter/rank by offer text or merge same-name/shared-domain branches.

## Delivered

- **Public page links connector:** deterministic visible anchors; same-host/hidden/invalid/private literal links and exact normalized duplicates are excluded. Different paths on a shared host remain separate. Candidate count is bounded; source order, filtered counts, capped results and coverage gaps are visible. Image-only links, external CSS visibility, pagination and JavaScript are outside scope.
- **Discovery evidence:** source URL, anchor text/raw href, source-body SHA-256 and retrieval time for each candidate. Directory contacts are not copied to prospect records. Candidate pages generate normal research with their own evidence, unresolved identity and the frozen brief.
- **Durable queue:** jobs, steps, attempts, controls, events, retry deadlines, page/active-time budgets and frozen scope persist in SQLite. Create returns 202 before page access. Authentication, origin/host/body checks and idempotency remain enforced.
- **Worker lifecycle:** one in-process background thread starts/stops with FastAPI lifespan and shares the execution lock with interactive research/benchmarks. No additional server, broker or dependency. The queue panel polls progress while open and recovers after temporary polling errors.
- **Pause/resume/cancel:** cooperative between pages; an already claimed/in-flight page can finish and retain its evidence. Resume does not reset quotas or bypass a retry deadline. Old control request replays do not reapply an action after a newer one.
- **Retry policy:** transient errors retry at most twice per step with exponential delay/jitter and parsed Retry-After seconds/HTTP dates. Access prohibitions are not retried. Failure/partial states retain completed evidence and show remaining gaps.
- **Restart safety:** 60-second leases/heartbeats, attempt reservation and conservative lost-time charging. Stale owners cannot commit results. Uncommitted reads can repeat within the original budget; there is no claim of exactly-once external HTTP access.
- **Atomic results:** research/evidence creation and workflow completion use one transaction with a stable per-step request key. An interrupted write rolls both back; retry commits one saved record. Previously reviewed contact suppressions apply to queued results.
- **Limits:** 20 unfinished jobs; 1–6 page attempts, 1–20 candidates, 30–300 active seconds per job. Source and retries consume attempts. Budget exhaustion, source exhaustion, candidate caps and failed inspections produce explicit partial coverage.
- **Synthetic demo:** a fictional directory plus north/south websites exercises discovery, persistence and saved research without business network requests. Jobs and resulting records stay labelled synthetic.
- **Migration 004:** adds queue tables, events, controls and immutable scope/evidence triggers. Prior research, evidence, corrections, brief history/snapshots and benchmark reports are preserved.

## Implementation

| Module | Responsibility |
|---|---|
| `backend/domain/jobs.py` | Typed input/control bounds and connector capabilities |
| `backend/adapters/discovery.py` | Visible external link candidates and source evidence |
| `backend/storage/jobs.py` | Atomic queue/controls, leases, recovery, progress and results |
| `backend/workflows/worker.py` | Bounded page execution, lifecycle and fixed synthetic sources |
| `backend/api/jobs.py` | Authenticated enqueue/control/detail/history endpoints |
| `backend/storage/repository.py` | Caller-owned transaction support for research writes |
| `backend/adapters/fetch.py` | Remaining job deadline and Retry-After propagation |
| `apps/web/src/QueuePanel.jsx` + stylesheet | Queue form, progress, controls, evidence and gaps |
| `tests/test_jobs.py` | Discovery, workflow, migration and API/lifespan acceptance |

## Executed verification

- Target checkout `.venv/bin/python -m unittest discover -s tests -q`: **86 tests pass**, no skips. This includes the previous 64 checks plus 22 discovery/queue cases.
- Verified cases include: visible-link evidence, hidden/private/credential link rejection, URL deduplication without branch merging, source/operator separation, frozen brief after edits/restart, retained suppression, pause/cancel during fetch, exact control replay, provider delay/resume, retry cap, page/time/candidate limits, explicit source exhaustion, stale owner rejection, repeated worker-crash limits, atomic rollback/retry, queue backpressure, shared execution lock and migration preservation from Sprint 3.
- In-process ASGI lifespan test starts the real worker thread, completes the three-page synthetic workflow, exits lifespan and verifies the thread stopped. This is actual local workflow execution with fictional pages; it is not browser or live-source acceptance.
- A separate synthetic run also completed source plus two candidate pages, producing two research records and no directory-operator contacts.
- Frontend production build passes with Node 24.21.0 / Vite 8.3.1: 21 modules, JavaScript approximately 266.92 kB (80.39 kB gzip), CSS 17.91 kB (4.63 kB gzip).
- Target environment `pip check`: no broken requirements. Python compilation, browser-script syntax and `git diff --check` pass.
- Worker shutdown uses an async bounded drain without the default executor. An initial lifecycle test exposed a sandbox event-loop wakeup hang during executor shutdown; the final lifecycle/full-suite checks complete normally.

## Live checks and practical limits

- Browser smoke was attempted. Chrome failed at launch with `setsockopt: Operation not permitted` / SIGTRAP before assertions or screenshots. The script now covers paused creation, resume, completion, discovery evidence, opening saved research, cancel, refresh persistence, polling recovery and mobile overflow, in addition to earlier flows. None of these browser assertions is claimed as executed here.
- A direct production-fetcher request to `https://example.com/` returned the explicit retryable DNS-resolution error. No live directory/contact accuracy or source compatibility is established.
- A page attempt can make up to eight HTTP requests across robots and redirect chains, each with the existing size/policy limits. Page attempts are not raw HTTP-request counts. The normal deadline is capped at 20 seconds/remaining job time; an in-flight socket operation can add up to its five-second timeout. Cancellation cannot interrupt that operation immediately.
- Paused, queued and retry-wait time is excluded from active time. A lost lease conservatively charges up to 60 seconds of unknown active work, so a crashed short-budget job may finish partial rather than repeat uncertain work.
- Jobs continue while the server runs even when the browser is locked/closed. Paused jobs remain paused on restart; authorised unfinished work resumes after any stale lease expires. A finished job requires an explicit new run.
- The application still targets one local server process/coordinator. Job claims are fenced in SQLite; the interactive execution lock is in-process and is not shared with independently launched app/CLI processes.
- Connector access uses robots/public-page restrictions; site-specific source suitability is not established by synthetic tests. Source availability, geographic coverage and product fit remain explicit gaps. No account, search provider or cloud inference was enabled.

## Desktop acceptance

```bash
cd /home/ammar/Downloads/LeadDesk_Blueprint
./launch.sh
```

Unlock, create/select a product brief, then open **Research queue**. Enable **Start paused** and choose **Run synthetic queue demo**. Resume it, inspect discovery evidence/coverage, and open either saved research record. Create another paused demo and cancel it; refresh and reopen the saved jobs. Only then try a suitable real public directory page with a small budget. The root README documents disposable-data browser automation and the exact queue API.

Next: B08, business/branch identity resolution and grounded analysis. The queue provides source candidates and evidence; it does not promote them to verified businesses, eligible prospects or customers.
