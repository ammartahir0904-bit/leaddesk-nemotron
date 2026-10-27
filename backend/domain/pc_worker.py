"""An allowlisted synthetic benchmark protocol. No remote tool execution."""
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.evaluation.cases import PARSER_CASES
from backend.evaluation.runner import digest

LEASE_SECONDS = 60
MAX_ATTEMPTS = 3
MAX_REPORT_BYTES = 12000


class StrictInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class PairWorker(StrictInput):
    name: str = Field(min_length=1, max_length=80, pattern=r'\S')


class WorkerTask(StrictInput):
    worker_id: str = Field(min_length=1, max_length=100)
    kind: Literal['synthetic_parser_benchmark']
    rounds: int = Field(default=2, ge=2, le=20)


class LeaseInput(StrictInput):
    lease_token: str = Field(min_length=32, max_length=100)


class WorkerHardware(StrictInput):
    system: str = Field(max_length=80)
    architecture: str = Field(max_length=80)
    python: str = Field(max_length=40)
    cpu: str | None = Field(max_length=200)
    logical_cores: int | None = Field(ge=1, le=100000)
    total_ram_bytes: int | None = Field(ge=0)
    available_ram_bytes: int | None = Field(ge=0)


class BenchmarkResult(StrictInput):
    protocol: Literal[1]
    executor_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    fixture_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    measured_at: str = Field(min_length=10, max_length=60)
    rounds: int = Field(ge=2, le=20)
    check_count: int = Field(ge=1, le=100)
    passed_count: int = Field(ge=0, le=100)
    failed_checks: list[str] = Field(max_length=100)
    total_ms: float = Field(ge=0, le=60000)
    peak_runner_rss_bytes: int = Field(ge=0)
    hardware: WorkerHardware

    @field_validator('measured_at')
    @classmethod
    def dated_measurement(cls, value):
        measured = datetime.fromisoformat(value)
        if measured.tzinfo is None:
            raise ValueError('Measurement time must include its timezone.')
        return value


class CompleteTask(LeaseInput):
    result: BenchmarkResult


class FailTask(LeaseInput):
    error_code: Literal['executor_mismatch', 'execution_failed', 'resource_limit']


def fixture_hash():
    return digest([vars(case) for case in PARSER_CASES])


def executor_hash():
    root = Path(__file__).resolve().parents[2]
    files = ('backend/domain/extract.py', 'backend/evaluation/cases.py',
             'backend/evaluation/runner.py', 'backend/adapters/hardware.py',
             'backend/domain/pc_worker.py', 'backend/workflows/pc_executor.py', 'requirements.lock')
    h = hashlib.sha256()
    for name in files:
        h.update(name.encode() + b'\0' + (root / name).read_bytes() + b'\0')
    return h.hexdigest()
