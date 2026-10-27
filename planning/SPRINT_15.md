# Sprint 15 — built-in deterministic contact ranker

Date: 20 October 2026, Asia/Karachi. Second B17 slice, after Sprint 14. The user asked to start the next sprint; the recommended scope was used: **B17 with a deterministic ranker on contact attribution**, no model, no new dependencies, stacked on the unmerged Sprint 14 branch.

## Outcome and acceptance plan

Close Sprint 14's provenance gap by giving the evaluator one candidate it actually executes. A bundled deterministic contact ranker runs locally on a frozen evaluation dataset and reads only reviewed input text and the source domain group. Its outputs go through the existing exact-text comparison against human-reviewed labels.

- The candidate must not read observed or expected outputs, reviewer names or reasons. Inputs are projected before execution, and a test shows that changing labels does not change decisions.
- Record a verifiable artifact hash (ranker source plus configuration), decision counts, inference time and peak memory alongside the existing hardware, date, configuration, sample count and evaluator hash.
- Keep Sprint 14's guarantees: hash-bound datasets, evaluation purpose only, idempotent replay, conflict on changed inputs, invalidation, deletion tombstones and no copied output bodies.
- Make no promotion or held-out improvement claim. Fictional fixtures cannot establish real contact quality.

## Delivered

- `backend/evaluation/contact_ranker.py`: `contact_ranker_v1`. Finds emails and phones in reviewed input text line by line, using the existing extractor's patterns. Scores each one on the text since the previous value on its line: third-party context −4, same-domain email +2, free mail 0, foreign-domain email −1, owner cue +1. It selects the unique top contact with a score of at least 1. Otherwise it abstains with `abstained_no_contact`, `abstained_low_score` or `abstained_tie`. `factual_support` examples are `not_applicable_task` abstentions. Weights were fixed on fictional fixtures before any real data and are not probabilities. Instruction-like text is inert data.
- `backend/storage/experiments.py`: shared `_receipt` / `_examples` / `_store` helpers, so imported and built-in runs use the same validation, limits and storage. `run_builtin` loads the frozen examples in the same `BEGIN IMMEDIATE` transaction, projects them to `id/task/input_text/domain_group`, and times inference with `perf_counter` and `tracemalloc`. The run is stored as `Built-in contact ranker v1` with `candidate_provenance: builtin_executed_locally`. Imported reports now say `imported_unverified` explicitly. Only the predictions' hash is stored. No migration: migration 011's table holds both kinds of report.
- `backend/domain/experiments.py`, `backend/api/experiments.py`: `BuiltinRunInput` accepts only `candidate: "contact_ranker_v1"`, an exact dataset hash and an optional `abstention_output` (1–1,000 characters; null keeps abstentions as incorrect). Extra fields are refused. The route is `POST /v1/experiments/builtin`, authenticated, with an `Idempotency-Key` and the existing body/origin/host policies.
- `backend/evaluation/experiments.py`: the limitation text distinguishes locally executed from imported candidates. The metric is unchanged (`exact_text_v1`).
- `apps/web/src/EvaluationPanel.jsx`: a **Run built-in contact ranker** form with an optional abstention text and retry-safe idempotency keys. The report shows executed versus asserted artifact, decision counts, and measured inference time and memory.
- `tests/test_contact_ranker.py` (9 cases) and an extended `scripts/evaluation-smoke.mjs`.

## Verification evidence

Host: Intel Core i5-8265U (8 threads), 7 GiB RAM, Linux 6.8.0-136, Python 3.12.3, Node 24.21.0, Google Chrome 151.0.7922.137.

- Full `.venv/bin/python -m unittest discover -s tests -q`: **303 tests pass** (294 prior plus 9 new), no skips, in **104.227 s**.
- Targeted `tests.test_contact_ranker tests.test_experiments`: **27 pass** in **12.733 s** after the final edits. Covered: scoring decisions (owner vs agency, tie, low score, no contact, free mail, phone with and without cue, other task, multiline context, instruction text); local execution provenance, timing, memory and replay; deterministic repeat runs; a paired gain where the observed baseline kept the agency contact; labels never read; the abstention convention and its hash/conflict effects; hash, unknown candidate, extra field, empty abstention, missing dataset and training-dataset refusals; stale-source invalidation with no receipt; authentication. No network fetches occurred.
- Node 24.21.0: **15 voice + 13 screen checks pass**. Vite 8 build: **48 modules**, JS **418.09 kB** (**116.28 kB gzip**), CSS **30.72 kB** (**6.80 kB gzip**).
- `npm run test:e2e:evaluation` against a new disposable data directory in the session scratchpad: **PASS**. Chrome launched on this host, unlike Sprint 14's blocked attempt. The flow covered the Sprint 14 steps (invalid JSON, foreign coverage, lost-response replay, export, refresh retry, invalidation, deletion, mobile overflow, no page errors) plus the built-in ranker run: report heading, `builtin_executed_locally`, decision counts `{abstained_no_contact: 1}` on the fictional text, and the inference-time display. The disposable server was stopped afterwards; the user's real database was not opened.
- `pip check`: no broken requirements. `git diff --check` and Python compilation are clean. No dependency or lockfile changes.

## Not done / remaining acceptance

- **No real reviewed data has been evaluated.** B17's "held-out improvement demonstrated or rejected" is still open. Next user steps:
  1. Review real contact-feedback or audit sources and write the correct contact as the expected output (or one fixed abstention phrase).
  2. Freeze a development evaluation dataset and a separate holdout one; domain/page reservation keeps them apart.
  3. Run the built-in ranker on development only. Fix weights only from development errors, then run the holdout once.
- Inference memory is Python `tracemalloc` peak, not process RSS. Timing covers ranking only, on this host.
- Exact text agreement does not verify contact ownership or reachability.
- Not exercised: keyboard-only use, multiple tabs and navigation during a request. Earlier live gates also remain open: live-source quality, file search, speech/capture, two-PC and email/calendar client. Chrome now launching here may make the other prepared browser flows runnable.
- B18 packaging stays after these gates.
