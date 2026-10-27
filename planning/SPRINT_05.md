# Sprint 5 — business/branch review and grounded need analysis

Date: 19 October 2026, Asia/Karachi. B08's manual review slice is implemented. Synthetic API, persistence and frontend-build checks pass; browser and live-source acceptance remain unverified.

## User outcome

Open an existing research record, review business/branch identity against the saved excerpts, attribute contacts separately, compare related local records, and save a cited need analysis. Source quotes remain separate from reviewer judgements. Corrections preserve the earlier analysis and flag it for a fresh review.

This is manual source review. It does not authenticate an official domain, independently corroborate identity/contact ownership, merge businesses, check reachability, establish buying interest/budget, qualify for outreach or invoke a model. Geography, exclusions, comparison decisions and whether a quoted phrase means the selected field are human judgements.

## Delivered

- **Typed identity review:** unresolved, source-attributed or disputed; page roles distinguish business/shared-brand from directory/agency. Names, branches, addresses and service areas require exact saved excerpt support. Matching allows case/whitespace differences and respects word boundaries. Missing/foreign evidence IDs and unsupported quotes are rejected. Every selected supporting excerpt must contain the quoted text.
- **Separate contact decisions:** source identity does not promote every extracted contact. Attribution requires that contact's own evidence, resolved identity/comparisons, and explicit branch wording in its own excerpt when a branch is selected. Existing suppression overrides manual review. Source attribution never implies reachability or independent corroboration.
- **Scoped identity dispute:** a disputed identity excludes contacts in that research record. Existing Report wrong contact retains its host/value suppression behavior. Both effects are visible; disputed contact values cannot support a new analysis.
- **Local comparisons:** shared host on a different URL, shared contact value and same source heading generate review hints. Shared hosts/contacts require resolution before attribution; same headings alone do not. Judgements cite both records and a reason. Same-page repeats are skipped and synthetic/live records remain separate. Records are never merged. Changes to compared identity/contact state invalidate the previous comparison.
- **Bounded comparison scope:** at most 200 recent records scanned and 20 related source pages displayed. Overflow/incomplete scans keep attribution unresolved. This is not an exhaustive business registry. Explicit API comparisons can link other same-mode local records with two-sided evidence.
- **Grounded analysis:** quoted observations, explicitly inferred need/offer relevance/fit, existing alternatives, competing explanations and missing checks. Possible fit requires effective reviewed identity/comparisons, cited matching geography, checked exclusions, observations/hypotheses and an alternative check. A source-described solution needs its own citation plus a reason to investigate change. An absence claim is limited to selected excerpts. Intent is fixed unknown; budget is null with a reason.
- **Revision safety:** separate optimistic identity/analysis revisions and request receipts. Retries do not duplicate revisions; replaying an older successful request returns the current record without reapplying the earlier judgement. Concurrent reviews cannot overwrite the same revision.
- **Staleness:** dependency fingerprints track local identity revisions, suppression flags and related/compared record signatures. Changes flag earlier analyses for review rather than replacing their claims/citations. The saved fit must be read together with its current/needs-review status. “Current” means dependencies have not changed, not that the inference is independently verified.
- **Local persistence:** migration 005 adds the current assessment document, immutable revision history and evidence links with foreign keys. Prior research, corrections, frozen brief snapshots and paused queue jobs survive migration. History displays up to 100 recent revisions.
- **Source context:** new research additionally retains at most 12 visible excerpts of 400 characters each. Hidden content is excluded under the existing parser policy. Raw pages remain unsaved; older records receive no invented/backfilled context.
- **UI:** evidence pickers expose full saved excerpts, URLs, retrieval dates and IDs; review states, conflicts, unknown intent/budget, history and reload are visible. The fictional demo now includes a location, existing calendar and manual stock-counting text to exercise the workflow without real prospects.

## Implementation

| Module | Responsibility |
|---|---|
| `backend/domain/assessments.py` | Typed review documents and strict scoped quote validation |
| `backend/storage/assessments.py` | Atomic revisions, citation links, replay and analysis gates |
| `backend/storage/assessment_views.py` | Bounded related hints, effective identity/contact states and staleness |
| `backend/storage/migrations/005_identity_analysis.sql` | Persistent assessments, append-only history/evidence links |
| `backend/api/assessments.py` | Authenticated review, related-record and history routes |
| `backend/domain/extract.py` | Bounded visible source context |
| `apps/web/src/AssessmentPanel.jsx` and review components | Source review, analysis and revision UI |
| `tests/test_assessments.py` | Citation, identity, branch, alternatives, persistence and correction checks |

## Executed verification

- Target checkout `.venv/bin/python -m unittest discover -s tests -q`: **111 tests pass**, no skips (86 prior checks plus 25 assessment/context cases). Full run: 27.024 seconds.
- New cases cover authentication/origin/key checks, scoped citations and invented wording, directory/agency/shared-brand roles, separate contact ownership, wrong-branch and word-boundary cases, suppression, disputed identity scope, two-sided comparisons and no merging, synthetic/live separation, bounded comparison overflow, unknown budget/intent, existing solutions/alternatives, possible-fit gates, stale analyses, concurrent edits, old replay, restart, immutable history/evidence and Sprint 4 migration preservation.
- Frontend production build passes under Node 24.21.0 / Vite 8.3.1. This verifies compilation, not rendered-browser behavior.
- Target `.venv` dependency check reports no broken requirements. Python compilation, browser-script syntax and whitespace checks pass.
- Browser smoke was extended with cited identity/analysis saves, invalid quote rejection, history/reload and staleness after a contact correction, alongside previous brief/queue flows. Attempted execution failed at Chrome launch with `setsockopt: Operation not permitted` / SIGTRAP. **No browser assertions or screenshots executed.**
- A fresh disposable-data Uvicorn run completed application startup, then could not bind `127.0.0.1:8765` in this sandbox and shut down cleanly. The desktop server is not running from this session. In-process API/lifespan tests pass; they do not replace a listening-server/browser check.

## Remaining acceptance and scope

Run `./launch.sh` from a normal desktop terminal, unlock and open a fresh synthetic demo. Cite the name, North branch and Synthetic market location; review exclusions. Save identity, then cite manual stock counting and the existing online calendar in a need analysis. Check that invented quotations are rejected, budget/interest remain unknown, history persists after reopening, and a contact correction marks analysis for review. Use the README's disposable-data browser command for automation; real source accuracy still requires separate review.

Source text can be misleading, stale or incomplete even when quoted correctly. Page-role decisions and geographic matching are manual. Limited excerpts cannot prove that an existing solution is absent; cross-site corroboration, automated resolution, a global entity graph and independent quality measurement remain outside this slice. Previous sprint live-fetch acceptance is still outstanding; no new live business/contact result is claimed here.

Next: B09, lead dashboard and export, using effective identity/contact states and analysis staleness so exports preserve evidence and uncertainty.
