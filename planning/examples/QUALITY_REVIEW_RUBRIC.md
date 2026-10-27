# Saved-source quality review rubric — version 1

This rubric scores frozen predictions against their saved public-source excerpts. It does not establish independently verified identity, contact reachability, buying intent, budget or release readiness. A model must never supply its own ground-truth label. Keep unknowns visible.

## Select the sample before scoring

Use at least three unrelated runtime offers and two target geographies. The release plan calls for at least 60 manually reviewed real prospects. Include apparent fits, no-need cases, good existing solutions, closed branches, copied listings, same-name businesses, directory-operator contacts, wrong branches and wrong phones. Do not require public requests to buy software. Choose a development or reserved holdout sample deliberately; holdout is a user declaration, not proof of blindness or independent selection. Avoid repeatedly tuning to it.

Select one saved record per source URL. This prevents exact-page repetition but does not resolve independent business/branch entities. Record any related-page or same-business correlation and selection bias. Do not manufacture a sample or repeat fixtures to reach 60. Synthetic examples stay in a separate mode and contribute zero real reviews. Freeze predictions before auditing; later corrections require a fresh baseline for current-system evaluation.

## Verdict meanings

- **Pass:** the reviewer judges the captured target supported within this saved-source scope. Cite its source evidence and explain why. For contacts, source publication and ownership are separate questions.
- **Fail:** the reviewer finds a specific mismatch, unsupported statement or wrong attribution. Cite the captured target's evidence and explain the problem; additional captured comparison evidence can support the explanation. A fail is useful evaluation data and remains in the denominator.
- **Unknown:** available excerpts cannot resolve the question. Do not turn ambiguity into pass or fail just to complete a sample. Keep the missing check in the reason/notes.
- **Unreviewed:** no judgement has been recorded for that target. Missing and explicitly unknown outcomes are shown separately. Neither counts as correct.

Every known judgement needs a reviewer label, reason and scoped evidence IDs. Labels are user supplied, not verified reviewer identities. Quality revisions do not correct live lead data; use its correction/review workflow separately. To revise a judgement, save a new audit revision rather than changing the frozen prediction.

## Audit each dimension separately

**Identity:** score the captured source-attributed business/branch prediction. Does the cited source identify this entity and branch? Distinguish official/business pages, shared brands, directories and agencies. Resolve same-name and shared-host ambiguity with captured comparison excerpts where available. A page heading alone may name the publisher or another business. An unresolved identity is an abstention, not an accurate attribution; it remains unknown here.

**Contact ownership:** does this exact contact belong to the stated business/branch, under the saved source evidence? Cite that contact's own excerpt. Check directory/agency numbers, shared reception lines, branch wording, copied listings, closed branches and existing corrections. A well-formed email/number or a source-publication pass is not an ownership pass. Only effective attributed contacts enter attribution precision; extracted, disputed and excluded values are abstentions/exclusions. Review those values too for a complete case, without promoting them into a prediction.

**Factual evidence support:** inspect each saved heading/contact-publication fact, identity quote, observed quote and existing-solution quote. Does its own cited excerpt support that exact claim without changing its meaning or entity? Reference presence alone is structural, not semantic proof. Need hypotheses, offer relevance, fit, intent and budget are not factual source units in this report. Do not introduce nonexistent source IDs or outside evidence the baseline did not capture.

**Offer relevance:** judge whether investigating this offer is relevant to the captured business/context. Check geography, exclusions, current solutions, alternatives, competing explanations and missing verification. A good existing solution or closed branch can support a negative judgement. Weak evidence stays unknown. A positive judgement is an inference about relevance, never confirmed demand, interest, willingness to pay or budget.

Tag scenarios/errors explicitly and explain them. Tags are descriptive reviewer flags, not independent proof that scenario coverage or factual correctness has been established.

## Read the report conservatively

Inspect every offer/location segment, its eligible count, reviewed count, failures, unknowns and missing reviews. A fully reviewed case requires known identity, relevance, contact and factual-support judgements; abstained identity remains incomplete. Audit revisions do not increase sample count.

Known pass/fail rates are descriptive; Wilson 95% intervals assume independent Bernoulli trials. Pages/contacts and reviewer decisions can be correlated. Nonrandom sample selection and source errors remain limitations outside that interval. Proposed thresholds are unchanged: identity/contact agreement and audited factual support at least 95%, factual reference coverage 100%. An observed point estimate meeting a target is not adequate sample size, statistical certification or overall release acceptance.

Unranked relevance is not precision@20. A genuine ranked shortlist and segment-specific adjudication are required for that gate. Outreach/file-search/retry gates require their respective implementations and evaluations. Independent real-source adjudication, browser/live acceptance and unresolved critical failures remain explicit follow-up work.
