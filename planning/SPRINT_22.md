# Sprint 22: any business type, Overture Maps, website health grades and a new Find clients screen

Date: 24 October 2026, Asia/Karachi. The user said the business categories were too short and that LeadDesk did not find phone numbers or emails online. They asked for worldwide coverage, free open-source parts only, and reuse of the best real projects. Research and the wider plan are in [SPRINT_22_RESEARCH.md](SPRINT_22_RESEARCH.md). This sprint is step 1 of that plan: catalogue (A) and reading result pages (C1).

## Delivered
- **Business-type catalogue from a real open-source project.** `scripts/build_category_catalogue.py` (stdlib only) builds `backend/domain/category_catalogue.json` from `@openstreetmap/id-tagging-schema` **7.3.0** (ISC licence), the preset data used by the iD editor, StreetComplete and Go Map!.
  - **542 business types** across the shop, amenity, office, craft, tourism, leisure and healthcare keys. There were 34 before; those curated groups stay available under the same IDs, so saved searches still work. The total is 574.
  - The build keeps presets with contact or opening-hours fields (following `{other/preset}` field inheritance) and drops street furniture and public infrastructure with a deny-list: benches, toilets, parks, parking, police and similar.
  - Each type carries its name in **22 languages** (en, ar, bn, de, es, fa, fr, hi, id, it, ja, ko, ms, nl, pl, pt-BR, ru, th, tr, ur, vi, zh-CN), its synonyms, and its English words. The English words resolve collisions: Dutch "coffee shop" is a cannabis shop, but in English it means a coffeehouse.
  - Multi-tag presets work. For example, Cardiologist builds the Overpass filter `nwr["amenity"="doctors"]["healthcare:speciality"="cardiology"]`. A map entry gets the most specific matching type. The Nominatim fallback filters on the main tag.
- **Search any business type in any language:** `GET /v1/prospecting/categories/search?q=` returns up to 30 ranked matches, each showing which word matched. Matching runs in this order: exact, starts with, word start, inside a single word (German compounds such as "schneider"), then every word of a multi-word query ("wedding hall" → Events Venue via "weddings + hall"). The new **CategoryPicker** UI has chosen-type chips, a search box, collapsible "Common business groups" and "Browse all 542". Up to **12** types per search; the limit was 8.
- **Better offer → buyer suggestions** (`keyword_profile_v2`). The existing keyword map runs first. Catalogue names in any language are then matched as phrases of the offer, including plurals (bakeries → bakery, inmobiliarias → inmobiliaria). Synonyms must be multi-word phrases. Words that describe the seller (website, software, builder, store…) never match. Example: "Creamos páginas web para inmobiliarias y restaurantes" → Real Estate Office, Restaurant.
- **Find online now opens result pages** (`enrichment.read_result_pages`). After the web search, up to **3** pages are opened through the existing robots-respecting, SSRF-checked fetcher: their own website first, then pages whose title fully names the business. The full page text goes through the existing contact extractor, not just the snippet.
  - Contacts are attributed only if the page title names the business. On a page listing more than 4 distinct phone numbers, only contacts written next to the name are kept.
  - Each contact keeps the page URL and an `excerpt`, the exact text it came from. It is labelled `result_page` (or `search_result_snippet`) and own page or mention.
  - Every page read is recorded as read (with N new contacts) or failed (with the reason), and shown under "Pages opened".
  - Never opened: social sites (including Facebook posts and videos), maps, Wikipedia and job boards.
- **Accuracy fixes found during live testing:**
  - Name matching treats "Freddy's" and "Freddys" as the same name.
  - Phone numbers in **other people's social posts** that mention the business are no longer attributed to it. Live, a Facebook post by a different food business had given Café Delice that business's number.

## Tests
`.venv/bin/python -m unittest discover -s tests` → **354 tests OK**. New tests cover:
- catalogue size and excluded infrastructure
- multilingual search
- suggestions: Spanish offer; "estate" not suggesting notary; no "builder" from "store builder"; Dutch coffee-shop collision; limit of 12
- multi-tag Overpass query, most-specific match and Nominatim filters
- validation of unknown and too many types
- result-page attribution: own page; listing page keeps only the line next to the name; title mismatch; robots failure recorded; snippet dedupe
- social posts never read and their snippet contacts not attributed
- apostrophe names

