# Sprint 17 — find clients by product and location

Date: 20 October 2026, Asia/Karachi. The user pointed out that the core goal was missing: give the app your product and a location, and it finds businesses that could buy it. Until now every lead had to be found by hand. This sprint adds that discovery step, free, with no account or API key.

## What the user can do now

**Find clients** is the first sidebar item, and the app opens on it after unlock.

1. **What do you sell?** Describe the product and optionally give your own website. `POST /v1/prospecting/profile` reads the description and the site's title, meta description and visible text (scripts excluded). It returns product keywords, an offer type, and suggested buyer types with reasons. For example, "coffee" suggests cafés, bakeries and restaurants; "tenders, procurement" suggests builders, trades, architects, companies and IT firms. Suggestions only; the user picks. No AI model is used.
2. **Where and which businesses?** Any city or area worldwide, up to 8 of 32 business types (well-established OpenStreetMap tags), an optional name keyword and a maximum of 1–100 results. The user must tick a consent box on each search: the location text and business types go to public OpenStreetMap servers. The API refuses a search without `use_public_osm: true` (strict boolean).
3. **Results** (`POST /v1/prospecting/searches`, saved with idempotent replay): name, type, address, phone, email, website, opening hours, and a link to the OpenStreetMap entry as evidence with retrieval time and ODbL attribution.
   - **Priority points** (transparent, not a probability): +1 each for a listed phone, email or website. For web/online offers, +2 when no website is listed, shown as "a possible need — verify; OSM data may be incomplete".
   - **Budget** is always `null` with a reason. A brand/chain tag is shown as a signal only.
   - Duplicates (same name and address, phone or about 100 m position) and unnamed entries are removed, with the counts shown.
   - CSV download, saved searches, open and delete.
4. **Check website** runs the existing website research on a business's listed site. Contacts and evidence are saved as a normal research record, then linked back. The panel reports which of your product words appear in the saved page excerpts, worded so that a missing word is not proof of absence.

## Data sources and reliability (measured today)

- **Nominatim** (geocoding and fallback search) answered every request in about 1 s. Requests are limited to one per second, and geocodes are cached in `geocode_cache`, as Nominatim's usage policy asks.
- **Overpass**: the main public server answered "at capacity" (HTTP 502) in testing. Two public mirrors did not answer within 100 s; maps.mail.ru answered once in about 32–40 s and timed out on a later try. The app therefore tries the main Overpass server once (30 s limit). If it fails, it runs bounded Nominatim searches: one per tag, at most 12 queries and 40 results each, limited to the place's boundary (points padded to about 3 km), keeping only results that carry the requested tag. Results say which source was used, and the fallback adds a coverage note.
- **Real check:** "We build modern websites with online ordering for coffee shops and cafes" + "Gulberg, Lahore, Pakistan" + cafés, maximum 15. Result: **15 named cafés** via the Nominatim fallback (30 returned, 2 unnamed skipped, 13 beyond the maximum). Top result: an address on MM Alam Road with a listed phone and email and no website, so +2 possible need. A café with a listed website was checked: the page was fetched and saved, with 0 contacts and no offer words in the excerpts, probably because content is rendered by scripts. An earlier direct Overpass query (mail.ru mirror) returned 27 named cafés in the same 3 km area, and most had no phone or website listed. **OpenStreetMap contact coverage for small shops in Lahore is thin.**

## Other fixes

- The extra menu item pushed the sidebar's saved-research list under other sidebar elements, so those items couldn't be clicked; the main browser test caught it. The sidebar now scrolls instead (`style.css`).
- Migration `012_prospecting.sql` (searches, geocode cache, website-check links). Earlier migration-preservation tests now expect 12 migrations.

## Verification evidence

Host: Intel Core i5-8265U (8 threads), 7 GiB RAM, Linux 6.8.0-136, Python 3.12.3, Node 24.21.0, Chrome 151.

- Full `.venv/bin/python -m unittest discover -s tests -q`: **310 tests pass** (303 earlier plus 7 new in `tests/test_prospecting.py`) in 124.5 s. The new tests use a fake OpenStreetMap transport and never touch the network. They cover:
  - profiling, including website text without scripts;
  - query building, including name-keyword escaping and refused injection;
  - ranking, deduplication, possible-need wording and null budget;
  - save, replay and key-conflict handling, and the geocode cache (second search makes no Nominatim call);
  - Overpass 502 falling back to bounded Nominatim, with tag filtering, address mapping and viewbox;
  - consent and validation refusals, authentication, website profile and private-address refusal;
  - website check (no website gives 409), linking, and search deletion that keeps the research.
- `scripts/run-browser-flows.sh`: **all 8 prepared flows pass** on the final run. During the sprint, `learning` failed once with HTTP 429 on its first request to a fresh instance, then passed 4 times in a row. The cause is not identified; this is recorded as an intermittent issue.
- Manual browser check of the new panel on a disposable instance, with the real searches above: the product read, the search, the result cards with no sideways scrolling at a 548 px viewport, and the website check. There is no scripted browser flow for this panel yet, because its search depends on live public servers.

## Not done / honest limits

- **Coverage:** OpenStreetMap misses many businesses and most phone numbers and emails in places like Lahore. Better shop coverage needs a paid source such as Google Places, which requires the user's own key; not added.
- **Need and fit are signals, not verdicts.** No AI model judges need yet; the local Ollama adapter exists but isn't wired here. Affordability is not inferred.
- Outreach, meetings and calls still stop at local drafts. Screen, voice and learning gates are unchanged.
