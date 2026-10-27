# Sprint 7 — frozen quality baselines and manual source audits

Date: 19 October 2026, Asia/Karachi. B10's source-audit workflow is implemented. It prepares reproducible per-segment reports; the planned real reviewed sample and independent accuracy/release acceptance remain outstanding.

## User outcome

Select saved research, freeze a named development/holdout sample, audit evidence with explicit pass/fail/unknown judgements, inspect failures and uncertainty for every offer/location segment, reopen revisions and download a report with the original predictions. Synthetic records and demonstrations remain separate from real source evaluation.

## Delivered

- **Frozen samples:** 1–100 user-selected research IDs, distinct source URLs, strict real/synthetic separation, dataset/case SHA-256 hashes, original research/evidence/contact/assessment/brief context and captured comparison sources. UI selection searches the newest 200 records per mode; the API can capture older known IDs. Source URL uniqueness is not independent business resolution. Capture is transactional; invalid/mixed/missing/oversize selections leave no partial baseline.
- **Versioned manual audits:** separate identity, contact ownership, factual support and offer relevance verdicts. Known outcomes require a reason and frozen, scoped evidence IDs; target-owned citations are required for contacts/facts and the captured business-name citation for identity. Inferred claims/hypotheses do not become factual units. Unknown/missing outcomes never become correct labels. Reviewer labels are user supplied; no independent adjudication is claimed.
- **Separate denominators:** identity accuracy/agreement counts captured source-attributed identity predictions; contact attribution precision/agreement counts only effective attributed contacts. Abstentions and excluded contacts are visible. Factual reference coverage checks IDs; semantic support has its own human audit. Unranked relevance is descriptive, not precision@20. Full-case count requires known identity, relevance, all contacts and all factual-unit judgements, so unresolved identities remain incomplete.
- **Segment reports:** offer/target-geography grouping normalizes case/whitespace, with sample/eligible/reviewed/pass/fail/unknown/unreviewed counts, reviewer scenario flags, unchanged proposed targets and Wilson 95% intervals. Incomplete audit coverage cannot meet a point gate. Observed target met refers only to that point estimate, never adequate sample size or release certification. Correlated pages/contacts, source errors, reviewer judgements and manual selection remain limitations.
- **Explicit gaps:** real sample requirement of 60 reviewed prospects, three unrelated offers and two geographies; scenario gaps and changed live records are shown. Synthetic examples count zero real reviews. Precision@20, outreach-approved queue safety, duplicate outbound actions, fabricated file/contact fixture evaluation and file success@3 are explicitly unmeasured in this report. Release readiness remains not established.
- **Revision and snapshot safety:** immutable baseline/case/audit rows, optimistic revision checks, idempotent create/save and safe replay of old successful requests. Concurrent reviewers cannot overwrite one revision. Current live-state changes are flagged without rewriting captured predictions. Audits leave live contacts, identity, suppression, analysis, intent and budget unchanged. Revision history shows the latest 100 with explicit bounds; revisions do not inflate sample size.
- **Report export:** authenticated JSON includes every captured case, its latest saved audit/revision, dataset/review hashes, code/rubric/configuration, hardware, model hash null, dates and all segment results. Snapshots and exports are each capped at 16 MiB with explicit failures, never silent partial files. Full audit chronology stays in storage/history rather than the report download. No model, source fetch, training, promotion or outbound action is invoked.
- **Interface:** Quality baseline panel with candidate selection/pagination, real/synthetic mode, development/holdout declaration, frozen evidence pickers, audit forms, scenario flags, segment tables, report download, history and error/retry controls. Drafts survive panel/case switches; explicit reload discards edits. Browser smoke adds the synthetic capture/audit/citation/history/download/draft/retry/mobile flow, but browser acceptance remains unverified.
- **Migration 006:** adds quality tables, indices and immutable-record triggers. Prior tables/data are preserved, including migration from Sprint 6 with existing corrections. The larger 128 KiB request limit applies only to bounded quality audit forms; all other mutations retain their existing limit.

## Implementation

