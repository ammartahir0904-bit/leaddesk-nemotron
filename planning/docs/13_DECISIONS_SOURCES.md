# Decisions, uncertainties and reference material

## Accepted design decisions
- Accuracy and useful business/contact analysis outrank volume.
- Runtime product and location inputs; no fixed café/tender-only product.
- Latent needs are valid research targets; public buying requests are optional.
- Local-first modular monolith; scale by evidence, not infrastructure fashion.
- Ordinary code and specialised pretrained models reduce generative calls.
- Memory correction first, evaluation-gated training later.
- Screen assistance and file search are part of the product, delivered after a reliable lead core.
- UI, workflow and connectors stay modular for integration and a stronger PC.

## Open questions that do not block the first slice
Actual CPU/GPU/VRAM; exact Ubuntu desktop/session; stronger PC access; initial discovery source; chosen email/calendar provider; target geography/language distribution; model licence preferences; public release versus personal-only use. Hardware benchmarks and connector access resolve these during implementation.

## Main risks and responses
| Risk | Response |
|---|---|
| No free comprehensive data source | Connector coverage report, bounded access, optional provider budget |
| Wrong or recycled contacts | Attribution checks, freshness, dispute workflow, direct confirmation label |
| Need inferred incorrectly | Alternatives and unknowns, manual review, outcome feedback |
| CPU-only latency | Sequential jobs, cached extraction, on-demand models, optional PC |
| Desktop portability | Test Wayland/X11 adapters on actual device |
| Training harms accuracy | Held-out gates, versioning, canary, rollback |
| Excessive complexity | One vertical slice at a time, modular monolith |

## Official references
These links informed the design and were consulted during the conversation on 18 October 2026. They are implementation starting points; versions, licences and limits must be rechecked when selecting dependencies. Architecture and thresholds in this package are proposals, not claims made by these sources.

- Ollama local-only configuration and FAQ: https://docs.ollama.com/faq
- Ollama running models API: https://docs.ollama.com/api/ps
- Ollama hardware support: https://docs.ollama.com/gpu
- Sentence Transformers retrieval and reranking: https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html
- Hugging Face TRL DPO: https://huggingface.co/docs/trl/dpo_trainer
- Playwright Python: https://playwright.dev/python/docs/intro
- whisper.cpp: https://github.com/ggml-org/whisper.cpp
- Open Home Foundation voice projects: https://github.com/ohf-voice
- Overpass shared public infrastructure guidance: https://dev.overpass-api.de/overpass-doc/en/preface/commons.html

## Claims we are not making
No universal contact accuracy guarantee, no guarantee that a prospect will buy, no measured model recommendation without hardware tests, no achieved benchmark values, no unlimited free search, no finished implementation, and no claim that feedback automatically improves weights.