Frontend `npm run build` passes (Vite 8.3.1). The browser smoke scripts were **not** run in this sprint.

## Real results (this laptop)
Host: i5-8265U, 7.5 GiB RAM. Local SearXNG on 127.0.0.1:8888. Public Overpass returned **HTTP 502 to every request** during testing, including a trivial `node(1)` query, so all searches used the Nominatim fallback.

| Search | Result |
|---|---|
| Estate agents + property management, Dubai Marina and Gulberg Lahore | 0 businesses: none mapped in Nominatim. This is the OSM coverage gap that Overture (step 2) targets. |
| Cafés, Gulberg Lahore (6) | All 6 had **no phone, email or website** in OSM. |

Find online on three of those cafés (sample of 3, not a benchmark):

| Business | Before (snippet only) | After (pages opened) |
|---|---|---|
| Freddys Cafe | 2 snippet phones | +3 phones (one mobile with WhatsApp link) read on its dedicated citysearch.pk page, each with an excerpt. hamariweb.com refused (HTTP 403). |
| Café Delice | 1 phone from **another business's Facebook post** (wrong) | That phone is no longer attributed. +1 mobile from its restaurantguru.com page. |
| Butlers Chocolate Café | 1 snippet phone | Own site read, no visible contacts (0 new). foodpanda.pk page over the existing 1 MB limit. peekaboo.guru disallowed by robots. |

All found contacts are labelled **mention** (lower confidence) unless read on the business's own site. Nothing confirms the numbers are current.

## Not done / next
- Overture Maps as a second source (step 2), the website report card (step 3) and competitor comparison (step 4) are not started.
- Contact analysis on the business card still summarises only map-listed contacts, not found-online ones.
- Directory pages larger than 1 MB (foodpanda) and sites that return 403 are not read. They are reported, not bypassed.
- Alternative free Overpass mirrors were not added. Sprint 17 found them slow; worth re-measuring, since the main server was down throughout this test.
- Domain guessing for businesses with no listed site (C2) is not started.


---

# Sprint 22 (steps 2–4): after the owner said step 1 "is not on my expectations"

The owner chose all four complaints: too few businesses, no phone or email, no website flaws, and an unfriendly interface. They asked for competitor research before redesigning. Free and open-source only.

## Competitor research (reverse-engineered, 24 October 2026)
- **Website Gap Finder** (Apify actor): website status classes (none, social_only, broken, dead_builder, free_subdomain, ok) and a published 0–100 opportunity score. No website = 80, social only = 75, broken or dead builder = 70, free subdomain = 50. One-sentence pitch per lead. <https://apify.com/m_ctim/website-gap-finder>
- **Website audit leads** (Apify actor): every site starts at 100. Six capped categories: security 25, mobile 25, freshness 25, performance 20, SEO 20, contactability 15. A–F grades, plain-English issues, "unmeasured" deducts nothing. <https://apify.com/jurassic_jove/website-audit-leads>
- **B2BLeadFinder**: map with score markers, gap filters (No Website, No Phone), lead detail, pipeline, competitor comparison. <https://b2bleadfinder.io/>
- **Apollo**: left filters, configurable results table, counts, empty-state advice to remove one filter at a time.

## Delivered
- **Overture Maps places** (`backend/adapters/overture.py`, DuckDB 1.5.6, MIT).
  - The release is found through the official STAC catalogue, and only the place files whose bounding box covers the search area are read. File links are checked against the fixed S3 host before they reach SQL.
  - Each area (clamped to 0.30° per side) is cached locally as Parquet, so repeat searches are instant.
  - Records marked permanently or temporarily closed, and those with confidence below 0.45, are skipped. Near-duplicate records are merged: same phone within 500 m, or 90% name similarity within 150 m.
