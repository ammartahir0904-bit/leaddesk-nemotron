# Sprint 13 — reviewed local email and calendar files

Date: 20 October 2026, Asia/Karachi. First B16 slice, following Sprint 12. User selected **Local email drafts and calendar files**. No provider account, sending, invitation, booking or availability check is authorised by this scope.

## Outcome and acceptance plan

Author an email against a saved source contact or a personal calendar planning draft, inspect the exact recipient/text or both parties' local times, approve the displayed revision for file export and download `.eml`/`.ics`. Edit or delete drafts locally. Downloads remain user-managed files; imports/sending happen separately in the user's chosen client.

- Separate source-contact review from file-export review. Suppressed, disputed, missing or unattributed source contacts cannot export. Changed source context invalidates earlier approval.
- Strict typed inputs, plain text only, one mailbox, no header/property injection. Source/body text never executes actions or automatically becomes approved facts.
- Explicit IANA timezones, UTC conversion, DST gap rejection and explicit fold choice for ambiguous times. Show both zones. Calendar files are tentative personal planning events with no attendees, organiser, alarms or scheduling requests.
- Persisted optimistic revisions and idempotent writes, current-context export checks, stable per-draft file identifiers and bytes on repeat download, deletion tombstones preventing replay resurrection. Downloads never mark mail sent or meetings accepted.
- Additive migration preserving every prior table; bounded storage/paging/requests/exports; meaningful synthetic API/storage/timezone/format/failure checks; full regression suite and frontend build. Prepare a disposable browser workflow and record actual execution limits.

## Delivered

- **Local file workflow selected by the user:** a new Email and calendar panel, real/personal vs synthetic modes, separate paged source/draft lists, email/calendar editors, saved previews, latest reviewer/note/time, explicit revision acknowledgement, guarded file download, optimistic editing and confirmed deletion. Unsaved edits disable approval/download and are temporary when leaving/refreshing the panel.
- **Source-bound mail drafts:** recipient selected from an existing saved email contact; user supplies one sender, subject and plain-text body. Drafts may be saved while source review is incomplete, but current effective source identity/contact attribution is required for file approval/export. Suppression, applicable reviewed offer exclusions, missing contacts/sources, disputed identities and new unresolved related-source comparisons block export. Changed identity signatures/context invalidate earlier approval. This is user-authored text, not a generated or independently verified pitch, authenticated sender account or permission to contact.
- **Time-aware planning drafts:** explicit IANA zones for both parties, local start and 5–480 elapsed minutes, UTC/offset-aware previews and dates 2000–2100. Invalid/skipped times are rejected. Ambiguous wall times require explicit earlier/later occurrence. UTC duration handles midnight/date rollover, fractional offsets and DST transitions. Missing/invalid timezone rules block export; changed resolved context invalidates review.
- **Deterministic `.eml`/`.ics` files:** standard-library plain-text UTF-8 MIME, one recipient, stable Message-ID and X-Unsent header; calendar UTC dates, stable UID, revision SEQUENCE, escaped TEXT and UTF-8 octet-aware line folding. Calendar events are tentative and transparent, with no ATTENDEE, ORGANIZER, VALARM or scheduling METHOD. Synthetic file subjects/titles are visibly labelled. Same approved revision yields identical bytes on repeat download; actual clients can still duplicate imports and are not reconciled here.
- **Durable review and deletion:** authenticated typed routes, expected revisions, displayed-context hashes and explicit file-only acknowledgement. Create/edit/review writes and hash-only receipts are transactional. Old request replays return current state without reapplying an old mutation/approval; deletion removes current text/approval and receipts prevent resurrection. Old draft bodies are not archived. Original research, feedback/suppression, notes, learning data and worker state are preserved. Limits: 500 drafts, 10,000 lifetime write receipts, existing 16,000-byte JSON body cap, 64,000-byte export cap and independent 20-item pagination.
- **Additive migration 010:** independent correspondence draft/request tables plus immutable kind, no updates to old tables or account credentials. The actual user database is not opened/migrated by verification. No provider SDK, dependency, SMTP/OAuth account, sender, calendar import, booking, availability request, model or cloud connection is introduced.

## Modules

`backend/domain/correspondence.py` validates the fixed local-draft/review contract, single mailboxes and IANA/DST conversion. `backend/adapters/draft_files.py` serializes files. `backend/storage/correspondence.py` owns source checks, revisions/reviews/receipts and guarded exports. `backend/api/correspondence.py` exposes owner-authenticated routes. `apps/web/src/CorrespondencePanel.jsx`/CSS provides the panel; `tests/test_correspondence.py` supplies disposable fixture checks and `scripts/correspondence-smoke.mjs` prepares desktop browser acceptance. README documents routes, limits, source-review steps and file/client boundaries.

