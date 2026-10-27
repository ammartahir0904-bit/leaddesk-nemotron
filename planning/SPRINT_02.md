# Sprint 2 — hardware and repeatable benchmarks

Date: 19 October 2026, Asia/Karachi. B05's profiling and evaluation foundation is implemented. Desktop acceptance and real-model performance/selection remain pending; this is not a completed model evaluation or an assistant release.

## Delivered

- **Hardware and models panel:** on-demand CPU, memory/swap, data-drive space and DRM GPU telemetry; refresh, CPU-mode explanation and explicit unknown values. No device serials, hostnames, user names or raw screenshots are collected.
- **Parser evaluation:** five fixed fictional cases, 20 rounds by default; visible contacts, hidden content, ambiguous identities, no inferred WhatsApp, explicit WhatsApp. Reports contain fixture SHA-256, hardware/date/configuration, individual results, timings and runner memory limits.
- **Saved reports:** reopen, inspect failures, download JSON. Benchmark history is separate from research; no synthetic benchmark contacts enter lead records.
- **API:** authenticated profile, parser-run, history and report routes. Runs require idempotency keys, reject conflicting reuse, bound inputs and share the web server's single research execution slot. Busy responses are retryable.
- **Local model adapter and CLI:** explicit installed name plus digest; fixed loopback runtime, CPU request, no client proxy/redirect/download path, reject remote-model metadata and digest changes, available-memory guard before every generation. Eight fictional checks cover extraction, tool choice, grounding and abstention. Generated tool choices are scored as text; no tools execute.
- **Database upgrade:** migration 002 only adds benchmark storage and its index. An upgrade test starts with schema 001 containing research/evidence/contact feedback, applies 002, and checks exact record preservation, foreign keys and restart persistence.
- **Modular code:** hardware and inference adapters, evaluation cases/runner and benchmark repository have separate modules. The new React panel and stylesheet are separate from the existing research UI. No dependencies were added.

## Executed verification

- Target checkout's `.venv/bin/python -m unittest discover -s tests -q`: **47 tests passed**. Coverage includes existing extraction/fetch/correction regressions plus missing GPU telemetry, cgroup memory limits, no serial collection, benchmark failures, migration preservation, persisted reports, auth/origin checks, idempotency/input limits, single execution slot, low-memory rejection, digest drift, remote metadata rejection and malformed/oversized runtime responses.
- Model adapter/evaluation tests use injected transports and fixed synthetic outputs. They do **not** measure an installed model's accuracy or inference performance.
- Frontend production build passes with Node 24.21.0 and Vite 8.3.1. The final backend suite is run against completed build artifacts. An earlier parallel build replaced the asset being checked and caused a transient asset 404; checks were then sequenced after the build.
- Target environment `pip check`: no broken requirements.
- CLI `--samples 2 --save` executed against an ignored disposable data directory: 10/10 checks passed; reopening the saved report matched the printed JSON exactly.
- Python compilation, browser-script syntax and `git diff --check`: pass.
- Read-only profiling executed on this laptop: i5-8265U, eight logical cores, approximately 7.45 GiB physical RAM; Intel PCI graphics device with i915 driver. Dedicated VRAM is unavailable in telemetry and remains null. Available memory and storage are snapshots in the saved report.
- [sprint-02-benchmark.json](sprint-02-benchmark.json): **100/100 synthetic parser checks passed**, fixture hash and exact timestamp/configuration included. First five-case round 2.99 ms, later-round median 1.00 ms, p95 round 1.72 ms, total 24.44 ms. Runner lifetime peak RSS approximately 26.36 MiB. These numbers exclude browser, server process tree, live sources and model inference.

## Remaining acceptance and measurement limits

- A fresh socket probe still fails with `PermissionError: [Errno 1] Operation not permitted`. No live server acceptance is claimed.
- The extended browser script reaches Chrome launch, then fails with `setsockopt: Operation not permitted` / SIGTRAP before assertions. It now includes hardware refresh, benchmark execution/history/export/retry, mobile layout and the original research/correction flow. None of those browser assertions is claimed as executed here.
- No model was selected, installed, downloaded or run. The adapter is implemented and tested with synthetic transports. No model size, throughput, compatibility, licence, language suitability or recommendation is established.
- The non-streaming adapter leaves first-response latency and inference-process peak RAM/VRAM null. Model load duration is retained when returned; model residency is not controlled across measurements. Two rounds are not labelled guaranteed cold/warm runs.
- The benchmark guard requires at least 3 GiB available RAM before each generation (2 GiB reserve plus 1 GiB headroom). It cannot guarantee a selected model fits or stop memory pressure that appears during a call. Runtime responses have bounded size and read/time limits; a read already in flight may extend the checked wall-time budget by its read timeout.
- Web research and parser runs share one server slot. Independently launched CLI processes are not coordinated; run one at a time.
- The shared database gains an additive table at the next startup. Automatic backup/restore, data deletion UI, persistent model jobs and model benchmarking through the web API remain later work.

## Desktop verification

Use the existing launcher in a normal terminal:

```bash
cd /home/ammar/Downloads/LeadDesk_Blueprint
./launch.sh
```

Unlock at `http://127.0.0.1:8765`, open **Hardware and models**, refresh measurements, run a parser benchmark, inspect/download it, and reopen it after refreshing. Switch back to Website research and exercise the synthetic correction flow. Browser automation still requires the disposable-data setup documented in [../README.md](../README.md).

For the explicit installed-model command and local-only runtime configuration, see the root README. The adapter contract was checked against official Ollama [generation](https://docs.ollama.com/api/generate), [installed model metadata](https://docs.ollama.com/api/tags), [API types](https://github.com/ollama/ollama/blob/main/api/types.go) and [cloud-disable instructions](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features). No runtime installation or service configuration was changed.

Next product slice: B06, an editable structured product brief accepting arbitrary offers and locations. A production generative model remains contingent on explicit selection and actual measurements; this sprint does not silently choose one.
