# Sprint 10 — on-demand screen context and reviewed local tools

Date: 20 October 2026, Asia/Karachi. Implements a bounded B13 slice from the Sprint 9 handoff. Code/fixture verification has passed; browser rendering and actual Ubuntu permission acceptance remain unverified. B13 is not marked complete.

## User outcome

Open Screen context, explicitly choose a window/tab/display for one temporary still, enter the relevant text and a source label, review a local action and run it. When selection is denied or unsupported, paste/type context instead. Search an approved folder, preview a current file, search scoped active memory, or explicitly save the reviewed text as an editable scoped note. Images never leave browser memory in this implementation.

## Delivered scope

- **Explicit capture:** browser `getDisplayMedia` invoked directly from the user's button click, window preference with browser-controlled source selection, audio disabled, no automatic recapture. Browser/Ubuntu chooser owns permission and source selection; there is no portal bypass or independent X11 adapter.
- **One temporary preview:** visible permission/capture/off states; one video frame, then all sharing tracks stopped before review. Selection deadline 30 seconds; frame reader deadline five seconds with a six-second controller bound. Sources limited to 16384 pixels per side and 33,554,432 pixels total; preview limited to 1600 × 1200 and 2.8 million data-URL characters. Detached video/canvas references are cleared on success/failure/cancel.
- **Cancellation and lifecycle:** explicit discard during selection/capture, prepared/read actions; page exit/panel change always cancels. Late permission streams are stopped and late frame/API results cannot restore cleared context. Chooser focus changes are permitted; hiding the tab after review clears context. A preview expires after five minutes subject to browser timer scheduling. An already-open browser chooser cannot be programmatically dismissed, but its late response is ignored and its tracks stopped.
- **User-assisted text:** up to 4,000 reviewed text characters and a 160-character source label, with optional client-reported capture time, surface type and full-surface dimensions/region. No claimed OCR, accessible-text extraction, independently identified app, image reasoning or model output. Source labels and screen text are untrusted data, rendered as text and never parsed as executable commands. Selecting a screen alone never sends context to the server.
- **Reviewed typed tools:** explicit file search with approved folder/keywords, active-memory search with exact scope/keywords, or scoped user-authored note saving. Preparation describes the action without searching/saving; edits invalidate the UI plan, and execution recomputes its hash over context, provenance and operation. Stale plans return 409. Unknown actions/image fields/ambiguous scopes are rejected.
- **Existing local policies:** file search/preview reuses current-content, symlink, changed/deleted-file and folder-revocation checks. Memory search returns up to three active scoped notes. Save reuses transactional idempotency, deletion receipts and editable/deletable private notes excluded from training. No schema migration, installed package, downloaded runtime or weight, native opener, arbitrary shell, file overwrite or external integration was added.
- **Privacy:** screenshot bytes never enter an API request, SQLite, application file, note, log or dataset. Only explicit reviewed note saving persists text and source details. Prepared/read context is not stored. There is no screenshot save/download control. App cancellation does not undo a note already committed; navigation/hidden-tab cancellation can lose its response, so inspect the selected scope before creating a new request.

## Modules

| Module | Responsibility |
|---|---|
| `apps/web/src/screen-session.js` | Bounded one-frame browser capture, deadlines and stream/lifecycle cleanup |
| `apps/web/src/ScreenPanel.jsx`, `ScreenPanel.css` | Temporary preview, source/text editing, action/scope review and results |
| `apps/web/src/main.jsx` | Screen context navigation, active-panel lifecycle |
| `backend/domain/screen.py` | Strict context/metadata/action schemas and review hash |
| `backend/api/screen.py` | Stateless authenticated prepare/execute tools using existing file/memory policies |
| `tests/test_screen.py` | Synthetic API, policy, provenance, idempotency and persistence regressions |
| `tests/screen-session.test.mjs` | Generated media/video/canvas controller and cleanup tests |
| `scripts/screen-smoke.mjs` | Fictional browser flow with generated canvas streams; no real desktop read |

## Verification evidence

