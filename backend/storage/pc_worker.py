"""Coordinator-owned pairing and fenced leases for the fixed PC workload."""
import hashlib
import hmac
import json
import secrets
import time

from backend.domain.errors import ResearchError
from backend.domain.pc_worker import LEASE_SECONDS, MAX_ATTEMPTS, MAX_REPORT_BYTES, executor_hash, fixture_hash
from backend.evaluation.cases import PARSER_CASES
from backend.storage.repository import request_hash, uid


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class PCWorkerRepository:
    def __init__(self, repository, clock=time.time):
        self.repository, self.clock = repository, clock

    @staticmethod
    def _worker(row, timestamp):
        return {k: row[k] for k in ('id', 'name', 'created_at', 'last_seen_at', 'revoked_at')} | {
            'connection': 'revoked' if row['revoked_at'] is not None else (
                'recently_seen' if row['last_seen_at'] is not None and timestamp - row['last_seen_at'] < LEASE_SECONDS else 'offline')}

    @staticmethod
    def _task(row, detail=True):
        report = json.loads(row['result_json']) if row['result_json'] else None
        result = {k: row[k] for k in ('id', 'worker_id', 'rounds', 'status', 'attempts', 'created_at',
                                     'updated_at', 'lease_until', 'error_code')}
        result.update(kind='synthetic_parser_benchmark', provenance='unverified_worker_report',
                      synthetic=True, model_hash=None, executor_sha256=row['executor_hash'], fixture_sha256=row['fixture_hash'])
        result['benchmark_status'] = ('passed' if report['passed_count'] == report['check_count'] else 'failed') if report else None
        if detail:
            result['result'] = report
        return result

    def _recover(self, db):
        timestamp = self.clock()
        db.execute("""UPDATE pc_task SET status=CASE WHEN attempts>=? THEN 'failed' ELSE 'queued' END,
            error_code=CASE WHEN attempts>=? THEN 'disconnect_limit' ELSE 'lease_expired' END,
            updated_at=?,lease_until=NULL,lease_started_at=NULL,lease_hash=NULL,claim_key=NULL
            WHERE status='running' AND lease_until<=?""", (MAX_ATTEMPTS, MAX_ATTEMPTS, timestamp, timestamp))

    @staticmethod
    def _receipt(db, operation, key, payload):
        row = db.execute('SELECT * FROM pc_request WHERE operation=? AND request_key=?', (operation, key)).fetchone()
        if row and row['request_hash'] != request_hash(payload):
            raise ResearchError('This request key was already used with different inputs.', status=409)
        return row['object_id'] if row else None

    def pair(self, payload, key):
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = self._receipt(db, 'pair', key, payload.model_dump())
            if previous:
                row = db.execute('SELECT * FROM pc_worker WHERE id=?', (previous,)).fetchone()
                return {'worker': self._worker(row, self.clock()), 'credential': None,
                        'message': 'Credential was returned once. If lost, revoke and pair again.'}
            if db.execute('SELECT COUNT(*) FROM pc_worker').fetchone()[0] >= 50:
                raise ResearchError('The 50-pairing history limit was reached.', status=429)
            identity, token, timestamp = uid(), secrets.token_urlsafe(32), self.clock()
            db.execute('INSERT INTO pc_worker(id,name,token_hash,created_at) VALUES(?,?,?,?)',
                       (identity, payload.name.strip(), token_hash(token), timestamp))
            db.execute('INSERT INTO pc_request VALUES(?,?,?,?)', ('pair', key, request_hash(payload.model_dump()), identity))
            row = db.execute('SELECT * FROM pc_worker WHERE id=?', (identity,)).fetchone()
            return {'worker': self._worker(row, timestamp),
                    'credential': {'schema_version': 1, 'worker_id': identity, 'token': token}}

    def overview(self):
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._recover(db)
            return {'workers': [self._worker(r, self.clock()) for r in db.execute('SELECT * FROM pc_worker ORDER BY created_at,id')],
                    'tasks': [self._task(r, False) for r in db.execute('SELECT * FROM pc_task ORDER BY created_at DESC,id DESC')],
                    'enabled': bool(db.execute('SELECT 1 FROM pc_worker WHERE revoked_at IS NULL').fetchone())}

    def create(self, payload, key):
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._recover(db)
            previous = self._receipt(db, 'task', key, payload.model_dump())
            if previous:
                return self._task(db.execute('SELECT * FROM pc_task WHERE id=?', (previous,)).fetchone())
            worker = db.execute('SELECT * FROM pc_worker WHERE id=? AND revoked_at IS NULL', (payload.worker_id,)).fetchone()
            if not worker:
                raise ResearchError('Select an active paired worker.', status=409)
            if db.execute('SELECT COUNT(*) FROM pc_task').fetchone()[0] >= 500:
                raise ResearchError('The 500-task history limit was reached.', status=429)
            if db.execute("SELECT COUNT(*) FROM pc_task WHERE status IN ('queued','running')").fetchone()[0] >= 20:
                raise ResearchError('The PC queue is full. Cancel pending work first.', status=429, retryable=True)
            identity, timestamp = uid(), self.clock()
            db.execute('''INSERT INTO pc_task(id,worker_id,rounds,executor_hash,fixture_hash,status,created_at,updated_at)
                          VALUES(?,?,?,?,?,'queued',?,?)''',
                       (identity, payload.worker_id, payload.rounds, executor_hash(), fixture_hash(), timestamp, timestamp))
            db.execute('INSERT INTO pc_request VALUES(?,?,?,?)', ('task', key, request_hash(payload.model_dump()), identity))
            return self._task(db.execute('SELECT * FROM pc_task WHERE id=?', (identity,)).fetchone())

    def get(self, task_id):
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._recover(db)
            row = db.execute('SELECT * FROM pc_task WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ResearchError('PC task not found.', status=404)
            return self._task(row)

    def cancel(self, task_id):
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM pc_task WHERE id=?', (task_id,)).fetchone():
                raise ResearchError('PC task not found.', status=404)
            db.execute("""UPDATE pc_task SET status='cancelled',updated_at=?,lease_hash=NULL,lease_until=NULL,
                       error_code='owner_cancelled' WHERE id=? AND status IN ('queued','running')""", (self.clock(), task_id))
        return self.get(task_id)

    def revoke(self, worker_id):
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM pc_worker WHERE id=?', (worker_id,)).fetchone():
                raise ResearchError('Worker not found.', status=404)
            db.execute('UPDATE pc_worker SET revoked_at=COALESCE(revoked_at,?) WHERE id=?', (self.clock(), worker_id))
            db.execute("""UPDATE pc_task SET status='cancelled',updated_at=?,lease_hash=NULL,lease_until=NULL,
                       error_code='pairing_revoked' WHERE worker_id=? AND status IN ('queued','running')""", (self.clock(), worker_id))
        return {'revoked': True, 'worker_id': worker_id}

    def _authenticate(self, db, token):
        row = db.execute('SELECT * FROM pc_worker WHERE token_hash=? AND revoked_at IS NULL', (token_hash(token),)).fetchone()
        if not row:
            raise ResearchError('Worker authentication failed. Pair again if revoked.', status=401)
        db.execute('UPDATE pc_worker SET last_seen_at=? WHERE id=?', (self.clock(), row['id']))
        return row['id']

    @staticmethod
    def _lease_token(token, task_id, attempt, key):
        return hmac.new(token.encode(), f'{task_id}:{attempt}:{key}'.encode(), hashlib.sha256).hexdigest()

    def _claim_response(self, row, token):
        return {'task': self._task(row, False) | {
            'lease_token': self._lease_token(token, row['id'], row['attempts'], row['claim_key'])},
            'lease_seconds': LEASE_SECONDS}

    def claim(self, token, key):
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            worker_id = self._authenticate(db, token)
            self._recover(db)
            previous = db.execute('SELECT * FROM pc_claim WHERE worker_id=? AND request_key=?', (worker_id, key)).fetchone()
            if previous:
                row = db.execute('SELECT * FROM pc_task WHERE id=?', (previous['task_id'],)).fetchone()
                if row['status'] == 'running' and row['attempts'] == previous['attempt'] and row['claim_key'] == key:
                    return self._claim_response(row, token)
                return {'task': None, 'lease_seconds': LEASE_SECONDS}
            if db.execute("SELECT 1 FROM pc_task WHERE status='running'").fetchone():
                return {'task': None, 'lease_seconds': LEASE_SECONDS}
            row = db.execute("SELECT * FROM pc_task WHERE worker_id=? AND status='queued' ORDER BY created_at,id LIMIT 1", (worker_id,)).fetchone()
            if not row:
                return {'task': None, 'lease_seconds': LEASE_SECONDS}
            attempt, timestamp = row['attempts'] + 1, self.clock()
            lease = self._lease_token(token, row['id'], attempt, key)
            db.execute("""UPDATE pc_task SET status='running',attempts=?,updated_at=?,lease_until=?,lease_started_at=?,lease_hash=?,
                       claim_key=?,error_code=NULL WHERE id=?""", (attempt, timestamp, timestamp + LEASE_SECONDS, timestamp, token_hash(lease), key, row['id']))
            db.execute('INSERT INTO pc_claim VALUES(?,?,?,?)', (worker_id, key, row['id'], attempt))
            return self._claim_response(db.execute('SELECT * FROM pc_task WHERE id=?', (row['id'],)).fetchone(), token)

    def _leased(self, db, token, task_id, lease):
        worker_id = self._authenticate(db, token)
        self._recover(db)
        row = db.execute('SELECT * FROM pc_task WHERE id=? AND worker_id=?', (task_id, worker_id)).fetchone()
        if not row or not row['lease_hash'] or not secrets.compare_digest(row['lease_hash'], token_hash(lease)):
            raise ResearchError('This task lease is no longer valid.', status=409)
        return row

    def heartbeat(self, token, task_id, lease):
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._leased(db, token, task_id, lease)
            if row['status'] != 'running':
                raise ResearchError('Task is no longer running.', status=409)
            expiry = min(self.clock() + LEASE_SECONDS, row['lease_started_at'] + 120)
            db.execute('UPDATE pc_task SET lease_until=?,updated_at=? WHERE id=?', (expiry, self.clock(), task_id))
            return {'lease_seconds': LEASE_SECONDS}

    def complete(self, token, task_id, payload):
        result = payload.result.model_dump()
        body = json.dumps(result, allow_nan=False, ensure_ascii=False)
        if len(body.encode()) > MAX_REPORT_BYTES:
            raise ResearchError('Worker report exceeds its size limit.', status=413)
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._leased(db, token, task_id, payload.lease_token)
            result_digest = request_hash(result)
            if row['status'] == 'completed' and row['result_hash'] == result_digest:
                return {'accepted': True, 'task_id': task_id}
            if row['status'] != 'running':
                raise ResearchError('This result conflicts with the completed task.', status=409)
            known_checks = {f'{c.id}:{i}' for c in PARSER_CASES for i in range(1, row['rounds'] + 1)}
            failures = result['failed_checks']
            if (result['executor_sha256'] != row['executor_hash'] or result['fixture_sha256'] != row['fixture_hash']
                    or result['rounds'] != row['rounds'] or result['check_count'] != len(known_checks)
                    or result['passed_count'] != len(known_checks) - len(failures)
                    or len(set(failures)) != len(failures) or not set(failures) <= known_checks):
                raise ResearchError('Worker report does not match the assigned benchmark.', status=422)
            db.execute("UPDATE pc_task SET status='completed',updated_at=?,lease_until=NULL,result_json=?,result_hash=? WHERE id=?",
                       (self.clock(), body, result_digest, task_id))
            return {'accepted': True, 'task_id': task_id}

    def fail(self, token, task_id, payload):
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._leased(db, token, task_id, payload.lease_token)
            if row['status'] == 'failed' and row['error_code'] == payload.error_code:
                return {'accepted': True, 'task_id': task_id}
            if row['status'] != 'running':
                raise ResearchError('Task is no longer running.', status=409)
            db.execute("UPDATE pc_task SET status='failed',updated_at=?,lease_until=NULL,error_code=? WHERE id=?",
                       (self.clock(), payload.error_code, task_id))
            return {'accepted': True, 'task_id': task_id}
