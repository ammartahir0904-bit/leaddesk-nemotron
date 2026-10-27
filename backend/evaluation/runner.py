"""Bounded benchmark reports with explicit measurement limits."""
import hashlib
import json
import math
import resource
import statistics
import time
from datetime import datetime, timezone
from typing import Protocol

from backend.domain.extract import extract
from backend.evaluation.cases import MODEL_CASES, PARSER_CASES


class ModelAdapter(Protocol):
    def generate(self, prompt: str) -> dict: ...


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def base_report(kind: str, hardware: dict, configuration: dict) -> dict:
    return {"schema_version": 1, "kind": kind, "measured_at": datetime.now(timezone.utc).isoformat(),
            "hardware": hardware, "configuration": configuration, "model_hash": None,
            "network_requests": 0, "inference_calls": 0, "external_spend": 0}


def run_parser_benchmark(hardware: dict, sample_count: int = 20) -> dict:
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or not 2 <= sample_count <= 200:
        raise ValueError("Sample count must be an integer between 2 and 200.")
    report = base_report("parser", hardware, {"parser": "visible_html_v1", "suite_version": 1,
                                              "rounds": sample_count, "case_count": len(PARSER_CASES), "concurrency": 1})
    report["fixture_sha256"] = digest([vars(case) for case in PARSER_CASES])
    timings, results = [], []
    for index in range(sample_count):
        started = time.perf_counter()
        for case in PARSER_CASES:
            actual = extract(case.html)
            contacts = sorted((c["type"], c["normalised_value"]) for c in actual.contacts)
            passed = actual.name == case.name and contacts == sorted(case.contacts)
            results.append({"case_id": case.id, "round": index + 1, "passed": passed})
        timings.append((time.perf_counter() - started) * 1000)
    report.update({
        "status": "completed" if all(r["passed"] for r in results) else "failed",
        "sample_count": len(results), "passed_count": sum(r["passed"] for r in results), "results": results,
        "timing": {"first_round_ms": timings[0], "warm_round_p50_ms": statistics.median(timings[1:]),
                   "round_p95_ms": sorted(timings)[math.ceil(.95 * len(timings)) - 1], "total_ms": sum(timings)},
        "memory": {"peak_runner_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                   "peak_model_ram_bytes": None, "peak_model_vram_bytes": None},
        "limitations": ["Synthetic parser checks do not establish live contact accuracy or model quality.",
                         "Timings cover a full fixture round. First round is not a cold-process measurement.",
                         "Runner peak RSS is a process-lifetime high-water mark; excludes browser and inference processes."],
    })
    return report


def run_model_benchmark(adapter: ModelAdapter, hardware: dict, model: dict, *, context: int = 2048) -> dict:
    report = base_report("local_model", hardware, {"suite_version": 1, "context": context, "rounds": 2,
                                                   "concurrency": 1, "device": "cpu", "max_output_tokens": 192})
    report["model"] = model
    report["model_hash"] = model["digest"]
    report["fixture_sha256"] = digest(MODEL_CASES)
    results = []
    for round_index in range(2):
        for case in MODEL_CASES:
            prompt = json.dumps({"instruction": case["instruction"], "source_evidence": case["evidence"]}, ensure_ascii=False)
            started = time.perf_counter()
            result = {"case_id": case["id"], "task": case["task"], "round": round_index + 1,
                      "passed": False, "first_response_ms": None}
            try:
                response = adapter.generate(prompt)
                report["inference_calls"] += 1
                output = json.loads(response["response"])
                # Canonical JSON keeps booleans distinct from numeric budgets.
                result.update({"passed": digest(output) == digest(case["expected"]), "output": output,
                               "load_duration_ns": response.get("load_duration"),
                               "eval_count": response.get("eval_count")})
                if not result["passed"]:
                    result["failure"] = "Output differs from the fixed, source-backed expectation."
            except (ValueError, KeyError, TypeError, RuntimeError) as error:
                result["failure"] = str(error)[:400]
                results.append(result | {"total_ms": (time.perf_counter() - started) * 1000})
                # Stop on runtime/resource failures; malformed JSON remains a
                # failed case and later independent cases can still be evaluated.
                if isinstance(error, RuntimeError):
                    report["status"] = "partial"
                    break
            else:
                results.append(result | {"total_ms": (time.perf_counter() - started) * 1000})
        if report.get("status") == "partial":
            break
    report.update({
        "status": report.get("status", "completed" if all(r["passed"] for r in results) else "failed"),
        "network_requests": getattr(adapter, "network_requests", None),
        "sample_count": len(results), "passed_count": sum(r["passed"] for r in results), "results": results,
        "memory": {"peak_runner_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                   "peak_model_ram_bytes": None, "peak_model_vram_bytes": None},
        "limitations": ["Eight synthetic checks are a smoke suite, not a model recommendation or production accuracy estimate.",
                         "First response time and inference-process peak RAM/VRAM are not measured by this non-streaming adapter.",
                         "Round one may use an already loaded model; load_duration is recorded, but cold/warm residency is not controlled.",
                         "Failed/blocked requests may have reached the runtime; inference_calls counts responses received."],
    })
    return report
