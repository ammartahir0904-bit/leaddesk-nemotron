"""Run local, synthetic benchmarks. Model inference requires explicit selection."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.adapters.hardware import profile_hardware
from backend.adapters.local_model import LocalModelError, OllamaAdapter
from backend.evaluation.runner import run_model_benchmark, run_parser_benchmark
from backend.settings import ROOT
from backend.storage.benchmarks import BenchmarkRepository
from backend.storage.repository import Repository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", action="store_true", help="Print a current read-only hardware snapshot.")
    parser.add_argument("--samples", type=int, default=20, help="Parser rounds (2–200; five synthetic cases each).")
    parser.add_argument("--model", help="Exact already installed Ollama model name; enables local CPU inference.")
    parser.add_argument("--digest", help="Required exact 64-character installed-model SHA-256 digest.")
    parser.add_argument("--port", type=int, default=11434, help="Ollama loopback port; remote addresses are unsupported.")
    parser.add_argument("--context", type=int, default=2048, help="Model context size (512–4096).")
    parser.add_argument("--save", action="store_true", help="Save benchmark in the workspace's local database.")
    args = parser.parse_args()
    if bool(args.model) != bool(args.digest):
        parser.error("--model and --digest must be supplied together; no default model is selected.")
    if args.profile and (args.model or args.save):
        parser.error("--profile cannot be combined with --model or --save.")
    data_dir = Path(os.environ.get("LEADDESK_DATA_DIR", ROOT / ".local"))
    # Profiling does not need to create local storage.
    hardware = profile_hardware(data_dir if data_dir.exists() else ROOT)
    try:
        if args.profile:
            report = hardware
        elif args.model:
            adapter = OllamaAdapter(args.model, args.digest, data_dir, port=args.port, context=args.context)
            try:
                model = adapter.inspect_model()
                report = run_model_benchmark(adapter, hardware, model, context=args.context)
            finally:
                adapter.close()
        else:
            report = run_parser_benchmark(hardware, args.samples)
        if args.save:
            report = BenchmarkRepository(Repository(data_dir / "leaddesk.sqlite3")).save(report)
    except (ValueError, LocalModelError) as error:
        parser.exit(2, f"Benchmark not started: {error}\n")
    print(json.dumps(report, indent=2))
    return 0 if report.get("status", "completed") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
