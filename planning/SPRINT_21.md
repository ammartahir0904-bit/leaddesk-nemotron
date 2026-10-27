# Sprint 21 — read websites properly, keep businesses apart, research agents

Date: 20 October 2026, Asia/Karachi. The user asked LeadDesk to read each business's website properly (Contact and About pages, plus structured business data), cross-check sources so similarly named businesses are not mixed up, and add real need signals. They also asked for Ollama agents that make the results more accurate and more useful for finding market problems to build products for.

## Delivered
- **Deep website read** (`backend/domain/site_reader.py`, `site_read_v2`). **Check website** reads the home page plus up to three pages from the same site (Contact, About, Menu/Services/Shop). Each page goes through the existing robots-respecting fetcher. On multi-branch sites the page naming the searched area wins (Lahore over Karachi). A failed extra page is recorded, never fatal. Each page keeps its URL and SHA-256.
  - **Structured data:** schema.org JSON-LD business entities, including `@graph` and nested departments/locations: name, types, phones, emails, addresses, sameAs, price range, menu, reservations, order actions, and the rating with its review count (self-published).
  - **Need signals**, each with the page URL and the text that triggered it: HTTPS, mobile viewport, online ordering/shop (text, same-site paths, delivery-app links, OrderAction, page title/description), online booking (text, scheduling widgets, ReserveAction), contact form, WhatsApp link, structured data, title/description, copyright year (stale if two or more years old) and platform. "not_found" means not seen on the pages read.
  - **Relevance:** a gap is marked "matters for your product" when the product description shares its topic words (for example ordering, booking, SEO), or when it is a website basic for website offers. Relevant gaps add +1 each, at most +3, with visible reasons.
  - Also recorded: the redirect from the map's link (and any path words it dropped) and the branch sections the site links to.
- **Identity cross-check** (`backend/domain/identity.py`, `identity_cross_check_v1`). Compares the map entry, the website and web findings on name (including spacing variants like "Lal Qila"/"Lalqila"), phone (last 9 digits), email, website link, address (two shared distinctive words required), social profile and branch page.
  - Verdicts: confirmed, probably_same, name_only, possible_other_branch, different_business, unverified.
  - On multi-branch sites, only phone or street address can confirm a branch, because the website, email domain and social pages are shared by every branch.
  - A website that may be another business or branch earns no points and is kept out of the AI evidence.
- **Social-only "website":** a map entry whose website is an Instagram/Facebook page is treated as "no own website". It becomes a need signal for website offers (+2) and is never read as a site.
- **Unreachable website:** a listed site that does not resolve or returns 404/410/5xx is saved as a dated finding (+2 for website offers). `example.com → www.example.com` redirects are followed by reading the www address.
- **Research agents (Ollama), with fixed roles and typed tools; the model never chooses actions:**
  - **Research top 3** (`POST /searches/{id}/research`, limit 1–10): find online → read website → AI analysis, per business. Automation only uses a web-found site whose name fully matches. Finished businesses are skipped; step failures are listed.
  - **Analyst:** the Sprint 20 fit analysis, now given the identity result, website checks, structured data and Contact/About/offer text (30 items, 6,144-token context). Statements that contradict the website check ("no online ordering" when an order link was found) are flagged.
  - **Verifier:** a second model pass sees each reason with only its cited evidence and labels it supported, partly or not supported. It can lower "likely" to "possible", never raise anything. Skipped reasons are shown as unchecked (`ollama_fit_analysis_v2`).
  - **Market problems** (`GET/POST /searches/{id}/market`). Deterministic counts over researched businesses: no website, each website gap, unreachable sites, AI fits. Other-business sites are excluded. **Find problems (AI)** turns the counts into up to 4 problems that must cite count/business IDs, each with a product idea and a validation question. Unsupported wording is flagged; the results are saved as proposals (migration `015_market.sql`).
- UI: identity badge and details, signal list with source links, pages read, redirect note, verifier marks per reason, Research top 3 and the Market problems panel. The CSV gains identity, website gaps and AI fit.
- Clean-up: removed one unused helper and five unused test imports (pyflakes and oxlint report no unused code).

## Real results (this laptop)
Host: i5-8265U, 7.5 GiB RAM (about 3.5 GiB free during AI runs), no GPU. Ollama 0.40.6 in Docker, `llama3.2:3b` Q4_K_M, digest `a80c4f17…b5b8b72`, temperature 0, seed 0, 6,144 context. Search: cafés and restaurants in Gulberg, Lahore (public OpenStreetMap, 68 named businesses). Five had their own website listed; two were analysed, so this is a sample of 2 analyses, not a benchmark.

| Business | First run | After fixes |
|---|---|---|
| Lal Qila | **Wrong:** the map's `/lahore/` link redirected to the Karachi page, the reader picked the Abu Dhabi contact page, and Karachi/UAE phones were attributed to a Lahore lead. It was called "probably the same" from shared email/website and one address word. | Reads the Lahore Garden Town branch pages and detects 5 branch sections. Verdict: possible_other_branch, so no details are attributed until a phone or street matches. |
| Uncle Tetsu | Online ordering "not found", although the page title says "Online Ordering" (the site is JavaScript-built). | Ordering "yes", cited from the title. Confirmed (name, email, map link). |
| Kruncheese | Refused: apex → www redirect. | www page read; confirmed. |
| Patakha Express | Error, nothing saved. | Saved as "listed website could not be loaded" (domain does not resolve). |
| P.F. Chang's Pakistan | HTTP 403 (site blocks automation). | Unchanged; reported, not bypassed. |

AI on the two first-run analyses: 112 s and 129 s wall time per business, analyst plus verifier (about 1,000–1,430 prompt tokens). Market summary: 79 s.
- Both answers claimed "not mobile-friendly" while the site declares a mobile viewport. The new contradiction check flagged both.
- The verifier answered for only 1 of 4 reasons each time. Its prompt now requires every reason ID, and skipped reasons are shown as unchecked; this fix has not been re-measured live.
- Market counts reused one site's wording ("on the 1 page read") for multi-site totals; they now use generic gap wording.
- Several reasons were bare signal labels (for example "Website platform"). This is a 3B-model limitation and not fixed.

## Verification evidence
- **343 tests pass**, including 15 Sprint 21 tests. The fictional fixtures copy the live failures: branch redirect, name spacing, weak address, title ordering, unreachable site, www redirect and an other-business site excluded from the AI. They also cover structured data, the signals, the verifier only lowering confidence, cited market problems and the full API sequence with a fake model.
- Frontend build passes. Browser flows were **not** rerun this sprint.
- After the fixes, the live checks above were rerun without AI. The AI analyses were not rerun after the fixes.

## Not done
- No browser acceptance run for the new UI.
- The verifier and analyst are still 3B on CPU; a 7–8B model on the stronger PC is unmeasured.
- JavaScript-only sites show little text to this reader (no headless browser).
- Address matching is word overlap, not geocoding. Branch detection relies on URL sections, multiple schema.org addresses or the words "branches/locations/outlets".
- No training; 👍/👎 verdicts are still being collected.
