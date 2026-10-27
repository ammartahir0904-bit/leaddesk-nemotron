# Accuracy and release evaluation

All numbers below are initial proposed gates, not measured performance or promises. Maintain a test report with sample counts, errors and uncertainty. Small datasets cannot justify universal accuracy claims.

## Definitions
Business identity accuracy: correctly matched businesses / reviewed businesses.
Contact attribution precision: contacts correctly associated with the stated business/branch / reviewed contacts.
Prospect precision@20: user-labelled relevant prospects among top 20 / 20.
Evidence support: supported factual claims / checked factual claims.
Coverage: usable records relative to a defined reviewed candidate set, not the unknowable entire worldwide market.
File success@3: tasks with correct accessible file in top three / evaluated file tasks.

## Initial evaluation set
At least three unrelated offers and two geographies; include local service, B2B software and tender-monitoring scenarios. Public buying requests must not be required. Include positives, no-need businesses, good existing solutions, closed branches, copied directories, same-name businesses and wrong phone cases. Start with at least 60 manually reviewed prospects and expand before broader claims.

Reviewers use recorded evidence and explicit rubrics. Mark unresolved examples unknown, not correct. Preserve source freshness and avoid repeatedly tuning to the held-out set. Contact ownership requires reliable adjudication; online-only checks cannot establish call reachability in every case.

## Proposed release gates
| Metric | Initial target |
|---|---|
| Factual claims with evidence references | 100% |
| Audited factual claims actually supported | At least 95% |
| Contact attribution precision | At least 95% on reviewed sample |
| Known disputed contacts in approved queue | Zero |
| Prospect precision@20 | At least 80% per tested offer/location segment |
| Duplicate outbound actions in retry tests | Zero |
| Fabricated file paths/contacts in fixtures | Zero |
| Local file success@3 | At least 90% on a representative 30-task set |

These gates do not certify every contact or guarantee demand. Show per-segment metrics and confidence intervals where practical, not only a flattering average. Do not loosen a gate silently to pass a release.

## Critical regression scenarios
Wrong branch with same brand; directory operator number; duplicate listing copied across sites; ambiguous country code; email syntax valid but attribution absent; stale/closed business; already solved need; invented source ID; page prompt injection; screenshot permission denied; symlink outside approved folder; moved/deleted file; interrupted job; lost send response; calendar race; feedback deletion; model rollback.

## Resource evaluation
Measure cold/warm loading, p50/p95 latency, peak process-tree RAM/VRAM, bytes downloaded, pages fetched, inference calls, tokens, failed tasks and external spend. Always record hardware/config. Compare equivalent task quality; lower resource use that materially reduces accuracy is not an improvement.

## Training promotion
Candidate must pass critical regressions and improve the target metric without unacceptable segment/resource regressions. Save evaluation report and baseline. If evidence is inconclusive, retain the current model. Track positive replies and qualified meetings as downstream outcomes separately from research accuracy.
