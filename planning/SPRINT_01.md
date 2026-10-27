# Sprint 1 — website research with inspectable evidence

Date: 19 October 2026, Asia/Karachi. Implementation is committed locally; live browser/source acceptance remains pending. This report describes executed checks, not a complete assistant release.

## Outcome and scope

B01–B03 plus the adjacent B04 correction flow form one usable slice: supply a website/product/target location, extract contact candidates, persist exact source excerpts with IDs/hashes/timestamps, inspect evidence, and suppress incorrect contacts. The root repository contains implementation; the original blueprint lives under `planning/`.

| Backlog | Implemented | Verification |
|---|---|---|
| B01 | FastAPI, React/Vite, local bearer key, host/origin policy, launcher, pinned environments | Production build and in-process frontend/health/API checks pass; desktop server/browser checks pending |
| B02 | Initial transactional SQLite migration, foreign keys, businesses, campaigns, contacts, evidence joins, source-name claim, feedback and suppression | Persistence after repository restart, foreign keys and immutable evidence checked |
| B03 | Single public HTML page, deterministic contact candidates, evidence/unknowns panel, idempotency, bounded public fetch | Synthetic extraction/mismatch/fetch-policy tests pass; live fetching unavailable in this sandbox |
| B04 | Report category, optional suggested value/notes, immutable evidence retained, disputed/suppressed state, history | Existing and future same-host matching contacts suppressed; other hosts untouched; UI browser check pending |

The implementation deliberately leaves all business identities unresolved and all contacts extracted or disputed. It does not identify an official company or branch from an arbitrary supplied page, merge same-name sites, promote directory numbers to attributed contacts, or infer buying interest. The UI has no approved outreach queue. Product/location are stored user inputs, not claims about a prospect.

## Executed verification

- `.venv/bin/python -m unittest discover -s tests -v`: **30 passed**, no skips, 2.201 seconds in the recorded final run. Uses this checkout's own Python environment.
- Tests cover saved excerpts/hashes and relations, restart persistence, idempotency/conflicts, same-name identity separation, pending directory contact attribution, wrong-branch suppression across existing/new runs, cross-host scope, no automatic replacement facts, synthetic labels, temporary network failure/retry, authentication, origin/host checks, input limits, private/multicast/mixed DNS addresses, connection address pinning, robots and redirect restrictions, oversized/compressed/non-HTML content, hidden content, explicit WhatsApp, unknown names, multiple headings, dates, overlong emails and deep HTML limits.
- In-process ASGI requests serve the built HTML/JavaScript and security headers. API tests use a timer to keep the sandbox's event loop awake when thread wakeup operations are restricted; no production bypass is installed.
- `npm run build`, Node 24.21.0 / Vite 8.3.1: **passed**, 15 modules, 677 ms. Built JavaScript 234.93 kB (73.21 kB gzip), CSS 11.77 kB (3.45 kB gzip).
- `.venv/bin/python -m pip check`: **No broken requirements found**.
- A clean `npm ci --offline` using the prepared cache: **passed**, 19 packages installed in 3 seconds. The initial offline-generated lockfile was incomplete for optional non-Linux binaries; 13 exact-version Rolldown platform records and integrity hashes were recovered from the existing `foster-fencing-main/package-lock.json`. The clean install confirms the repaired lockfile on this Ubuntu checkout. Other operating systems were not tested.
- Python compilation and `bash -n launch.sh scripts/setup.sh`: **passed**.
- Python transitive versions are pinned in `requirements.lock`; npm lockfile uses registry URLs and SHA-512 integrity values. Dependencies were installed from available cached distribution artifacts into this project, using an isolated npm metadata cache because network access is restricted. No other project's virtual environment was used. Fresh online installation has not been exercised here.

## Actual machine and resource measurements

Read-only host inspection: Ubuntu 24.04.5, Wayland, Intel Core i5-8265U (4 cores / 8 threads), 7.45 GiB RAM, 8 GiB swap, Intel UHD Graphics 620; no dedicated GPU was identified by lspci. Available RAM was approximately 3.8 GiB and available disk space 68 GiB at initial inspection. No GPU or inference runtime was used.

See [sprint-01-benchmark.json](sprint-01-benchmark.json) for timestamp, fixture hash and exact configuration. One fictional HTML fixture was parsed 100 times: cold 3.64 ms, warm median 1.31 ms, p95 1.67 ms, peak parser-process RSS 18.625 MiB. Model hash is null, inference calls/network requests/external spend zero. These are parser measurements, not live contact accuracy, server idle memory, browser memory or full process-tree performance.

`/usr/bin/time` measured the Python test process peak at 56,112 KiB (about 54.8 MiB), including in-process API tests. No full desktop process-tree benchmark is claimed. B05's model benchmark runner and model selection remain future work.

Runtime choices were checked against official [Python support status](https://devguide.python.org/versions/), [Node release status](https://nodejs.org/en/about/previous-releases) and [Vite requirements](https://vite.dev/guide/). Python 3.12 remains supported; the preinstalled Node 24 release was used instead of this shell's default Node 20, which is past support.

## Live checks blocked by this session

- Uvicorn successfully imported the production app and completed startup, then failed to bind `127.0.0.1:8765`. A direct socket bind returned `PermissionError: [Errno 1] Operation not permitted`.
- `npm run test:e2e` reached the browser launch step, but Chrome exited with `setsockopt: Operation not permitted`, signal SIGTRAP. No browser assertions or screenshots completed. The browser check is supplied in `scripts/browser-smoke.mjs`; its behavior has not been validated in a real browser yet.
- Fetching `https://example.com/` returned the explicit retriable DNS-resolution error. No live-source record or live contact accuracy was established.

Use the normal desktop terminal commands in [../README.md](../README.md). Then exercise the labelled synthetic demo, inspect an evidence excerpt, report a wrong contact, refresh/reopen the saved record, and try a real business contact page. Verify the page belongs to the intended business/branch manually. The fresh disposable-data browser command is documented there as well.

## Limits and next sprint

Single-page HTML only; no link crawling, JavaScript rendering or autonomous discovery. External CSS visibility and complex email/phone validity are not resolved. Suppression uses source host, contact type and stored normalized value; local phone formatting variants are not region-normalized. Cross-host redirects require entering the destination explicitly. Fetches respect robots rules, validate every redirect and pin the connection IP; the per-source policy is conservative. The single-process research lock is not a persistent worker or multi-process coordinator.

Evidence is retained locally without raw page bodies. Retention/deletion UI, backup/restore, SQLite upgrade/rollback workflows, voice, memory/file search, model inference, outreach, external accounts and training are not implemented. No global quality percentages are claimed from synthetic fixtures.

Next: close the desktop/live-source acceptance checks, refine extraction using reviewed errors, then B05 hardware/model benchmarking and B06 a grounded product brief. Model selection and downloads require hardware measurements and an explicit chosen model; none are silently enabled by this sprint.