## Verification evidence

- Final target `.venv/bin/python -m unittest discover -s tests -q`: **276 tests pass**, no skips, in **112.069 seconds** (252 previous plus 24 correspondence cases). This run starts after the production build completes so the existing frontend-serving check also runs against present assets.
- Target `.venv/bin/python -m unittest tests.test_correspondence -q`: **24 tests pass**, no skips, in **9.676 seconds**. Checks cover UTC/two-zone/date rollover, New York DST gaps/folds, elapsed time across DST and fractional offsets, strict types/controls, malformed sender errors, MIME Unicode/plain-text/single recipient, UTF-8 octet folding and property escaping, stable identifiers/bytes, missing review, optimistic revisions, stale tabs/context, exact request replay and deleted-draft tombstones, source suppression/disputes/new related records/missing contacts/sources, pagination/mode separation, restart, failed-write rollback/export bounds, timezone unavailability and every old table's migration preservation.
- Migration verification starts from all nine earlier migrations and seeds real storage objects with **fictional** source research/feedback/suppression, private-note text and a paired worker/pending task. Every earlier table is compared before/after migration 010, followed by foreign-key and version checks. Earlier preservation regressions advance only their migration-count assertion to ten. Verification uses disposable databases and does not open the user's actual data.
- Node **24.21.0**: existing **15 voice + 13 screen controller checks pass**, no skips. These do not exercise the new editor.
- Final Node 24 / Vite **8.3.1** frontend production build passes: **47 modules**, JavaScript **408.26 kB** (**113.90 kB gzip**), CSS **30.45 kB** (**6.76 kB gzip**). Compilation does not establish browser rendering or successful client imports.
- Target `.venv/bin/python -m pip check`: no broken requirements. Python compilation, browser-script syntax and whitespace checks pass. Dependencies/lockfiles remain unchanged.
- `npm run test:e2e:correspondence` attempted under Node 24: **blocked at Chrome launch**, `setsockopt: Operation not permitted`, SIGTRAP. It stopped before reading the access key, opening a page, creating a source/draft, downloading a file or running browser assertions. There is no browser/client acceptance claim.
- Email validation normalises the standard-library parser's `IndexError`/header-parse failures into user-facing validation errors; a malformed sender cannot become an unhandled server error. The Unicode/folding fixture stays within the actual title bound. Neither check changes real records or sends anything.

## Remaining desktop/client acceptance

Use a normal desktop and a separate empty data directory. Stop a regular instance on port 8765 first:

```bash
LEADDESK_DATA_DIR="$PWD/.local/browser-check" ./launch.sh
# In a second terminal:
cd apps/web
nvm use 24.21.0
LEADDESK_TEST_TOKEN_FILE=../../.local/browser-check/access-token npm run test:e2e:correspondence
```

The prepared browser script creates fictional drafts, rejects a skipped/ambiguous New York time, chooses a fold, retries a lost create response, checks both-zone preview and review/download gating, downloads an ICS, edits/re-reviews it, creates a fictional source/contact review, downloads an EML, applies a late correction, confirms blocked export/deletion and original suppression, and checks mobile overflow/page errors. It attempts to delete its draft/download copies and leaves the original synthetic source/correction in disposable data. It has not run past Chrome launch in this session.

Separately test keyboard/navigation, multiple pages, stale tabs, lost review/edit responses and leaving/refreshing with unsaved edits. Import only deliberately authored non-sensitive test files into the user's chosen client, verifying Unicode rendering, editable-draft behaviour, timezone/DST display, tentative/transparent handling, repeat import/update behaviour and manual deletion. X-Unsent and UID/SEQUENCE handling varies by client and is unverified here. No send/invite/import/meeting acceptance or real recipient permission is demonstrated by unit checks.

This slice does not complete provider integration: provider availability, OAuth, scoped sending, send reconciliation, inbox opt-outs and remote event creation remain future work. Prior live-source quality, file search, speech/capture, reviewed-dataset and real PC-worker gates stay open. Next ordered backlog candidate: B17, a bounded reviewed-data ranker/evaluation experiment with its own chosen dataset/scope; no automatic training or promotion is implied.

Format references used during implementation: [Python 3.12 email message API](https://docs.python.org/3.12/library/email.message.html), [Python IANA timezone support](https://docs.python.org/3.12/library/zoneinfo.html), [RFC 5545](https://www.rfc-editor.org/rfc/rfc5545.html). Source text was treated as reference material, not tool authorisation.
