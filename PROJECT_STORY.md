## Inspiration

We build websites and software for small businesses in Lahore. Finding them was always the hardest part. A café with no website, or only an Instagram page, never posts "looking for a developer." The need is real, but it's hidden.

The lead tools we tried had two problems:

1. **They make things up.** Ask a language model for "cafés in Gulberg that need a website" and you get believable names, phone numbers and "pain points." Many of them are invented, or belong to a branch of the same chain in another city.
2. **They are paywalled or hosted in the cloud.** Most of them sit on top of the paid Google Places API, and your prospect lists and notes live on someone else's server.

So we wrote one rule before any code, and it is the first line of our `AGENTS.md`:

> Accuracy is first. Never invent business identities, contact information, … or test outcomes.

LeadDesk is our answer: a **local-first personal assistant** that finds real businesses that might need what you sell, and shows the evidence for every claim.

## What it does

You describe your product in any language and pick a place anywhere in the world. LeadDesk then:

- **Finds real businesses** from open data: OpenStreetMap, plus **Overture Maps Places** read locally with DuckDB. It covers 542 business types, named in 22 languages, so "Creamos páginas web para inmobiliarias" is matched to *Real Estate Office*.
- **Reads their websites properly.** It reads the home, Contact, About and Menu/Services pages, plus schema.org data. It records need signals (HTTPS, mobile layout, online ordering or booking, WhatsApp, an outdated copyright year) and gives each site a health grade. Every signal is cited to the page and text it came from.
- **Keeps businesses apart.** An identity cross-check compares name, phone, email, address, social profiles and branch pages, so *Lal Qila Lahore* is never mixed up with *Lal Qila Karachi*.
- **Verifies contacts.** A phone or email is *corroborated* when it appears in two or more independent sources. An opt-in mailbox check talks to the mail server but **never sends a message**.
- **Explains fit with local AI.** On **Ollama**, an *Analyst* agent writes a fit verdict, reasons, an opening line and discovery questions. A *Verifier* agent checks each reason. A *Market problems* agent summarises gaps that are common across a whole area. Every reason cites numbered evidence.
- **Acts as a personal assistant.** It has voice and typed commands, an on-demand view of your screen (with your permission), keyword search in folders you approve, memory you can edit and delete, and drafts for local email and calendar files that you review first.
- **Learns from you.** If you mark a contact as wrong, it is suppressed in future research. 👍/👎 on AI answers builds a labelled dataset for later evaluation.

## How we built it

**Stack:**
- Python 3.12 backend, built as a modular monolith on SQLite with versioned migrations
- React and Vite frontend
- Ollama in Docker for local inference
- Local SearXNG for web search
- DuckDB over Overture GeoParquet

Everything runs on `127.0.0.1` behind a local access key. We used no paid APIs and no cloud inference by default.

We built it in **22 short sprints**. Each one has a dated write-up with its test count, the hardware, real results and an honest "Not done" list.

**Rules before models.** Deterministic parsing always runs before any model call:

$$
\text{listing} \rightarrow \text{fetch + parse} \rightarrow \text{identity check} \rightarrow \text{verify contacts} \rightarrow \{E_1,\dots,E_{30}\} \rightarrow \text{LLM}
$$

The model sees only a bounded, numbered evidence pack, with each item at most 400 characters. It must answer in a strict schema: fit $\in \{\text{likely}, \text{possible}, \text{unlikely}, \text{unknown}\}$, with reasons that cite evidence IDs. An answer that cites an ID not in the pack is rejected.

**Grounding check.** For each reason $r$ with cited evidence $C(r)$, we compute the content words the reason uses but the cited evidence does not:

$$
U(r) = W(r) \setminus \Big( W(\text{name}) \cup \bigcup_{E \in C(r)} W(E) \Big)
$$

If $U(r) \neq \varnothing$, the reason is flagged ⚠ *"not found in cited evidence."* Facts LeadDesk collected beat the model's wording:

- If LeadDesk found no website but the model claims one, the reason is flagged.
- If the model says "likely" but also "already has something similar," the verdict is lowered to "possible."
- If the model says "no online ordering" but the crawler found an order link, the contradiction is flagged.

