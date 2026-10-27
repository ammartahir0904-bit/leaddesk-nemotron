# Sprint 19 — find each business online (web and social pages)

Date: 20 October 2026, Asia/Karachi. The user asked for details from the internet (websites, social media pages, contact cards) for businesses found anywhere in the world, and chose **SearXNG on my PC** as the free web search source.

## Delivered
- **Local search engine:**
  - `scripts/searxng.sh start|stop|status` runs the official `searxng/searxng` Docker image on `127.0.0.1:8888` only, with `deploy/searxng/settings.yml`: JSON output on, the public-instance limiter and image proxy off, and a random secret generated on each first start.
  - With the user's approval it was downloaded and started: image 384 MB, digest `sha256:5ed0323b…eae271`. It keeps running until `scripts/searxng.sh stop`.
  - `LEADDESK_SEARXNG_URL` may only point to this computer.
- **Find online** for one business, or **Find online for top 10** (limit 1–20, sequential). Each business gets two queries, `"name" area, city` and `"name" area facebook OR instagram`. `backend/domain/enrichment.py` then sorts the results:
  - **Own website:** only a domain containing a distinctive word of the business name (or the website listed on OpenStreetMap). Blogs, marketplaces and directories go under **Mentioned on**.
  - **Social profiles:** only profile pages (Facebook, Instagram, LinkedIn, TikTok, X, YouTube…) whose handle resembles the name. Posts, reels, videos and other people's pages count as mentions. Profiles are **linked, not scraped**: Facebook and Instagram require login and restrict automated access.
  - **Contacts:** emails and phones in result titles and snippets, only from results that name the business. Each keeps its source URL and is labelled **Their own page** or **Lower confidence: another page mentioning the name**. Duplicates written differently are merged, and everything runs through the Sprint 18 email/phone analysis.
  - **Points:** +1 each for an own website, a social profile and a contact on their own page.
- **Check this website** runs normal research on a website found online. Only URLs found for that business are accepted.
- Phone analysis now checks national number lengths for 12 countries, flags numbers that look joined together, and recognises country codes written without `+`.
- The results header shows whether the search engine is ready, and warns that business names and location go to the engines SearXNG uses. CSV export gains website, social and web-contact columns. Migration `013_enrichment.sql`.

## Real results (Gulberg, Lahore cafés, 20 Oct 2026)
- 10 businesses enriched in **22.3 s** (two queries each; Brave and Google CSE answered through SearXNG).
- **Arcadian Café:** own website `arcadiancafe.com`, Instagram and Facebook profiles `arcadiancafe`, and mobile **(number redacted) from its own Instagram profile** (WhatsApp link). A second number came from another page and is shown as lower confidence.
- **Cafe Costa:** own Facebook page `cafecosta.lhr` and a `wordpress.com` site. Numbers from **Costa Coffee Pakistan** (a different business with a similar name) appear only as lower-confidence mentions: the exact business/branch mismatch the rules must not hide.
- **Uncle Tetsu:** `uncletetsu.pk`; a food blogger's Facebook video and Instagram reels are mentions, not profiles.
- Several cafés: "No web results clearly name this business." Coverage depends on what the public web has.
- The first live run treated blogs and property sites as websites and a blogger's video as the café's Facebook page. The rules above were tightened from that real output, and tests now cover those cases.

## Verification evidence
Host: i5-8265U, 7.5 GiB RAM, Python 3.12.3, Node 24.21.0, Chrome 151, Docker 29.8.0.
- **323 tests pass** in 137.8 s (5 new enrichment and search-client tests using a fake SearXNG; contact tests extended; migration counts now 13).
- All **8 browser flows pass**. A headless Chrome screenshot of the enriched card was checked (the Claude preview pane's own screenshots came out blank after scrolling, a pane rendering artifact; the DOM and the headless capture were correct).

## Limits
- Search snippets can be stale or belong to similarly named businesses; open the source before contacting.
- No Facebook or Instagram scraping, no login, no "business card" image reading (OCR) yet.
- No AI model or Hugging Face model is used yet; matching is rule-based. Results depend on the engines SearXNG reaches, which can rate-limit.
