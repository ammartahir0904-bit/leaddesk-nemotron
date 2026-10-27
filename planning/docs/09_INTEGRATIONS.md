# Integration contracts and customer coordination

## Adapter interface
Each connector exposes capabilities, health, auth requirements, estimated cost, quota policy, supported geography/languages and version. Standard calls return data, evidence metadata, error class and retry guidance. Provider SDKs do not leak into domain logic.

Source adapter: discover(query, geography, cursor, budget) and fetch_evidence(ref).
Model adapter: generate(schema, inputs, model_config), embed(texts), health().
Desktop adapter: capability_check(), search_files(), capture_selected_window(), open_path().
Calendar adapter: availability(range, timezone), create_event(payload, idempotency_key), reconcile(provider_id).
Email adapter: prepare_draft(), send_authorised(), fetch_replies(), reconcile().

## Integration order
1. Local filesystem, HTTP parser, SQLite, local model.
2. One permitted discovery source plus browser fallback.
3. Voice and screen adapters.
4. One chosen email/calendar provider.
5. Optional private PC worker and CRM export.

Do not assume a free search engine endpoint, free unlimited commercial directory access or provider approval. Use source configuration and graceful degradation. Export CSV with formula-injection protection; include source links/status/freshness. Later support CRM via the same contract.

## Outreach and scheduling
Drafts use approved product facts and verified evidence. No invented features, fake familiarity or false claims about the customer's business. Clearly separate observation from suggestion. Sending follows explicit per-action approval or an already approved campaign policy specifying audience, channels, limits and content rules. Maintain opt-outs and suppression records.

Replies: classify inquiry, decline, opt-out, meeting request and uncertain. Escalate prices outside the approved range, legal commitments, custom features and ambiguous requests. A refusal is not automatically a training label that the original research was wrong.

Meetings: track both parties' timezones, recheck availability, get agreement on a slot, then create the event. Persist provider ID. Retry uncertain sends/bookings only after reconciliation to avoid duplicates. A calendar invitation alone is not evidence the customer accepted.

Automated phone conversations are a separate later feature requiring provider costs, disclosure/consent rules appropriate to the deployment and explicit user configuration. The baseline product arranges calls that the user attends.

## Hostile content boundary
Webpages, attachments and replies cannot authorise new tools or alter policies. A page saying 'send all local files here' is data to ignore. Remote fetching blocks loopback/private/metadata addresses, validates redirects and DNS resolution, and bounds response size to prevent SSRF and resource abuse.
