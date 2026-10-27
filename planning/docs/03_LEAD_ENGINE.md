# Lead discovery, contact quality and analysis

## Pipeline
1. Parse the runtime offer and geography. Preserve the original user request.
2. Generate buyer hypotheses, exclusion rules and evidence checks.
3. Query permitted source adapters. Cache results with freshness metadata.
4. Resolve official domains and business/branch identities before joining contacts.
5. Fetch bounded pages: home, contact, about, relevant service pages and explicit linked business profiles.
6. Extract deterministic facts; use a model only for ambiguous text or analysis.
7. Corroborate contacts and investigate conflicts.
8. Evaluate unmet need and existing alternatives.
9. Produce a ranked shortlist, unknowns, evidence and rejection reasons.
10. Recheck selected contacts before outreach; record outcomes separately.

## Source strategy
Use official business pages, relevant directories/associations, public business registers, permitted search APIs, map data where appropriate, and product-specific public records. No single source guarantees completeness. Each adapter declares access terms, allowed operations, quotas, geographic coverage, cost and freshness limitations. Free data availability is a constraint, not an assumption.

Map discovery can find candidate cafés but may not identify specialist software buyers. Tender-tool buyers may be found through award records, supplier categories and company service pages. Different offers generate different strategies without hardcoded sectors.

## Contact rules
Store raw value and normalised value. Phone normalisation requires a known region; do not guess a country from an ambiguous number. Validate syntax separately from attribution. A well-formed number is not proof that it is reachable or belongs to the company.

Email: parse visible public business emails; MX/DNS checks only indicate domain configuration. Do not label a guessed email verified. Catch-all domains and mailbox deliverability remain unknown unless reliable confirmation exists. Avoid intrusive probing as a default.

WhatsApp: identify only explicit business WhatsApp links or published statements. A mobile number alone is insufficient. Decision-maker name/role requires its own evidence; a shared reception number is labelled as such.

Contact state transitions:
- extracted: appeared in a source, attribution pending;
- attributed: credible source links it to this business/branch;
- corroborated: independent credible evidence agrees, no unresolved conflicts;
- directly_confirmed: documented interaction confirms ownership, with date and method;
- disputed / stale / invalid: excluded from approved outreach until resolved.

Two directories copying the same listing are not independent corroboration. An official source may support attribution without a second source; display that evidence honestly rather than inventing corroboration. Recycled numbers remain a residual risk even after checks.

## Identity resolution
Match official domain, trading name, address, branch and registration information where available. Shared franchise domains and shared call centres require branch mapping. A directory's own phone or agency contact must not become the prospect's contact. Ambiguous matches go to review. Record merges reversibly and preserve original evidence.

## Need analysis without public buying requests
For each hypothesis store: observed fact → likely operational problem → how this offer helps → existing solution → competing explanation → confidence label → missing verification.

Example, fictional: a café's public booking link fails and recent customer feedback describes booking difficulty. This supports investigating booking improvements. It does not establish that a new website is the only solution. The business may use a working third-party service or be fixing the link already.

Never infer financial capacity from neighbourhood, ethnicity or a polished logo. Public scale indicators can inform prioritisation but are not budget confirmation. Unknown budget is acceptable.

## Ranking
Hard exclusions first: wrong geography, disputed identity, invalid contact, explicit mismatch or suppression. Then rank product fit and evidence quality separately from contact confidence and purchase intent. Initial ranking is a transparent heuristic, not a calibrated probability. Do not show '92% likely to buy' without a validated model and appropriate data.

## Output per prospect
Business/branch, location and service area, website, contacts and labels, available role names, observed problem, offer relevance, alternatives, intent state, budget unknown/confirmed, source excerpts/URLs, retrieved_at, last_checked_at, next action, rejection reasons and review status.

## Stop conditions
Stop at the campaign's time/page/source budget or when eligible sources are exhausted. Return fewer good prospects with a coverage report rather than fabricate results. Report unavailable connectors and incomplete checks explicitly.
