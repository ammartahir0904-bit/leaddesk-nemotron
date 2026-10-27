# Sprint 18 — contact analysis, AI model advisor, simpler menu

Date: 20 October 2026, Asia/Karachi. The user asked which Ollama models are set up and how they help, asked for analysis of each business's email and phone, wanted system-specification checks with model recommendations for a stronger PC, and asked to remove unneeded parts of the interface.

## Facts at the start
- **No Ollama models were set up.** Ollama is not installed on this laptop. The existing `OllamaAdapter` is used only by a script for drafting product briefs and by the model benchmark, not by any screen.
- This laptop: Intel Core i5-8265U, 7.5 GiB RAM, Intel UHD 620 integrated graphics (no NVIDIA GPU).

## Delivered
1. **Contact analysis** for every business found (`backend/domain/contact_analysis.py`, `backend/adapters/dns_mx.py`):
   - **Email:**
     - format check;
     - generic inbox (info@, sales@…) vs named mailbox vs no-reply;
     - free mail vs own domain vs disposable;
     - whether the domain matches the business website (a warning flags possible web-agency or directory addresses);
     - **mail-server (MX) lookup** through the system resolver, using a small built-in stdlib DNS client with no new dependency. It detects "has MX", "null MX" (RFC 7505: accepts no mail), "no MX" and "domain does not exist". The mailbox itself is not verified.
   - **Phone:**
     - international (E.164) form using the search country, which now comes from Nominatim `addressdetails` for about 40 countries' calling codes and trunk prefixes;
     - mobile vs landline for 11 numbering plans, judged by the number's own country code;
     - WhatsApp `wa.me` links only for mobile or unknown lines;
     - ambiguous numbers are flagged ("check the area code"), never guessed.
   - **Points:** +1 when the email domain can receive mail, +1 for a mobile number. Results show "Reachable by …".
   - **Check website:** contacts found on the business's site are analysed too.
2. **AI model advisor** (`POST /v1/hardware/advisor`; `backend/domain/model_advisor.py`, `backend/adapters/model_probe.py`). It reads RAM, CPU, disk, NVIDIA GPUs (fixed `nvidia-smi` query, 5 s timeout), the integrated/AMD graphics label, and whether Ollama is installed and running with which models (loopback only).
   - It recommends one main model plus `nomic-embed-text` from a catalogue of 7 Ollama models with approximate 4-bit sizes. Each model shows its fit (GPU / CPU / too big / no disk), speed expectation, role and what LeadDesk uses it for, with **planned** uses marked as planned.
   - Install commands are shown; nothing is downloaded or installed.
   - On this laptop it reports "Light laptop (CPU only)", Intel integrated graphics, Ollama not installed, and recommends `llama3.2:3b` + `nomic-embed-text`. Fake 32 GB CPU-only and 12 GB GPU machines produce `llama3.1:8b` and `qwen2.5:14b`. Run it on the stronger PC to get that machine's advice.
3. **Simpler menu.** The main items are Find clients, Leads, Website research, Email and calendar, and AI models and hardware. Files and memory, Voice, Screen context, Product briefs, Research queue, Quality baseline, Learning and datasets, and PC workers moved under **More tools**. The section stays open across reloads and opens automatically when one of its screens is active. Nothing was deleted.

## Verification evidence
Host as above, Python 3.12.3, Node 24.21.0, Chrome 151.
- Full suite: **318 tests pass** in 75.2 s (310 earlier plus 5 contact-analysis/DNS tests and 3 advisor tests; prospecting tests now use a fake MX lookup and assert analysis and points).
- 15 voice and 13 screen JS checks pass. Build passes. **All 8 browser flows pass** after updating them for the new menu: they open More tools after unlocking, and one heading match is now exact.
- **Live check** on a disposable instance: "coffee shop websites" + Gulberg, Lahore + cafés returned 15 cafés, country `pk`, via the Nominatim fallback (Overpass busy again). Examples:
  - Turkish Restaurant & Cafe: Gmail address, MX present, "good"; its phone "357855773" was flagged to check the area code.
  - Drip – Coffee Brewery & Bakery: phone formatted in E.164 (number redacted), mobile, with a WhatsApp link.
- The advisor was checked live on this laptop through the screen.

## Not done
- **Internet and social-media enrichment** (finding each business's website, Facebook or Instagram page, and phone numbers listed elsewhere) needs a web search source. Waiting on the user's choice of provider; see the handoff.
- No AI model is called by the lead pipeline yet; semantic matching and need analysis are listed as planned. No Hugging Face integration, training or reinforcement learning.
- MX shows the domain accepts mail, not that the mailbox exists. Mobile detection covers 11 numbering plans only.
