# Start building tomorrow

Target start date: 19 October 2026, Pakistan time. Work in small complete slices. Do not attempt all features on day one.

## First session: collect facts and initialise
- Record Ubuntu version, CPU, available RAM, free disk, session type (Wayland/X11), and GPU/VRAM on the actual user machine.
- Useful read-only commands: `lscpu`, `free -h`, `df -h`, `echo "$XDG_SESSION_TYPE"`, and `lspci`. If installed and appropriate for NVIDIA, `nvidia-smi` provides GPU information. Missing commands are not evidence of missing hardware.
- Create a Git repository for the implementation. Copy this blueprint into `planning/`; put AGENTS.md at repository root.
- Select a supported Python and Node release from official docs at build time, pin dependencies, and commit lockfiles. Do not blindly install unpinned latest dependencies.
- Create a Python backend, a React/Vite frontend, and SQLite migrations. No Docker, Redis, vector server, Kubernetes or multi-agent framework is required for the initial version.

## First working slice
Build this path before using an LLM:
1. Paste a business website URL plus a product description and location.
2. Fetch bounded public HTTP content and extract visible business/contact text.
3. Save source URL, retrieval time, content hash, and supporting excerpt.
4. Show business identity, contacts, evidence, and unknown fields.
5. Let the user report a wrong contact and record the correction.

This proves extraction and provenance, not autonomous worldwide discovery. Synthetic fixture data must be visibly labelled; never present it as real leads.

## Next slice
Add a locally benchmarked model to generate a product research brief and grounded need analysis. Then add one usable discovery connector with permitted access. Include manually supplied URLs as a fallback, not as the final discovery capability.

## First session acceptance checklist
- [ ] Backend health and frontend work locally.
- [ ] SQLite migration creates evidence, business, contact, and feedback records.
- [ ] Fixture contact extraction works without an LLM.
- [ ] Each contact opens its exact evidence excerpt.
- [ ] Wrong contact feedback removes it from the approved queue.
- [ ] Network failure displays a retriable error, not fabricated output.
- [ ] README contains actual installation and run commands for implemented code.

## Suggested first coding instruction
Read planning/README.md, planning/docs/02_ARCHITECTURE.md, planning/docs/07_DATA_API.md, and root AGENTS.md. Implement only backlog B01–B03. Use a modular monolith, SQLite and explicit tool functions. Include meaningful fixture tests for incorrect business/contact attribution. Report what works, what remains, and measured memory usage. Do not implement outbound messages or model training in this slice.

## Definition of a completed task
A working behaviour, necessary regression checks, evidence of verification, updated documentation, and a small Git commit. A mocked screenshot or a promising explanation alone is not completion.
