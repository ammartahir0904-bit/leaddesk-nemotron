# Ordered agile backlog

Effort depends on developer experience, source access and hardware. These are milestones, not promised dates. Keep one vertical slice active; integrate continuously.

| ID | Deliverable | Depends on | Done when |
|---|---|---|---|
| B01 | Repo, settings, backend/frontend health | None | Local run documented, no secret leakage |
| B02 | Schema, migrations, evidence repository | B01 | Records persist and relations validate |
| B03 | URL-to-business/contact extraction | B02 | Evidence visible; mismatch fixtures pass |
| B04 | Feedback report and suppression | B03 | Wrong contact removed and history retained |
| B05 | Hardware profiler and benchmark runner | B01 | Actual measurements and graceful no-GPU path |
| B06 | Model adapter and structured product brief | B02,B05 | Arbitrary offers accepted, assumptions editable |
| B07 | First discovery connector and workflow queue | B03,B06 | Bounded discovery, pause/resume, source gaps visible |
| B08 | Identity resolution and grounded analysis | B07 | Branch conflicts handled, alternatives checked |
| B09 | Lead dashboard and export | B04,B08 | Complete contacts/evidence/analysis view |
| B10 | Quality baseline | B09 | Per-segment report against proposed gates |
| B11 | Approved-folder search and memory | B02,B04 | Rename/delete and wrong-file scenarios pass |
| B12 | Push-to-talk and optional speech output | B05,B11 | Transcript correction and cancellation work |
| B13 | On-demand screen context and local tools | B11,B12 | Ubuntu permissions tested; no silent capture |
| B14 | Learning dashboard and dataset review | B04,B10 | Versioned reviewed data and deletion controls |
| B15 | Optional PC worker | B05,B07 | Authentication, disconnect and resume tested |
| B16 | Email/calendar integration | B09,B10 | Authorised actions idempotent, timezones correct |
| B17 | Candidate ranker/fine-tuning experiment | B14,B15 | Held-out improvement demonstrated or rejected |
| B18 | Packaging and scale review | Earlier release gates | Install/update/backup/restore documented |

## Release sequence
A: accurate research and feedback (B01–B10).
B: practical personal assistant (B11–B13).
C: controlled learning and integrations (B14–B17).
D: broader distribution after operational validation (B18).

## Sprint rhythm
Pick a small measurable user outcome, implement, review errors, update priorities and record decisions. Do not add RL just because it sounds advanced. Select training work from the actual error distribution. If extraction is accurate but source coverage is poor, improve connectors rather than weights.

## Current implementation handoff — 20 October 2026

[Sprint 21](../SPRINT_21.md) adds a deep website read (Contact/About/offer pages, schema.org data, cited need signals relevant to the user's product), an identity cross-check that keeps similarly named businesses apart, a social-only "website" need signal, a fixed research sequence (find online → read website → AI), a second-pass AI verifier that can only lower confidence, and a market-problems view (deterministic counts plus cited AI problem ideas). No training yet.

[Sprint 20](../SPRINT_20.md) adds local Ollama fit analysis (llama3.2:3b in Docker on this laptop, 20–90 s per business on CPU) over numbered evidence, with mandatory citations, one format retry, deterministic grounding and fact checks, and 👍/👎 verdicts as reviewed data. AI output never changes rule points. No training yet.

[Sprint 19](../SPRINT_19.md) adds web enrichment through a user-run local SearXNG: own website, social profiles and contacts found online for each business, each with its source and an own-page/mention confidence label. In a live Lahore run, 10 cafés were enriched in 22 s. Social pages are linked, not scraped.

[Sprint 18](../SPRINT_18.md) adds email/phone contact analysis (DNS MX, international phone format, mobile detection, WhatsApp links) to every found business, a hardware-aware Ollama model advisor (none was installed; this laptop gets llama3.2:3b + nomic-embed-text), and a simpler menu with older tools under More tools. Web and social-media enrichment awaits the user's choice of search provider.

[Sprint 17](../SPRINT_17.md) adds the missing core of the product: **Find clients**. The user's product (text, optionally their website) plus any location and business types gives a saved, ranked list of real businesses from free OpenStreetMap data (Overpass, with a bounded Nominatim fallback when it is busy), each linked to its OpenStreetMap entry, plus a one-click website check through the existing research pipeline. In a live check, "coffee shop websites" + Gulberg, Lahore returned 15 named cafés. Contact coverage in OpenStreetMap is thin; Google Places (paid, the user's own key) and AI need judgement are not added.

