"""Single fixed workload; receives only a bounded round count."""
from pathlib import Path

from backend.adapters.hardware import profile_hardware
from backend.domain.pc_worker import BenchmarkResult, executor_hash
from backend.evaluation.runner import run_parser_benchmark


def execute_benchmark(rounds):
    hardware = profile_hardware(Path.cwd())
    report = run_parser_benchmark(hardware, rounds)
    result = BenchmarkResult(
        protocol=1, executor_sha256=executor_hash(), fixture_sha256=report['fixture_sha256'],
        measured_at=report['measured_at'], rounds=rounds, check_count=report['sample_count'],
        passed_count=report['passed_count'],
        failed_checks=[f"{r['case_id']}:{r['round']}" for r in report['results'] if not r['passed']],
        total_ms=report['timing']['total_ms'], peak_runner_rss_bytes=report['memory']['peak_runner_rss_bytes'],
        hardware={'system': hardware['os']['system'], 'architecture': hardware['os']['architecture'],
                  'python': hardware['os']['python'], 'cpu': hardware['cpu']['model'],
                  'logical_cores': hardware['cpu']['logical_cores'],
                  'total_ram_bytes': hardware['memory']['total_bytes'],
                  'available_ram_bytes': hardware['memory']['effective_available_bytes']})
    return result.model_dump()


if __name__ == '__main__':
    import json
    import sys

    print(json.dumps(execute_benchmark(int(sys.argv[1])), allow_nan=False))
