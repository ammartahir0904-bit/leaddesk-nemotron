# LeadDesk

**Find the businesses that need what you sell — with evidence, checked contacts and a pitch you can send.**
Built for the **Nebius × NVIDIA Global AI Hackathon** (Best Apps and Agents track). Licence: [MIT](LICENSE).

## The problem
Small agencies and freelancers (web designers, booking-software sellers, marketers) spend hours finding prospects on maps,
guessing whether a business needs them, and copying contacts that turn out to be fake, temporary or someone else's.
Generic AI lead tools make it worse: they invent "pain points" and confident messages that are not true for the business.

## What LeadDesk does
1. **Find** businesses of any type anywhere (OpenStreetMap + Overture Maps, 574 business types in 22 languages).
2. **Read** each business's website properly — up to 6 pages, JavaScript sites in a local Chrome, layout measured on a phone
   view — and find its contacts and Facebook/Instagram pages on the web (local SearXNG or **Tavily**).
3. **Review every contact** before you see it: approved / needs review / rejected with reasons (temporary-email domains,
   placeholders, fake numbers, domains that take no email, a number shared by many unrelated businesses).
4. **Compare** what you sell with what the business has (Has / Missing / Not seen, each with the page text as evidence),
   and write a pitch from those facts. Every sentence cites its evidence.
5. **NVIDIA Nemotron on Nebius Token Factory** rewrites the message so it reads naturally — and LeadDesk checks every word:
   a rewording that adds a fact, number, promise or "as we discussed" is rejected and LeadDesk keeps its own wording.
6. **Your corrections change results**: mark a contact wrong, correct a feature, edit a message; it applies at once and in
   future searches. Repeated corrections become rules you approve. A quality report shows what is improving.

## How NVIDIA Nemotron and Nebius Token Factory are used
- `backend/adapters/token_factory.py` calls Token Factory's OpenAI-compatible API (`https://api.tokenfactory.nebius.com/v1`)
  with JSON-mode answers, and lists only NVIDIA open models (Nemotron) for the user to choose.
- **Where Nemotron works:** rewording each pitch (`offer_fit.polish_prompt`), the "reword top 5" batch, and the market
  problems summary across a search — all through one service (`backend/workflows/ai_service.py`).
- **Guarded, not trusted:** the model only sees the facts LeadDesk collected; its answer is checked against them
  (`offer_fit.check_polish`) and refused if it adds anything. Nemotron's job is to write well *within* the facts; the
  quality report counts how often its wording was accepted and approved.
- **Opt-in:** nothing is sent until you pick a Token Factory model and tick the consent box; the key is only read from the
  `NEBIUS_API_KEY` environment variable. A local Ollama model remains available for fully offline use.
- **Tavily** (`backend/adapters/tavily.py`) is an opt-in search provider for "Find online": free search engines block
  automated searches, and Tavily gives reliable results with domain filters for Facebook and Instagram.

