# Sprint 22 research: finding businesses that need what you sell

Status: research and plan. **Step 1 (A + C1) is built; see [SPRINT_22.md](SPRINT_22.md).** Steps 2–5 are not started. Dated 2026-10-24. Licences, prices and quotas below come from web sources found on that date. Check each one again before building on it.

## 1. What the app is meant to do (owner's words, restated)

> Find businesses that exist but **lack the digital product I sell** (e.g. a real-estate agency with no website). If they *do* have one, show **where mine would be better**: find the flaws in their site, see what already exists in their market, and propose how we would make it best. Also find their **phone, email and other contact details** online.

## 2. Why it falls short today (from the code)

| Problem the owner sees | Root cause in the code |
|---|---|
| **Categories too short** | `backend/domain/prospecting.py:17` hard-codes **34** categories, with 1 to 4 OSM tags each. For example, "Real estate" is only `office=estate_agent`. Offer-to-buyer mapping is a fixed list of 15 keyword sets (`SUGGESTIONS`). Anything outside them, such as wedding halls, schools of a specific kind, car rental, property developers or tailors, can't be searched except by name keyword. |
| **No phones/emails found** | Contacts come from only three places: (1) OSM tags, which are very sparse in many countries; (2) the business's own website, *if* it has one; (3) the **title/snippet text** of SearXNG results (`enrichment.py: snippet_contacts`). Result pages, even directory or listing pages that clearly show a phone number, are **never opened**. Businesses without a website, which are exactly the best prospects for a website offer, therefore end up with almost no contacts. |
| **Weak website flaw finding** | `site_reader.need_signals` checks whether things are *present*: HTTPS, viewport tag, booking/ordering words, form, WhatsApp, schema.org, title/description, copyright year, platform. It never measures **quality**: speed, Core Web Vitals, accessibility, broken links, image weight, outdated tech, or design. |
| **No "my product is better" comparison** | Nothing compares a prospect with **its local competitors** or with a **feature checklist for the product being sold**. The AI step can only restate the few presence signals it is given. |
| **No market availability check** | Nothing searches for existing providers, apps or platforms for the product in that city. The "Market problems" step only counts gaps across the businesses already researched. |

## 3. What others do (research)

### Commercial tools aimed at exactly this ("businesses with no website")
- **No-Website Lead Finder** (Apify actor): Google Maps by category and city, keeps only listings with no website, and scores 0–100 using "missing-signal" tags. <https://apify.com/santhej/nowebsite-lead-finder>
- **BirdSift**: plain-language query → Google Places. Flags no website, social-only, outdated, not mobile-optimised and quality issues; exports CSV. <https://www.goodfirms.co/software/birdsift>
- **BizVoid**, **SiteSeeker**, **FindLeadly**: no-website filter, plus audits of businesses that *have* sites and drafted pitches. SiteSeeker also generates a website-builder prompt for each lead. <https://hunted.space/product/bizvoid>, <https://hunted.space/product/siteseeker-2>
- **WebHunter** (indie, Spain): treats a Facebook or Instagram page used as the "website" as a lead, and adds a Kanban pipeline. <https://www.indiehackers.com/post/5cc8a2d16c>

**Lesson:** all of them start from **Google Maps/Places**, which has far better phone, website and review coverage than OSM. They then (a) filter on the website field, (b) audit sites that exist, and (c) write a pitch. LeadDesk already does (c) with evidence checks, which is better than they do. It loses on (a) data coverage and (b) audit depth.

### Open-source building blocks

