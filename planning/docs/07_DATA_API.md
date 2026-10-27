# Data model and API contracts

## Storage conventions
UUID identifiers; UTC timestamps with timezone-aware display; schema_version on saved model outputs; null for unknown values; immutable evidence references. Use parameterised queries and migrations. Initial SQLite foreign keys and transactional writes enabled. One coordinator owns writes. Full-text search first; vector index is optional and rebuildable.

## Core entities
| Entity | Important fields |
|---|---|
| campaign | id, user_request, product_brief, geography, exclusions, budgets, status |
| business | id, canonical_name, trading_names, official_domain, branch_id, address, service_area, identity_status |
| campaign_prospect | campaign_id, business_id, fit_label, intent_state, review_state, rank_reason |
| contact | id, business_id, type, raw_value, normalised_value, role, attribution_state, last_checked_at, suppressed |
| evidence | id, source_url, publisher, retrieved_at, published_at_if_known, excerpt, content_hash, extraction_method |
| claim | id, subject_id, predicate, value, evidence_ids, inference_flag, contradiction_state |
| job | id, campaign_id, step, status, lease_owner, lease_expiry, attempts, idempotency_key |
| file_record | id, canonical_path, approved_root, hash, modified_at, extraction_status |
| memory | id, type, content, scope, source_id, expiry, supersedes_id |
| feedback | id, target_type, target_id, run_id, category, expected_value, evidence_ids, reviewed |
| model_run | id, model_hash, prompt_version, tool_versions, input_refs, output, timing, resource_metrics |
| experiment | id, dataset_version, base_hash, adapter_hash, config, evaluation_id, promotion_state |
| external_action | id, provider, scope, payload_hash, approval_ref, idempotency_key, provider_id, status |
| suppression | id, contact_or_business, channel, reason, created_at |

Evidence-to-claim and contact-to-evidence are many-to-many joins. One business may appear in many campaigns with different fit assessments. Never overwrite universal business facts with campaign-specific opinions.

## Proposed HTTP API v1
| Method/path | Purpose |
|---|---|
| GET /v1/health | Liveness and component status |
| POST /v1/hardware/profile | Inspect authorised local hardware |
| POST /v1/models/benchmark | Queue a bounded benchmark |
| POST /v1/campaigns | Save request and draft brief |
| PATCH /v1/campaigns/{id}/brief | Correct targeting assumptions |
| POST /v1/campaigns/{id}/runs | Start idempotent research job |
| GET /v1/campaigns/{id}/prospects | Cursor-paginated results |
| GET /v1/prospects/{id} | Details, claims, evidence, contacts |
| POST /v1/jobs/{id}/cancel | Cooperative cancellation |
| POST /v1/files/search | Search approved index |
| POST /v1/desktop/actions | Execute typed, scoped action |
| POST /v1/feedback | Persist correction and disposition |
| GET/POST /v1/memories | Inspect/create scoped memories |
| DELETE /v1/memories/{id} | Delete and invalidate retrieval |
| POST /v1/experiments | Queue reviewed training/evaluation |
| POST /v1/models/promotions | Promote only after gates |
| POST /v1/models/rollback | Restore known model version |
| POST /v1/actions | Prepare/execute scoped external effect |

All state-changing requests require authentication/CSRF protections appropriate to the client; localhost is not automatic trust. POST job/action requests accept Idempotency-Key. Invalid input returns 422, policy conflict 403, state/version conflict 409, budget/quota exhaustion 429 where appropriate. Long jobs return 202 with job_id; progress uses SSE. Do not hold an HTTP request open for a whole campaign.

## Example grounded analysis output (synthetic)
```json
{
  "schema_version": "1",
  "business_id": "fixture-business-01",
  "fit_label": "review",
  "observations": [{"text": "Booking link failed during inspection", "evidence_ids": ["fixture-evidence-01"]}],
  "need_hypothesis": "Booking support may be useful",
  "alternative_explanations": ["Temporary outage", "Another booking channel exists"],
  "intent_state": "unknown",
  "budget": null,
  "missing_checks": ["Check alternative booking channel"]
}
```

Validate JSON schema and referenced IDs. Reject nonexistent evidence IDs. A valid JSON structure is not proof of factual correctness. Limit repair attempts and mark unresolved output as failed.
