# Feedback, automatic improvement and training

## Three distinct mechanisms
Memory updates affect retrieval immediately. Ranking updates affect prioritisation. Fine-tuning changes model parameters. Reinforcement learning is a further option for sequential decisions with measurable rewards; it is not the default response to every error.

## Report mistake panel
Each answer, file match, lead and tool run has Report mistake. Capture object/run ID, task, observed output, error category, expected result, supporting evidence, user comment and scope. Categories: wrong business, wrong branch, wrong contact, stale record, unsupported need, wrong file, wrong transcription, unsafe/wrong action, duplicate, other.

A correction immediately marks disputed facts, suppresses invalid contacts from action queues and saves the corrected scoped association. It does not rewrite all similar records without review. Preserve history and allow undo.

## Automatic improvement allowed initially
- Retry transient failures within limits.
- Re-index moved files and invalidate stale caches.
- Detect conflicting records and send them to review.
- Apply user-approved deterministic correction rules within their scope.
- Build candidate evaluation datasets from eligible reviewed corrections.

Automatic issue detection is not automatic truth. A model-generated correction must remain a proposal unless supported by deterministic evidence or user review. No self-generated labels silently become training truth.

## Dataset lifecycle
Collect → redact secrets/private data → verify labels → deduplicate → version → split → train candidate → evaluate → compare → approve/promote → monitor/rollback.

Split by business/domain and time where relevant, not random copied pages, to prevent leakage. Keep a held-out set that is not reused as training examples. Preserve rare negative cases. Dataset manifest includes source permissions, consent scope, label provenance and deletions. Never train on raw credentials or private screen captures by default.

## Training progression
1. Baseline: rules + retrieval + prompts; collect errors.
2. Improve retrieval/ranker if poor matches dominate.
3. Supervised fine-tuning on reviewed examples if repeated extraction/tool-use problems persist. Parameter-efficient adapters are a candidate, with hardware-specific feasibility testing.
4. Preference training such as DPO when genuine chosen/rejected examples exist. DPO is not the same as online reinforcement learning.
5. Optional RL for a bounded research policy in a replay/sandbox environment, after a stable baseline and evaluation suite exist.

Potential RL decisions: which permitted source to check next, whether another check is worth its resource cost, when to abstain. Reward verified attribution and evidence-supported fit; penalise false claims, duplicate work, time/cost overruns and incorrect actions. Do not optimise phone-count, message-count or reply-count alone. Sales outcomes are delayed and confounded by offer, price, timing and communication.

## Training/release panel
Tabs: Mistakes, Review queue, Dataset versions, Experiments, Evaluation, Active model, Rollback. Show base model/hash, adapter hash, dataset version, training config, licence, metrics by segment, regression failures, resource usage and owner approval.

Train off the live interactive path, ideally on the capable PC. Keep current production model serving. Canary candidate on read-only tasks first. Promotion requires quality gates in 10_QUALITY.md and no critical regression. Default is manual promotion; optional automatic promotion must be explicitly enabled and bounded by the same gates. Automatically roll back on specified regression alerts.

## Important limitation
A model cannot become reliably better merely by collecting more feedback. Quality, coverage, task choice and independent evaluation determine whether an update helps. Keep an improvement only when measured results justify it.
