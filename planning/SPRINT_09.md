# Sprint 9 — reviewed local voice commands

Date: 20 October 2026, Asia/Karachi. B12's bounded push-to-talk interface, optional whisper.cpp adapter, transcript review/correction, deterministic local tools and optional local speech output. Code/fixture verification is separate from real microphone, model and desktop acceptance.

## User outcome

Open Voice, dictate a short command with an explicitly configured local model or use typed input, correct the transcript, review the exact local action and scope, then apply a file search, active-memory search or user-authored note save. Cancel capture/transcription before acting. No speech runtime was found on PATH and none was installed/downloaded; default microphone input remains unavailable until local setup, while typed commands work.

## Delivered

- **Push-to-talk capture:** same-origin AudioWorklet, pointer/Space/Enter hold-and-release plus a short-recording toggle, visible permission/recording/transcribing indicators, mono PCM WAV encoding at 16 kHz and a 30-second frame/time cap. Safe cleanup on release, cancel, microphone disconnect, panel/window/tab changes and unmount. A late permission response or stale permission failure cannot start/stop a newer recording. No browser SpeechRecognition/cloud dictation is used.
- **Local ASR adapter:** explicit absolute CLI/model paths and SHA-256 through settings; no automatic discovery/download/service fallback. Models bounded to 512 MiB; digest/metadata verification before inference, 3 GiB effective available-memory guard, two CPU threads, one process, GPU disabled, 90-second subprocess budget, 15-second between-chunk hash budget and process-group termination on cancel/timeout. Stdin/stdout/stderr are discarded; argv is typed and there is no shell or inherited credential/proxy environment. Temporary private WAV/transcript files are cleaned on normal exit/failure/cancellation. Model metadata drift during inference discards output.
- **Ephemeral sessions:** streamed 1 MB audio route, complete mono 16-bit/16 kHz/0.2–30 second WAV validation, near-silence abstention, client UUID replay/conflict checks, bounded session count, status polling, cancellation tombstones that beat late uploads and suppression of late results. Research/benchmarks/queue pages and ASR share one execution lane. No voice table or migration. Sessions are unavailable after five minutes from completion/cancellation and pruned on the next voice operation; restart loses them. Client requests/polling have a separate two-minute deadline.
- **Reviewed typed commands:** `find files <keywords>`, `search memory <keywords>` and `remember <note>`, with explicit selected approved folder/exact memory scope. English prefixes only; Unicode query/note content is retained. Preparing only describes a typed operation/risk. UI edits invalidate it, and server execution recomputes and compares its hash. Reads reuse current-file and expiry policies; writes use existing idempotent user-authored memory creation. No outbound message, arbitrary command, native file action or screen-capture tool is enabled.
- **Optional local output:** default off, explicit enable/voice/Read aloud controls, only browser voices flagged local, recheck at playback, stop on cancellation/navigation/window changes and no remote fallback. Missing browser audio/output support leaves text usable.
- **Interface and acceptance tools:** Voice navigation, transcript editor, scoped plan/results/file preview, cancellation/error/typed fallback, codec/controller/worklet tests and a focused browser script using generated audio and synthetic ASR/TTS. Original research, files, notes and quality workflows are preserved. No dependency was added or downloaded.

## Modules

| Module | Responsibility |
|---|---|
| `backend/domain/voice.py` | Audio bounds, configuration and deterministic action plans |
| `backend/adapters/speech.py` | Explicit offline CLI, model verification and process cleanup |
| `backend/workflows/voice.py` | Ephemeral sessions, execution lane, replay/expiry/cancel |
| `backend/api/voice.py`, `backend/settings.py` | Authenticated routes and optional runtime configuration |
| `apps/web/public/voice-worklet.js` | Bounded mono capture processor |
| `apps/web/src/voice-audio.js`, `voice-session.js` | Codec, capture/speech policy and cancellation controller |
| `apps/web/src/VoicePanel.jsx`, `VoicePanel.css` | Transcript review, plans/results and optional speech UI |
| `tests/test_voice.py`, `tests/voice-audio.test.mjs` | Synthetic API/child-process/media/controller regressions |
| `scripts/voice-smoke.mjs` | Fictional desktop browser acceptance without physical devices |

