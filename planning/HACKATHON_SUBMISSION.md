# Devpost submission text: LeadDesk (Nebius × NVIDIA Global AI Hackathon)

Track: **Best Apps and Agents**. Fill in the three `[FILL IN]` items after you have run LeadDesk with your own Nebius Token
Factory key; only write what you actually saw.

---

## Tagline
Find the businesses that need what you sell — with evidence, checked contacts and a pitch NVIDIA Nemotron writes without making things up.

## Inspiration
Freelancers and small agencies sell websites, booking systems and marketing to local businesses. Finding those businesses
takes hours, and the result is often wrong: contacts that are fake, temporary or belong to someone else, and AI-written
"pain points" that are not true for that business. We wanted a lead tool you can trust enough to send what it writes.

## What it does
- Finds businesses of any type, anywhere (OpenStreetMap and Overture Maps; 574 business types in 22 languages).
- Reads each business's website properly: up to 6 pages, JavaScript sites in Chrome, the layout measured on a phone screen,
  "coming soon" and bot-check pages detected. Finds its Facebook and Instagram pages and contacts on the web (Tavily or a
  local search engine), and rejects same-named businesses elsewhere.
- Reviews every phone and email before you see it: approved, needs review or rejected, with reasons (temporary-email
  domains, placeholders, fake numbers, domains that take no email, one number shared by many businesses).
- Compares what you sell with what the business has (Has / Missing / Not seen, each backed by the page text) and writes a
  pitch and questions from those facts, every sentence citing its evidence.
- **NVIDIA Nemotron on Nebius Token Factory** rewrites the message so it reads like a person wrote it. LeadDesk checks every
  word: if the rewording adds a fact, a number, a promise or "as we discussed", it is rejected and the factual version is kept.
- Your corrections change results immediately and in future searches; repeated corrections become rules you approve; a
  quality report shows what is improving.

## How we built it
- FastAPI + SQLite modular monolith, React front end. Deterministic parsing and checks first; models only where language is needed.
- Nebius Token Factory through its OpenAI-compatible API with JSON-mode answers; only NVIDIA open models (Nemotron) are offered.
- Nemotron is used for message rewording (single and batch) and the market-problems summary, behind word-level evidence checks.
- Tavily as the search provider for "Find online", with domain filters for Facebook and Instagram.
- Website reading: robots-respecting fetcher with DNS pinning and SSRF checks; optional Chrome over its DevTools pipe with
  every request checked and screenshots deleted after 24 hours.
- 443 automated tests; a public demo mode with fictional data and capped AI use.

## Challenges
- Free search engines block automated searches quickly. We now detect it and say "incomplete" instead of "nothing found",
  and added Tavily.
- Same-named businesses: a Tunisian song and another organisation's Instagram were being attributed to a UAE restaurant.
  Results now need the place, type or a local phone number.
- Bot-check pages: Chrome was shown "Checking your browser" and measured that instead of the real site. Now detected and discarded.
- Keeping AI honest: the model may only reword facts LeadDesk proved.

## Accomplishments
- On our saved searches, the contact review rejected contacts whose domains do not exist; a live DNS check confirmed each one.
- Corrections that actually change the result, including the pitch, at once.

## What we learned
[FILL IN: e.g. how Nemotron's rewordings compared with a small local model on the same leads (acceptance rate shown in the quality report)].

## What's next
Measured accuracy from owner audits, more languages for messages, and team sharing.

## Feedback on Nebius Token Factory and NVIDIA models
[FILL IN after use: setup experience, model choice (Nano vs Super), JSON mode reliability, latency, rate limits, credits.]

## Built during the submission period
LeadDesk was built from 19 October 2026 (first commit), inside the submission period (26 August – 30 October 2026).

## Links
- Public repository: [FILL IN]
- Hosted demo: [FILL IN]
- Video (3 minutes or less, public on YouTube): [FILL IN]

## Built with
python, fastapi, sqlite, react, vite, nvidia-nemotron, nebius-token-factory, tavily, openstreetmap, overture-maps, duckdb, chrome-devtools-protocol, libphonenumber

---

## 3-minute video script
1. **0:00–0:20 Problem.** "Finding businesses that need your service takes hours, and the contacts are often wrong."
2. **0:20–0:50 Find and read.** Open the Camden demo search. Show the list, score badges and the map. Open Harbor Bean Café:
   layout findings, Has / Missing table with evidence links.
3. **0:50–1:30 Contact review.** Show approved vs rejected: the temporary email, the 020 0000 0000 placeholder and the number
   shared by three cafés. Mark one contact "Wrong → Fake" and show it move to Rejected.
4. **1:30–2:20 Nemotron.** In AI models, show the NVIDIA models listed from Nebius Token Factory and the consent box. Back on
   the lead, click "Reword with AI": show the Nemotron wording and that it was checked. Show one rejected rewording (a
   promise or new number) and the factual version kept.
5. **2:20–2:45 Corrections.** "Actually they have it" on a feature: the pitch is rebuilt. Approve the message. Quality report.
6. **2:45–3:00 Close.** Repo link, "MIT licence, runs locally or on Nebius."