## Try it (test build: the demo in 2 commands)
Needs only [Docker](https://docs.docker.com/get-docker/). From the repository folder:
```
docker build -t leaddesk-demo .
docker run --rm -p 8765:8765 leaddesk-demo
```
Open **http://127.0.0.1:8765**. The demo key is already filled in: click **Unlock workspace**, then go to
**Find clients → Saved searches → Camden Town** and open any café.

- All data in the demo is **fictional**: nine invented cafés in Camden, London, with reserved `.example` web addresses and
  phone numbers reserved for drama. Searching the map and the web and reading real websites are switched off in the demo.
- **To see NVIDIA Nemotron on Nebius Token Factory** rewording a pitch, add your key and choose an NVIDIA model:
  ```
  docker run --rm -p 8765:8765 -e NEBIUS_API_KEY=<your Token Factory key> leaddesk-demo
  ```
  then **AI models and hardware → NVIDIA Nemotron on Nebius Token Factory → Use this model**, and on a café click
  **Reword with AI**.
- Things to try: the **Rejected contacts** box (temporary email, placeholder number, a number shared by three cafés),
  **What you offer vs. what they have**, correcting a feature ("Actually they have it") and watching the pitch change,
  and **Quality report and learned rules**.

**Run the full app on your own computer** (real searches): `./scripts/setup.sh` (Python 3.12, Node 24),
`cp .env.example .env` and add your keys (optional), then `./launch.sh` and paste the printed access key.

## Architecture
FastAPI modular monolith + SQLite (local, migrations) + React (Vite). Deterministic parsing and checks first; models only
where language is needed, always behind evidence checks. Details: [planning/SPRINT_23.md](planning/SPRINT_23.md),
[planning/SPRINT_24.md](planning/SPRINT_24.md).


A local research workspace for source-backed business contact records. It includes supplied-website research, hardware benchmarks, editable product briefs, a persistent bounded discovery/research queue, manual identity/need reviews with citations, a prospect dashboard with JSON/CSV downloads, frozen quality samples with manual audits and per-segment reports, approved-folder keyword search, scoped user-authored memory, a reviewed voice/typed-command panel with an optional local speech adapter, on-demand screen previews with user-assisted context and reviewed local actions, a learning dashboard for reviewed local dataset versions, optional paired PC workers for synthetic benchmarks, and reviewed local email/calendar files. The original specification is preserved in [planning/README.md](planning/README.md).

You can enter a public website, any product description and target location; inspect candidate contacts and their source excerpts; save research; and report wrong contacts. Corrections suppress the same contact on the same source host in existing and future research. Suggested replacement values remain unverified feedback, never automatic facts.

Business identity, branch and location can receive a manual source review; contact attribution is reviewed separately. Need and fit judgements stay labelled as inferences. Independent corroboration, reachability, intent and budget remain unconfirmed. Synthetic demos are fictional and visibly labelled. Live speech recognition needs an explicitly configured local runtime/model and desktop acceptance; screen capture needs browser/Ubuntu permission acceptance. Model-assisted lead analysis, search-engine discovery, automatic screen OCR/vision, outreach and training are future work.

## Start on this laptop

The project environment and frontend build have been prepared in this checkout:

```bash
cd /home/ammar/Downloads/LeadDesk_Blueprint
./launch.sh
```

Open **http://127.0.0.1:8765**. Paste the local access key printed in your terminal. Keep the terminal open; Ctrl+C stops the server. Try **Explore synthetic demo** first, then supply a real public website. You may need to enter the final HTTPS address directly if a site redirects to another host.

## Install from a fresh checkout

Use Ubuntu/Python 3.12 and Node 24 (the tested Node version is pinned in `.nvmrc`). If you use nvm, run `nvm install` then `nvm use` from the repository root. Use your normal user terminal for package downloads.

```bash
./scripts/setup.sh
./launch.sh
```

Setup creates this repository's `.venv`, installs the exact dependencies in `requirements.lock`, runs `npm ci` using the frontend lockfile, and builds the React/Vite app. The backend serves the built frontend, so only one server is needed. No Docker or model downloads.

## Verify

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
(cd apps/web && npm run build)
.venv/bin/python scripts/benchmark.py
```

These use synthetic fixtures and an injected transport. They do not prove live website contact accuracy. The parser benchmark reports its hardware/configuration, fixture hash, sample count and process memory separately from server/browser costs.

To run the browser smoke check in a normal desktop terminal, start a separate test instance on port 8765 with an empty disposable data directory. Stop any normal instance first:

```bash
LEADDESK_DATA_DIR="$PWD/.local/browser-check" ./launch.sh
# In a second terminal, from the same repository root:
cd apps/web
LEADDESK_TEST_TOKEN_FILE=../../.local/browser-check/access-token npm run test:e2e
```

The browser check requires Google Chrome (`CHROME_PATH` can select another compatible binary). It covers hardware/benchmarks/export/retry, brief revisions/frozen context, synthetic extraction, cited identity/analysis, invalid quotes, stale analysis after correction, prospect filters/JSON/CSV/retry, quality sample/audit/citation/history/export/draft/retry flows, persistence, queue controls/discovery, rejected local URLs, mobile overflow and browser errors. It modifies only the disposable instance's synthetic data; use an empty test directory for each run. Screenshots go to ignored `apps/web/test-results/`. The managed sandbox cannot launch Chrome; run browser acceptance from a normal desktop terminal.

## Local candidate evaluation

In **Learning and datasets**, freeze or inspect a ready **evaluation** dataset in the selected real/synthetic source mode. In **Local candidate evaluation**, enter a candidate name and the SHA-256 of your deliberately chosen offline artifact, then paste one JSON output for every frozen example:

```json
[{"example_id":"ID from the dataset manifest","output":"supplied candidate text"}]
```

**Prepare abstention template** fills the example IDs with null outputs, without copying expected labels. Replace them with your supplied outputs; explicit null is an abstention counted as incorrect. **Compare candidate outputs** compares both the dataset's reviewed observed-output baseline and your candidate outputs with the human-reviewed expected text. Equality is exact, including case, Unicode and whitespace; this is descriptive text agreement, not semantic accuracy, contact verification or a ranking metric. The reviewed baseline is not a freshly executed production model.

Reports show sample counts, exact-match rates, paired gains/regressions, abstentions and task/domain segments, plus dataset/artifact/prediction/evaluator hashes, split, date, fixed metric configuration, evaluation-host hardware and comparison time. Candidate identity and outputs are user assertions; the artifact is not loaded or verified. Model identity, inference time and candidate memory remain unknown. Development results are for tuning; holdout labels may have been inspected and repeated comparisons cannot establish independent held-out improvement. The prior-report count includes retained reports only, excluding deleted ones. A sample improvement is not a release gate, significance test or promotion approval. No imported candidate, model, training, cloud or remote worker executes through this panel; only the bundled deterministic ranker below runs, and only when you choose it.

**Inspect evaluation report** rechecks current source reviews and permissions. Changed/excluded/deleted examples, superseded feedback, changed audits and later holdout reservations invalidate affected reports and clear metrics. Dataset deletion cascades to reports. **Export evaluation report** checks freshness again and downloads JSON; report storage contains aggregate metrics/hashes rather than copied example or candidate-output bodies. **Delete evaluation report** preserves datasets and original research/corrections. Hash-only receipts prevent old requests resurrecting deleted reports; downloaded copies and backups need separate management. Unsaved candidate inputs are temporary.

Limits: 100 examples per comparison, 1,000 characters per supplied output, the existing **16,000-byte total JSON request** cap, 200 retained reports, 2,000 lifetime write receipts, and 20 reports per page. For larger text, deliberately freeze a smaller dataset; incomplete prediction coverage is refused. Training-purpose datasets are refused as test sets. No actual user data is selected or evaluated by automated verification.

Authenticated APIs: `GET/POST /v1/experiments`, `GET/DELETE /v1/experiments/{id}`, and `GET /v1/experiments/{id}/export`. Create requires `Idempotency-Key` and the exact frozen `dataset_sha256`; prediction IDs must match the entire dataset. Canonical prediction ordering permits reordered retries; changed payloads under the same key conflict. Existing owner authentication, origin/host checks and no-store responses apply. Additive migration 011 preserves previous tables and installs dataset-invalidation propagation.

Verify with `.venv/bin/python -m unittest tests.test_experiments -q`. The prepared disposable-data browser workflow is `npm run test:e2e:evaluation` from `apps/web` under Node 24, using the separate empty browser-check instance described above. It covers errors/retry, comparison/export, invalidation/deletion and mobile overflow. See [Sprint 14](planning/SPRINT_14.md) for actual execution evidence and remaining acceptance. This is B17's evaluation foundation; a trained candidate ranker and demonstrated independent held-out improvement remain future work.

## Find clients (Sprint 17)

After unlocking, LeadDesk opens on **Find clients**:

1. Describe what you sell, optionally with your website, then click **Read my product**. You get product words and suggested buyer types.
2. Enter any city or area, choose up to 8 business types (or a name keyword) and a maximum. Tick the consent box, because the search sends your location text and business types to public OpenStreetMap servers. Then click **Find businesses**.

Each business shows its name, address, phone, email, website, transparent priority points, need signals (for example, "no website listed" for website offers) and a link to its OpenStreetMap entry. **Check website** runs normal website research on its site and links the evidence back. You can download results as CSV, and searches are saved.

It's free and needs no account or key. The main Overpass server is tried first; when it is busy, a bounded Nominatim search is used. OpenStreetMap is volunteer data, so many businesses or contact details may be missing. Budget is never guessed. Verify with `.venv/bin/python -m unittest tests.test_prospecting -q`. See [Sprint 17](planning/SPRINT_17.md) for measured results and limits.

### Contact analysis and AI model advisor (Sprint 18)

Every business found shows **Contact analysis**:
- **Email:** generic or named mailbox, free mail or own domain, whether it matches their website, and whether the domain has mail servers (DNS MX).
- **Phone:** international format, mobile or landline where known, and a WhatsApp link for mobiles.

**AI models and hardware → Check this computer** recommends local Ollama models for the machine LeadDesk runs on, with install commands. Nothing is installed automatically. Rarely used screens are under **More tools** in the sidebar. See [Sprint 18](planning/SPRINT_18.md).

### Find businesses online (Sprint 19)

Start the free local search engine once (needs Docker, about 384 MB):

```bash
scripts/searxng.sh start
```

In **Find clients** results, use **Find online** on a business or **Find online for top 10**. LeadDesk searches the web for each business's own website, Facebook, Instagram and other profiles, and contact numbers or emails in search results. Every finding links to its source and is marked as from **their own page** or a **lower-confidence mention**. Stop the search engine with `scripts/searxng.sh stop`. See [Sprint 19](planning/SPRINT_19.md).

### AI analysis with a local model (Sprint 20)

```bash
scripts/ollama.sh start
scripts/ollama.sh pull llama3.2:3b
```

Then in **AI models and hardware → Model for AI lead analysis**, choose the model. In Find clients, use **AI analysis** on a business or **AI analyse top 5**. The model reads your product and the saved evidence and returns fit, need, reasons citing evidence (E1, E2…), an opening line and questions. LeadDesk flags unsupported wording, invented earlier contact and website claims that contradict collected facts. Mark answers 👍/👎 to build reviewed data. Everything runs on your computer. See [Sprint 20](planning/SPRINT_20.md).

If **Research top 3** produces no AI answer, check the **AI analysis** status above the results. A running Ollama still needs a model selected with **Use this model**. For this checkout's Docker setup, run `scripts/ollama.sh status` and `scripts/ollama.sh start` if needed; pull a model only if none is installed. After starting services, use **Refresh connections** in Find clients. Research reports unavailable AI and web-search steps explicitly. **Find online** separately needs `scripts/searxng.sh start`; OpenStreetMap business search works without Ollama.

### Deep website read, identity cross-check and research agents (Sprint 21)

**Check website** now reads the home page plus the site's Contact, About and Menu/Services pages (same site only, robots policy respected). It also reads the schema.org business data many sites publish. It reports need signals, each with the page and text it came from: HTTPS, mobile layout, online ordering or shop, online booking, contact form, WhatsApp, structured data, search basics, a stale copyright year and the site platform. Signals that matter for *your* product are marked and add transparent points (at most +3). "Not found" means not seen on the pages read.

The **identity cross-check** compares the map entry, the website and web findings on name, phone, email, website link, address and social profile. The result is: same business, probably the same, only the name matches, possibly another branch, or may be a different business. A website that may belong to another business earns no points and is kept out of the AI's evidence. If the map lists only an Instagram or Facebook page as the "website", that is treated as "no own website" (a need for website offers), not as a site to read. A listed website that no longer loads is saved as a dated finding. On sites with several branches, LeadDesk prefers the page for your searched area and only links details to this business when a phone number or street address matches.

**Research top 3** runs a fixed sequence per business: find online → read website → AI analysis. Each AI analysis now has a second pass, a strict checker that sees each reason with only its cited evidence. It can lower "likely" to "possible", never raise it. **Market problems** counts recurring gaps across the businesses you researched. **Find problems (AI)** turns those counts into cited problem ideas, a product to build, and a question to validate each with owners. See [Sprint 21](planning/SPRINT_21.md).

### Websites read properly, layout and rules-first pitch (Sprint 23)

**Find online** now searches with the business's own city and type, and for its Facebook and Instagram pages. Results that do not mention the place, type or a local phone number are listed under "Possibly a different business" and give no contacts until you answer **Is this them?**. **Check website** reads up to 6 pages, follows a site that forwards to another address (recorded), and can draw JavaScript sites in your installed Chrome when you tick **Read JavaScript websites with Chrome** (phone and desktop screenshots, deleted after 24 hours; "checking your browser" pages are detected and never used). Each lead shows its **layout**, **What you offer vs. what they have** (Has / Missing / Not seen with evidence) and a **pitch written by LeadDesk** from those checks; your AI model may only reword it, and its wording is rejected if it adds facts. Use **Analyse a business website** for any URL, or **Add website** on a lead. See [Sprint 23](planning/SPRINT_23.md).

### Contact review, corrections and the quality report (Sprint 24)

Every phone and email is **approved**, **needs review** or **rejected** with its reasons (temporary-email domains from a local 9,963-domain list, placeholders, fake or invalid numbers, domains that take no email, contacts shared by many unrelated businesses). Rejected contacts are hidden from lists, messages and the CSV and shown under **Rejected contacts** with an override. Mark a contact **Wrong**, confirm it, add the right one, correct a feature ("Actually they have it"), or **Approve / Edit / Reject** a message: each correction applies at once and in future searches of that business. After 3 or more corrections of the same kind LeadDesk proposes a rule you can approve or switch off. **Quality report and learned rules** shows, per source, how many contacts were approved, rejected or corrected by you. Refresh the temporary-email list with `.venv/bin/python scripts/update_disposable_domains.py`. Free search engines limit automated searches; when they block, Find online says so and saves nothing rather than reporting "nothing found". See [Sprint 24](planning/SPRINT_24.md).

### Browser acceptance flows

Stop your regular instance on port 8765, then run `scripts/run-browser-flows.sh` under Node 24 (optionally naming flows such as `main files evaluation`). Each flow gets a fresh disposable `.local/browser-flow-*` instance, and passing flows' data is deleted afterwards. See [Sprint 16](planning/SPRINT_16.md) for results and what headless fictional runs do not establish.

### Built-in contact ranker (Sprint 15)

With a ready evaluation-purpose dataset selected, **Run built-in contact ranker** executes the bundled deterministic `contact_ranker_v1` on this computer. It reads only each frozen example's reviewed input text and source domain group, never the observed or expected output. Contacts in the text are scored transparently: third-party context such as "designed by", "powered by" or "agency" before the value (−4), an email on the source's own domain (+2), a free-mail mailbox (0), a different domain (−1), and an owner cue such as "Reception", "Sales" or "Tel" (+1). It outputs the single highest contact scoring at least 1, and otherwise abstains (no contact, low score or tie). Factual-support examples are always abstentions. The weights were fixed on fictional fixtures before any real reviewed data and are not a calibrated probability.

The optional **Abstention text** replaces null abstentions with your reviewers' exact wording; it is part of the configuration hash. Reports label provenance `builtin_executed_locally` and record the candidate artifact SHA-256 (ranker source plus configuration), decision counts, inference time and Python `tracemalloc` peak memory alongside the existing hardware/date/configuration fields. Outputs are not stored, only their hash. Promotion remains disabled, and development-split results are for inspection, not proof of held-out improvement. API: `POST /v1/experiments/builtin` with `Idempotency-Key`, `dataset_id`, exact `dataset_sha256`, `candidate: "contact_ranker_v1"` and optional `abstention_output`. Verify with `.venv/bin/python -m unittest tests.test_contact_ranker -q`. See [Sprint 15](planning/SPRINT_15.md).

## Local email and calendar files

Open **Email and calendar** after unlocking. This is the selected local-file workflow: no email/calendar account is connected and no message, invitation, booking or availability request is sent. Choose **Real sources and personal planning** or **Synthetic demos only**. Save before leaving or refreshing the panel; unsaved edits are temporary.

For **New email draft**, choose a saved research record and its email contact, enter your sender address, subject and plain-text body, then **Save local draft**. Source lists and saved drafts have independent 20-item pagination. The sender is user supplied, not an authenticated email account. The recipient comes only from the chosen saved contact; arbitrary recipient lists, attachments and generated pitches are not supported. Unicode subject/body text is supported; mailboxes use one plain ASCII addr-spec with a DNS domain. Source-reviewed contact ownership does not prove reachability, interest or permission to send.

Unreviewed/suppressed contacts can be saved as blocked drafts. Export requires current manual source identity/contact attribution, no applicable reviewed offer exclusion and no unresolved identity/comparison dispute. Save the draft, use **Open source evidence and reviews**, finish the appropriate source review, then return and **Open local draft** from the list. Any correction, changed identity signature or new blocking comparison invalidates previous file approval. Corrected replacement contacts remain unverified feedback. This does not implement a general unsubscribe inbox or campaign opt-out service; existing host-scoped contact suppression is enforced.

For **New calendar draft**, enter a title, optional description/location, both parties' IANA timezones (for example `Asia/Karachi` and `Europe/London`), your local start time and elapsed duration of 5–480 minutes. Dates from 2000 through 2100 are supported. Invalid zones and skipped daylight-saving times are rejected. If a local time occurs twice, explicitly choose **Earlier occurrence** or **Later occurrence**. Save to inspect both parties' times, including offsets, and UTC start/end. Duration is elapsed UTC time even across clock changes. Unavailable/invalid timezone rules block review/export; changed conversions invalidate earlier approval and require a fresh review of current times. No availability or agreement is inferred.

Inspect **Review the saved file**, enter a reviewer/note and explicitly acknowledge the saved recipient/time, text and sharing scope. **Approve this file revision** permits only that local file export. Unsaved edits disable review/download; saving edits clears approval, and stale tabs/revisions/context hashes are rejected. Manually authored text remains a human assertion: review factual claims and sharing permission yourself. Source instructions and literal HTML remain plain data, not executable commands.

Download `.eml` for email or `.ics` for calendar. Email uses a plain-text UTF-8 MIME message, one recipient, a stable Message-ID and `X-Unsent: 1`; whether it opens as an editable draft depends on the chosen client. Calendar uses a stable UID, revision sequence, UTC times, escaped/folded UTF-8 content and a tentative transparent personal event. It contains no attendees, organiser, alarm or scheduling METHOD; importing does not mean a meeting was agreed. Synthetic records get visible file-title labels. Repeat downloads of the same approved revision are byte-stable, but a client may still duplicate repeated imports; LeadDesk does not reconcile client-side imports or sending.

**Delete local draft** removes its text and file approval while preserving original research, corrections, suppression, memory, learning data and PC tasks. Hash-only request receipts block deleted-draft resurrection through replay. There is no stored archive of old draft bodies; the latest reviewer/note/time is retained only on the current draft and cleared by edits/deletion. Downloaded/in-flight copies, backups and physical SQLite/WAL erasure need separate management. Limits: 500 saved drafts, 10,000 lifetime write receipts, 16,000-byte JSON requests and 64,000-byte file exports. Migration 010 adds independent draft/request tables; migration 009 remains the PC worker storage.

Authenticated APIs: `GET /v1/correspondence/sources`, `GET/POST /v1/correspondence/drafts`, `GET/PATCH/DELETE /v1/correspondence/drafts/{id}`, `POST /v1/correspondence/drafts/{id}/review`, and `GET /v1/correspondence/drafts/{id}/export?revision=...&context_hash=...`. Create/edit/review require `Idempotency-Key`; edits/reviews require `expected_revision`, and review also binds the displayed `context_hash`. Lists accept `mode=live|synthetic` and `offset`; existing owner-auth/origin/host/no-store policies apply. There are no provider credentials, SMTP/OAuth routes or sending endpoints.

Verify with `.venv/bin/python -m unittest tests.test_correspondence -q`. For the prepared fictional browser workflow, start an empty disposable instance using `LEADDESK_DATA_DIR="$PWD/.local/browser-check" ./launch.sh`, then from `apps/web` run `LEADDESK_TEST_TOKEN_FILE=../../.local/browser-check/access-token npm run test:e2e:correspondence` under the pinned Node 24. It exercises local downloads without sending or importing. Browser/client acceptance remains separate from unit checks; see [Sprint 13](planning/SPRINT_13.md). Format references: [Python email](https://docs.python.org/3.12/library/email.message.html), [IANA zone handling](https://docs.python.org/3.12/library/zoneinfo.html), [iCalendar RFC 5545](https://www.rfc-editor.org/rfc/rfc5545.html).

## Optional PC benchmark worker

Open **PC workers** after unlocking. Nothing is paired or remotely executed by default. Enter a computer name and choose **Pair PC worker**. Download its credential once, transfer it privately to that computer, then choose **Forget displayed credential**. Leaving this panel also clears the credential from its view. The coordinator stores only credential hashes. If the pairing response/credential is lost, refresh the list, revoke that pairing and pair again; replay never returns the secret a second time. Browser downloads remain on disk until you remove them.

The paired Ubuntu computer needs the same checkout and exact Python dependencies from `requirements.lock`, in its own `.venv`; it does not need a frontend build or shared database. Use Python 3.12, create `.venv` with `python3.12 -m venv .venv`, then `.venv/bin/python -m pip install -r requirements.lock` from that checkout. Matching executor and fixture hashes are required; mismatched workers fail explicitly. Reports include their own Python/hardware values but do not attest that the worker is trustworthy.

With private SSH access already configured, establish this tunnel **from the paired computer** to the laptop running LeadDesk (replace the account/host):

```bash
ssh -N -L 127.0.0.1:18765:127.0.0.1:8765 YOUR_USER@YOUR_LAPTOP
```

Keep SSH open. In a second terminal **on the paired computer**, from its LeadDesk checkout:

```bash
chmod 600 /path/to/worker-credential.json
.venv/bin/python scripts/pc_worker.py \
  --coordinator http://127.0.0.1:18765 \
  --credential-file /path/to/worker-credential.json
```

The application does not configure SSH, change firewall rules or expose a listener. Both the forwarded port and coordinator stay on loopback; SSH encrypts the connection between computers. The CLI accepts only `http://127.0.0.1:PORT`, rejects redirects and environment proxies, checks owned mode-600 regular credential files and never passes credentials on the command line. Do not forward the port publicly. `--once` polls once and exits; normal mode reconnects with delays capped at 30 seconds until Ctrl+C. Only one CLI should use a paired credential at a time.

Select the computer and **Queue worker benchmark** (2–20 rounds, five bundled fictional cases/round). Offline tasks remain queued. **Refresh workers and tasks** updates last-seen/task state and an inspected result; status is a recent heartbeat observation, not proof of reachability. Inspect reports for checks, measured time, process peak RSS, CPU/RAM/Python and executor/fixture hashes. **Worker-reported measurements are unverified** and are stored separately from local benchmarks and research. Failed fixture checks remain visible even when a task finishes. No model or live-source accuracy is established.

Only round counts and fixed protocol metadata leave the coordinator: no research records, dataset examples, folders, notes, audio or screenshots. Workers receive only the fixed synthetic-parser workload. There is no remote inference, research fetching, arbitrary command, file tool or automatic local/cloud fallback. Each benchmark executes in a fixed child process with a 30-second timeout; cancellation/revocation rejects any late result, but an already executing child may finish before the worker observes it.

Leases last 60 seconds, heartbeats can extend an attempt to at most 120 seconds, and three disconnected attempts end in an explicit failure. A lost claim response returns the same current lease. A lost completion response retries the exact in-memory result without duplicating it. Restarting the CLI loses that in-memory result; after expiry, a new attempt may recompute this side-effect-free benchmark. Coordinator task/pairing state persists across restart. **Cancel worker task** stops pending acceptance; **Revoke** cancels that worker's pending tasks and rejects subsequent authentication. Completed reports remain. Limits: 50 lifetime pairing records, 500 task records, 20 pending tasks, one active PC task globally, 12,000-byte reports; no history-deletion UI yet. PC execution is separate from the coordinator's local execution slot.

Owner-authenticated APIs: `GET/POST /v1/pc-workers`, `POST /v1/pc-workers/{id}/revoke`, `POST /v1/pc-tasks`, `GET /v1/pc-tasks/{id}`, `POST /v1/pc-tasks/{id}/cancel`. Pair/task creation require `Idempotency-Key`. Worker-only APIs: `POST /v1/pc-worker/claim` (also requires `Idempotency-Key`), and `POST /v1/pc-worker/tasks/{id}/heartbeat|complete|fail` (also require a task lease token). A worker credential cannot access owner APIs or another worker's tasks; the owner key cannot act as a worker. Existing host/origin/body/no-store policies apply. Migration 009 is additive.

Verify with `.venv/bin/python -m unittest tests.test_pc_worker -q`. The prepared disposable-data browser check is `npm run test:e2e:workers` from `apps/web`, after starting an empty instance with `LEADDESK_DATA_DIR="$PWD/.local/browser-check" ./launch.sh`. It simulates a worker with local fictional benchmark measurements; it does not connect a real PC. Chrome launch is blocked in this session; browser flow and actual SSH/two-computer reconnect acceptance remain unverified. See [Sprint 12](planning/SPRINT_12.md).

## Learning and reviewed datasets

Open **Learning and datasets** after unlocking. Choose real source records or visibly labelled synthetic demos. The review queue contains saved contact corrections and the latest pass/fail contact or factual-unit quality audits. Unknown audits, private notes, files, voice/screen context and model-generated proposals are not automatic dataset candidates. Source lists, reviewed examples and dataset versions have independent 20-item pagination. Dataset selection can span example pages, up to 100 examples.

Choose **Review source**. Inspect original research, saved excerpts, the source verdict and any suggested correction (still unverified). Edit **Redacted example input**, **Reviewed observed output** and **Human-reviewed expected output**, select supporting evidence, identify the reviewer and explain the decision. Record a **Source permission basis** and choose evaluation-only permission (default) or explicit local-training permission. An optional shared business group keeps the same business or copied source together across domains. Confirm that you removed secrets/private material; edits reset that confirmation. A conservative credential-pattern check rejects obvious credential assignments/private-key headers, but manual redaction and source-permission review are still required.

**Include reviewed example** saves a revision for the selected source; **Exclude source from datasets** saves the exclusion and removes its copied example material. Neither runs training or changes the source research, contact suppression or active model. Expected output remains an explicit human label, not independent proof of ownership, reachability, intent or correctness. A changed/superseded source or stale review revision is rejected; refresh and review the source again. Quality snapshots whose current research state changed must be recaptured/audited before inclusion.

Select current included examples, enter a **Dataset version name**, choose purpose and development/holdout split, then **Freeze dataset version**. Evaluation uses either permission scope; training-purpose preparation requires explicit local-training permission on every example. Holdouts can only serve evaluation. Real and synthetic examples cannot mix. Duplicate source targets or identical reviewed examples cannot inflate one dataset. Each version records a stable SHA-256, reviewed revisions, evidence IDs/hashes/retrieval times, source revision/origin, human-label provenance and permitted use. Only the edited review fields are copied; raw source comments, unverified replacements, full URL paths/queries and unselected excerpts are excluded.

Split checks reserve domain groups, exact source-body hashes, source targets and optional shared business groups. Domain grouping conservatively uses the final two DNS labels without a public-suffix dependency: this can group unrelated `co.uk`-style sites together. Review shared-business groups across different domains manually; there is no automatic entity resolution or near-duplicate detector. Existing quality holdouts are protected, including saved comparison sources. Group reservations persist as hashes even after deleting a version, so previously exposed material cannot later become a fresh holdout. Capture/review times remain available for manually selecting chronological samples; no automatic temporal split is claimed.

Inspect a dataset manifest and choose **Export reviewed dataset** to download its JSON (maximum 2 MiB). A fresh source/revision/permission/split check runs before returning it. Review edits, exclusion, permission changes or example deletion invalidate every affected version and clear **all** copied member payloads in those versions. Changed/deleted sources or new quality holdout conflicts are detected when versions are listed, inspected or exported, with exports rejected. Delete an invalid version and build a new one from current reviews. **Delete reviewed example** preserves original research/feedback/suppression; **Delete dataset version** preserves source examples. Request receipts retain only hashes/IDs and prevent replay from recreating deleted learning material. Downloads, in-flight responses, old backups and database/WAL forensic erasure are outside these app-level deletion controls.

Authenticated APIs: `GET /v1/learning/sources`, `GET/POST /v1/learning/examples`, `DELETE /v1/learning/examples/{id}`, `GET/POST /v1/learning/versions`, `GET /v1/learning/versions/{id}`, `GET /v1/learning/versions/{id}/export`, and `DELETE /v1/learning/versions/{id}`. POSTs require `Idempotency-Key`; reviews require expected source hash/revision, version selection requires example revisions. Existing bearer, origin/host, no-store and 16,000-byte JSON protections apply. Limits: 2,000 saved reviews, 200 versions, 100 examples/version. Migration 008 adds separate learning tables without changing existing records. No dependency/model installation, cloud upload, trainer, experiment, promotion or rollback executor is enabled.

Verify with `.venv/bin/python -m unittest tests.test_learning -q`. For fictional desktop browser acceptance, start a separate empty-data instance using `LEADDESK_DATA_DIR="$PWD/.local/browser-check" ./launch.sh`, then from `apps/web` run `LEADDESK_TEST_TOKEN_FILE=../../.local/browser-check/access-token npm run test:e2e:learning`. Stop a regular server on port 8765 first. This script creates a labelled synthetic demo/correction, reviews/exports/deletes its learning material and preserves the original synthetic feedback in the disposable database. Chrome launch is blocked in the managed sandbox; browser buttons, downloads and layout remain unverified here. See the [Sprint 11 report](planning/SPRINT_11.md).

## Voice and reviewed commands

Open **Voice** after unlocking. Typed commands work with the default installation. Microphone controls remain unavailable until you configure an installed local whisper.cpp CLI and model; no speech executable was found on PATH during Sprint 9 implementation, and no runtime or model was installed or downloaded.

Use one of these explicit command prefixes (case-insensitive):

- `find files clinic proposal` — select an approved folder; uses its existing bounded index and current-file checks.
- `search memory clinic` — enter the exact memory scope; retrieves active, unexpired notes and shows up to three.
- `remember Clinic proposals use the reviewed template` — enter the exact scope; prepares one user-authored project-context note.

The command text can contain Unicode keywords or note content, but the parser currently needs these English prefixes. Urdu/Roman Urdu natural command interpretation is not implemented. **Transcript or typed command** is editable. Choose **Prepare reviewed command**, inspect the action and folder/scope, then choose **Run reviewed search** or **Save reviewed memory**. Preparing and transcribing never apply an action automatically. Edits invalidate the displayed plan; the server also rejects a mismatched plan hash. Note saves use an idempotency key, and can be edited/deleted in Files and memory. There are no voice commands for shell execution, sending messages, screen capture, file opening/deletion or arbitrary desktop control.

For dictation, hold **Hold to talk** with a pointer, Space or Enter and release to transcribe. **Start short recording / Finish short recording** provides an alternative to holding. A visible microphone indicator distinguishes waiting for permission, recording and local transcription. Audio is capped at 30 seconds, downsampled to mono 16-bit PCM WAV at 16 kHz, and uploaded only to this authenticated loopback app. Capture stops on release, cancellation, microphone disconnect, panel change, window blur or a hidden tab. Releasing/cancelling while permission is pending stops a stream that arrives later. Permission denial, unsupported capture, silence, missing runtime, memory pressure and transcription errors leave typed input available.

**Cancel voice command** stops capture, aborts the pending upload/poll and requests cancellation of its server session. An early server cancellation creates a short-lived tombstone to prevent a late upload starting inference. Late transcripts cannot replace a cancelled/newer command. Cancellation does not undo a note already applied; delete it through Files and memory. The button is disabled while a reviewed action is being applied. Leaving the panel can hide an in-flight action's response even when an explicitly approved note save has completed; inspect the selected scope if its response is lost.

Configure only a compatible, trusted whisper.cpp executable and a local model you have selected and licensed appropriately. The adapter supports model files up to 512 MiB and checks their exact SHA-256 before each non-silent transcription. It uses two CPU threads, one process, GPU disabled and the same execution slot as research/benchmarks/queue pages. At least 3 GiB effective available RAM is required before inference; this is a guard, not a measured model-fit or accuracy recommendation. The runtime is bounded to 90 seconds, with a separate 15-second between-chunk model-verification budget. In-flight filesystem calls cannot be forcibly interrupted. No model is recommended or benchmarked by this sprint. [Official whisper.cpp CLI options](https://github.com/ggml-org/whisper.cpp/blob/master/examples/cli/README.md).

```bash
# In your normal terminal, supply actual absolute paths and the model's digest:
sha256sum /absolute/path/to/model.bin
export LEADDESK_WHISPER_CLI="/absolute/path/to/whisper-cli"
export LEADDESK_WHISPER_MODEL="/absolute/path/to/model.bin"
export LEADDESK_WHISPER_SHA256="PASTE_THE_64_LOWERCASE_HEX_CHARACTERS"
./launch.sh
```

Restart after changing configuration. Status checks only validate configuration/file availability; digest and memory checks happen before inference. Auto, English and Urdu language selections are passed to the configured local model. Real English/Urdu/Roman Urdu/code-switching recognition, latency, CPU/RAM costs and hardware/model compatibility require actual recording tests. A near-silence energy check avoids invoking the model on very quiet input; it is not a voice-activity detector or a guarantee against hallucinated transcripts. All output remains unreviewed text until you inspect it.

Raw audio is held in browser/request memory and in a private temporary WAV directory only for the local runtime call; normal completion, failure, timeout, cancellation and shutdown clean up temporary files. Abrupt OS/process termination can leave temporary files; there is no crash-time secure erasure guarantee. Audio and unreviewed transcripts are not inserted into SQLite, logs or training datasets. Up to 32 ephemeral sessions, including cancellation tombstones, are retained in process memory. Completed/cancelled/failed sessions expire for retrieval after five minutes and are pruned on the next voice request; restarting loses all sessions. Browser-held text remains until cleared or the page closes. An explicitly saved reviewed note persists as normal editable memory.

**Optional spoken output** stays off by default. Enable it, choose a local voice and click **Read aloud** to speak up to the first 1,000 characters of the displayed plan or result summary; **Stop speech output**, cancellation and leaving the panel/window stop playback. Only voices whose browser `localService` flag is true are offered and rechecked at playback, with no remote voice fallback. If none are available, output stays textual. The browser's local speech service and language quality need desktop verification. [Browser local-voice flag](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesisVoice/localService).

Authenticated APIs: `GET /v1/voice/status`, `PUT/GET/DELETE /v1/voice/transcriptions/{client_uuid}`, `POST /v1/voice/commands/prepare`, and `POST /v1/voice/commands/execute`. The PUT accepts `audio/wav` and optional `language=auto|en|ur`, streams a maximum 1,000,000 bytes, validates PCM/duration and returns 202. Reusing an ID with different accepted audio/language returns 409. Commands retain the 16,000-byte JSON body limit; execution requires `expected_plan_hash` and `Idempotency-Key`. All retain bearer/origin/no-store protections. No schema migration is needed.

Run controller/codec tests with Node 24 from `apps/web`: `npm run test:voice`. For fictional browser acceptance against a disposable-data server, use `LEADDESK_TEST_TOKEN_FILE=../../.local/browser-check/access-token npm run test:e2e:voice`. This injects generated audio, a denied-permission case, synthetic ASR replies and synthetic local/remote voice metadata; it never accesses a physical microphone or a real model/speaker. Chrome cannot launch in the managed sandbox, so browser assertions and real microphone/speech acceptance remain unverified. [Sprint 9 report](planning/SPRINT_09.md).

## Screen context and reviewed local actions

Open **Screen context** after unlocking. Choose **Choose screen or window**, then select a window, tab or display in the browser/Ubuntu chooser. The browser controls available sources; the app's window preference cannot restrict that chooser. Permission is requested for each capture, with no audio requested. See the [browser screen-capture contract](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getDisplayMedia).

The panel shows selection/capture status, takes one still and stops all sharing tracks before showing the preview. Selection is bounded to 30 seconds; frame reading has a five-second budget, with a six-second controller deadline. **Discard screen context** cancels pending selection or capture, ignores late results and clears the preview, context and action. A browser chooser may remain open after app cancellation; any late stream is immediately stopped. Focus changes during selection are permitted so the chooser can work. Page exit/panel navigation always cancels; hiding the tab after capture clears context. A captured preview also expires after five minutes. Browsers can delay timers in inactive pages.

Preview dimensions are bounded to 1600 × 1200 with at most 2.8 million data-URL characters; source dimensions are recorded separately, capped at 16384 per side and 33,554,432 pixels. The region is the full user-selected surface, beginning at (0,0); this slice has no crop editor. Screenshot bytes stay in browser memory and never enter an API request, SQLite, application file or training dataset. There is no screenshot download/save control. Capture is never triggered by page load, voice input or model text.

Enter a **Context source label** and type/paste the **Reviewed context text** (up to 4,000 characters). These fields are user-assisted text, not OCR output or independently verified application identity. Capture time, surface type and source dimensions, when available, are client-reported metadata. If capture is denied, missing or unavailable, text entry still works without any screen permission. Automatic OCR, accessible-text extraction from other applications, image explanation, native file opening/revealing, filesystem note writes and OS control are not implemented in this slice.

Choose one explicit action: search an already approved folder using separate keywords, search active notes in an exact scope, or save the reviewed context as a scoped note. Choose **Prepare context action**, review the text, source, scope and action, then **Run reviewed context search** or **Save reviewed context**. Preparing never saves a note or runs a search. Edits invalidate the plan, and execution rechecks its hash. Screen text is always data: apparent commands in it cannot choose or run a tool. File results use the existing current-file/symlink/revocation checks; **Preview current file** rechecks the file before showing text. Folder approval/reconciliation, wrong-file correction and note editing/deletion remain in **Files and memory**.

Only a chosen **Save reviewed context** persists the reviewed text and its source details as private, user-authored memory, excluded from training. Repeating a save with the same plan/request key returns the same note. Discarding context or leaving the panel does not undo an approved note save that has already committed, including when its response is lost; inspect/delete it in Files and memory.

Authenticated APIs: `POST /v1/screen/commands/prepare` and `POST /v1/screen/commands/execute`. Inputs are strict text/source/frame metadata plus one of `search_files`, `search_memories` or `save_note`, keywords and the applicable folder/scope. Image fields and unknown actions are rejected. Execution requires `expected_plan_hash` and `Idempotency-Key`; existing bearer, host/origin, no-store and 16,000-byte JSON limits apply. No dependency or database migration was added.

Run Node 24 controller tests from `apps/web` with `npm run test:screen`. For fictional browser acceptance against a running disposable-data instance, use `LEADDESK_TEST_TOKEN_FILE=../../.local/browser-check/access-token npm run test:e2e:screen`. This replaces screen selection with generated canvas media and denial/late-permission fixtures; it does not read the real desktop. Chrome launch is blocked by the managed sandbox (`setsockopt: Operation not permitted`, SIGTRAP), so no browser assertions or real Ubuntu permissions have passed here. Follow the [Sprint 10 desktop checklist](planning/SPRINT_10.md) in a normal desktop terminal. B13's Ubuntu acceptance remains open.

## Files and memory

Open **Files and memory** after unlocking. Enter an absolute path to a dedicated project folder inside your home or `/tmp` and choose **Approve folder**, then **Reconcile folder**. Approval alone reads directory identity, not file content. No folder is approved by default. Broad home/temp/filesystem roots, hidden paths, symlink paths, overlapping approvals and the app's data directory are rejected. Hidden items, dependency/build directories, known credential filenames, symlinks and special files are skipped; choose folders containing material you intend to index.

A manual reconciliation replaces that folder's snapshot. It inspects at most 500 directory entries, twelve directory levels, 1 MiB per supported text file and 8 MiB total, checking a five-second deadline between operations. Filesystem operations already in flight are not forcibly interrupted. Partial scans and read errors are shown. Entries outside a partial scan are removed from the snapshot; use smaller project folders for useful coverage. There is no background watcher or periodic scan in this slice.

Supported text is UTF-8 (optionally BOM-prefixed): `.txt`, `.md`, `.rst`, `.csv`, `.tsv`, `.json`, `.log`, `.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.css`, `.html`, `.xml`, `.yaml`, `.yml` and `.toml`. Content is decoded as text, never executed or rendered as HTML. PDF/office formats are filename-only with **unsupported** status. Oversized, binary/non-UTF-8, unreadable and byte-budget-limited files have separate indexing statuses. OCR and document parsers are future work.

Search uses up to twenty keyword tokens, all required, over filenames and supported text in the selected approved folder. It shows at most three choices with path, modification date, status and excerpt; it abstains when no current match exists. Punctuation and FTS operators do not become executable query syntax. **Preview file** shows up to 16,000 text characters. **Copy folder location** provides a path for your file manager's location bar; there is no native desktop opener. Every returned file is checked again against its current scope, identity, metadata and content hash. Changed, moved, deleted, linked and unavailable files cannot return stale stored text. Reconcile to find moves/new files; a uniquely identified same-filesystem rename retains its file ID. Duplicate contents and hardlinks remain separate path records; cross-filesystem moves receive a new ID.

Enter a correction reason and choose **Wrong file** to exclude that exact file/content for the displayed query and folder. To associate a different file, find it, set **Correction query** to the original words and choose **Use this file for query**. The chosen file can appear even without a keyword match. Saved choices can be undone, do not affect other queries/folders, and disappear when their file content changes or the folder is revoked. **Revoke folder approval → Remove folder index** deletes approval, indexed text, search entries and file corrections without editing original files.

For **Scoped memory**, enter an exact project/scope name and choose **Load memory scope**. Create/edit/delete user-authored preferences, file aliases, project context, product facts or corrections; record their source/reason, optional expiry and pin. These notes are user assertions, not automatically verified business facts. They do not invoke a model, execute file instructions, change lead claims or automatically alter file ranking. The file correction controls above provide explicit query-to-file associations. Expired notes are inspectable in this panel but excluded from normal retrieval, even when pinned. Edits use revision checks to reject stale writes. Changing a note's scope requires a new note. Pages show 100 notes each, with a global limit of 1,000 notes. **Export scoped notes** downloads the entire scope including expired notes; **Forget this scope** deletes all of its notes after the panel's explicit delete step. A replayed create request cannot resurrect a deleted note.

Deletion removes live records and derived search results. It is not a forensic erase guarantee for SQLite/WAL free pages, prior exports, browser copies or backups. No embeddings, training datasets or model updates are created by these features. User-authored notes are separate from indexed file text; revoking a folder does not delete independent notes you wrote about it.

Authenticated APIs: `GET/POST /v1/files/roots`, `DELETE /v1/files/roots/{id}`, `POST /v1/files/roots/{id}/reconcile`, `POST /v1/files/search`, `GET /v1/files/{id}/preview`, `POST /v1/files/corrections`, `DELETE /v1/files/corrections/{id}`; `GET/POST /v1/memories`, `PATCH/DELETE /v1/memories/{id}`, `GET /v1/memories/export?scope=...`, and `DELETE /v1/memories/scope?scope=...`. Memory lists require `scope` and accept `q`, `include_expired` (default false) and `offset` (pages of 100). Creates require `Idempotency-Key`; edits require `expected_revision`. All use the existing bearer authentication, origin checks, request bounds and no-cache policy. Migration 007 adds these tables and FTS5 without rewriting earlier research or quality records; SQLite must support FTS5.

For browser acceptance, start a fresh disposable-data instance using the browser procedure above, then from `apps/web` with Node 24 run:

```bash
LEADDESK_TEST_TOKEN_FILE=../../.local/browser-check/access-token npm run test:e2e:files
```

This creates, indexes and removes its own fictional `/tmp` folder and temporary memory scope. It covers approval, preview, wrong-file/undo, moves/deletion, unsupported formats, error/retry, note edit/export/delete, persistence and mobile layout. Chrome cannot launch in the managed sandbox; desktop acceptance remains unverified. [Sprint 8 report](planning/SPRINT_08.md).

## Saved prospects and downloads

Open **Leads** after unlocking. Real source records are selected initially. Choose **Synthetic demos only** to inspect fictional records; demos and real-source records are never mixed in this panel or its downloads. Search by saved name/branch, source URL, contact, offer or target location, then select identity, contact, analysis, current fit and review filters. Click **Apply prospect filters**. Each card keeps source identity, contact ownership and inferred fit separate, shows contact evidence/dates, and suggests the next check. **Open evidence and reviews** opens the original record, alternatives, citations, corrections and assessment history.

The panel recomputes current review states when opened, refreshed or filtered. Disputed identity, outside-target geography, offer exclusions and a current not-a-fit judgement exclude the record's contacts from availability in this view. Individual corrected contacts stay excluded across matching source-host research. Excluded values appear only in the audit section. Stale analysis retains its saved fit and inference but receives an effective **review** fit, unless a separate current exclusion applies. The **possible fit** filter cannot promote a stale judgement. **Source reviewed** means the implemented local review checks are current; it does not establish independent corroboration, reachability, interest, budget or outreach approval.

Filters and downloads cover the **newest 200 records in the selected mode**, ordered by saved time then ID; the panel reports scanned/total counts and any omitted older records. Pagination shows 20 matching records at a time. Filtering occurs within that bounded scope. Records are not merged, ranked or automatically refreshed in the background. Refresh to see changes made in another tab; page membership may shift between requests when new records or reviews arrive.

**Download prospects JSON/CSV** uses a fresh, consistent database snapshot with the applied filters, across all matching result pages within that scope. No business page is fetched. JSON includes current effective labels, complete saved research/evidence, frozen product brief, feedback, up to 100 recent assessment revisions per record, history truncation flags, and foreign source evidence cited by included comparisons. It preserves exact contact values. Unknown intent/budget remain explicit. Excluded contacts are retained and labelled for audit; these downloads are not an outreach-approved list or a database backup.

CSV uses UTF-8 with a BOM, one row per contact, or one blank-contact row for a record without contacts. It includes states, exclusions, dates, unknowns and contact evidence. The first row for each research ID contains `research_audit_json` with the saved research/history/comparison bundle; subsequent contact rows leave that cell empty. Spreadsheet formula prefixes, including leading `+` in phone numbers, receive an apostrophe; JSON and the embedded audit retain original values. Empty selections produce an empty JSON record list or CSV header. Serialized record data is limited to 16 MiB; larger selections return a clear error requiring narrower filters, with no partial file. The CSV file itself can be larger due to quoting and contact rows.

Authenticated API: `GET /v1/leads` and `GET /v1/leads/export`. Shared query filters: `mode=live|synthetic` (default `live`), `q` (up to 200 characters), `identity=all|unresolved|source_attributed|disputed`, `contact=all|attributed|extracted|excluded|none`, `analysis=all|not_reviewed|current|needs_review`, `fit=all|unknown|review|possible_fit|not_a_fit`, `review=all|needs_review|excluded|source_reviewed`. Other filters default to `all`. List queries additionally accept `offset` (0–200) and `limit` (1–50, default 20), with `next_offset` in the response. Export accepts `format=json|csv` (default JSON) and rejects pagination arguments to avoid silently exporting only one page. Both enforce existing authentication, origin and no-cache policies; invalid filters return 422, oversized record data returns 413. No new schema migration or service is required. Sprint report: [planning/SPRINT_06.md](planning/SPRINT_06.md).

## Quality baseline and manual audits

Open **Quality baseline**, select real-source records or synthetic demos, name the baseline and choose development or holdout purpose. Find/select saved records across candidate pages, then **Capture quality baseline**. The picker searches the newest 200 records in its selected mode; a baseline can contain 1–100 explicitly selected IDs. The API can also capture older known record IDs. Repeated source URLs are rejected, even across offers/locations, to avoid inflating the sample with repeated research. Different URLs may still describe the same business; no independent business deduplication is claimed. Real and synthetic records cannot share a baseline.

The baseline freezes source evidence, prediction/review states, corrections, product context and factual audit units before scoring. It also saves hardware, code fingerprint, rubric/configuration, date and a dataset hash. The model hash is null because quality review invokes no model. Changing a live record does not rewrite its frozen case: reopen/reload the baseline to see **changed live records**. Audits evaluate the saved snapshot, not the changed record. **Open live evidence and corrections** leads to the normal correction workflow; a quality audit itself does not change identity, contacts, suppression or fit.

Choose a case and enter a reviewer label. Audit identity, contact ownership, factual source support and inferred offer relevance separately. **Pass/fail requires a reason and evidence IDs from the frozen case or its captured comparison sources**. Contact/factual audits must cite their own target's source excerpt; identity audits require the captured business-name evidence. Inferred need/fit text is excluded from factual-unit scoring. Leave unresolved outcomes **unknown**. Reviewer labels and decisions are user supplied, not authenticated independent adjudication or buying-interest evidence. See [the review rubric](planning/examples/QUALITY_REVIEW_RUBRIC.md).

Reports show global and offer/target-location segments, pass/fail counts, unknown and unreviewed counts, eligible units, proposed thresholds and 95% Wilson intervals. Rates use known pass/fail outcomes only. Unknown/unreviewed items never count as correct, and incomplete audit coverage cannot meet a point threshold. Identity and contact precision count only captured source-attributed identity and effective attributed contacts; abstentions and excluded contacts are shown separately. **Reference coverage** checks that factual evidence IDs exist; **audited support** asks a reviewer whether those excerpts actually support each fact. Neither establishes independent truth. A fully reviewed case requires known identity, relevance, all contact and all factual-unit judgements; unresolved identity remains incomplete rather than forcing a positive label.

Intervals are descriptive independent-Bernoulli approximations: multiple contacts/pages can be correlated, selection is manual and the sources can be wrong. **Observed target met** means a fully audited point estimate reaches the proposed threshold; sample adequacy, uncertainty and each segment still require review. **Release readiness remains not established**. Precision@20 is unmeasured because the app has no ranked shortlist; unranked relevance is reported separately. Outreach, duplicate-send, fabricated-path and file-search gates are explicitly unmeasured here. Existing synthetic parser regression checks remain separate from quality audits. Collect at least 60 real reviewed prospects across three unrelated offers and two geographies, including the rubric's difficult scenarios, before broader claims. Label counts do not prove that offers are unrelated or records independent. Synthetic examples never count towards real reviewed cases.

Saving an audit creates an immutable revision with optimistic concurrency and an idempotency key. Retrying cannot create duplicate revisions or replay an old judgement over a later one. Draft edits survive panel/case switches; **Reload baseline · Discard audit edits** reloads saved revisions. Opening another baseline starts that baseline's drafts. History shows up to 100 recent revisions per case with a limit flag; earlier revisions remain stored. The baseline list shows the latest 20, with a total count; known IDs remain accessible. **Download quality report JSON** includes every frozen case, its latest audit/revision, hashes, configuration and the per-segment report. Unsaved edits and full historical audit chronology are not included in that download. Snapshot capture and downloaded JSON each have a 16 MiB limit; oversize requests fail explicitly, with no partial baseline/file. Baseline/case deletion is not implemented in this slice; retention/dataset controls remain later work.

To inspect six visibly fictional authored examples across three offers and two geographies without touching normal app data:

```bash
.venv/bin/python scripts/quality_demo.py --output /tmp/leaddesk-fictional-quality.json
```

This uses disposable storage, invented `.example` pages and developer-authored audit labels. It includes positive/negative/unknown relevance, incorrect attribution and abstention; it is a demonstration, never 60 real reviews or a measured accuracy claim. An executed example is preserved at [planning/sprint-07-synthetic-quality.json](planning/sprint-07-synthetic-quality.json).

Authenticated API: `GET/POST /v1/quality/baselines`, `GET /v1/quality/baselines/{id}`, `GET /v1/quality/baselines/{id}/export`, `POST /v1/quality/baselines/{id}/cases/{research_id}/audit`, and `GET /v1/quality/baselines/{id}/cases/{research_id}/history`. Create requires `name`, `mode=live|synthetic`, `research_ids`, optional `split=development|holdout`, and `Idempotency-Key`. Audit requires `expected_revision` (0 initially), `reviewer`, optional `identity`/`relevance` verdicts, `contacts`/`claims` lists with `target_id`, `issue_tags` and `notes`, plus a key. Verdicts contain `outcome=pass|fail|unknown`, `evidence_ids` and `reason`. Omitted verdicts are unreviewed; explicit unknowns remain unknown. Missing targets return 404, invalid scope/citations 422, stale revisions/conflicting keys 409, oversize payloads 413. Audit bodies alone allow up to 128 KiB for large bounded contact/claim forms; other mutation routes retain their 16,000-byte limit. Migration 006 only adds quality tables/triggers; previous research, assessments, feedback, briefs, benchmarks and jobs are preserved. [Sprint 7 report](planning/SPRINT_07.md).

## Product briefs

Open **Product briefs** after unlocking. Enter any offer and target geography, with an optional problem, capabilities, service geography, exclusions and price. Create a draft, edit its buyer hypotheses and verification checks, and keep or reject hypotheses. These are planning assumptions; keeping one does not confirm buyer need, contact ownership, interest or budget. Missing inputs stay null with reasons. Your price remains separate from a prospect's unknown budget.

Save changes to create a new immutable revision. Changing offer inputs resets kept hypotheses to unreviewed; older revisions retain their original review states. A conflicting edit from another tab returns 409 rather than overwriting it. Reopen the saved brief to load the latest revision. The editor preserves its unsaved state when switching workspace panels; **Use this brief for research** is disabled until changes are saved or discarded.

Select **Use this brief for research**, then supply a website or try the labelled synthetic demo. Research keeps a frozen copy of the selected brief revision. Editing the brief afterwards affects future selection, not existing records. A stale selection is rejected before fetching; reopen the brief and select its latest revision. **Use manual details instead** restores the original offer/location workflow. Exclusions and checks are recorded for review; identity and need analysis can be reviewed on individual research records. Automatic exclusion matching remains future work. Bounded link discovery is available separately in Research queue.

Default drafting is deterministic and uses your inputs without network requests. A CLI is also available:

```bash
.venv/bin/python scripts/draft_brief.py planning/examples/offer.json
.venv/bin/python scripts/draft_brief.py planning/examples/offer.json --save
```

The example is a planning input, not evidence about a real business. `--save` creates a new brief in the selected `LEADDESK_DATA_DIR` (default `.local`); each CLI invocation is a new draft. To explicitly use an already installed local Ollama model, add both `--model YOUR_INSTALLED_MODEL` and `--digest YOUR_64_CHARACTER_DIGEST`. The same loopback-only, CPU, memory, digest and remote-model restrictions described below apply. Brief generation allows up to 512 output tokens. Only typed hypotheses/checks are accepted from the model; your input fields are preserved. Invalid output saves nothing and does not silently substitute a different draft. Model suggestions require review and are never stored as prospect facts. No model is selected or invoked by the web brief routes.

## Research queue and link discovery

Open **Research queue**, select a saved brief revision, and supply a public directory or association page. Set page attempts, retained candidate count and active seconds, then queue the job. **Start paused** lets you save it before execution. **Run synthetic queue demo** uses a fixed fictional directory and two fictional websites without any business network requests.

The first connector reads anchors with visible text and retains external HTTP(S) links in source order. It ignores same-host links, hidden anchors, invalid/private literal URLs and exact duplicate normalized URLs. Image-only links, external CSS visibility, pagination, JavaScript rendering and search engines are outside its scope. Different paths on a shared host remain separate candidates; no business/branch merge is inferred. Each candidate retains source URL, anchor text/href, body SHA-256 and retrieval time. Directory-operator contacts are never copied from the source page into a candidate record.

The worker inspects candidate pages within the saved budget and creates normal research records with their own contact evidence, unresolved identity and the job's frozen brief. Existing contact corrections/suppression still apply. **Open saved research** leads to the original evidence/correction workflow. A link is not proof of a business identity or product fit; offer text, geography and exclusions do not filter or rank this connector's links. Review the coverage gaps and existing alternatives before treating a candidate as relevant.

Jobs persist across browser refresh and server restart. Pause/resume and cancellation act between pages; a page already claimed/in flight may finish and retain its evidence. Switching panels or locking the browser does not pause authorised jobs while the server runs. Resume retains the original scope, brief, counters and retry deadline; it cannot enlarge the budget. Finished jobs require a new explicit run. At most 20 unfinished jobs are accepted.

A job allows 1–6 page attempts (default 3), 1–20 retained candidates (default 10), and 30–300 active seconds (default 120). The source page, failed attempts and retries consume attempts. Every attempt uses the existing robots, public-address/DNS-pinning, TLS, same-host redirect and 1 MB response policies. A logical page attempt can make up to eight HTTP requests across robots and redirect chains; the page budget is **not** an HTTP-request counter. The normal page deadline is capped at 20 seconds and remaining job time; an in-flight socket read may add up to its five-second timeout. Paused/queued/backoff time is excluded from active time.

Transient failures retry at most twice per step with exponential delay/jitter and provider Retry-After guidance. Prohibited access is not retried. A crash reserves/consumes an attempt; stale leases recover after 60 seconds and conservatively charge at most 60 seconds of unknown active work. Uncommitted read-only fetches may repeat, but stale workers cannot commit results. Research/evidence and step completion commit in one transaction using a stable request key, preventing duplicate saved records after an interrupted commit. Coverage remains partial when budgets, failures, candidate caps or source exhaustion leave gaps.

One in-process worker starts/stops with the server lifespan and shares the execution slot with interactive research and parser benchmarks. It does not require Redis, Docker, another service, a model or an account integration. Queue progress polls once per second while the panel is open. The launcher still runs one server process; independently launched app/CLI processes are outside the shared in-process execution lock.

## Business identity and grounded need review

Open any saved research record and use **Business and branch review**. Choose the page's role and quote its business name, branch and location from the selected evidence. Each quote must occur in every cited excerpt (case/whitespace differences are allowed). Unsupported wording and foreign/missing evidence IDs are rejected. These checks establish textual support only; the meaning of the field, page role and geography remain manual reviewer judgements. A business-page selection does not authenticate an official domain.

Directory/agency pages cannot receive business-source attribution. A shared-brand page needs a cited branch. Each contact requires a separate decision citing its own excerpt; a branch-specific contact attribution also requires the branch phrase in that excerpt. Attribution does not prove reachability, independent corroboration or outreach permission. A disputed identity excludes this record's contacts; **Report wrong contact** retains the existing suppression of that value across its source host. An identity review cannot restore suppressed values.

Related-record hints compare up to 200 recent records and display at most 20 related source pages. Shared hosts on different pages or shared contacts require a comparison before effective attribution; same names alone are informational. Comparison judgements need evidence from both records and a reason. Records remain separate even after a same-business/branch judgement. Repeated identical URLs are skipped; synthetic and real data are kept separate. If the bounded scan cannot cover all comparisons, attribution stays unresolved. This is local manual reconciliation, not automatic identity resolution or a global deduplicated business registry.

In **Grounded need analysis**, cite source observations and existing solutions. Write need, offer relevance and fit as hypotheses, with competing explanations and missing checks. **Possible fit** requires effective reviewed identity/comparisons, a cited location/service area judged to match the target, checked exclusions, observations and existing-alternative checks. If a solution is described, cite it and explain why investigating a change may help. “Not described in selected excerpts” records a limited absence; a solution may exist elsewhere. Budget remains null and interest remains unknown.

Reviews append immutable revisions and evidence links. Identity changes, contact corrections and changes to compared/related records flag saved analyses as needing review. The earlier analysis remains visible with its original citations and caveat; reload and save a new revision to reassess it. The history shows up to 100 recent review revisions. New research saves up to 12 additional visible excerpts, each at most 400 characters, for these reviews. Existing records are not backfilled because raw page bodies were never retained.

## Hardware and benchmarks

After unlocking, open **Hardware and models**. Refresh the current CPU, RAM, swap, data-drive and GPU telemetry; then run the parser benchmark. Five fixed fictional cases run for 20 rounds, checking visible contacts, hidden content, ambiguous names and explicit WhatsApp links. Reports persist separately from research and can be reopened or downloaded as JSON. A failed check stays visible. This is a synthetic regression suite, not an estimate of live contact accuracy.

Read-only profiling and parser benchmarks also work from the terminal:

```bash
.venv/bin/python scripts/benchmark.py --profile
.venv/bin/python scripts/benchmark.py --samples 20 --save
```

`--save` writes to the same local database used by the app; without it, the script only prints JSON. Reports include hardware, timestamp, configuration, fixture hash, check count, failures and timing. Parser memory is the runner process's lifetime peak RSS; it excludes browser and inference processes. Missing telemetry is null with an explanation. GPU presence does not establish model compatibility.

An optional **terminal-only** Ollama adapter accepts an exact already installed model name and its 64-character digest. No model is selected, downloaded, pulled or benchmarked automatically. For a runtime you manage, disable its cloud features using `OLLAMA_NO_CLOUD=1` when starting Ollama, as described in the [official local-only instructions](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features). Inspect the installed names/digests with `curl http://127.0.0.1:11434/api/tags`, then substitute both values:

```bash
.venv/bin/python scripts/benchmark.py --model YOUR_INSTALLED_MODEL --digest YOUR_64_CHARACTER_DIGEST --save
```

Only `127.0.0.1` is accepted; `--port` selects another loopback port. The adapter disables client proxies and redirects, rejects remote-model metadata, checks digest stability around each call, and requests CPU inference with a bounded context/output and two threads. Each response is bounded to 1 MB with a 60-second read timeout and a 90-second checked wall-time budget (an in-flight read can add up to its timeout). Available memory is rechecked before each generation; less than 3 GiB or unavailable telemetry stops the run. This reserves 2 GiB plus 1 GiB headroom, **not** a model-fit guarantee. Run one benchmark CLI at a time; its independent process is not coordinated with the running web server's execution slot.

The model suite covers extraction, tool choice, grounded fields and abstention twice using fixed fictional evidence. Tool choices are scored as text; no tools execute. It records failures and stops on runtime/resource errors. No real model has been tested in this checkout. First-response latency, inference-process peak RAM/VRAM, runtime version, licence and language suitability remain unmeasured/unconfirmed; the report makes those limits explicit. No production model recommendation is made.

## Implementation

- `backend/api`: authenticated API; data routes require a local bearer key, with host/origin checks. No cookies or cross-origin access.
- `backend/adapters/fetch.py`: HTTP(S) only, public-address validation on every hop, pinned DNS connections, certificate/hostname verification, robots policy, size/time limits, no proxy environment inheritance. Cross-host redirects and HTTPS downgrades are rejected. One research request runs at a time.
- `backend/domain/extract.py`: deterministic HTML/contact candidates. No browser rendering, guessed emails or inferred WhatsApp numbers. Multiple headings leave the candidate name unknown. All extracted contacts require ownership review, including directory/operator contacts. `backend/domain/briefs.py` owns typed offer inputs and planning hypotheses.
- `backend/adapters/hardware.py`, `backend/evaluation`: read-only resource profiling and bounded, versioned synthetic benchmarks. `backend/adapters/local_model.py` is an explicit CLI-only loopback adapter; research never invokes it.
- `backend/storage`: SQLite foreign keys, transactional writes, immutable excerpts/revisions and host-scoped suppression. Versioned migrations apply at startup. Migration 002 adds benchmark storage; 003 adds briefs/research snapshots; 004 adds jobs, steps, controls, audit events and immutable queue/link scope; 005 adds identity/analysis revisions, evidence links and request receipts; 006 adds quality snapshots/audits; 007 adds approved-folder search/memory; 008 adds reviewed learning examples, version members, request receipts and split reservations; 009 adds PC pairings/tasks/leases; 010 adds reviewed local correspondence drafts and hash-only request receipts. Existing records, queues, notes and histories are preserved.
- `apps/web`: React interface, saved records, inspectable evidence and corrections.
- `planning/SPRINT_01.md`: verification evidence and remaining checks.
- `planning/SPRINT_02.md`: hardware/benchmark implementation and validation limits.
- `planning/SPRINT_03.md`: product brief implementation and validation limits.
- `backend/adapters/discovery.py`, `backend/workflows`, `backend/storage/jobs.py`: bounded source-link discovery, durable queue and transactional worker results.
- `planning/SPRINT_04.md`: queue/discovery implementation and acceptance limits.
- `backend/domain/assessments.py`, `backend/storage/assessments.py`, `backend/storage/assessment_views.py`: typed reviews, citation validation, immutable revisions, bounded comparisons and effective/stale states.
- `planning/SPRINT_05.md`: identity/analysis review implementation and acceptance limits.

Implemented API: `GET /v1/health`, `GET /v1/research`, `GET /v1/research/{id}`, `POST /v1/research`, `POST /v1/demo`, `POST /v1/feedback`. Research/demo POSTs require `Idempotency-Key`. Interactive single-page requests remain bounded and synchronous; persistent queue jobs use the separate API below and progress polling. SSE is not implemented. Input/policy errors have explicit messages; transient network failures return a retryable error and save no invented record.

Hardware API: authenticated `POST /v1/hardware/profile`, `POST /v1/benchmarks/parser`, `GET /v1/benchmarks`, `GET /v1/benchmarks/{id}`. Parser POST requires `Idempotency-Key` and accepts 2–200 rounds (`sample_count`, default 20). Reusing a key with different inputs returns 409. Parser benchmarks and research share the web server's single execution slot; overlap returns a retryable 429. Model inference has no HTTP endpoint in this sprint.

Brief API: authenticated `GET/POST /v1/briefs`, `GET/PATCH /v1/briefs/{id}`, `GET /v1/briefs/{id}/revisions`. Create and edit require `Idempotency-Key`; edit also requires `expected_revision`. Replays return the exact originally saved revision, even after later edits. An edited document contains `input`, `hypotheses` (text plus `unreviewed`/`kept`/`rejected`) and `verification_checks`; origin and prospect facts cannot be supplied. Research POST accepts either manual `product`/`location` or `brief_id`/`brief_revision`, never both. Demo POST optionally accepts the brief reference pair; all demo contacts remain fictional and labelled. `product_brief` on research is the frozen snapshot or null for manual/legacy records.

## Data and limits

Assessment API: authenticated `GET /v1/research/{id}/related`, `GET /v1/research/{id}/assessments/history`, `POST /v1/research/{id}/identity-review`, `POST /v1/research/{id}/need-analysis`. Both POSTs require `Idempotency-Key` and `expected_revision` (0 initially, then the saved revision). Stale revisions or conflicting key reuse return 409; invalid citation/input returns 422. Successful writes return the full current research record. Replaying an old successful request returns the latest record and never reapplies the old judgement. Identity and analysis revisions advance independently. Analysis responses include dependency/staleness state; saved fit must be interpreted with that state.

Queue API: authenticated `GET /v1/discovery/connectors`, `GET/POST /v1/jobs`, `GET /v1/jobs/{id}`, `POST /v1/jobs/{id}/control`. Create returns 202 before page access; it requires `brief_id`, `brief_revision`, a source URL (or `synthetic: true` without a source), the bounded optional budgets and `Idempotency-Key`. Control accepts `action: pause|resume|cancel` and an idempotency key. Create replays identify the same job and return its current progress. Control replays never reapply an old action after a newer one. Conflicting key reuse, stale briefs and invalid terminal-state controls return 409. Queue/body/input limits and source failures are explicit. Job detail exposes steps, result record IDs, source evidence, retry timing, events and coverage gaps. There is no arbitrary shell execution or model-driven tool selection.

Local data lives in ignored `.local/`: `leaddesk.sqlite3`, its WAL files and a private `access-token`. `LEADDESK_DATA_DIR` selects another directory. The access key is held in browser session storage; lock clears it. Stop the server and remove only `access-token` to rotate the key. Never share the key or commit local data. This is a single-user loopback app; internet deployment is outside this sprint.

Interactive research inspects one supplied HTML page. Queue research can inspect a bounded set of external candidate pages; nested links and linked contact pages are not recursively crawled. The fetcher also requests robots.txt, with at most four requests per redirect chain, a 1 MB body limit per response and a 20-second overall budget plus a possible final socket timeout. Robots failures stop access; 404 allows access. JavaScript pages, compressed-only responses, unsupported formats and restricted sources may require a different public page. Hidden HTML and inline hidden styles are excluded; external stylesheet visibility is not evaluated. Phone-like text can still contain false positives. Source headings and raw contact candidates must be reviewed for agency, directory and branch mismatches.

Raw page bodies are not saved. Evidence excerpts contain public contacts and are retained locally; automated retention, deletion UI and backup/restore are not implemented yet. Screen previews are explicitly requested and remain temporary in browser memory; voice recordings remain temporary for configured local transcription. Only explicitly saved reviewed notes persist as memory. No cloud inference, paid services, account integrations or training uploads are enabled.

### Any business type, contacts read from pages (Sprint 22, step 1)

**Find clients** can now search **574 business types** in 22 languages ("real estate", "inmobiliaria", "wedding hall", "خياط"). They are generated from the OpenStreetMap iD editor's open preset data (`scripts/build_category_catalogue.py`, ISC licence). Choose up to 12 types. **Find online** now opens up to 3 result pages that name the business (robots respected; social sites never opened) and reads their contacts. Each contact shows the page and the exact text it came from. See [Sprint 22](planning/SPRINT_22.md) and the [research and plan](planning/SPRINT_22_RESEARCH.md).

### Overture Maps, website grades and the new Find clients screen (Sprint 22)

Tick **Include Overture Maps** (free; read from the public Overture release with DuckDB and cached on this computer per area) to search millions more businesses with phones, emails, websites and social links. For example, 95 real estate businesses in Gulberg, Lahore, where OpenStreetMap had none. Results are ranked by a transparent **opportunity score** (no website +80, social page only +75, dead site +70, …; phone/email/social add reachability), shown as a list or a map, with filters. **Check website** now gives an **A–F website health grade** with every problem and its evidence. See [Sprint 22](planning/SPRINT_22.md).

**Verify contacts** labels each phone and email **Confirmed** (on their own website, or accepted by their mail server — no email is sent, and only if you tick that option), **Corroborated** (two independent sources), **Single source** or **Likely wrong** (invalid number for that country, rejected mailbox). **Competitors nearby** compares each business with the 5 nearest of the same type: website grade, booking, WhatsApp, social pages, with plain findings for your pitch.