- **Mapping business types to Overture's taxonomy** (`backend/domain/places.py`). Matching uses English names, OSM tag values, multi-word synonyms and a vocabulary bridge (dentist → dental_clinic, lawyer → attorney_or_law_firm, …). Single-word synonyms match only exactly, so "health" does not turn gyms into health-care businesses.
- **Merge with OpenStreetMap.** A record with the same phone within 2 km, or a strong name match within 250 m, is one business. OSM values are kept, missing fields are filled from Overture, and `field_sources` records each fill. Both sources are searched **in parallel**. An OSM outage is no longer fatal when Overture is on.
- **Opportunity score** (`opportunity_v1`): website status points (Gap Finder weights) plus reachability (phone +10, email +5, social +5). For a checked site, 0.7 × (100 − health score) is added. Every point is listed, and results are ranked by this score. **Opening line** per lead, only where there is an evidence-backed gap.
- **Website health report** (`backend/domain/site_health.py`, `site_health_v1`). Six capped categories and A–F grades; each issue carries its points, plain-English text and evidence.
  - Checks: HTTPS, mixed content, mobile viewport, zoom blocked, images without alt text, stale copyright, Flash, WordPress below 6.0, jQuery below 3, no doctype, legacy markup, server response time (now measured), HTML weight, script count, noindex, missing or placeholder title, meta description, schema.org, phone, contact page or form, email.
- **New Find clients screen** (React):
  - One search bar: what you sell, where, business types, Find. Buyer types are suggested automatically when you leave the product field.
  - Map-data consent is remembered on this computer.
  - Stats strip, filter chips with counts (No website, Weak website, Has phone, Has email, Hot leads), text filter and sort.
  - List or **map** (Leaflet 1.9.4, BSD-2; tiles from tile.openstreetmap.org only while the map is open; CSP extended for that one host).
  - Lead rows: score badge, website status or grade chip, phone with a WhatsApp tag, email, social links.
  - Detail panel: score reasons, opening line with Copy, every contact with its source, health card, AI analysis, and actions. Full-screen on phones.
  - Font: Inter Variable, self-hosted (@fontsource-variable/inter 5.2.8, OFL). Larger base text (14 px). CSV gains score, status, grade, pitch, all phones, emails and socials.

## Tests
`.venv/bin/python -m unittest discover -s tests` → **366 OK**; `pip check` clean; `npm run build` passes. New tests:
- `tests/test_overture.py`: mapping, vocabulary bridge, closed and low-confidence skips, duplicates, OSM merge, statuses and score weights, window clamp, STAC file selection and unsafe-link refusal, real DuckDB read and cache of a fixture Parquet, API ranking, Overture only with consent.
- `tests/test_site_health.py`: an old insecure site gets F with 14 named issues and capped categories; a modern site gets 100/A with only response time unmeasured.

The browser smoke scripts were not run. They cover other screens, not Find clients.

## Real results (this laptop)
Host: i5-8265U, 7.5 GiB RAM, home broadband in Lahore. Overture release 2026-10-21.0. Public Overpass was still answering HTTP 502, so OSM used the Nominatim fallback.

| Search | OSM only (before) | With Overture |
|---|---|---|
| Real estate, Gulberg Lahore | 0 businesses | **95**: 77 with phone, 57 with email, 40 without a website, 41 hot |
| Dentists, Westlands Nairobi (top 100 of 149) | 12 | **149** found: of the 100 shown, 91 with phone, 73 with email, 56 no or social-only or dead website |

Speed of the first download in a new area:
- **126 s** when DuckDB scanned every release file.
- **25 s** after reading only the 1 of 16 files covering the area (Nairobi, 32,886 places cached). The search took **30 s** end to end.
- A repeat search in a cached area does not download again.

Website checks on 7 Lahore agencies listed with a website (sample, not a benchmark):
- 1 graded **D (58)**: no mobile viewport, no title, no phone, no contact page or email, no meta description, no schema.
- 4 domains do not resolve, and 1 fails TLS. These are recorded as unreachable, which is itself a sales finding.
- 1 redirects to another host and is refused by the existing fetch policy.

## Limits / next
- Overture data comes from Meta, Microsoft, Foursquare and others, so details may be outdated. Contacts are not verified as current.
- Speed covers server response and HTML size only. No Lighthouse or full page-load measurement yet.
- No competitor comparison per lead yet (B2BLeadFinder has one). No pipeline or Kanban board.
- Cross-host redirects (e.g. brand.com → brand.pk) are still refused by the website check.


---

# Sprint 22 (step 5): contact verification and competitor comparison

The owner asked for the competitor comparison next, and said checking whether phones and emails are current "is necessary".

