# Hardware adaptation and model routing

## Profile actual hardware
Collect OS/session, CPU, available/total RAM, disk, GPU model/VRAM/driver and supported inference backend. User can disable GPU or remote execution. Store no serial numbers or unnecessary device identifiers. Recheck available memory when starting a heavy job.

## Benchmark before recommendation
Model registry fields: model ID, immutable hash/revision, task capabilities, quantisation, licence, language coverage, download size, context setting, supported runtime and measured requirements. Candidate selection is based on current official model/runtime documentation and actual tests, not these docs naming a universal winner.

Run fixed extraction, tool-choice, grounded-summary and abstention cases. Record correctness, first-response time, total runtime, peak RAM/VRAM and failures. Warm and cold runs differ. Reserve memory for Ubuntu, the browser, UI and speech components. Context and concurrency affect memory; model file size alone is insufficient.

## Initial operating policies (proposals)
| Profile | Scheduling policy |
|---|---|
| 8 GB CPU laptop | One inference job, one browser context, bounded text, unload optional models |
| Larger CPU machine | Increase concurrency only after memory/runtime measurement |
| Supported GPU PC | Benchmark suitable quantised models and optionally vision |
| Laptop plus private PC | Lightweight local interface; heavy jobs on authorised PC worker |

A rough non-model idle-process budget of 500 MB RSS is a tuning goal, excluding browser and inference processes. Measure the entire process tree separately. If the goal fails, profile before adding features. No promised tokens/second or guaranteed model size fit.

## Routing order
Rules/parsers → keyword retrieval → embeddings → small reranker/classifier → small generative model → heavier local model → optional cloud fallback. Escalate based on task failure/uncertainty and measured benefit. Low-confidence identity facts require better evidence, not merely a bigger model's opinion.

Load only needed models. Reuse embeddings for unchanged content hashes. Batch small extraction tasks within measured context limits. Pause background research during interactive voice tasks. Avoid severe swap pressure and sustained resource exhaustion; notify and lower workload.

## Dependencies as replaceable adapters
Ollama: local generation runtime. Sentence Transformers: embedding/retrieval and reranking candidate. whisper.cpp: speech recognition candidate. Piper: speech output candidate. These are proposed components; verify versions, hardware compatibility, voice availability and licences during implementation. No claim that every component or model has the same licence.

## PC worker
Pair through explicit authentication and encrypted private transport. Scoped job tokens, no public unauthenticated inference endpoint. File contents/screen data stay local unless selected for remote processing. If the PC disappears, queue heavy work or use a measured smaller fallback and label changed capability. Never silently switch to paid cloud inference.
