# Sprint 3 — editable product briefs and frozen research context

Date: 19 October 2026, Asia/Karachi. B06's offer-planning slice and optional local drafting bridge are implemented. Desktop interaction and real-model acceptance remain unverified. Discovery, need analysis and outreach are later backlog items.

## User outcome

Create a brief for any offer and target geography; add the problem, capabilities, service geography, exclusions and price; inspect/edit buyer hypotheses and verification checks; then select the saved brief for a supplied website or the fictional demo.

Brief hypotheses remain planning assumptions. Keeping one does not establish need, identity, ownership, interest or budget. Your offer price is kept separate from a prospect's unknown budget. Missing optional inputs are null with reasons. No model, external account or paid service is needed for the default workflow.

## Delivered behavior

- Separate Product briefs panel, shared offer fields, editable hypotheses/checks, review states, saved briefs and revision history. Switching panels preserves the editor state; research selection is disabled while edits are unsaved.
- Rules-based draft using runtime inputs without sector-specific branches, guessed buyer identities or network calls. Arabic-script/Urdu and unrelated industries are covered by input-preservation tests.
- Append-only brief revisions and atomic version checks. A conflicting save returns 409 instead of overwriting another tab. Changing offer inputs resets kept hypotheses to unreviewed; older reviews remain unchanged in history.
- Create/edit idempotency with exact revision replay. Retrying an old request does not return a newer document or create another revision. Conflicting key reuse returns 409.
- Research captures the selected brief before fetching and freezes the entire saved revision. Later edits, including an edit during extraction, cannot rewrite that research context. A stale selection is rejected before source access. Database triggers protect revision rows and populated research snapshots from updates.
- Existing manual offer/location research remains supported; ambiguous mixtures of manual fields and brief references are rejected. Legacy/manual records expose `product_brief: null`.
- Synthetic demo optionally accepts a brief reference, retains its fictional labels and makes no business network request. This gives the brief/research workflow a usable offline example.
- Optional CLI accepts a JSON offer and can save a rules draft. Explicit model name/digest enables the existing local-only CPU adapter with a 512-token output limit. A typed bridge accepts only hypotheses/checks; it cannot replace user inputs or add prospect fact fields. Invalid output saves nothing. Model suggestions start unreviewed.
- Migration 003 adds brief/revision/request tables and a nullable snapshot column. Upgrade checks preserve prior research, evidence, corrections and benchmark artefacts. No new dependencies.

## Implementation boundaries

- `backend/domain/briefs.py`: typed offer/edit/generation schemas, rules drafts, unknowns and review invalidation.
- `backend/adapters/briefs.py`: optional structured model-drafting bridge.
- `backend/storage/briefs.py`: atomic revisions, history and idempotency.
- `backend/api/app.py`: authenticated brief routes and research selection policy.
- `backend/storage/repository.py`: explicit legacy-compatible campaign inserts and frozen snapshot storage/serialization.
- `apps/web/src/ProductBriefPanel.jsx` and its stylesheet: offer editor and review workflow.
- `scripts/draft_brief.py`, `planning/examples/offer.json`: bounded CLI and generic input example.
- `tests/support.py`: shared in-process API setup, avoiding duplicate fixture/test execution.

## Executed verification

- Target checkout `.venv/bin/python -m unittest discover -s tests -q`: **64 tests pass**, no skips, including the existing 47 checks. New cases cover arbitrary/Urdu inputs, input and review validation, auth/origin/body limits, exact replay after later revisions, conflicting edits, kept-review invalidation, missing values, legacy compatibility, migration/restart preservation, immutable revisions/snapshots, selected-brief demo, stale selection before fetching, frozen context during edits and typed model-output rejection.
- Frontend production build: **passes**, Node 24.21.0 / Vite 8.3.1, 19 modules. JavaScript approximately 255.45 kB (77.97 kB gzip); CSS 16.30 kB (4.35 kB gzip). Tests run after the build so asset-serving checks use completed artifacts.
- `.venv/bin/python -m pip check`: no broken requirements.
- Python compilation, browser-script syntax and `git diff --check`: pass.
- `scripts/draft_brief.py planning/examples/offer.json --save` executed against `.local/sprint-03-validation`, a disposable directory. Reopening the saved revision matched the printed JSON; generator metadata confirmed rules/no model.
- Model-drafting tests use injected synthetic output. They establish schema/preservation behavior, not real-model quality or instruction-following performance.

## Acceptance limits

The extended browser smoke script was attempted. Chrome failed at launch with `setsockopt: Operation not permitted` / SIGTRAP before browser assertions ran. It now contains brief create/edit/use, dirty-selection protection, frozen research context, plus the existing hardware/benchmark/research/correction/mobile checks. No browser success or screenshots are claimed here. The session's previously established socket restrictions also prevent live server acceptance.

No real model was selected, downloaded or run. No model recommendation is made. The model bridge uses the existing loopback, CPU, memory and digest restrictions; real model/runtime compatibility and output quality require explicit selection and evaluation outside this sandbox. The web routes always use rules and have no model inference endpoint.

Exclusions, hypotheses and verification checks are planning context. They do not automatically filter sources, establish product fit or mark checks complete. Research still inspects one supplied HTML page. Discovery connectors, a persistent job queue, pause/resume, budgeted multi-page research, identity analysis, outreach and retention/deletion/backup controls remain later work.

## Try it on the desktop

```bash
cd /home/ammar/Downloads/LeadDesk_Blueprint
./launch.sh
```

Unlock, open **Product briefs**, create a draft, edit/review a hypothesis and save. Select **Use this brief for research**, then try **Explore synthetic demo**. Expand the saved brief in the research context. Edit the brief again and confirm the existing research still displays its earlier revision. Use the disposable browser-test procedure in the root README for automated desktop acceptance.

Next: B07, a bounded discovery connector and persistent workflow queue with pause/resume and explicit source coverage gaps. No discovery source or account integration has been enabled by Sprint 3.
