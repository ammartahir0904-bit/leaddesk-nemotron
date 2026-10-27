# Sprint 6 — prospect dashboard and evidence-preserving export

Date: 19 October 2026, Asia/Karachi. B09's local dashboard/export slice is implemented. Automated API/storage checks and the frontend build pass. Desktop browser and live-source acceptance remain pending.

## User outcome

Open **Leads**, search saved prospects and apply separate identity/contact/analysis/fit/review filters. Inspect public contacts, source quotes and dates, excluded values, targeting context, need hypotheses and outstanding checks. Open the original research record to review identity, alternatives, citations and history. Download a fresh JSON or CSV snapshot with the applied filters.

## Delivered

- **Separate states:** identity, contact attribution, reachability, inferred fit, analysis staleness, unknown interest and unknown budget remain distinct. Source reviewed means implemented manual checks are current, never independent verification or outreach approval. Names/locations are source quotes; target geography remains a targeting input.
- **Immediate correction effects on reads:** effective states come from the existing assessment/suppression logic. Suppressed contacts, disputed identity, outside-target geography, offer exclusions and current not-a-fit judgements produce explicit exclusions. Historical positive-fit judgements are preserved but stale ones cannot pass the possible-fit filter. Changed related-record reviews remove ineffective contact attribution.
- **Bounded dashboard:** newest 200 saved records per mode, deterministic saved-time/ID ordering, 20 results per UI page and explicit scanned/total/limited coverage. Real-source records are the default; synthetic demos have a separate mode, prominent labels and separate downloads. Records are not merged or ranked. Search accepts arbitrary offers/geographies.
- **Consistent read snapshots:** list/export reads share one SQLite transaction, including comparisons, corrections and history. A correction committed mid-export cannot mix old and new suppression flags inside the downloaded file. New downloads recompute states instead of exporting a cached browser payload. Ordinary record reads retain their existing API.
- **JSON audit bundle:** effective summary plus complete saved research, evidence excerpts/IDs/hashes/URLs/dates, claims, feedback with unverified suggestions, frozen product brief, up to 100 recent assessment revisions and explicit history bounds. Sources cited by current or included historical cross-record comparisons carry their own evidence, even when outside the selected results.
- **CSV:** UTF-8 BOM, one row per contact and a blank-contact row for records without contacts. Review/exclusion labels, saved/effective fit, inference interpretation, unknown intent/budget, check/review times and contact evidence remain present. The first row per research ID contains the complete research/history/comparison audit JSON. Formula-like cells receive a spreadsheet-safe apostrophe; exact values remain in JSON/audit data.
- **Read-only authenticated endpoints:** `/v1/leads` and `/v1/leads/export`, strict query/filter bounds, existing origin/host/token/no-cache protections and no source fetches. Export covers every matching result page within the bounded scope and rejects pagination arguments. Empty JSON/CSV retains its schema. Export record data above 16 MiB returns 413 with a narrower-filter instruction and no partial attachment.
- **Interface:** filter application, summary counts, pagination, empty/error/retry paths, excluded-contact audit, downloadable files and a responsive layout. The browser script adds synthetic-mode separation, stale-fit filtering, excluded evidence, JSON/CSV content checks, empty search, outage/retry, reopening details and mobile overflow checks.
- **Preservation:** no schema migration, dependency, model call, cloud service or outbound messaging was added. Existing research, corrections, briefs, queue jobs and benchmarks remain in place. Automated read-only/reopen checks cover the export path.

## Implementation

| Module | Responsibility |
|---|---|
| `backend/domain/leads.py` | Typed filters, effective summary states, exclusions and next checks |
| `backend/domain/lead_export.py` | CSV quoting, formula protection and audit columns |
| `backend/storage/leads.py` | Bounded selection, consistent snapshots and evidence/history export |
| `backend/storage/repository.py` | Caller-owned read transaction support |
| `backend/api/leads.py` | Authenticated dashboard and download endpoints |
| `apps/web/src/LeadsPanel.jsx` and stylesheet | Prospect filters, contact/evidence cards and downloads |
| `tests/test_leads.py` | API, correction, staleness, export and storage regression checks |

## Verification

- Target checkout `.venv/bin/python -m unittest discover -s tests -q`: **133 tests pass**, no skips, in 40.913 seconds (111 prior checks plus 22 dashboard/export cases).
- New cases cover authentication/origin/query bounds, empty files, real/synthetic separation, arbitrary-offer/location search, independent identity/contact filters, identity/geography/offer exclusions, no-contact records, current not-a-fit judgements, host-scoped corrections in existing/future exports, stale positive fit, changed comparisons, unknown intent/budget/reachability, comparison evidence including history, history truncation, export byte limits, queued synthetic results with frozen briefs, deterministic pagination/all-page exports, CSV formula/quote/newline handling, read-only reopening, the 200-record scope and a concurrent-correction snapshot.
- Frontend production build passes with Node 24.21.0 / Vite 8.3.1: 28 modules, JavaScript 299.15 kB (87.58 kB gzip), CSS 21.93 kB (5.36 kB gzip). This is compilation evidence, not rendered-browser acceptance.
- Target `.venv` dependency check reports no broken requirements. Python compilation, browser-script syntax, launcher/setup shell syntax and `git diff --check` pass.
- Browser smoke was attempted after extending it for Leads; Chrome failed at launch before assertions or screenshots. The disposable-data server attempt reached startup and then failed to bind, as described below.

All source pages in automated tests are fictional. Build/API results do not establish rendered browser behavior or real contact accuracy.

## Desktop acceptance and limits

Run `./launch.sh` from this checkout in a normal desktop terminal and open `http://127.0.0.1:8765`. Unlock, open or create a synthetic demo, then choose **Leads → Record source → Synthetic demos only → Apply prospect filters**. Inspect contact evidence/dates and download both formats. Review identity/need, report a wrong contact, return to Leads, and confirm exclusion and stale-analysis labels; filter possible fit to ensure the stale result is omitted. Check file contents, refresh/reopen persistence, keyboard access and mobile layout. Use the root README's disposable-data browser procedure for automation.

This sandbox cannot launch Chrome (`setsockopt: Operation not permitted`, SIGTRAP). No browser assertions or screenshots ran. A disposable-data Uvicorn run completed application startup, failed to bind `127.0.0.1:8765`, and shut down cleanly; no server remains running from that attempt. In-process API checks do not replace a listening-server check.

The newest-200 scan is an explicit first dashboard scope; older records remain stored and accessible through existing record APIs but are outside dashboard filters/downloads. History exports contain at most 100 recent revisions per record, with truncation labels. Source freshness is not rechecked by opening/filtering/exporting. A subsequent request may see new records or changed reviews; pagination is not a pinned multi-request snapshot. Large exports require narrower filters. Files retain excluded/public contact values for audit and do not constitute a qualified outreach list, independent corroboration, database backup or quality evaluation. No live website/contact result is claimed.

Next: B10, a quality baseline with reviewed examples across offers/geographies and explicit per-segment uncertainty. No precision or accuracy target is claimed as achieved by this sprint.