| Need | Project | Notes |
|---|---|---|
| Rich business listings | **Overture Maps Places**: <https://docs.overturemaps.org/guides/places> | 64M+ places with **websites, phones, socials, emails** and categories. Free GeoParquet; licence CDLA-Permissive-2.0 (some sources CC0/Apache). Can be queried **locally with DuckDB** by bounding box, with no account or key. Biggest single win. |
| Rich business listings | **Foursquare OS Places**: <https://foursquare.com/resources/blog/data/evolving-fsq-open-source-places/> | 100M+ POIs, Apache-2.0, 6-level category tree. Now needs a free portal token. |
| Category catalogue | **openstreetmap/id-tagging-schema** | The preset list used by iD, StreetComplete and Go Map!: hundreds of business presets with names, aliases, search terms **and translations**. Replace the 34 hand-made categories with a searchable catalogue generated from it. |
| Google Maps listings | **gosom/google-maps-scraper**: <https://github.com/gosom/google-maps-scraper> | MIT, about 6.8k★, Docker plus local web UI/REST API, 36 fields per place, optional website email crawl. **Scraping Google may breach Google's ToS.** Only an explicit, user-run, opt-in adapter. Never on by default. |
| Google Maps (official) | **Google Places API (New)** | Phone and website fields bill at the *Enterprise* tier: about 1,000 free calls/month, then about $35 per 1,000 (2026 price list, <https://developers.google.cn/maps/billing-and-pricing/pricing>). Paid, user's own key, opt-in only (AGENTS.md: no silent paid services). |
| Website quality | **Lighthouse** (Apache-2.0) / **PageSpeed Insights API v5** | PSI is free with a key, reported at about 25,000/day (<https://unlighthouse.dev/learn-lighthouse/pagespeed-insights-api/rate-limits>). Lighthouse can also run locally with Chrome, with no key. Gives performance, accessibility, SEO, best-practice scores and Core Web Vitals, each audit with its own explanation, so every result is citable. |
| Tech stack / outdated software | **enthec/webappanalyzer**: <https://github.com/enthec/webappanalyzer> | Open continuation of the Wappalyzer fingerprints (JSON regexes over HTML, headers, scripts). Detects WordPress or jQuery versions, Wix, page builders, missing analytics and the like. Check its licence before bundling the data. |
| Contact crawling | **Crawl4AI** (Apache-2.0, Python, Playwright) | Renders JavaScript sites to clean Markdown for the extractor and the local model. Useful for JavaScript-heavy sites that the current httpx reader sees as empty. |
| Email deliverability | **reacherhq/check-if-email-exists**: <https://github.com/reacherhq/check-if-email-exists> | AGPL-3.0 Rust, Docker HTTP backend. SMTP check without sending mail. Run it as a separate user-started service, so LeadDesk code isn't AGPL-linked. Results are estimates (catch-all servers), and probing from a home IP can harm reputation. Opt-in only. |
| Site age / last change | **Wayback Machine availability/CDX API**: <https://archive.org/help/wayback_api.php> | Free. First-seen and last-capture dates are dated evidence for an "old website" claim. Better than the copyright-year guess. |

Sources for search results: [gosom](https://github.com/gosom/google-maps-scraper), [Code-Media-Labs](https://github.com/Code-Media-Labs/google-maps-scraper), [Overture places](https://docs.overturemaps.org/guides/places), [FSQ OS Places](https://foursquare.com/resources/blog/products/foursquare-open-source-places-a-new-foundational-dataset-for-the-geospatial-community/), [Reacher](https://github.com/reacherhq/check-if-email-exists), [webappanalyzer](https://github.com/enthec/webappanalyzer), [Lighthouse](https://developer.chrome.com/docs/lighthouse/overview), [OSM craft key](https://wiki.openstreetmap.org/wiki/Key:craft), [OSM office key](https://wiki.openstreetmap.org/wiki/Key:office).

## 4. Proposed plan, ordered by impact

Each item keeps the project rules: evidence IDs for every claim, null plus a reason when unknown, typed tools, explicit opt-in for network, paid or third-party services.

### A. Categories that cover any business (fixes "too short")
1. Generate `backend/domain/category_catalogue.json` from id-tagging-schema presets for the `shop`, `amenity`, `office`, `craft`, `tourism`, `leisure` and `healthcare` keys. This gives hundreds of types, each with aliases and search terms, and translations available.
2. Replace the 8-checkbox picker with a **searchable multi-select** ("estate" → Estate agent, Property developer, Property management…). Keep groups.
3. Offer → buyer suggestions: keep the deterministic keyword map, but match against catalogue **terms/aliases** instead of 15 hand lists. Optionally ask the local model to *rank* catalogue entries; it may only pick IDs that exist, so nothing is invented.
4. Free-text fallback: "type anything". Name and `description` regex over Overpass, plus Overture category text.

### B. A second free data source with real contacts (fixes "no numbers/emails")
1. New adapter `backend/adapters/overture.py`: DuckDB `read_parquet` over the Overture places release, filtered by the geocoded bounding box. Gives websites, phones, socials, emails and confidence. Cache the extract locally for each area.
2. **Merge** OSM and Overture records with the existing identity cross-check (`identity.py`), using name similarity, distance, phone and domain. Each field keeps its source; any conflict is shown, never silently resolved.
3. Optional, off by default, clearly labelled: Google Places API (user's key and cost shown), and gosom scraper (user-run Docker, ToS warning).

### C. Contact discovery that actually opens pages
1. For search results that name the business with a `strong` match, **fetch the page** (same SSRF and robots rules as the site reader, bounded to N pages) and run the existing extractor on the full text, not the snippet. Directory and listing pages become `mention` confidence with their URL.
2. **Domain guessing** for businesses with no listed site: `name.com`, `name.<country TLD>`, `namecity.com` → DNS check, then fetch, then a name match on the page. This proves "has a site OSM didn't know about", or strengthens "no website found".
3. Read `tel:`, `mailto:`, `wa.me` and footer contacts on every page read. Run JavaScript-rendered sites through an optional Crawl4AI/Playwright path.
4. Email quality: keep MX, add optional Reacher SMTP check (user-started service). The label is "deliverable / risky / unknown", never "verified".

### D. A real website audit (fixes "AI doesn't find the flaws")
A **Website report card** for each prospect site, every line linked to evidence:
- Lighthouse or PSI: performance, accessibility, SEO, best practices, LCP/CLS/INP, page weight, and the top failing audits (each has a title and description from Lighthouse).
- Tech fingerprint (webappanalyzer): CMS or builder and version, an outdated jQuery or PHP banner, missing analytics or pixel, no CDN.
- Wayback: first seen and last changed.
- Content checks: broken internal links, images without alt text, missing pages for the offer (e.g. no listings page), no contact or lead form, no reviews or testimonials.
- Optional screenshot plus local vision model (e.g. `llava`/`qwen2.5-vl` in Ollama) to describe design age and clutter. It is labelled as an **opinion**, and the screenshot is temporary, per AGENTS.md.

### E. "Why mine is better": offer feature packs and competitor comparison
1. **Offer feature pack**: the user, or the local model from the product description, lists the features their product delivers. For a real-estate website, for example: property search with filters, map view, listing pages, WhatsApp enquiry, lead form, virtual tour, agent profiles, mobile speed. The pack is editable and saved with the product brief.
2. For each prospect, check each feature against the pages read: **has / missing / not seen**, with evidence.
3. **Local competitor benchmark**: from the same search (same category and area), take the 3–5 strongest sites, by report-card score and feature count, and build a matrix: *you vs. the best near you vs. what we deliver*. This is the concrete pitch: "2 agencies near you show property search and WhatsApp enquiry; your site has neither."
4. **Market availability check**: SearXNG queries such as `"<product type>" <city>` and `site:play.google.com <category> <city>` list existing providers, apps or platforms in the market. The result is shown as "already available here" or "nothing found", with links. It never proves absence.

### F. Solution proposal per prospect
The AI step receives the report card, the feature-pack gaps and the competitor matrix, all as cited evidence. It outputs an **improvement plan**: the top 3 fixes, what we would build, a website-builder or mockup prompt (like SiteSeeker), an opening line and questions. It can't state impact numbers, prices or budgets: those stay null, with a reason. The existing strict checker pass still applies.

### Scoring update
Priority points become transparent per part: **need** (no site, social-only, poor report card, missing features), **reachability** (verified phone, deliverable email, WhatsApp) and **identity confidence**. Each part is shown with its reasons. Budget stays unknown.

## 5. Suggested build order

| Step | Scope | Why first |
|---|---|---|
| 1 | A (catalogue) + C1 (open result pages) | Small, no new services, fixes the two most visible complaints. |
| 2 | B (Overture + merge) | Biggest data coverage jump, still free and local. |
| 3 | D (report card: PSI/Lighthouse, fingerprint, Wayback) | Turns "has a site" into concrete flaws. |
| 4 | E + F (feature packs, competitor matrix, improvement plan) | The actual "mine is better" pitch. |
| 5 | Optional adapters (Google Places, gosom, Reacher, vision) | Opt-in, each with cost or ToS disclosure. |

Each step ships with tests for business or branch mismatch, contact conflicts and evidence failures, and benchmarks that record hardware, configuration, sample count and date, as AGENTS.md requires.

## 6. Decisions needed from the owner
1. ~~Overture Maps?~~ **Approved by the owner, 2026-10-24.** Owner also requires: worldwide, free and open-source only (so no Google Places API).
2. Do you want the **Google Places API** (paid after the free tier, your key) and/or the **Google Maps scraper** (free, but against Google's ToS) as opt-in options, or neither?
3. **PageSpeed Insights API** (free key, sends the prospect's URL to Google) or **local Lighthouse** (no key, needs Chrome, slower)?
4. Main target country? It decides the TLDs for domain guessing and which directories to trust (current code hints at Pakistan: foodpanda.pk, olx.com.pk, etc.).
