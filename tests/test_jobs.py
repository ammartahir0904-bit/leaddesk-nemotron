import asyncio
import hashlib
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import patch

from backend.adapters.discovery import discover_links
from backend.adapters.fetch import Page, fetch_page, retry_delay
from backend.domain.briefs import OfferInput, rules_draft
from backend.domain.errors import ResearchError
from backend.domain.extract import extract
from backend.domain.jobs import JobInput
from backend.evaluation.runner import run_parser_benchmark
from backend.storage.benchmarks import BenchmarkRepository
from backend.storage.briefs import BriefRepository
from backend.storage.jobs import JobRepository, LEASE_SECONDS
from backend.storage.repository import Repository
from backend.workflows.worker import WorkflowWorker
from tests.support import APITestCase

SOURCE = 'https://directory.example/'
DIRECTORY = ('<h1>Directory operator</h1><p>operator@directory.example</p>'
             '<a href="https://north.example/">Shared name · North</a>'
             '<a href="https://south.example/">Shared name · South</a>')


class DiscoveryTests(unittest.TestCase):
    def test_visible_external_links_preserve_source_without_operator_attribution(self):
        html = (DIRECTORY + '<a href="https://north.example/#contact">Duplicate</a>'
                '<a href="/local">Local profile</a><a hidden href="https://hidden.example/">Hidden</a>'
                '<a href="http://127.0.0.1/">Private</a><a href="mailto:operator@directory.example">Email</a>'
                '<a href="https://user:pass@credential.example/">Credentials</a>')
        page = Page(SOURCE, html.encode(), html)
        result = discover_links(page, 20)
        self.assertEqual([c['url'] for c in result['candidates']], ['https://north.example/', 'https://south.example/'])
        self.assertEqual(result['counts']['duplicate'], 1)
        self.assertEqual(result['counts']['invalid'], 3)
        self.assertEqual(result['counts']['same_host'], 1)
        for candidate in result['candidates']:
            self.assertEqual(candidate['source_sha256'], hashlib.sha256(html.encode()).hexdigest())
            self.assertEqual(candidate['source_url'], SOURCE)
            self.assertIn(candidate['source_href'], html)
            self.assertNotIn('contacts', candidate)

    def test_limit_is_visible_and_same_domain_branches_are_not_merged(self):
        html = '<a href="https://branch.example/north">North</a><a href="https://branch.example/south">South</a>'
        page = Page(SOURCE, html.encode(), html)
        self.assertEqual(len(discover_links(page, 20)['candidates']), 2)
        limited = discover_links(page, 1)
        self.assertEqual(len(limited['candidates']), 1)
        self.assertEqual(limited['counts']['over_limit'], 1)

    def test_retry_after_seconds_date_invalid_and_fetch_propagation(self):
        self.assertEqual(retry_delay('90'), 90)
        self.assertIsNone(retry_delay('invalid'))
        future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=120), usegmt=True)
        self.assertGreater(retry_delay(future), 0)
        with patch('backend.adapters.fetch.request', side_effect=[(404, {}, b''), (429, {'retry-after': '90'}, b'')]):
            with self.assertRaises(ResearchError) as caught:
                fetch_page(SOURCE)
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(caught.exception.retry_after, 90)
        with self.assertRaises(ResearchError):
            fetch_page(SOURCE, budget_seconds=0)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'jobs.sqlite3'
        self.repository = Repository(self.path)
        self.briefs = BriefRepository(self.repository)
        self.brief = self.briefs.create(rules_draft(OfferInput(offer='Any useful offer', target_geography='Any market')), 'brief', 'digest')
        self.clock = [1000.0]
        self.jobs = JobRepository(self.repository, clock=lambda: self.clock[0])
        self.calls = []
        self.failure = None
        self.on_fetch = None
        self.lock = threading.Lock()
        self.worker = WorkflowWorker(self.jobs, self.lock, fetcher=self.fetcher)

    def fetcher(self, url, remaining):
        self.calls.append(url)
        self.assertGreater(remaining, 0)
        self.assertLessEqual(remaining, 300)
        if self.on_fetch:
            self.on_fetch(url)
        if self.failure:
            raise self.failure
        html = DIRECTORY if url == SOURCE else f'<h1>Shared business name</h1><p>team@{url.split("/")[2]}</p>'
        return Page(url, html.encode(), html)

    def create(self, key='job', **changes):
        return self.jobs.create(JobInput(brief_id=self.brief['id'], brief_revision=1, source_url=SOURCE, **changes), key)

    def drain(self, limit=10):
        for _ in range(limit):
            if not self.worker.run_once():
                break

    def test_end_to_end_directory_contacts_are_not_copied_and_identity_stays_unresolved(self):
        job = self.create()
        self.drain()
        result = self.jobs.get(job['id'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['page_attempts'], 3)
        self.assertEqual(self.calls, [SOURCE, 'https://north.example/', 'https://south.example/'])
        records = [self.repository.get(step['research_id']) for step in result['steps'] if step['research_id']]
        self.assertEqual(len(records), 2)
        self.assertNotEqual(records[0]['business_id'], records[1]['business_id'])
        self.assertEqual(records[0]['canonical_name'], records[1]['canonical_name'])
        for record in records:
            self.assertEqual(record['identity_status'], 'unresolved')
            self.assertEqual(record['product_brief'], self.brief)
            self.assertTrue(all(c['raw_value'] != 'operator@directory.example' for c in record['contacts']))
        self.assertIn('retrieved_at', result['steps'][1]['candidate'])
        self.assertIn('geographic coverage', result['coverage_gaps'][0])

    def test_pause_before_run_and_during_page_preserves_results_without_next_fetch(self):
        job = self.create(start_paused=True)
        self.assertFalse(self.worker.run_once())
        self.assertEqual(self.calls, [])
        self.jobs.control(job['id'], 'resume', 'resume')
        self.on_fetch = lambda url: self.jobs.control(job['id'], 'pause', 'during-page')
        self.worker.run_once()
        paused = self.jobs.get(job['id'])
        self.assertEqual(paused['status'], 'paused')
        self.assertEqual(paused['steps'][0]['state'], 'completed')
        self.assertEqual(paused['page_attempts'], 1)
        self.assertFalse(self.worker.run_once())
        self.on_fetch = None
        self.jobs.control(job['id'], 'resume', 'resume-again')
        self.drain()
        self.assertEqual(self.jobs.get(job['id'])['status'], 'completed')
        self.assertEqual(len(self.calls), 3)

    def test_cancellation_during_candidate_fetch_retains_that_result_and_stops_next_page(self):
        job = self.create()
        self.worker.run_once()
        self.on_fetch = lambda url: self.jobs.control(job['id'], 'cancel', 'cancel')
        self.worker.run_once()
        result = self.jobs.get(job['id'])
        self.assertEqual(result['status'], 'cancelled')
        self.assertIsNotNone(result['steps'][1]['research_id'])
        self.assertIsNone(result['steps'][2]['research_id'])
        self.assertFalse(self.worker.run_once())
        self.assertEqual(len(self.calls), 2)

    def test_control_replays_do_not_reapply_old_pause_or_reset_budgets(self):
        job = self.create()
        self.jobs.control(job['id'], 'pause', 'old-pause')
        self.jobs.control(job['id'], 'resume', 'new-resume')
        repeated = self.jobs.control(job['id'], 'pause', 'old-pause')
        self.assertEqual(repeated['status'], 'queued')
        with self.assertRaises(ResearchError) as caught:
            self.jobs.control(job['id'], 'cancel', 'old-pause')
        self.assertEqual(caught.exception.status, 409)
        self.worker.run_once()
        self.jobs.control(job['id'], 'pause', 'pause-two')
        self.jobs.control(job['id'], 'resume', 'resume-two')
        self.assertEqual(self.jobs.get(job['id'])['page_attempts'], 1)

    def test_retries_respect_provider_delay_and_resume_cannot_bypass_it(self):
        job = self.create(page_budget=6)
        self.failure = ResearchError('HTTP 429', retryable=True, status=502, retry_after=90)
        self.worker.run_once()
        waiting = self.jobs.get(job['id'])
        self.assertEqual(waiting['status'], 'retry_wait')
        self.assertEqual(waiting['next_attempt_at'], 1090)
        self.jobs.control(job['id'], 'pause', 'pause')
        resumed = self.jobs.control(job['id'], 'resume', 'resume')
        self.assertEqual(resumed['next_attempt_at'], 1090)
        self.clock[0] = 1089
        self.assertFalse(self.worker.run_once())
        self.failure = None
        self.clock[0] = 1090
        self.drain()
        self.assertEqual(self.jobs.get(job['id'])['status'], 'completed')
        self.assertEqual(self.jobs.get(job['id'])['page_attempts'], 4)

    def test_retry_cap_and_non_retryable_source_failure(self):
        job = self.create(page_budget=6)
        self.failure = ResearchError('Temporary failure', retryable=True)
        self.worker.run_once()
        self.clock[0] += 10
        self.worker.run_once()
        self.assertEqual(self.jobs.get(job['id'])['status'], 'failed')
        self.assertEqual(len(self.calls), 2)
        self.failure = ResearchError('Robots denied', status=403)
        other = self.create('other')
        self.worker.run_once()
        self.assertEqual(self.jobs.get(other['id'])['status'], 'failed')
        self.assertEqual(self.jobs.get(other['id'])['page_attempts'], 1)

    def test_candidate_failure_is_partial_but_other_candidate_evidence_survives(self):
        job = self.create(page_budget=6)
        self.worker.run_once()
        self.failure = ResearchError('Access denied', status=403)
        self.worker.run_once()
        self.failure = None
        self.worker.run_once()
        result = self.jobs.get(job['id'])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['steps'][1]['state'], 'failed')
        self.assertIsNotNone(result['steps'][2]['research_id'])

    def test_page_time_and_candidate_limits_stop_without_fabricating_results(self):
        page_limited = self.create(page_budget=1)
        self.drain()
        result = self.jobs.get(page_limited['id'])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['page_attempts'], 1)
        self.assertEqual(self.repository.recent(), [])
        timed = self.create('timed', time_budget_seconds=30)
        self.jobs.claim('timed-owner')
        discovery = discover_links(Page(SOURCE, DIRECTORY.encode(), DIRECTORY), 10)
        self.jobs.complete(timed['id'], 'timed-owner', 31, discovery=discovery)
        self.assertEqual(self.jobs.get(timed['id'])['status'], 'partial')
        limited = self.create('limited', candidate_limit=1)
        self.drain()
        self.assertEqual(self.jobs.get(limited['id'])['status'], 'partial')
        self.assertIn('Candidate limit', self.jobs.get(limited['id'])['stop_reason'])

    def test_expired_lease_is_recovered_and_stale_owner_cannot_commit(self):
        job = self.create(page_budget=6, time_budget_seconds=300)
        first = self.jobs.claim('old-owner')
        self.assertIsNotNone(first)
        self.assertIsNone(self.jobs.claim('other-worker'))
        self.clock[0] += LEASE_SECONDS + 1
        recovered = self.jobs.claim('new-owner')
        self.assertEqual(recovered['active_step']['attempts'], 2)
        discovery = discover_links(Page(SOURCE, DIRECTORY.encode(), DIRECTORY), 10)
        self.assertFalse(self.jobs.complete(job['id'], 'old-owner', 1, discovery=discovery))
        self.assertFalse(self.jobs.heartbeat(job['id'], 'old-owner'))
        self.assertFalse(self.jobs.fail(job['id'], 'old-owner', ResearchError('Late failure'), 1))
        self.assertTrue(self.jobs.complete(job['id'], 'new-owner', 1, discovery=discovery))
        self.assertEqual(self.jobs.get(job['id'])['page_attempts'], 2)

    def test_repeated_worker_crashes_exhaust_attempts_without_unbounded_replays(self):
        job = self.create(page_budget=6, time_budget_seconds=300)
        self.jobs.claim('first-worker')
        self.clock[0] += LEASE_SECONDS + 1
        self.jobs.claim('second-worker')
        self.clock[0] += LEASE_SECONDS + 1
        self.assertIsNone(self.jobs.claim('third-worker'))
        self.assertEqual(self.jobs.get(job['id'])['status'], 'failed')
        self.assertEqual(self.jobs.get(job['id'])['page_attempts'], 2)
        self.assertEqual(self.calls, [])

    def test_exhausted_source_returns_an_explicit_gap_instead_of_leads(self):
        job = self.create()
        html = '<h1>Directory without external text links</h1>'
        self.worker.fetcher = lambda url, remaining: Page(url, html.encode(), html)
        self.drain()
        result = self.jobs.get(job['id'])
        self.assertEqual(result['status'], 'partial')
        self.assertIn('Source exhausted', result['stop_reason'])
        self.assertEqual(len(result['steps']), 1)
        self.assertEqual(self.repository.recent(), [])

    def test_result_and_step_rollback_together_then_commit_once(self):
        job = self.create()
        self.worker.run_once()
        claimed = self.jobs.claim('owner')
        step = claimed['active_step']
        page = self.fetcher(step['url'], 100)
        original = self.repository.save_in_transaction

        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('Simulated process interruption before step commit')

        with patch.object(self.repository, 'save_in_transaction', side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.jobs.complete(job['id'], 'owner', 1, page=page, extracted=extract(page.html))
        self.assertEqual(self.repository.recent(), [])
        self.assertEqual(self.jobs.get(job['id'])['steps'][1]['state'], 'running')
        self.assertTrue(self.jobs.complete(job['id'], 'owner', 1, page=page, extracted=extract(page.html)))
        self.assertFalse(self.jobs.complete(job['id'], 'owner', 1, page=page, extracted=extract(page.html)))
        self.assertEqual(len(self.repository.recent()), 1)

    def test_restart_preserves_scope_brief_pause_and_control_receipts(self):
        job = self.create(start_paused=True)
        changed = self.brief['document'] | {'input': self.brief['document']['input'] | {'offer': 'New offer'}}
        self.briefs.update(self.brief['id'], 1, changed, 'edit', 'edit-digest')
        repeated = self.create(start_paused=True)
        self.assertEqual(repeated['id'], job['id'])
        restarted = JobRepository(Repository(self.path), clock=lambda: self.clock[0])
        self.assertEqual(restarted.get(job['id'])['status'], 'paused')
        self.assertEqual(restarted.get(job['id'])['product_brief'], self.brief)
        restarted.control(job['id'], 'resume', 'resume-after-restart')
        new_worker = WorkflowWorker(restarted, self.lock, fetcher=self.fetcher)
        for _ in range(3):
            new_worker.run_once()
        result = restarted.get(job['id'])
        self.assertEqual(result['status'], 'completed')
        record = self.repository.get(result['steps'][1]['research_id'])
        self.assertEqual(record['product_brief'], self.brief)
        with self.assertRaises(ResearchError) as caught:
            self.create('stale-brief')
        self.assertEqual(caught.exception.status, 409)

    def test_job_scope_is_immutable_and_queue_backpressure_is_bounded(self):
        first = self.create(start_paused=True)
        with self.repository.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('UPDATE workflow_job SET input_json=? WHERE id=?', ('{}', first['id']))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('UPDATE workflow_step SET url=? WHERE job_id=?', ('https://other.example/', first['id']))
        for index in range(19):
            self.create(str(index), start_paused=True)
        with self.assertRaises(ResearchError) as caught:
            self.create('overflow')
        self.assertEqual(caught.exception.status, 429)
        self.jobs.control(first['id'], 'cancel', 'cancel-first')
        self.create('new-slot', start_paused=True)

    def test_interactive_execution_lock_prevents_a_background_fetch(self):
        self.create()
        with self.lock:
            self.assertFalse(self.worker.run_once())
        self.assertEqual(self.calls, [])
        self.assertTrue(self.worker.run_once())

    def test_prior_corrections_suppress_contacts_in_future_queued_results(self):
        first = self.create()
        self.drain()
        research_id = self.jobs.get(first['id'])['steps'][1]['research_id']
        contact = self.repository.get(research_id)['contacts'][0]
        self.repository.correct(contact['id'], 'wrong_branch', 'Previously reviewed', None)
        second = self.create('second-run')
        self.drain()
        next_id = self.jobs.get(second['id'])['steps'][1]['research_id']
        self.assertTrue(self.repository.get(next_id)['contacts'][0]['suppressed'])

    def test_upgrade_from_sprint_three_preserves_briefs_snapshots_feedback_and_benchmarks(self):
        path = Path(self.temp.name) / 'sprint-three.sqlite3'
        migrations = Path('backend/storage/migrations')
        with sqlite3.connect(path) as db:
            for version, name in ((1, '001_initial.sql'), (2, '002_benchmarks.sql'), (3, '003_product_briefs.sql')):
                db.executescript((migrations / name).read_text())
                db.execute('INSERT INTO schema_migration VALUES(?,?)', (version, 'old'))
                db.commit()
        with patch.object(Repository, 'migrate'):
            old = Repository(path)
        old_brief = BriefRepository(old).create(self.brief['document'], 'old-brief', 'old-digest')
        page = self.fetcher('https://north.example/', 120)
        payload = {'product': 'Original offer', 'location': 'Original city'}
        record = old.save(payload, 'old-research', page, extract(page.html), brief_snapshot=old_brief)
        corrected = old.correct(record['contacts'][0]['id'], 'wrong_branch', 'Original correction', None)
        benchmark = BenchmarkRepository(old).save(run_parser_benchmark({}, 2))
        upgraded = Repository(path)
        self.assertEqual(upgraded.get(record['id']), corrected)
        self.assertEqual(BriefRepository(upgraded).get(old_brief['id']), old_brief)
        self.assertEqual(BenchmarkRepository(upgraded).get(benchmark['id']), benchmark)
        self.assertEqual(JobRepository(upgraded).recent(), [])
        with upgraded.connect() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM schema_migration').fetchone()[0], 18)


class JobAPITests(APITestCase):
    async def make_brief(self):
        return (await self.send('POST', '/v1/briefs', headers={'Idempotency-Key': 'brief'},
            json={'offer': 'Any useful offer', 'target_geography': 'Any market'})).json()

    async def test_authenticated_async_enqueue_replay_validation_and_controls(self):
        for method, path in [('GET', '/v1/jobs'), ('GET', '/v1/jobs/missing'), ('GET', '/v1/discovery/connectors'),
                             ('POST', '/v1/jobs'), ('POST', '/v1/jobs/missing/control')]:
            self.assertEqual((await self.send(method, path, json={}, headers={'Authorization': ''})).status_code, 401)
        brief = await self.make_brief()
        payload = {'brief_id': brief['id'], 'brief_revision': 1, 'synthetic': True, 'start_paused': True}
        response = await self.send('POST', '/v1/jobs', json=payload, headers={'Idempotency-Key': 'queue'})
        self.assertEqual(response.status_code, 202, response.text)
        job = response.json()
        self.assertEqual(job['status'], 'paused')
        self.assertEqual(self.calls, [])
        repeat = await self.send('POST', '/v1/jobs', json=payload, headers={'Idempotency-Key': 'queue'})
        self.assertEqual(repeat.json()['id'], job['id'])
        conflict = await self.send('POST', '/v1/jobs', json=payload | {'page_budget': 6}, headers={'Idempotency-Key': 'queue'})
        self.assertEqual(conflict.status_code, 409)
        for change in ({'page_budget': 7}, {'page_budget': True}, {'synthetic': False}, {'source_url': 'https://real.example/'}, {'unknown': True}):
            invalid = await self.send('POST', '/v1/jobs', json=payload | change, headers={'Idempotency-Key': 'invalid'})
            self.assertEqual(invalid.status_code, 422, invalid.text)
        control = await self.send('POST', f"/v1/jobs/{job['id']}/control", json={'action': 'resume'}, headers={'Idempotency-Key': 'resume'})
        self.assertEqual(control.json()['status'], 'queued')
        for _ in range(3):
            self.app.state.workflow_worker.run_once()
        completed = (await self.send('GET', f"/v1/jobs/{job['id']}")).json()
        self.assertEqual(completed['status'], 'completed')
        self.assertEqual(completed['product_brief'], brief)
        for step in completed['steps'][1:]:
            record = (await self.send('GET', f"/v1/research/{step['research_id']}")).json()
            self.assertTrue(record['synthetic'])
        self.assertEqual(self.calls, [])

    async def test_server_lifespan_runs_worker_and_shutdown_leaves_no_background_thread(self):
        brief = await self.make_brief()
        response = await self.send('POST', '/v1/jobs', headers={'Idempotency-Key': 'automatic'}, json={
            'brief_id': brief['id'], 'brief_revision': 1, 'synthetic': True})
        job_id = response.json()['id']
        async with self.app.router.lifespan_context(self.app):
            for _ in range(100):
                state = (await self.send('GET', f'/v1/jobs/{job_id}')).json()['status']
                if state == 'completed':
                    break
                await asyncio.sleep(.02)
            self.assertEqual(state, 'completed')
        self.assertFalse(self.app.state.workflow_worker.thread.is_alive())