## Verification

- Target `.venv/bin/python -m unittest discover -s tests -q`: **198 tests pass**, no skips, in 34.971 seconds (177 prior checks plus 21 new voice cases).
- New Python cases cover upload/poll/replay and changed-input conflicts, no audio database storage, early-cancel tombstones, in-flight/late-result cancellation, shared-lane release, expiry and text deletion, near-silence abstention, private diagnostic suppression, unavailable runtime and busy lanes, authentication/origin/content-type/UUID/language/PCM/input bounds, streamed/chunked upload limits, review-before-save, stale transcript/scope plans, idempotent corrected notes, scoped/expired memory search, current-file/revocation checks, unsupported commands, session quotas, invalid adapter results and normal/failing voice shutdown with existing worker cleanup. Generated local executable tests exercise actual child-process cancellation/timeout, CPU argv, minimal environment, digest drift, low-memory refusal, invalid/oversized output and temporary-directory deletion.
- Node 24 `npm run test:voice`: **15 tests pass**, no skips. Covers PCM downsampling/clamping/limits, late/denied permission, stale failures, track/context cleanup, actual worklet frame cap/flush, review without auto-execution, early/upload/poll cancellation, late response rejection, failures/silence, disposal/abortable polling and remote-output exclusion/revalidation. Uses in-process Node test isolation for the managed sandbox; media devices, ASR and speakers are fixtures.
- Frontend build passes with Node 24.21.0 / Vite 8.3.1: 38 modules, JavaScript 352.86 kB (101.02 kB gzip), CSS 26.31 kB (6.15 kB gzip). The built public worklet exactly matches its source. This establishes compilation and asset copying, not browser rendering.
- Target `.venv` reports no broken requirements. Python compilation, focused browser-script syntax and `git diff --check` pass. No dependencies, speech runtimes or weights were downloaded.
- `npm run test:e2e:voice` was attempted and stopped at Chrome launch (`setsockopt: Operation not permitted`, SIGTRAP). No browser assertions, generated-audio flow, screenshots, physical recording or speech output ran. The script is prepared for a normal desktop against disposable data.

Every recording, executable and model used in automated tests is a generated fixture; the executable writes authored text and is not a speech recognizer. No actual model accuracy or language performance follows from these tests. Existing browser/live-source and real-dataset acceptance remains unverified.

## Desktop setup and remaining acceptance

See README's Voice section for the three `LEADDESK_WHISPER_*` variables and the focused Node/browser commands. Configure a compatible installed CLI and a deliberately selected model, run `./launch.sh` in a normal desktop terminal, unlock Voice and exercise permission denial, hold/release, the recording toggle, transcript edits, late cancellation, tab/panel/window changes, supported/unsupported commands, explicit note scope/save/replay and local output stop. Run the fictional browser check only against a disposable-data server; then test actual user-approved recordings separately.

Real speech recognition is not configured or executed here. Physical microphone permissions, AudioWorklet/browser behavior, installed voice output, English/Urdu/Roman Urdu/code-switching accuracy, latency and RAM/CPU/model-fit measurements remain unverified. No model/voice quality or release-readiness claim is made. Parser prefixes are English; users can correct the transcript or type the supported form. There is no wake word, global shortcut, always-listening service, arbitrary natural-language action planner, speech-driven outreach or OS/screen control.

Cancellation stops pending capture/transcription and discards its text; it does not undo a reviewed note already committed, including when an in-flight save's response is lost during navigation. Delete that note in Files and memory. Raw audio is not durable application data, but private temporary files can survive abrupt OS/process termination; no crash-time or forensic erasure guarantee is made. Browser-held copies and explicitly saved notes have separate lifetimes. Session expiry is enforced at retrieval and pruned lazily.

Next roadmap item after this slice and its desktop acceptance: B13, on-demand screen context and local tools. Prior browser, B10 real-source and B11 representative file-search acceptance remain outstanding.
