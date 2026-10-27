# Sprint 20 — local AI fit analysis with Ollama

Date: 20 October 2026, Asia/Karachi. The user asked to add Ollama AI analysis and start the next sprint, and chose **Docker + llama3.2:3b** for a real test on this laptop.

## Delivered
- **Ollama setup.** `scripts/ollama.sh start | pull <model> | stop | status` runs the official `ollama/ollama` image on `127.0.0.1:11434`, with `--gpus all` added automatically when an NVIDIA GPU and Docker GPU support exist. With the user's approval it was started: image 9.38 GB, much larger than the "few GB" estimate because it bundles GPU libraries; Ollama 0.40.6. `llama3.2:3b` was pulled (2.02 GB, Q4_K_M, digest `a80c4f17…b5b8b72`).
- **Model choice:** a "Model for AI lead analysis" section in AI models and hardware. `GET /v1/ai/status` and `POST /v1/ai/model` cover choosing an installed local model; cloud or remote models are excluded. The exact digest is recorded, and analysis stops when it changes ("select it again").
- **AI analysis:** **AI analysis** per business, or **AI analyse top 5** (limit 1–10, sequential, failures listed).
  - The model receives the seller's product plus a numbered, bounded evidence pack (E1…E24, 400 characters each) built only from saved data: map entry, web findings and the website check.
  - It returns fit (likely / possible / unlikely / unknown), a need summary, whether they already have something similar, reasons with evidence IDs, an opening line, and 1–3 discovery questions.
  - Answers in the wrong format get one automatic retry; then nothing is saved.
  - Citing evidence that doesn't exist, or a likely/unlikely verdict without reasons, is rejected.
  - Results are saved as `status: proposal` with model, digest, seconds and token counts. They **never change rule-based points**.
- **Guardrails added after real outputs** (`ground()`):
  - A reason's words that are missing from the evidence it cites are flagged (⚠ "not found in cited evidence"). The summary and opening line are checked against all evidence.
  - Collected facts outrank the model's wording: a "has a website" claim when no website was listed or found is flagged, and "already has something similar" becomes unknown.
  - "Likely" plus "already has something similar" becomes "possible", with a visible note.
  - Opening lines that imply earlier contact ("follow up on our previous discussion") are flagged.
  - The instructions now state the seller's viewpoint, that owning a similar product lowers fit, and that questions are for the owner.
- **Your review:** 👍/👎 per AI answer (`/ai-verdict`). Counts appear in AI settings; these reviewed answers are the labelled data for future evaluation and training. A new answer replaces the old one and its verdict.
- **Connector:** `OllamaAdapter` gains GPU use, thread count, keep-alive, memory threshold and request time limit as options. Benchmarks keep their old CPU / 2 threads / unload / 90 s behaviour. Analysis lets Ollama use a GPU, keeps the model warm for 5 minutes, allows 10 minutes per answer, and skips the free-memory check when that exact model is already loaded.
- Migration `014_ai_analysis.sql`.

## Real results (this laptop, CPU only, llama3.2:3b, 4096 context)
| Business | Time | Result after guardrails |
|---|---|---|
| Arcadian Café | 45–89 s (about 1,080 prompt tokens, 253 output tokens) | Possible: the model said "likely" while also saying they already have a website, so it was adjusted. Cited its menu page, Instagram and Facebook (532k followers) and Gulberg address. Its "online ordering" claim and an invented "previous discussion" were flagged. |
| Cafe Costa | 43 s | Possible (adjusted). Cited website, Facebook, TripAdvisor and WordPress blog. Unsupported summary words flagged. |
| Alif Milk Waly | 20–24 s | The model wrongly said "already has a website". This is now flagged "website (none found)", and "already has something similar" was changed to unknown. |

Problems seen on real output and fixed:
- The first call was cut off at 60 s (Ollama logged a 500 at exactly 1m0s); the limit is now 10 minutes for analysis.
- A second call was refused because the loaded model's RAM counted as "used"; the free-memory check is now skipped when that model is already loaded.
- One answer was in the wrong format and was not saved; one automatic retry was added.

**Assessment:** a 3B model on CPU writes usable discovery questions, but it often overstates facts. The guardrails catch the cases above, so treat its output as a draft for review. A 7–8B model on the stronger PC should do better; this has not been measured.

## Verification evidence
Host: i5-8265U, 7.5 GiB RAM, about 3 GiB free, no GPU, Docker 29.8.0, Python 3.12.3, Node 24.21.0, Chrome 151.
- **328 tests pass** (5 AI tests: evidence pack and prompt, parsing and rejection, grounding, fact checks, and an API flow with a fake model covering selection, analysis, verdicts, retry, a model error that keeps the previous answer, and digest drift).
- All **8 browser flows pass**. The AI card was checked in a headless Chrome screenshot.

## Not done
- No training or reinforcement learning. Verdicts are being collected, and a held-out evaluation needs enough of them first.
- No benchmark on the stronger PC yet; run the advisor and `scripts/ollama.sh` there.
- Grounding is word-overlap only and can miss paraphrased claims or flag harmless words.
