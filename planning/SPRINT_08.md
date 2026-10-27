# Sprint 8 — approved-folder search and scoped memory

Date: 20 October 2026, Asia/Karachi. Roadmap item B11's bounded text-search and user-authored memory slice. Rename/delete, wrong-file, scope revocation and memory deletion have automated fixture coverage. Desktop browser acceptance and representative file success@3 remain unverified.

## User outcome

Explicitly approve a project folder, reconcile its bounded snapshot, find up to three current keyword matches, preview safe text and correct the chosen file for one query. Keep editable project-scoped notes with source/reason, expiry, pinning, export and deletion. Folder approval does not trigger indexing; no user folders were indexed during implementation or tests.

## Delivered

- **Approved scopes:** authenticated approval/revocation, at most ten dedicated home or `/tmp` roots, no hidden/broad/overlapping/data-folder scopes. Open every directory component using descriptors with `O_NOFOLLOW`; pin root device/inode and recheck before file use. Symlinks and special files are skipped. Hidden/dependency/build entries and known credential filenames are skipped.
- **Bounded text snapshots:** manual scans, maximum 500 entries, twelve levels, 1 MiB/file and 8 MiB total; five-second deadline checked between filesystem operations. UTF-8 text and filenames are indexed with SQLite FTS5. Each record contains root/path, device/inode, hash, modification/change metadata and extraction status. Partial/error counts and unsupported/oversized/non-UTF-8/unreadable/budget statuses are visible. No background scans, PDF/office parsing, embeddings or OCR.
- **Current-file retrieval:** query-local top three keyword choices, filename weighting, excerpts/dates/paths and 16,000-character previews. File identity, metadata, hash and scope are rechecked; changed/deleted/linked/unavailable paths cannot return stored previews. Reconciliation retains unique same-filesystem renamed identities, removes vanished/stale records and keeps duplicate contents/hardlinks separate. Partial scans drop unvisited old entries and report incomplete coverage. Native open/reveal remains a user-assisted copy-location flow.
- **Scoped corrections:** wrong-file exclusions and one preferred file for a normalized exact query/root; preferred files can be chosen outside keyword matches. File hash checks prevent applying old-content corrections. Explicit comment, undo, cross-query/root isolation and cascading removal on file deletion/content replacement or root revocation. No original file is edited and no correction becomes a training label.
- **User-authored memory:** separate scopes/types/content/source, UTC expiry, pinning, optimistic edit revisions, idempotent creation, 100-note list pages, full-scope export and a 1,000-note global bound. Expired notes remain inspectable but are excluded from normal retrieval. Individual deletion and forget-scope remove live content; create-request tombstones prevent deleted-note resurrection. Notes are labelled private/user-authored and excluded from training, with no inferred facts or automatic changes to lead records.
- **Interface and API:** Files and memory navigation/panel with approval/revocation, indexing health, query/preview/correction/undo controls, note editor and pagination/export/delete. Typed authenticated endpoints retain origin/request-size/no-store protections. No shell, model, desktop action, public source request or external service is invoked.
- **Migration 007:** additive approved-folder, local-file, FTS, file-correction, memory and idempotency tables. File index/corrections cascade on revocation; deletion triggers remove FTS entries. Prior migration checks now expect seven versions. Existing lead and quality features are preserved.

## Implementation

| Module | Responsibility |
|---|---|
| `backend/adapters/local_files.py` | Descriptor-based traversal, bounds and current-file validation |
| `backend/domain/files.py` | Typed folder, search, correction and memory inputs |
| `backend/storage/files.py` | Approval, snapshots, scoped search/corrections and revocation |
| `backend/storage/memories.py` | Memory retrieval, revisions, expiry, export support and deletion |
| `backend/api/files.py` | Authenticated local file/memory endpoints |
| `backend/storage/migrations/007_files_memory.sql` | Additive schema and FTS deletion propagation |
| `apps/web/src/FilesPanel.jsx`, `FilesPanel.css` | File search and memory panel |
| `tests/test_files_memory.py` | Disposable-filesystem/API/migration regression checks |
| `scripts/files-smoke.mjs` | Desktop browser acceptance with generated `/tmp` fixtures |

## Verification

- Target checkout `.venv/bin/python -m unittest discover -s tests -q`: **177 tests pass**, no skips, in 97.153 seconds (155 existing checks plus 22 new file/memory cases).
- New checks cover explicit/no-implicit approval, broad/hidden/data/symlink/overlapping roots, scope isolation, provenance/previews, changed/deleted files, rename/correction persistence, external and nested symlink replacement, replaced roots, unsupported/non-UTF-8/oversized/secret-name statuses, entry/byte/time budgets, read errors, FTS text removal, query-specific wrong/preferred choices and undo, ambiguous top-three choices/abstention, content-change invalidation, duplicate contents, revocation cascades, literal FTS input, untrusted/bounded previews, memory replay/conflict/expiry/pinning/deletion/forget/export/pagination, authentication/origin/input limits and preservation of populated Sprint 7 research/suppression/quality snapshots/audits across migration.
- Frontend production build passes with Node 24.21.0 / Vite 8.3.1: 34 modules, JavaScript 334.85 kB (95.83 kB gzip), CSS 25.43 kB (6.00 kB gzip). This verifies compilation, not rendered behavior.
- Target `.venv` has no broken requirements. Python compilation, focused browser-script syntax and `git diff --check` pass. No dependency was added or downloaded.
- Focused browser acceptance was attempted with `npm run test:e2e:files` and stopped at Chrome launch: `setsockopt: Operation not permitted`, SIGTRAP. No browser assertions or screenshots ran, and this attempt created no fixture directory or index because browser launch precedes fixture creation. The command is ready for a normal desktop terminal against a disposable-data instance.

All filesystem fixtures are generated in disposable directories outside the app's temporary data directory; no personal documents or real credential files are read. Existing browser/live-source acceptance is unchanged; no real file-search accuracy, model quality or release readiness is claimed.

## Limits and desktop acceptance

The full blueprint's PDF/office parsing, semantic retrieval, file watchers/periodic reconciliation and native OS Open/Reveal tools remain future work. Indexing is deliberately manual and bounded; the deadline cannot interrupt a filesystem call already in flight. Representative 30-task file success@3 and the proposed 90% gate have not been measured. Fixture tests are safety/behavior regressions, not evidence of personal-document retrieval quality.

Deletion is logical removal from live records/retrieval, not guaranteed secure erasure of SQLite/WAL free pages, prior exports/browser copies or backups. Independent user-authored notes about a folder are not derived indexed text and remain until explicitly deleted. There is no training pipeline or model-weight memory.

In a normal desktop terminal, run `./launch.sh`, unlock, then open **Files and memory**. Approve a disposable project folder containing several fictional UTF-8 files and one unsupported document. Reconcile, search, preview, mark/undo a wrong match, associate a preferred file to the earlier query, rename/delete it, and reconcile again. Confirm stale previews fail and revocation removes the index while originals remain. Create/edit/pin/expire/export/delete scoped notes and forget a scope. Exercise keyboard and mobile controls and the focused `npm run test:e2e:files` procedure in README against a disposable-data server.

Next roadmap item after this slice and its desktop acceptance: B12, push-to-talk and optional speech output. Existing B10 real-source/manual-audit acceptance remains outstanding.
