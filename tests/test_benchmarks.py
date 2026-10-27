import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from backend.adapters.fetch import Page
from backend.adapters.hardware import GIB, profile_hardware
from backend.adapters.local_model import LocalModelError, OllamaAdapter
from backend.domain.extract import extract
from backend.evaluation.cases import MODEL_CASES
from backend.evaluation.runner import run_model_benchmark, run_parser_benchmark
from backend.storage.benchmarks import BenchmarkRepository
from backend.storage.repository import Repository

DIGEST = 'a' * 64


class HardwareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.proc, self.sys = self.root / 'proc', self.root / 'sys'
        self.proc.mkdir(); self.sys.mkdir()
        self.addCleanup(self.temp.cleanup)

    def profile(self):
        return profile_hardware(self.root, proc_root=self.proc, sys_root=self.sys)

    def test_absent_telemetry_stays_unknown_without_gpu_requirement(self):
        result = self.profile()
        self.assertIsNone(result['cpu']['model'])
        self.assertIsNone(result['memory']['effective_available_bytes'])
        self.assertIsNone(result['memory']['total_bytes'])
        self.assertEqual(result['gpu']['devices'], [])
        self.assertIn('does not prove', result['gpu']['reason'])
        self.assertEqual(result['execution']['mode'], 'cpu')
        self.assertFalse(result['execution']['cloud_enabled'])
        self.assertFalse(result['execution']['remote_enabled'])
        self.assertGreater(result['disk']['free_bytes'], 0)

    def test_resource_values_cgroup_limits_and_gpu_without_dedicated_vram(self):
        (self.proc / 'cpuinfo').write_text('model name : Synthetic CPU\nSerial : must-not-collect\n')
        (self.proc / 'meminfo').write_text('MemTotal: 8388608 kB\nMemAvailable: 4194304 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n')
        group = self.sys / 'fs/cgroup'; group.mkdir(parents=True)
        (group / 'memory.max').write_text(str(3 * GIB))
        (group / 'memory.current').write_text(str(GIB))
        device = self.sys / 'class/drm/card0/device'; device.mkdir(parents=True)
        (device / 'vendor').write_text('0x8086'); (device / 'device').write_text('0x1234')
        (device / 'serial').write_text('private-gpu-identifier')
        result = self.profile()
        self.assertEqual(result['cpu']['model'], 'Synthetic CPU')
        self.assertEqual(result['memory']['total_bytes'], 8 * GIB)
        self.assertEqual(result['memory']['effective_available_bytes'], 2 * GIB)
        self.assertEqual(result['memory']['swap_free_bytes'], 0)
        self.assertIsNone(result['gpu']['devices'][0]['vram_bytes'])
        self.assertNotIn('must-not-collect', json.dumps(result))
        self.assertNotIn('private-gpu-identifier', json.dumps(result))

    def test_unlimited_or_missing_cgroup_usage_does_not_invent_available_ram(self):
        group = self.sys / 'fs/cgroup'; group.mkdir(parents=True)
        (group / 'memory.max').write_text('max')
        self.assertIsNone(self.profile()['memory']['effective_available_bytes'])
        (group / 'memory.max').write_text(str(GIB))
        self.assertIsNone(self.profile()['memory']['effective_available_bytes'])


class BenchmarkTests(unittest.TestCase):
    def test_parser_suite_is_repeatable_bounded_and_has_no_inference(self):
        first = run_parser_benchmark({}, 3)
        second = run_parser_benchmark({}, 3)
        self.assertEqual(first['fixture_sha256'], second['fixture_sha256'])
        self.assertEqual(first['sample_count'], 15)
        self.assertEqual(first['passed_count'], 15)
        self.assertEqual(first['status'], 'completed')
        self.assertIsNone(first['model_hash'])
        self.assertEqual(first['network_requests'], 0)
        self.assertEqual(first['inference_calls'], 0)
        self.assertIsNone(first['memory']['peak_model_ram_bytes'])
        for count in (0, 1, 201, True, 2.5):
            with self.subTest(count=count), self.assertRaises(ValueError):
                run_parser_benchmark({}, count)

    def test_parser_failure_is_reported_instead_of_hidden(self):
        with patch('backend.evaluation.runner.extract', return_value=extract('')):
            report = run_parser_benchmark({}, 2)
        self.assertEqual(report['status'], 'failed')
        self.assertLess(report['passed_count'], report['sample_count'])

    def test_upgrade_preserves_existing_research_evidence_and_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'existing.sqlite3'
            migration = Path('backend/storage/migrations/001_initial.sql').read_text()
            with sqlite3.connect(path) as db:
                db.executescript(migration + "\nINSERT INTO schema_migration VALUES(1,'old');")
            with patch.object(Repository, 'migrate'):
                legacy = Repository(path)
            html = '<h1>Fictional</h1><p>hello@fictional.example</p>'
            values = {'url': 'https://fictional.example', 'product': 'Any offer', 'location': 'Any city', 'synthetic': True}
            saved = legacy.save(values, 'existing-key', Page(values['url'], html.encode(), html), extract(html), True)
            before = legacy.correct(saved['contacts'][0]['id'], 'wrong_branch', 'Preserve correction', None)
            upgraded = Repository(path)
            self.assertEqual(upgraded.get(saved['id']), before)
            reports = BenchmarkRepository(upgraded)
            report = reports.save(run_parser_benchmark({}, 2), key='benchmark-key', request_hash='hash')
            restarted = BenchmarkRepository(Repository(path))
            self.assertEqual(restarted.get(report['id']), report)
            self.assertEqual(restarted.cached('benchmark-key', 'hash'), report)
            self.assertEqual(len(restarted.recent()), 1)
            with upgraded.connect() as db:
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertEqual(db.execute('SELECT COUNT(*) FROM schema_migration').fetchone()[0], 18)


class LocalModelTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.tag_digest = DIGEST
        self.remote = False
        self.response = {'done': True, 'response': '{}', 'load_duration': 1}
        self.status = 200
        self.adapter = OllamaAdapter('fictional:small', DIGEST, Path('/tmp'), transport=httpx.MockTransport(self.handle))
        self.addCleanup(self.adapter.close)
        self.memory = patch('backend.adapters.local_model.profile_hardware', return_value={
            'memory': {'effective_available_bytes': 4 * GIB}})
        self.memory.start(); self.addCleanup(self.memory.stop)

    def handle(self, request):
        self.calls.append(request)
        self.assertEqual(request.url.host, '127.0.0.1')
        if request.url.path == '/api/tags':
            model = {'name': 'fictional:small', 'digest': self.tag_digest, 'size': 100}
            if self.remote: model['remote_host'] = 'https://remote.example'
            return httpx.Response(200, json={'models': [model]})
        return httpx.Response(self.status, json=self.response)

    def test_explicit_local_generation_uses_cpu_limits_and_no_download_tool(self):
        self.adapter.generate('Synthetic evidence only')
        self.assertEqual([r.url.path for r in self.calls], ['/api/tags', '/api/generate', '/api/tags'])
        payload = json.loads(self.calls[1].content)
        self.assertEqual(payload['options']['num_gpu'], 0)
        self.assertEqual(payload['options']['num_ctx'], 2048)
        self.assertEqual(payload['keep_alive'], 0)
        self.assertFalse(payload['stream'])
        self.assertEqual(self.adapter.network_requests, 3)

    def test_digest_mismatch_prevents_generation(self):
        self.tag_digest = 'b' * 64
        with self.assertRaisesRegex(LocalModelError, 'digest'):
            self.adapter.generate('Synthetic')
        self.assertEqual([r.url.path for r in self.calls], ['/api/tags'])

    def test_remote_metadata_is_rejected(self):
        self.remote = True
        with self.assertRaisesRegex(LocalModelError, 'Remote'):
            self.adapter.generate('Synthetic')
        self.assertEqual(len(self.calls), 1)

    def test_invalid_model_selection_never_creates_a_runtime_client(self):
        for model, digest in (('', DIGEST), ('fictional model', DIGEST), ('fictional:small', 'latest')):
            with self.subTest(model=model), self.assertRaises(ValueError):
                OllamaAdapter(model, digest, Path('/tmp'))
        self.assertEqual(self.calls, [])

    def test_tag_drift_after_generation_is_rejected(self):
        original = self.handle

        def drift(request):
            response = original(request)
            if request.url.path == '/api/generate':
                self.tag_digest = 'b' * 64
            return response

        self.adapter.client.close()
        self.adapter.client = httpx.Client(base_url='http://127.0.0.1:11434', transport=httpx.MockTransport(drift))
        with self.assertRaisesRegex(LocalModelError, 'digest'):
            self.adapter.generate('Synthetic')

    def test_memory_is_rechecked_and_failure_makes_no_runtime_request(self):
        with patch('backend.adapters.local_model.profile_hardware', return_value={
            'memory': {'effective_available_bytes': 2 * GIB}}):
            with self.assertRaisesRegex(LocalModelError, 'memory'):
                self.adapter.generate('Synthetic')
        self.assertEqual(self.calls, [])

    def test_redirect_incomplete_and_oversized_runtime_responses_fail_closed(self):
        for response, status in (({'done': False}, 200), ({}, 302),
                                 ({'done': True, 'response': 'x' * 1_000_001}, 200)):
            with self.subTest(status=status):
                self.response, self.status = response, status
                with self.assertRaises(LocalModelError):
                    self.adapter.generate('Synthetic')

    def test_suite_records_failures_abstention_and_resource_stop(self):
        class FixedAdapter:
            index = 0
            def generate(self, prompt):
                case = MODEL_CASES[self.index % len(MODEL_CASES)]
                self.index += 1
                return {'response': json.dumps(case['expected'])}
        passed = run_model_benchmark(FixedAdapter(), {}, {'digest': DIGEST})
        self.assertEqual(passed['passed_count'], 8)
        self.assertEqual(passed['status'], 'completed')
        self.assertEqual(passed['model_hash'], DIGEST)
        self.assertIsNone(passed['memory']['peak_model_ram_bytes'])
        with patch.object(FixedAdapter, 'generate', return_value={'response': '{broken'}):
            failed = run_model_benchmark(FixedAdapter(), {}, {'digest': DIGEST})
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['sample_count'], 8)
        with patch.object(FixedAdapter, 'generate', side_effect=LocalModelError('Memory pressure')):
            partial = run_model_benchmark(FixedAdapter(), {}, {'digest': DIGEST})
        self.assertEqual(partial['status'], 'partial')
        self.assertEqual(partial['sample_count'], 1)
        self.assertEqual(partial['results'][0]['failure'], 'Memory pressure')