- Target `.venv/bin/python -m unittest discover -s tests -q`: **208 tests pass**, no skips, in 39.442 seconds (198 prior plus ten screen cases). New cases cover review-before-save, literal/untrusted and Unicode manual text, timezone/region provenance, context/action/scope hash invalidation, idempotent writes and deleted-note replay, scoped/expired/three-choice memory search, changed/deleted/revoked files, strict action/image/metadata/bounds validation, authentication/origin/body limits/no-store and absence of persisted prepared/read context. Existing regression tests include storage preservation and previous research/voice/file workflows.
- Node 24.21.0 `npm run test:screen`: **13 tests pass**, no skips. Tests exercise no automatic capture/audio, track release before preview, denial/missing support, late permission/cancel/rejection, permission/frame timeout, cancellation during frame reading, track-ended/dispose/double-start, generic diagnostic handling, actual frame-reader scaling/dimension/output bounds and video/canvas cleanup. Media, frames and canvas are generated fixtures.
- `npm run test:voice`: **15 existing tests pass**, no skips.
- Node 24.21.0 / Vite 8.3.1 frontend production build passes: 41 modules, JavaScript 366.56 kB (104.40 kB gzip), CSS 27.21 kB (6.29 kB gzip). This proves compilation, not browser rendering.
- Target `.venv/bin/python -m pip check`: no broken requirements. Python compilation, browser-script syntax and `git diff --check` pass. No dependency or lockfile change was needed.
- `npm run test:e2e:screen` attempted: **blocked at Chrome launch**, `setsockopt: Operation not permitted`, SIGTRAP. It stopped before reading the local access key or opening the app. No browser assertion, generated-canvas capture flow, mobile-layout assertion, real chooser permission or real desktop capture ran. The script remains prepared for a normal desktop against disposable data.

## Desktop acceptance still required

Use a normal Ubuntu desktop terminal. This sprint's synthetic browser check replaces capture with generated media; real permissions must be exercised separately.

1. Start `./launch.sh` with ordinary data only for personal/manual acceptance, unlock and open Screen context. Verify that opening/refreshing the panel never opens a chooser or starts sharing.
2. Choose a non-sensitive test window in the real chooser; inspect the browser/Ubuntu capture indicator and verify sharing ends before preview. Check source dimensions, time and full-surface region. Repeat with any other supported source types. Available types are browser/desktop dependent.
3. Deny permission and confirm typed/pasted context remains usable. Cancel while the chooser is open, then approve late: no preview should appear and sharing must stop. Check stopped sharing, missing sources and unsupported-browser errors without a crash.
4. Review a still, then discard, leave the panel, hide the tab and wait for expiry in separate trials. Context/preview must clear. Chooser focus changes must not cause a stale capture or leave tracks active. Confirm keyboard access, visible indicators and small-window layout.
5. Correct text/source/scope after preparation: review must disappear. Prepare again and explicitly save in a disposable scope. Repeating that save returns one note. Edit/delete it in Files and memory; screenshot bytes must never appear in requests or exports.
6. Approve/reconcile a dedicated synthetic folder through Files and memory. Search from context and preview a current result. Change/delete/revoke it and verify stale content cannot be returned; use existing wrong-file controls for corrections.
7. For the fictional automated flow, first start a separate empty-data server (stop any regular server on port 8765): `LEADDESK_DATA_DIR="$PWD/.local/browser-check" ./launch.sh`. In another terminal run `cd apps/web` and `LEADDESK_TEST_TOKEN_FILE=../../.local/browser-check/access-token npm run test:e2e:screen`. It creates/removes only a uniquely scoped fictional note and never reads a real screen.

Prior browser/live-source, B10 representative quality, B11 representative file search and B12 microphone/model/language/output acceptance remain open. This sprint does not establish OCR accuracy, natural-language screen understanding, real capture latency/RAM, portal compatibility, unattended desktop control or release readiness. Native open/reveal/filesystem note-writing tools and automatic OCR/vision remain future slices. Next implementation item after reviewing B13 and earlier acceptance gates: B14, reviewed learning datasets/dashboard.