[Sprint 16](../SPRINT_16.md) ran all eight prepared browser flows for the first time, now that Chrome launches on this host; all pass after fixing one app defect (a deleted file was reported as a missing/symlinked folder), showing discovery source URLs as visible text and repairing a stale test selector. `scripts/run-browser-flows.sh` repeats the run on disposable instances. Real microphone/screen permission, two-PC, live-source, file-search and email-client acceptance remain open; B17 still needs real reviewed datasets.

[Sprint 15](../SPRINT_15.md) adds the first executed B17 candidate: a bundled deterministic contact ranker (`contact_ranker_v1`) that runs locally on frozen evaluation datasets, reading only reviewed input text and source domain. Reports record a verified source/configuration hash, decision counts, inference time and traced peak memory. Disposable fictional tests and the prepared browser evaluation flow pass on this host. No real reviewed dataset has been evaluated, no independent held-out improvement is demonstrated, and promotion stays disabled. B17 remains open until the user freezes representative real development and untouched holdout evaluation datasets and runs the ranker on them; B18 follows only after that and the earlier live gates.

[Sprint 14](../SPRINT_14.md) implements the user's selected B17 local-evaluation foundation: exact-text comparison of supplied candidate outputs and reviewed observed-output baselines against frozen human-reviewed evaluation labels, paired gains/regressions, task/domain segments, labelled real/synthetic and development/holdout reports, hash-bound replay, guarded JSON export and source-change/deletion invalidation. No ranker/model execution, training, promotion or independent held-out improvement is claimed. Candidate identity/output provenance remains unverified. B17 remains open pending a deliberately scoped actual candidate/ranking experiment and representative independent evaluation; B18 is the next ordered milestone after those gates, not an automatic new active slice. Earlier live acceptance gates remain open.

[Sprint 13](../SPRINT_13.md) implements the user's selected B16 local-file slice: user-authored source-contact email drafts, personal calendar planning in two IANA zones, revision/context-bound file review, guarded `.eml`/`.ics` exports, current suppression/identity checks, optimistic edits and deletion/replay protection. No provider account, SMTP/OAuth, send, invitation, availability or booking is enabled. Client imports/sending, provider reconciliation and opt-out inbox handling remain outside this slice. Browser/client acceptance and all prior live gates remain open. The next ordered item is B17, a bounded candidate-ranker/evaluation experiment using deliberately selected reviewed data; training/provider/model selection and promotion require their own defined scope and evidence.

[Sprint 12](../SPRINT_12.md) adds B15's first optional paired-PC slice: scoped/revocable pairing, explicit synthetic benchmark tasks, persisted fenced leases, heartbeat/expiry recovery, bounded attempts, separately labelled worker reports, an opt-in CLI and a dashboard. The coordinator remains loopback-only; the user must establish private encrypted SSH forwarding. Only the bundled parser benchmark is allowlisted. No remote model/research/file/screen/audio execution or automatic fallback is enabled. Real two-computer authentication/tunnel/disconnect/resume and browser acceptance remain open; B15's full hardware/inference capability is not claimed complete.

[Sprint 11](../SPRINT_11.md) implements B14's reviewed local dataset slice: contact-feedback/latest known quality-unit review, edited/redacted examples, recorded local-use permission, versioned JSON manifests, group-aware development/holdout protection and deletion/invalidation controls. Training/experiments/model promotion are not implemented. Browser acceptance is blocked at Chrome launch; representative real reviewed datasets and source-permission decisions require user review. Automated checks are separate from release acceptance.

[Sprint 10](../SPRINT_10.md) implements the preceding B13 screen-context slice, whose actual Ubuntu/Wayland chooser permissions, denial/cancellation and track release remain unverified. Automatic OCR/vision and native OS/file control are outside that slice. Prior B10 real-source, B11 representative file-search and B12 real microphone/model/browser acceptance also remain open. No remote worker is paired by default.

## Handoff note
Tomorrow's coding session should start with START_HERE.md and B01–B03. Deliver a demonstrable slice before adding more features. No need to settle branding or build a marketing site first.
