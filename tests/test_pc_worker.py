"""Disposable storage, ASGI and injected transport; never connects a real PC."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from pydantic import ValidationError

from backend.domain.errors import ResearchError
from backend.domain.pc_worker import (CompleteTask, FailTask, PairWorker, WorkerTask, executor_hash, fixture_hash)
from backend.storage.pc_worker import PCWorkerRepository
from backend.storage.repository import Repository
from backend.workflows.pc_client import (PCWorkerClient, WorkerProtocolError, WorkerRevoked, coordinator_url,
                                        execute_subprocess, read_credential)
from backend.workflows.pc_executor import execute_benchmark
from tests.support import APITestCase, TOKEN


class PCWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'test.sqlite3'
        self.repository = Repository(self.path)
        self.time = [1000.0]
        self.workers = PCWorkerRepository(self.repository, clock=lambda: self.time[0])
        self.paired = self.workers.pair(PairWorker(name='Synthetic PC'), 'pair')
        self.credential = self.paired['credential']
        self.token = self.credential['token']
        self.worker_id = self.credential['worker_id']

    def create(self, key='task', **changes):
        return self.workers.create(WorkerTask(worker_id=self.worker_id, kind='synthetic_parser_benchmark', rounds=2, **changes), key)

    def claim(self, key='claim', token=None):
        return self.workers.claim(token or self.token, key)['task']

    def completion(self, claimed, **changes):
        return CompleteTask(lease_token=claimed['lease_token'], result=execute_benchmark(claimed['rounds']) | changes)

    def test_default_disabled_pair_once_and_only_hashes_persist(self):
        blank = PCWorkerRepository(Repository(Path(self.temp.name) / 'empty.sqlite3'))
        self.assertFalse(blank.overview()['enabled'])
        self.assertIsNone(self.workers.pair(PairWorker(name='Synthetic PC'), 'pair')['credential'])
        with self.assertRaises(ResearchError) as error:
            self.workers.pair(PairWorker(name='Different PC'), 'pair')
        self.assertEqual(error.exception.status, 409)
        with self.repository.connect() as db:
            persisted = str([tuple(r) for r in db.execute('SELECT * FROM pc_worker')])
        self.assertNotIn(self.token, persisted)
        self.assertNotIn(self.token, json.dumps(self.workers.overview()))

    def test_offline_queue_and_single_slot_require_explicit_worker(self):
        first = self.create()
        other = self.workers.pair(PairWorker(name='Second PC'), 'pair-2')['credential']
        self.assertIsNone(self.claim(token=other['token']))
        self.assertEqual(next(w for w in self.workers.overview()['workers'] if w['id'] == self.worker_id)['connection'], 'offline')
        self.assertEqual(self.workers.get(first['id'])['status'], 'queued')
        leased = self.claim()
        self.assertEqual(leased['id'], first['id'])
        self.create('second-task')
        self.assertIsNone(self.claim('parallel'))
        self.assertEqual(self.claim()['lease_token'], leased['lease_token'])
        with self.assertRaises(ResearchError):
            self.workers.heartbeat(other['token'], first['id'], leased['lease_token'])

    def test_completion_replay_conflict_and_separate_unverified_provenance(self):
        first = self.create()
        leased = self.claim()
        payload = self.completion(leased)
        self.workers.complete(self.token, first['id'], payload)
        self.time[0] += 1000
        self.assertTrue(self.workers.complete(self.token, first['id'], payload)['accepted'])
        conflict = payload.model_copy(update={'result': payload.result.model_copy(update={'total_ms': 1234.0})})
        with self.assertRaises(ResearchError):
            self.workers.complete(self.token, first['id'], conflict)
        task = self.workers.get(first['id'])
        self.assertEqual(task['status'], 'completed')
        self.assertEqual(task['provenance'], 'unverified_worker_report')
        self.assertTrue(task['synthetic'])
        self.assertIsNone(task['model_hash'])
        self.assertEqual(self.repository.recent(), [])
        self.assertIsNone(self.claim())  # Replayed old claim cannot take new work.
        with self.repository.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM benchmark_run').fetchone()[0], 0)

    def test_lost_claim_response_replays_same_lease_without_extending_it(self):
        self.create()
        leased = self.claim()
        self.time[0] += 10
        self.assertEqual(self.claim(), leased)
        self.assertEqual(self.workers.get(leased['id'])['lease_until'], 1060)
        with self.repository.connect() as db:
            stored = str([tuple(r) for r in db.execute('SELECT * FROM pc_task')])
        self.assertNotIn(leased['lease_token'], stored)
        self.assertNotIn(leased['lease_token'], json.dumps(self.workers.overview()))

    def test_disconnect_restart_expiry_and_late_result_fencing(self):
        first = self.create()
        old = self.claim()
        self.time[0] += 61
        restarted = PCWorkerRepository(Repository(self.path), clock=lambda: self.time[0])
        resumed = restarted.claim(self.token, 'after-restart')['task']
        self.assertEqual(resumed['id'], first['id'])
        self.assertEqual(resumed['attempts'], 2)
        with self.assertRaises(ResearchError):
            restarted.complete(self.token, first['id'], self.completion(old))
        self.assertTrue(restarted.complete(self.token, first['id'], self.completion(resumed))['accepted'])

    def test_repeated_disconnects_stop_after_three_attempts(self):
        first = self.create()
        for number in range(3):
            self.assertEqual(self.claim(f'claim-{number}')['attempts'], number + 1)
            self.time[0] += 61
        self.assertIsNone(self.claim('fourth'))
        result = self.workers.get(first['id'])
        self.assertEqual((result['status'], result['error_code']), ('failed', 'disconnect_limit'))

    def test_heartbeat_extends_lease_but_cannot_run_forever(self):
        self.create()
        leased = self.claim()
        self.time[0] += 50
        self.workers.heartbeat(self.token, leased['id'], leased['lease_token'])
        self.assertEqual(self.workers.get(leased['id'])['lease_until'], 1110)
        self.time[0] += 50
        self.workers.heartbeat(self.token, leased['id'], leased['lease_token'])
        self.assertEqual(self.workers.get(leased['id'])['lease_until'], 1120)
        self.time[0] = 1121
        with self.assertRaises(ResearchError):
            self.workers.heartbeat(self.token, leased['id'], leased['lease_token'])
        self.assertEqual(self.workers.get(leased['id'])['status'], 'queued')

    def test_cancel_and_revoke_beat_late_results_and_replays(self):
        first = self.create()
        leased = self.claim()
        self.workers.cancel(first['id'])
        self.workers.cancel(first['id'])
        with self.assertRaises(ResearchError):
            self.workers.complete(self.token, first['id'], self.completion(leased))
        self.assertEqual(self.create()['status'], 'cancelled')
        second = self.create('second')
        next_lease = self.claim('next')
        self.workers.revoke(self.worker_id)
        self.workers.revoke(self.worker_id)
        self.assertEqual(self.workers.get(second['id'])['status'], 'cancelled')
        for action in (lambda: self.claim('after-revoke'), lambda: self.workers.complete(self.token, second['id'], self.completion(next_lease))):
            with self.assertRaises(ResearchError) as error:
                action()
            self.assertEqual(error.exception.status, 401)
        self.assertIsNone(self.workers.pair(PairWorker(name='Synthetic PC'), 'pair')['credential'])
        self.assertFalse(self.workers.overview()['enabled'])

    def test_mismatched_forged_results_and_bad_values_are_rejected(self):
        self.create()
        leased = self.claim()
        for change in ({'rounds': 3}, {'fixture_sha256': '0' * 64}, {'executor_sha256': '0' * 64},
                       {'check_count': 9}, {'passed_count': 9}, {'failed_checks': ['unknown:1']},
                       {'failed_checks': ['visible:1', 'visible:1'], 'passed_count': 8}):
            with self.assertRaises(ResearchError):
                self.workers.complete(self.token, leased['id'], self.completion(leased, **change))
        for change in ({'total_ms': float('nan')}, {'rounds': True}, {'hardware': {'secret': 'private'}},
                       {'files': ['private']}, {'measured_at': '2026-10-20T12:00:00'}, {'measured_at': 'not-a-date'}):
            with self.assertRaises(ValidationError):
                self.completion(leased, **change)
        self.assertEqual(self.workers.get(leased['id'])['status'], 'running')

    def test_failed_benchmark_checks_remain_visible_without_becoming_source_facts(self):
        self.create()
        leased = self.claim()
        from backend.evaluation.cases import PARSER_CASES
        payload = self.completion(leased, passed_count=9, failed_checks=[f'{PARSER_CASES[0].id}:1'])
        self.workers.complete(self.token, leased['id'], payload)
        result = self.workers.get(leased['id'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['benchmark_status'], 'failed')
        self.assertEqual(self.workers.overview()['tasks'][0]['benchmark_status'], 'failed')
        self.assertEqual(self.repository.recent(), [])

    def test_oversized_result_rolls_back_without_losing_lease(self):
        self.create()
        leased = self.claim()
        payload = self.completion(leased, passed_count=9, failed_checks=['x' * 13000])
        with self.assertRaises(ResearchError) as error:
            self.workers.complete(self.token, leased['id'], payload)
        self.assertEqual(error.exception.status, 413)
        self.assertEqual(self.workers.get(leased['id'])['status'], 'running')
        self.workers.complete(self.token, leased['id'], self.completion(leased))

    def test_explicit_failure_is_replay_safe_and_cannot_replace_result(self):
        self.create()
        leased = self.claim()
        payload = FailTask(lease_token=leased['lease_token'], error_code='executor_mismatch')
        self.workers.fail(self.token, leased['id'], payload)
        self.workers.fail(self.token, leased['id'], payload)
        self.assertEqual(self.workers.get(leased['id'])['error_code'], 'executor_mismatch')
        with self.assertRaises(ResearchError):
            self.workers.complete(self.token, leased['id'], self.completion(leased))

    def test_fixed_task_scope_idempotency_queue_limit_and_atomic_failure(self):
        first = self.create()
        self.assertEqual(self.create()['id'], first['id'])
        with self.assertRaises(ResearchError):
            self.workers.create(WorkerTask(worker_id=self.worker_id, kind='synthetic_parser_benchmark', rounds=3), 'task')
        with self.repository.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('UPDATE pc_task SET rounds=3 WHERE id=?', (first['id'],))
        with patch('backend.storage.pc_worker.executor_hash', side_effect=OSError('Synthetic failure')):
            with self.assertRaises(OSError):
                self.create('rolled-back')
        self.assertEqual(len(self.workers.overview()['tasks']), 1)
        for index in range(19):
            self.create(f'task-{index}')
        with self.assertRaises(ResearchError) as error:
            self.create('overflow')
        self.assertEqual(error.exception.status, 429)
        self.workers.cancel(first['id'])
        self.create('new-slot')

    def test_upgrade_from_sprint_eleven_preserves_all_prior_tables(self):
        path = Path(self.temp.name) / 'old.sqlite3'
        with sqlite3.connect(path) as db:
            for migration in sorted(Path('backend/storage/migrations').glob('*.sql'))[:8]:
                db.executescript(migration.read_text())
                db.execute('INSERT INTO schema_migration VALUES(?,?)', (int(migration.name[:3]), 'fixture'))
                db.commit()
        with patch.object(Repository, 'migrate'):
            old = Repository(path)
        # Seed actual feedback/suppression and compare every prior table.
        from backend.adapters.fetch import Page
        from backend.domain.extract import extract
        html = '<h1>Fictional branch</h1><p>test@fixture.example</p>'
        record = old.save({'product': 'Synthetic offer', 'location': 'Synthetic city'}, 'fixture',
                          Page('https://fixture.example/', html.encode(), html), extract(html), True)
        old.correct(record['contacts'][0]['id'], 'wrong_branch', 'Fictional correction', None)
        with old.connect() as db:
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name<>'schema_migration'")]
            before = {name: [tuple(r) for r in db.execute(f'SELECT * FROM "{name}"')] for name in tables}
        upgraded = Repository(path)
        with upgraded.connect() as db:
            self.assertEqual(before, {name: [tuple(r) for r in db.execute(f'SELECT * FROM "{name}"')] for name in tables})
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM schema_migration').fetchone()[0], 18)

    def transport(self, lose_claim=False, lose_completion=False):
        lost = {'claim': False, 'complete': False}

        def handle(request):
            token = request.headers['Authorization'][7:]
            body = json.loads(request.content or b'null')
            try:
                if request.url.path.endswith('/claim'):
                    value = self.workers.claim(token, request.headers['Idempotency-Key'])
                    if lose_claim and not lost['claim']:
                        lost['claim'] = True
                        raise httpx.ReadTimeout('Synthetic lost claim response')
                else:
                    task_id = request.url.path.split('/')[-2]
                    if request.url.path.endswith('/heartbeat'):
                        value = self.workers.heartbeat(token, task_id, body['lease_token'])
                    elif request.url.path.endswith('/complete'):
                        value = self.workers.complete(token, task_id, CompleteTask.model_validate(body))
                        if lose_completion and not lost['complete']:
                            lost['complete'] = True
                            raise httpx.ReadTimeout('Synthetic lost completion response')
                    else:
                        value = self.workers.fail(token, task_id, FailTask.model_validate(body))
                return httpx.Response(200, json=value)
            except ResearchError as error:
                return httpx.Response(error.status, json={'message': str(error)})
        return httpx.MockTransport(handle)

    def client(self, **options):
        client = PCWorkerClient('http://127.0.0.1:18765', self.credential, **options)
        self.addCleanup(client.close)
        return client

    def test_client_lost_claim_and_completion_retry_without_duplicate_execution(self):
        first = self.create()
        execution = []
        def execute(rounds):
            execution.append(rounds)
            return execute_benchmark(rounds)
        client = self.client(transport=self.transport(lose_claim=True, lose_completion=True), executor=execute)
        with self.assertRaises(httpx.ReadTimeout):
            client.run_once()
        with self.assertRaises(httpx.ReadTimeout):
            client.run_once()
        self.assertIsNotNone(client.pending)
        self.assertEqual(client.run_once(), 'accepted')
        self.assertEqual(execution, [2])
        self.assertEqual(self.workers.get(first['id'])['attempts'], 1)

    def test_client_after_restart_waits_for_lease_then_resumes(self):
        self.create()
        client = self.client(transport=self.transport())
        self.claim('crashed-client')
        self.assertEqual(client.run_once(), 'idle')
        self.time[0] += 61
        self.assertEqual(client.run_once(), 'accepted')

    def test_client_executor_mismatch_never_executes_and_revocation_stops(self):
        first = self.create()
        client = self.client(transport=self.transport(), executor=lambda rounds: self.fail('Unexpected workload'))
        with patch('backend.workflows.pc_client.executor_hash', return_value='0' * 64):
            self.assertEqual(client.run_once(), 'accepted')
        self.assertEqual(self.workers.get(first['id'])['error_code'], 'executor_mismatch')
        self.workers.revoke(self.worker_id)
        with self.assertRaises(WorkerRevoked):
            client.run_once()

    def test_client_cancel_during_execution_discards_result(self):
        first = self.create()
        def execute(rounds):
            self.workers.cancel(first['id'])
            return execute_benchmark(rounds)
        client = self.client(transport=self.transport(), executor=execute)
        self.assertEqual(client.run_once(), 'stale')
        self.assertIsNone(self.workers.get(first['id'])['result'])

    def test_credential_permissions_symlinks_and_loopback_transport_policy(self):
        credential = Path(self.temp.name) / 'credential.json'
        credential.write_text(json.dumps(self.credential))
        credential.chmod(0o600)
        self.assertEqual(read_credential(credential), self.credential)
        credential.chmod(0o644)
        with self.assertRaises(WorkerProtocolError):
            read_credential(credential)
        credential.chmod(0o600)
        link = credential.with_suffix('.link')
        link.symlink_to(credential)
        with self.assertRaises(WorkerProtocolError):
            read_credential(link)
        for url in ('http://public.example:80', 'https://127.0.0.1:8765', 'http://127.0.0.1:8765/path',
                    'http://user:secret@127.0.0.1:8765', 'http://127.0.0.1:8765/?x=1', 'http://127.0.0.1:99999'):
            with self.assertRaises(WorkerProtocolError):
                coordinator_url(url)
        self.assertEqual(coordinator_url('http://127.0.0.1:18765/'), 'http://127.0.0.1:18765')

    def test_client_rejects_redirects_large_responses_and_arbitrary_job_kinds(self):
        for response in (httpx.Response(302, headers={'Location': 'http://public.example'}),
                         httpx.Response(200, content=b' ' * 16001),
                         httpx.Response(200, json={'task': {'id': self.worker_id, 'worker_id': self.worker_id,
                             'kind': 'shell', 'rounds': 2, 'lease_token': '0' * 64}})):
            client = self.client(transport=httpx.MockTransport(lambda request: response), executor=lambda rounds: self.fail('Unexpected workload'))
            with self.assertRaises(WorkerProtocolError):
                client.run_once()

    def test_fixed_executor_subprocess_reports_real_synthetic_measurement(self):
        report = execute_subprocess(2)
        self.assertEqual(report['check_count'], 10)
        self.assertEqual(report['passed_count'], 10)
        self.assertEqual(report['executor_sha256'], executor_hash())
        self.assertEqual(report['fixture_sha256'], fixture_hash())
        self.assertGreater(report['peak_runner_rss_bytes'], 0)


class PCWorkerAPITests(APITestCase):
    async def pair(self):
        response = await self.send('POST', '/v1/pc-workers', headers={'Idempotency-Key': 'pair'}, json={'name': 'Synthetic PC'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['credential']

    async def test_owner_worker_auth_isolation_and_complete_api_flow(self):
        credential = await self.pair()
        auth = {'Authorization': f"Bearer {credential['token']}"}
        task = (await self.send('POST', '/v1/pc-tasks', headers={'Idempotency-Key': 'task'}, json={
            'worker_id': credential['worker_id'], 'kind': 'synthetic_parser_benchmark', 'rounds': 2})).json()
        for path in ('/v1/research', '/v1/learning/versions', '/v1/pc-workers', f"/v1/pc-tasks/{task['id']}"):
            self.assertEqual((await self.send('GET', path, headers=auth)).status_code, 401)
        for bad in ('', 'Bearer wrong-worker-token-01234567890123456789', f'Bearer {TOKEN}'):
            response = await self.send('POST', '/v1/pc-worker/claim', headers={'Authorization': bad, 'Idempotency-Key': 'claim'})
            self.assertEqual(response.status_code, 401)
        claim = await self.send('POST', '/v1/pc-worker/claim', headers=auth | {'Idempotency-Key': 'claim'})
        self.assertEqual(claim.status_code, 200)
        self.assertEqual(claim.headers['cache-control'], 'no-store')
        leased = claim.json()['task']
        self.assertEqual(set(leased) & {'research', 'files', 'notes', 'screen', 'audio'}, set())
        heartbeat = await self.send('POST', f"/v1/pc-worker/tasks/{task['id']}/heartbeat", headers=auth, json={'lease_token': leased['lease_token']})
        self.assertEqual(heartbeat.status_code, 200)
        payload = {'lease_token': leased['lease_token'], 'result': execute_benchmark(2)}
        for _ in range(2):
            response = await self.send('POST', f"/v1/pc-worker/tasks/{task['id']}/complete", headers=auth, json=payload)
            self.assertEqual(response.status_code, 200, response.text)
        result = (await self.send('GET', f"/v1/pc-tasks/{task['id']}")).json()
        self.assertEqual(result['result']['passed_count'], 10)
        await self.send('POST', f"/v1/pc-workers/{credential['worker_id']}/revoke")
        self.assertEqual((await self.send('POST', '/v1/pc-worker/claim', headers=auth | {'Idempotency-Key': 'next'})).status_code, 401)

    async def test_strict_inputs_origin_body_limits_and_no_automatic_pairing(self):
        overview = (await self.send('GET', '/v1/pc-workers')).json()
        self.assertEqual(overview, {'workers': [], 'tasks': [], 'enabled': False})
        self.assertEqual((await self.send('POST', '/v1/pc-workers', json={'name': 'PC'}, headers={'Authorization': '', 'Idempotency-Key': 'pair'})).status_code, 401)
        credential = await self.pair()
        payload = {'worker_id': credential['worker_id'], 'kind': 'synthetic_parser_benchmark', 'rounds': 2}
        for change in ({'kind': 'shell'}, {'rounds': True}, {'rounds': 21}, {'path': '/private'}, {'url': 'https://public.example'}):
            response = await self.send('POST', '/v1/pc-tasks', headers={'Idempotency-Key': 'invalid'}, json=payload | change)
            self.assertEqual(response.status_code, 422)
        self.assertEqual((await self.send('POST', '/v1/pc-workers', headers={'Idempotency-Key': 'origin', 'Origin': 'https://evil.example'}, json={'name': 'PC'})).status_code, 403)
        self.assertEqual((await self.send('POST', '/v1/pc-workers', headers={'Idempotency-Key': 'large'}, content='x' * 16001)).status_code, 413)