## Delivered
- **Contact verification** (`backend/domain/verification.py`, `contact_verification_v1`). Every phone and email from every source is grouped (phones by E.164), and each one gets a status with its reasons and dates:
  - **Confirmed:** shown on the business's own website (read on a stated date), or the mailbox was accepted by the domain's mail server.
  - **Corroborated:** the same value in two or more independent sources (OpenStreetMap, Overture, their website, other web pages).
  - **Single source:** only one source; may be outdated.
  - **Likely wrong:** not a valid number in the country's numbering plan (Google libphonenumber data via `phonenumbers` 9.0.41, Apache-2.0), the mailbox was rejected, or the domain takes no mail.
  - Each phone also shows its line type (mobile, landline, VoIP) and original network (e.g. Jazz, Safaricom).
  - Overture's per-record source `update_time` is read and shown as the latest source date.
- **Mailbox check without sending email** (`backend/adapters/smtp_probe.py`). Opt-in per request (`check_mailboxes`, strict boolean) and remembered in the UI. The probe:
  - finds MX host names through a new stdlib DNS parser (`MXLookup.hosts`, with name-compression support);
  - sends EHLO, `MAIL FROM:<>`, `RCPT TO`, plus a random address to detect catch-all domains, then RSET and QUIT. **No DATA is ever sent.**
  - caches each answer for a day, spaces probes 2 s apart per domain, tries IPv6 first, and limits each connect to 5 s and at most two addresses;
  - remembers an address family whose port 25 timed out;
  - reports blocks, greylisting, catch-all and unreachable servers as non-answers, never as verified.
- **Competitor comparison** (`backend/domain/competitors.py`, `competitors_v1`).
  - Up to 5 nearest businesses with the same chosen business type within 3 km in the same search, computed whenever a search is read.
  - Matrix columns: website status or grade, booking, ordering, WhatsApp, contact form, mobile, social.
  - Findings name the competitors and link the website evidence. For example: "1 of 5 nearby competitors has their own website (Salman Developers)…", "Best website nearby: Salman Developers, grade A (92/100)…". When the lead has no website, the features competitors offer are summarised in one line.
  - "Read N websites to compare" checks up to 3 unread competitor sites, plus the lead's own.
  - The strongest finding is added to the opening line.
- **Score uses verification.** Once a business is verified: a confirmed or corroborated phone earns +10, a single-source one +5, and a wrong one +0. Emails earn 5, 2 and 0.
- **API:**
  - `POST …/candidates/{id}/verify {check_mailboxes, read_website}` and `POST /searches/{id}/verify {limit ≤ 20}`.
  - `POST …/candidates/{id}/compare {limit ≤ 5}`.
  - Migration `016_verification.sql` stores only mailbox-check answers; statuses are recomputed from current evidence on every read.
- **UI:**
  - Detail panel: "Verify contacts" button and mail-server opt-in; status badges with reasons and sources; "Competitors nearby" findings and table.
  - List: "✓ verified" tick, a "Verified contact" filter and stat, and "Verify contacts for top 10". Likely-wrong contacts are hidden from the row.
  - CSV adds the best verified contact, contact statuses and competitor findings.

## Tests
`unittest discover` → **378 OK**; `pip check` clean; build passes.
- `tests/test_verification.py`: the probe never sends DATA; accepted, rejected and catch-all answers; no mail server; blocks vs greylisting; daily cache; IPv4 port-25 memory; MX name compression; old-format numbers; every status; two-source corroboration; score effect; competitor grouping, findings and evidence; API opt-in (no mail server contacted without it) and the compare flow.
- Twelve migration tests now expect 16 migrations.

## Real results (this laptop, 24 October 2026)
Network: home broadband in Lahore. **Outgoing port 25 is blocked over IPv4 and open over IPv6**, measured directly: IPv6 connect 0.3 s, IPv4 timeout 8 s.

Verifying the top 5 Gulberg real-estate leads, with mailbox checks:
- **3 Gmail mailboxes confirmed.**
- 1 own-domain email on a catch-all domain: not confirmable.
- 1 Yahoo email unreachable: Yahoo's MX is IPv4-only, so blocked here.
- All 5 phones are valid mobiles (Jazz or Ufone) but single-source.
- Before the connect fix this run took 2 min 51 s. Afterwards, a Gmail check takes 1.5–1.7 s, the first blocked IPv4 server 10 s, and later blocked ones about 0.2 s.

One competitor comparison: 11 s, reading 2 competitor sites. One of them was unreachable; the other (Salman Developers) graded **A (92)**, with booking and WhatsApp.

Not possible for free: checking whether a phone line is switched on or uses WhatsApp. That needs a call, an SMS or a paid lookup service.