The Verifier agent can **lower** confidence, but never raise it.

**Explainable scoring.** Scores are additive, and every point has a visible reason. For example, website gaps that matter for your product add $\Delta = \min(3,\, g_{\text{relevant}})$. Verified phones add $+10$, single-source phones $+5$, and wrong ones $0$. The AI verdict is stored as a *proposal* and **never changes the rule-based score**.

**Typed tools, not free-form agents.** Agents run in fixed roles and use typed tools that pass policy checks. Deterministic code chooses every action, and the model never runs arbitrary commands.

**GPU-aware.** A model advisor probes `nvidia-smi` and the installed models. Our Ollama script turns on `--gpus all` automatically when it finds an NVIDIA GPU, and falls back to CPU otherwise.

<!-- TODO: if you ran LeadDesk on NVIDIA GPUs / Nebius for the hackathon, add the real numbers here:
     GPU type, model + digest, seconds per lead, sample count, date. -->

## Challenges we ran into

- **Small models overstate.** On real cafés our 3B model claimed "not mobile-friendly" for sites that declare a mobile viewport. It also invented a "previous discussion" in an opening line. For each failure like this we added a deterministic check, not just a better prompt.
- **Branches and redirects.** A map link for `/lahore/` redirected to the Karachi page, and the reader then picked the *Abu Dhabi* contact page. Now, on multi-branch sites, only a matching phone or street address can confirm a branch.
- **Wrong attribution from social posts.** A Facebook post by a *different* food business gave Café Delice that business's phone number. Contacts from other people's social posts are no longer attributed.
- **Sparse open data.** OSM had no phone, email or website for any of the six Gulberg cafés we searched. Public Overpass also returned HTTP 502 for days. Adding Overture and reading the result pages, not just the search snippets, closed most of that gap.
- **A 7.5 GiB laptop.** The first AI call was cut off at 60 s, and the model's own RAM was counted as "used." We fixed both. The first Overture download scanned every release file and took 126 s; reading only the one file covering the area brought it down to 25 s.

## Accomplishments that we're proud of

- **Real coverage from free, open data.** Some measured runs:

| Search | Before (OSM only) | With Overture |
|---|---|---|
| Real-estate agencies, Gulberg Lahore | 0 | **95**: 77 with phone, 57 with email, 40 without a website |
| Dentists, Westlands Nairobi | 12 | **149** |

- **Every factual claim is traceable** to a source URL and an excerpt. If a value is missing, it is shown as null with a reason, never guessed.
- **350+ automated tests.** Their fixtures reproduce real failures we saw live: branch redirects, name spacing variants, other businesses' sites, and unreachable domains.
- **Honest benchmarks.** Every result records the hardware, model digest, configuration, sample count and date. Our AI runs used `llama3.2:3b` Q4_K_M at temperature 0 and seed 0. Analyst plus verifier took 112–129 s per business on an i5-8265U with no GPU, and we say exactly that.
- **Fully local and private by default.** It needs no account, no paid API and no cloud upload.

## What we learned

- **Verifiers should only ever lower confidence.** One rule, "a second pass may downgrade, never upgrade," removed a whole class of hallucinated "likely" verdicts.
- **Open data is better than expected once you merge sources.** We match records on the same phone within 2 km, or a strong name match within 250 m. The combination beat either source alone.
- **Evidence IDs are a UX feature, not just a safety feature.** People trust a lead they can click through to its source.
- **A number without metadata is a story, not a result.** Writing down the hardware, model, sample count and date kept us honest.
- **Write down what is *not* done.** A "Not done" list in every sprint stopped us from claiming progress we hadn't measured.

## What's next for LeadDesk personal assistant

- **Bigger models on NVIDIA GPUs:** run 7–8B models and measure their accuracy against our 👍/👎-labelled answers.
- **Deeper website audits:** full Lighthouse scores, and rendering for JavaScript-heavy sites.
- **Competitor comparison per lead:** "here's where your product would beat what they have."
- **A pipeline board** from prospect to interested prospect to customer, with outreach drafts you review before anything is sent.
- **Careful local fine-tuning:** train only on reviewed corrections, evaluate before every release, and keep a way to roll back.
