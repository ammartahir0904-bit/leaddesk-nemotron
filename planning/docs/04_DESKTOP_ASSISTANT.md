# Voice, desktop, files and memory

## Interaction
Push-to-talk is the default. Show microphone/capture indicators. Transcribe locally, display the recognised instruction, classify action risk and execute an allowed tool. Let the user correct the transcript. Urdu, Roman Urdu and English code-switching must be evaluated on actual recordings; do not assume equal recognition accuracy.

Commands include: 'find my clinic test-case document', 'look at this window and explain the error', 'remember that this folder contains my client proposals', 'save this note in my project folder', and 'show the file location'.

## File search
Index approved roots only. Start with filenames, modification dates and full-text extraction; add local embeddings for semantic retrieval. Store path, file identity where available, content hash, extraction status and access scope. Use incremental rescans/file watchers with a periodic reconciliation pass. Handle renamed/moved/deleted files and duplicate contents.

Search exact/keyword matches plus optional semantic candidates; rerank a small set. Show three plausible matches with filename, excerpt, folder and date. Actions: Open, Reveal location, Correct file, Wrong file. Abstain when no useful match exists. 'Memory' cannot recover unavailable file bytes.

Supported first: text and text-bearing PDFs/documents with safe parsers. Scanned documents need optional OCR. Password-protected, unsupported or unreadable files get a visible status. Sandbox parsing and bound file sizes/pages.

## Screen context
On-demand selected window/screen capture first. Extract accessible text or OCR before invoking vision. Keep screenshot bytes in temporary memory/files only for the task, then delete them. Ask explicitly before saving a screenshot as a durable artefact. Source application, timestamp and selected region accompany extracted context.

Ubuntu Wayland often requires portal/user-mediated capture and restricts global input. Prototype the actual session's permissions; do not promise cross-desktop control or silent capture. Unsupported operations should degrade to a user-assisted action. X11 support is a separate tested adapter, not a reason to weaken the user's session.

## Safe local actions
Typed tools: search_files, preview_file, open_file, reveal_path, create_note, remember_fact, capture_window. Canonicalise paths, enforce approved roots after resolving symlinks, prevent path traversal, and block overwrites unless authorised. Writes use temporary file + atomic replace where possible; keep undo history for supported operations.

Never turn free-form model text directly into a shell command. Complex actions are plans of explicit tools. A desktop 'stop' action cancels queued work and asks running tools to stop safely.

## Memory records
Types: user preference, file alias, project context, approved product facts, correction. Fields: content, scope, source, created_at, updated_at, expiry, confidence, sensitivity and supersedes_id. User-authored corrections outrank inferred memories in the same scope. Do not let one project's preference silently affect all projects.

Memory panel supports inspect/edit/delete/export, pinning, expiry and 'forget this project'. Removing a file from scope removes its indexed text and embeddings. Deleted memories also leave future training datasets; already trained weights cannot guarantee exact unlearning, so sensitive memories are excluded from training by default.

## Acceptance scenarios
Moved file is found after reconciliation; deleted file is not presented as openable; ambiguous name shows choices; wrong speech transcript is correctable; capture denied does not crash; deleted memory is no longer retrieved; save action cannot escape the allowed folder.
