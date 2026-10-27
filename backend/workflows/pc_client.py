"""Opt-in polling client. Coordinator is loopback via an explicit SSH tunnel."""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

from backend.domain.pc_worker import BenchmarkResult, MAX_REPORT_BYTES, WorkerTask, executor_hash, fixture_hash

ROOT = Path(__file__).resolve().parents[2]


class WorkerProtocolError(Exception):
    pass


class WorkerRevoked(WorkerProtocolError):
    pass


def read_credential(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'r') as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid() or info.st_size > 2000:
                raise ValueError()
            value = json.loads(file.read(2001))
        if (set(value) != {'schema_version', 'worker_id', 'token'} or type(value['schema_version']) is not int
                or value['schema_version'] != 1 or not isinstance(value['token'], str)
                or not 32 <= len(value['token']) <= 100 or not value['token'].isascii()):
            raise ValueError()
        UUID(value['worker_id'])
        return value
    except (OSError, ValueError, TypeError, KeyError):
        raise WorkerProtocolError('Use a valid owned credential file with mode 600; symlinks are rejected.') from None


def coordinator_url(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port
                or parsed.username or parsed.password or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment):
            raise ValueError()
        return f'http://127.0.0.1:{parsed.port}'
    except ValueError:
        raise WorkerProtocolError('Coordinator must be http://127.0.0.1:PORT through an explicit SSH loopback tunnel.') from None


def execute_subprocess(rounds):
    try:
        process = subprocess.run([sys.executable, '-m', 'backend.workflows.pc_executor', str(rounds)],
                                 cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=True)
        if len(process.stdout) > MAX_REPORT_BYTES:
            raise ValueError()
        return BenchmarkResult.model_validate_json(process.stdout).model_dump()
    except (subprocess.SubprocessError, OSError, ValueError):
        raise WorkerProtocolError('The fixed benchmark executor failed or exceeded its resource limit.') from None


class PCWorkerClient:
    def __init__(self, url, credential, *, transport=None, executor=execute_subprocess):
        self.worker_id, self.token = credential['worker_id'], credential['token']
        self.http = httpx.Client(base_url=coordinator_url(url), timeout=5, trust_env=False, follow_redirects=False,
                                 transport=transport, headers={'Authorization': f'Bearer {self.token}'})
        self.executor = executor
        self.claim_key = str(uuid4())
        self.pending = None

    def close(self):
        self.http.close()
        self.pending = None
        self.token = ''

    def _request(self, path, body=None, key=None):
        with self.http.stream('POST', path, json=body, headers={'Idempotency-Key': key} if key else {}) as response:
            if response.status_code == 401:
                raise WorkerRevoked('Worker credential was rejected. Stop and check pairing.')
            if response.status_code == 409:
                return None  # Cancellation, expired/replaced lease or conflicting replay.
            if not response.is_success:
                raise WorkerProtocolError('Coordinator rejected the worker protocol request.')
            content = bytearray()
            for part in response.iter_bytes():
                content.extend(part)
                if len(content) > 16000:
                    raise WorkerProtocolError('Coordinator response exceeded the protocol limit.')
        try:
            return json.loads(content)
        except ValueError:
            raise WorkerProtocolError('Coordinator returned an invalid protocol response.') from None

    def run_once(self):
        # Keep the exact result in memory across a lost completion response.
        if self.pending is None:
            response = self._request('/v1/pc-worker/claim', key=self.claim_key)
            task = response.get('task') if isinstance(response, dict) else None
            if task is None:
                self.claim_key = str(uuid4())
                return 'idle'
            try:
                UUID(task['id'])
                WorkerTask.model_validate({k: task[k] for k in ('worker_id', 'kind', 'rounds')})
                lease = task['lease_token']
                if task['worker_id'] != self.worker_id or not isinstance(lease, str) or len(lease) != 64:
                    raise ValueError()
            except (ValueError, TypeError, KeyError):
                raise WorkerProtocolError('Invalid assigned task. No workload was executed.') from None
            path = f"/v1/pc-worker/tasks/{task['id']}"
            if task.get('executor_sha256') != executor_hash() or task.get('fixture_sha256') != fixture_hash():
                self.pending = (path + '/fail', {'lease_token': lease, 'error_code': 'executor_mismatch'})
            else:
                if self._request(path + '/heartbeat', {'lease_token': lease}) is None:
                    self.claim_key = str(uuid4())
                    return 'stale'
                try:
                    result = self.executor(task['rounds'])
                    self.pending = (path + '/complete', {'lease_token': lease, 'result': result})
                except WorkerProtocolError:
                    self.pending = (path + '/fail', {'lease_token': lease, 'error_code': 'execution_failed'})
        path, payload = self.pending
        accepted = self._request(path, payload)
        self.pending = None
        self.claim_key = str(uuid4())
        return 'accepted' if accepted else 'stale'
