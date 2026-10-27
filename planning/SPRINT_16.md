# Sprint 16 — first browser acceptance run

Date: 20 October 2026, Asia/Karachi. Started on request after Sprint 15. B17 cannot move without the user's real reviewed datasets, and B18 is gated, so this sprint closes the open gate that can be closed on this host. Chrome now launches here, so every prepared browser flow was run for the first time.

## Outcome and acceptance plan

Run all eight prepared Playwright flows, each against its own fresh, empty, disposable instance. Fix real defects with regression tests, fix stale test selectors without weakening their assertions, and record actual results.

## Findings and fixes

1. **App defect: deleted files reported as a folder problem.** `approved_directory()` in `backend/adapters/local_files.py` wrapped its `yield` in `except OSError`. Any error in the caller's body was rewritten as "The approved folder is unavailable or contains a symlink", including opening a file that had been deleted after indexing. The status (409) was right but the message was wrong, which pointed the user at the wrong fix. The catch now covers only opening and checking the folder. `tests/test_files_memory.py` now asserts the messages for both changed and deleted files; the deleted-file assertion fails before the fix and passes after.
2. **Evidence visibility: queue discovery evidence hid the source address.** "Discovery source evidence" showed the page only as a "Source page ↗" link. It now shows `Source page: <url> ↗` (`apps/web/src/QueuePanel.jsx`), as the main flow expected.
3. **Test drift: ambiguous selector.** `getByLabel('Notes')` in `scripts/browser-smoke.mjs` also matched the later "Identity review notes" field. It now targets the correction notes field exactly.
4. **New `scripts/run-browser-flows.sh`.** Refuses to run if port 8765 is in use. Starts a fresh `.local/browser-flow-*` instance per flow, runs it, stops the process group and deletes the data of passing flows. Failing flows keep their logs.

## Verification evidence

Host: Intel Core i5-8265U (8 threads), 7 GiB RAM, Linux 6.8.0-136, Python 3.12.3, Node 24.21.0, Google Chrome 151.0.7922.137 (headless). All data was fictional and disposable; the user's database was not opened.

| Flow | Result | Time (s) |
|---|---|---|
| main (`test:e2e`) | PASS after fixes 2 and 3 | 17.4 |
| learning | PASS | 4.0 |
| files | PASS after fix 1 | 5.9 |
| voice | PASS (generated audio, mocked speech) | 4.9 |
| screen | PASS (generated canvas stream) | 3.7 |
| workers | PASS (simulated worker, no SSH) | 3.3 |
| correspondence | PASS | 3.3 |
| evaluation | PASS | 2.8 |

- Full `.venv/bin/python -m unittest discover -s tests -q`: **303 tests pass** in 91.271 s. `tests.test_files_memory`: 22 pass; the strengthened case failed before the adapter fix.
- Vite build passes. The runner script itself was checked with the learning and evaluation flows: both passed and the port was released.

## What this does and does not establish

These flows prove the browser UI works end to end in headless Chrome on fictional data. They do **not** establish:
- a real microphone or speech model, or real Wayland screen-chooser permissions;
- a real two-PC SSH pairing;
- real-source lead quality or representative file search;
- an email/calendar client import;
- keyboard-only or assistive-technology use.

Those gates remain open. B17 still needs the user's real development and holdout evaluation datasets (see Sprint 15). B18 packaging follows those gates.