| Module | Responsibility |
|---|---|
| `backend/domain/quality.py` | Typed samples/verdicts, factual targets and scoped audit validation |
| `backend/evaluation/quality.py` | Denominators, unknowns, Wilson intervals, segment reports and unmet gates |
| `backend/storage/quality.py` | Snapshot capture, immutable revisions, retries/history and report reads |
| `backend/api/quality.py` | Authenticated baseline, audit, history and JSON routes |
| `backend/storage/migrations/006_quality.sql` | Additive quality schema and immutability |
| `apps/web/src/QualityPanel.jsx`, `QualityAuditForm.jsx`, `QualityReport.jsx` | Sample selection, manual audit and report UI |
| `backend/evaluation/quality_demo.py`, `scripts/quality_demo.py` | Disposable, clearly fictional report example |
| `tests/test_quality.py` | Audit validation, statistics, persistence, concurrency and migration checks |

## Executed demonstration

`planning/sprint-07-synthetic-quality.json` contains six fictional `.example` source cases across three offers and two geographies. Labels are authored demonstration judgements, not independent manual review or real performance evidence. It includes incorrect attribution, negative/unknown relevance and identity/contact abstention, with zero real reviewed cases and release readiness not established. The CLI uses disposable SQLite storage and does not modify the app's `.local` data. The preserved file contains hardware/configuration, dates, full snapshots and their hashes.

## Verification

- Target checkout `.venv/bin/python -m unittest discover -s tests -q`: **155 tests pass**, no skips, in 61.411 seconds (133 prior checks plus 22 quality cases).
- New checks cover strict authentication/origin/input bounds, mode separation, distinct-source/atomic sample capture, frozen snapshots after correction, scoped contact/factual/identity citations, unknown versus unreviewed denominators, incomplete coverage, per-segment failures/flags, small-sample Wilson intervals, abstentions/exclusions, inference exclusion from factual units, idempotent retries and old replay, concurrent reviewer conflicts, immutable revisions/reopen/export, history limits without sample inflation, foreign comparison evidence, bounded large audit forms, snapshot/export limits, additive migration from Sprint 6 and the fictional demonstration.
- Frontend production build passes with Node 24.21.0 / Vite 8.3.1: 32 modules, JavaScript 319.84 kB (92.32 kB gzip), CSS 24.43 kB (5.77 kB gzip). This verifies compilation, not rendered browser behavior.
- Target `.venv` reports no broken requirements. Python compilation, browser-script syntax, shell syntax and `git diff --check` pass.
- Executed CLI demonstration: six synthetic cases, six segments, one identity abstention, two unknown relevance judgements, zero real reviewed cases, readiness not established. The preserved JSON is 105,750 bytes. Hardware/configuration/date and full review snapshots are included.
- Browser smoke was attempted and failed before assertions at Chrome launch. A disposable-data server reached startup and failed to bind, as described below.

All pages and judgements in automated checks are invented; they do not establish real prospect accuracy.

## Desktop acceptance and remaining scope

Run `./launch.sh` in a normal desktop terminal and unlock. Create/select synthetic research, then open **Quality baseline**, name a sample, choose **Synthetic demos only**, select a record and capture. Confirm unreviewed metrics are unknown, then save a cited audit and inspect its segment, revision history and JSON download. Check that missing/foreign citations fail, unknowns remain separate, unsaved drafts survive switching panels, explicit reload discards them and a later live contact correction flags the frozen case as changed. Exercise keyboard/mobile behavior and the disposable-data browser procedure in README.

Chrome cannot launch in this sandbox (`setsockopt: Operation not permitted`, SIGTRAP), so no browser assertions or screenshots ran. A disposable-data Uvicorn instance completed startup, could not bind `127.0.0.1:8765`, and shut down; no server remains running from that attempt. Frontend build/API tests do not establish browser operation.

The planned 60 real manually reviewed prospects, independent identity/contact adjudication, semantic audit quality, genuine ranked precision@20 and live browser/source checks remain outstanding. A user-entered holdout label does not establish a blind held-out evaluation; reviewers must manage selection/tuning discipline. Source cases may be correlated or describe the same business. Labels/flags and offer/geography label diversity do not prove independent truth or unrelated sectors. Baseline deletion/retention, dataset training controls and automatic quality promotion remain future work. No quality threshold was relaxed, no real adoption/accuracy claim is made, and no benchmark result recommends a model.

Next roadmap item: B11, approved-folder search and memory. Real B10 acceptance remains a separate requirement before accuracy or release claims.
