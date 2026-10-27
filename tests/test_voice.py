"""Synthetic audio/CLI fixtures establish control behavior, never ASR accuracy."""
import asyncio
import hashlib
import io
import struct
import sys
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from backend.adapters.hardware import GIB
from backend.adapters.speech import SpeechCancelled, WhisperAdapter
from backend.domain.errors import ResearchError
from backend.domain.voice import MAX_AUDIO_BYTES, SpeechConfig, VoiceCommand, prepare_command, validate_audio
from backend.storage.repository import Repository
from tests.support import APITestCase


def wav(*, seconds=.25, channels=1, rate=16000, width=2, silent=False):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as audio:
        audio.setnchannels(channels); audio.setsampwidth(width); audio.setframerate(rate)
        frames = int(rate * seconds)
        sample = b'\0' * width if silent else (struct.pack('<h', 1000) if width == 2 else b'\x20' * width)
        audio.writeframes(sample * frames * channels)
    return stream.getvalue()


class FakeSpeech:
    def __init__(self, text='find files clinic', blocked=False):
        self.text, self.calls = text, 0
        self.entered = threading.Event(); self.release = threading.Event()
        if not blocked: self.release.set()

    def status(self):
        return {'available': True, 'max_seconds': 30, 'engine': 'fictional_test_adapter', 'cloud_enabled': False}

    def transcribe(self, body, language, cancelled):
        self.calls += 1; self.entered.set()
        while not self.release.wait(.01):
            if cancelled.is_set(): raise SpeechCancelled()
        return self.text


class VoiceAPITests(APITestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.voice = self.app.state.voice_service
        self.fake = FakeSpeech(); self.voice.adapter = self.fake

    async def asyncTearDown(self):
        self.voice.close()
        await super().asyncTearDown()

    async def upload(self, job_id=None, body=None, **kwargs):
        job_id = job_id or str(uuid4())
        response = await self.send('PUT', f'/v1/voice/transcriptions/{job_id}', content=body if body is not None else wav(),
                                   headers={'Content-Type': 'audio/wav'}, **kwargs)
        return job_id, response

    async def finished(self, job_id):
        for _ in range(100):
            response = await self.send('GET', f'/v1/voice/transcriptions/{job_id}')
            if response.json().get('state') != 'running': return response.json()
            await asyncio.sleep(.01)
        self.fail('Fictional voice job did not finish')

    async def prepare(self, transcript, **context):
        return await self.send('POST', '/v1/voice/commands/prepare', json={'transcript': transcript, **context})

    async def execute(self, plan, key='voice-command', **changes):
        operation = plan['operation']
        payload = {'transcript': plan['transcript'], 'expected_plan_hash': plan['plan_hash']}
        if operation['kind'] == 'search_files': payload['root_id'] = operation['root_id']
        else: payload['scope'] = operation.get('scope') or operation['note']['scope']
        return await self.send('POST', '/v1/voice/commands/execute', headers={'Idempotency-Key': key}, json=payload | changes)

    async def test_audio_upload_poll_replay_and_raw_audio_is_not_in_database(self):
        job_id, response = await self.upload()
        self.assertEqual(response.status_code, 202, response.text)
        result = await self.finished(job_id)
        self.assertEqual(result['state'], 'completed'); self.assertEqual(result['transcript'], 'find files clinic')
        self.assertEqual((await self.upload(job_id))[1].status_code, 202)
        self.assertEqual(self.fake.calls, 1)
        self.assertEqual((await self.upload(job_id, wav(seconds=.3)))[1].status_code, 409)
        with Repository(self.directory / 'leaddesk.sqlite3').connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM local_memory').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM schema_migration').fetchone()[0], 18)
            self.assertFalse(any('voice' in row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")))

    async def test_cancel_before_upload_is_a_tombstone_and_never_starts_inference(self):
        job_id = str(uuid4())
        self.assertEqual((await self.send('DELETE', f'/v1/voice/transcriptions/{job_id}')).status_code, 200)
        response = (await self.upload(job_id))[1]
        self.assertEqual(response.status_code, 202); self.assertEqual(response.json()['state'], 'cancelled')
        self.assertEqual(self.fake.calls, 0)

    async def test_cancel_in_flight_discards_late_result_and_releases_shared_lane(self):
        self.voice.adapter = self.fake = FakeSpeech(blocked=True)
        job_id, response = await self.upload()
        self.assertEqual(response.status_code, 202)
        self.fake.entered.wait(1)
        self.assertEqual((await self.send('POST', '/v1/demo', headers={'Idempotency-Key': 'busy'})).status_code, 429)
        for _ in range(2): await self.send('DELETE', f'/v1/voice/transcriptions/{job_id}')
        self.fake.release.set()
        self.voice.jobs[job_id]['thread'].join(1)
        self.assertIsNone((await self.finished(job_id))['transcript'])
        self.assertEqual((await self.send('POST', '/v1/demo', headers={'Idempotency-Key': 'after-cancel'})).status_code, 200)

    async def test_cancel_completed_text_and_expiry_remove_retrieval(self):
        job_id, _ = await self.upload(); await self.finished(job_id)
        await self.send('DELETE', f'/v1/voice/transcriptions/{job_id}')
        self.assertIsNone((await self.finished(job_id))['transcript'])
        self.voice.jobs[job_id]['finished'] -= 301
        self.assertEqual((await self.send('GET', f'/v1/voice/transcriptions/{job_id}')).status_code, 404)

    async def test_near_silence_abstains_without_model_and_adapter_failures_do_not_leak_diagnostics(self):
        job_id, response = await self.upload(body=wav(silent=True)); self.assertEqual(response.status_code, 202)
        self.assertEqual((await self.finished(job_id))['transcript'], ''); self.assertEqual(self.fake.calls, 0)
        with patch.object(self.fake, 'transcribe', side_effect=RuntimeError('Private fixture diagnostics')):
            job_id, _ = await self.upload(); result = await self.finished(job_id)
        self.assertEqual(result['state'], 'failed'); self.assertNotIn('Private', result['message'])

    async def test_unavailable_runtime_and_occupied_lane_fail_without_queueing(self):
        with patch.object(self.fake, 'status', return_value={'available': False}):
            self.assertEqual((await self.upload())[1].status_code, 503)
        self.voice.execution_lock.acquire()
        try: self.assertEqual((await self.upload())[1].status_code, 429)
        finally: self.voice.execution_lock.release()
        self.assertEqual(self.voice.jobs, {})

    async def test_auth_origin_content_type_uuid_and_audio_validation(self):
        job_id = str(uuid4()); path = f'/v1/voice/transcriptions/{job_id}'
        self.assertEqual((await self.send('PUT', path, content=wav(), headers={'Authorization': '', 'Content-Type': 'audio/wav'})).status_code, 401)
        self.assertEqual((await self.send('DELETE', path, headers={'Origin': 'https://untrusted.example'})).status_code, 403)
        self.assertEqual((await self.send('GET', '/v1/voice/status', headers={'Authorization': ''})).status_code, 401)
        self.assertEqual((await self.send('PUT', path, content=wav(), headers={'Content-Type': 'audio/webm'})).status_code, 415)
        self.assertEqual((await self.send('PUT', '/v1/voice/transcriptions/not-a-uuid', content=wav(), headers={'Content-Type': 'audio/wav'})).status_code, 422)
        self.assertEqual((await self.upload(body=b'not a wave'))[1].status_code, 422)
        for body in (wav(channels=2), wav(rate=8000), wav(width=1), wav(seconds=.1), wav()[:-4]):
            self.assertEqual((await self.upload(body=body))[1].status_code, 422)
        response = await self.send('PUT', path + '?language=arbitrary', content=wav(), headers={'Content-Type': 'audio/wav'})
        self.assertEqual(response.status_code, 422)

    async def test_only_audio_route_allows_large_bodies_and_chunked_upload_is_bounded(self):
        self.assertGreater(len(wav(seconds=1)), 16000)
        self.assertEqual((await self.upload(body=wav(seconds=1)))[1].status_code, 202)
        self.assertEqual((await self.send('POST', '/v1/voice/commands/prepare', json={'transcript': 'x' * 16000})).status_code, 413)
        async def chunks():
            for _ in range(5): yield b'x' * 250001
        response = await self.send('PUT', f'/v1/voice/transcriptions/{uuid4()}', content=chunks(), headers={'Content-Type': 'audio/wav'})
        self.assertEqual(response.status_code, 413)
        self.assertEqual((await self.upload(body=b'x' * (MAX_AUDIO_BYTES + 1)))[1].status_code, 413)

    async def test_prepare_does_not_save_and_changed_transcript_or_scope_cannot_apply_old_plan(self):
        plan = (await self.prepare('remember Original fictional note', scope='fixture-a')).json()
        self.assertEqual(plan['risk'], 'writes_memory')
        self.assertEqual((await self.send('GET', '/v1/memories?scope=fixture-a')).json()['total'], 0)
        self.assertEqual((await self.execute(plan, transcript='remember Corrected fictional note')).status_code, 409)
        self.assertEqual((await self.execute(plan, scope='fixture-b')).status_code, 409)
        corrected = (await self.prepare('remember Corrected fictional note', scope='fixture-a')).json()
        first = await self.execute(corrected); repeat = await self.execute(corrected)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['result']['id'], repeat.json()['result']['id'])
        self.assertEqual(first.json()['result']['content'], 'Corrected fictional note')
        self.assertFalse(first.json()['result']['training_eligible'])
        self.assertEqual((await self.send('GET', '/v1/memories?scope=fixture-b')).json()['items'], [])

    async def test_memory_search_is_explicit_scope_and_excludes_expired_notes(self):
        for index, values in enumerate([{'scope': 'fixture-a'}, {'scope': 'fixture-b'}, {'scope': 'fixture-a', 'expires_at': '2000-01-01T00:00:00Z'}]):
            await self.send('POST', '/v1/memories', json={'content': 'Fictional clinic requirements', **values}, headers={'Idempotency-Key': f'note-{index}'})
        plan = (await self.prepare('search memory clinic', scope='fixture-a')).json()
        result = (await self.execute(plan)).json()
        self.assertEqual(result['result']['total'], 1); self.assertEqual(result['result']['items'][0]['scope'], 'fixture-a')

    async def test_file_search_rechecks_revocation_and_missing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'clinic.txt'; file.write_text('Fictional clinic requirements')
            root = (await self.send('POST', '/v1/files/roots', json={'path': folder})).json()
            await self.send('POST', f"/v1/files/roots/{root['id']}/reconcile")
            plan = (await self.prepare('find files clinic', root_id=root['id'])).json()
            self.assertEqual(plan['risk'], 'read_only')
            self.assertEqual(len((await self.execute(plan)).json()['result']['items']), 1)
            file.unlink()
            self.assertEqual((await self.execute(plan)).json()['result']['items'], [])
            await self.send('DELETE', f"/v1/files/roots/{root['id']}")
            self.assertEqual((await self.execute(plan)).status_code, 404)

    async def test_unsupported_commands_and_missing_scopes_are_rejected_without_side_effects(self):
        for text in ('delete file /tmp/example', 'send an email', 'open a terminal', 'capture the screen', 'sudo reboot', 'yaad rakho note'):
            self.assertEqual((await self.prepare(text, scope='fixture')).status_code, 422)
        self.assertEqual((await self.prepare('find files clinic')).status_code, 422)
        self.assertEqual((await self.prepare('remember a note')).status_code, 422)
        self.assertEqual((await self.prepare('search memory note')).status_code, 422)
        self.assertEqual((await self.prepare('find files ' + 'x' * 250, root_id='unknown')).status_code, 422)
        self.assertEqual((await self.send('POST', '/v1/voice/commands/prepare', json={'transcript': 'remember note', 'scope': 'fixture', 'shell': 'bad'})).status_code, 422)

    async def test_session_quota_shutdown_and_invalid_adapter_output(self):
        with patch('backend.workflows.voice.MAX_JOBS', 1):
            first, _ = await self.upload(); await self.finished(first)
            self.assertEqual((await self.upload())[1].status_code, 429)
        self.fake.text = {'not': 'text'}
        job_id, _ = await self.upload()
        self.assertEqual((await self.finished(job_id))['state'], 'failed')
        self.voice.close()
        self.assertEqual(self.voice.jobs, {})
        self.assertEqual((await self.upload())[1].status_code, 503)

    async def test_server_shutdown_cancels_voice_and_leaves_no_voice_or_queue_thread(self):
        self.voice.adapter = self.fake = FakeSpeech(blocked=True)
        job_id, response = await self.upload()
        self.assertEqual(response.status_code, 202)
        thread = self.voice.jobs[job_id]['thread']
        async with self.app.router.lifespan_context(self.app):
            self.assertTrue(thread.is_alive())
        self.assertFalse(thread.is_alive())
        self.assertFalse(self.app.state.workflow_worker.thread.is_alive())
        self.assertEqual(self.voice.jobs, {})

    async def test_voice_shutdown_failure_still_stops_the_existing_queue_worker(self):
        with patch.object(self.voice, 'aclose', side_effect=RuntimeError('Fictional shutdown timeout')):
            with self.assertRaisesRegex(RuntimeError, 'shutdown timeout'):
                async with self.app.router.lifespan_context(self.app):
                    self.assertTrue(self.app.state.workflow_worker.thread.is_alive())
        self.assertFalse(self.app.state.workflow_worker.thread.is_alive())


class WhisperAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / 'fictional-model.bin'; self.model.write_bytes(b'fictional model fixture, not weights')
        self.cli = self.root / 'fictional-whisper-cli'
        self.write_cli("from pathlib import Path\nimport sys\noutput=sys.argv[sys.argv.index('--output-file')+1]\nPath(output+'.txt').write_text('find files clinic')\n")
        self.config = SpeechConfig(self.cli, self.model, hashlib.sha256(self.model.read_bytes()).hexdigest())
        self.adapter = WhisperAdapter(self.config, self.root)
        self.memory = patch('backend.adapters.speech.profile_hardware', return_value={'memory': {'effective_available_bytes': 4 * GIB}})
        self.memory.start(); self.addCleanup(self.memory.stop)

    def write_cli(self, code):
        self.cli.write_text('#!' + sys.executable + '\n' + code); self.cli.chmod(0o700)

    def test_explicit_runtime_cpu_args_minimal_environment_and_temp_cleanup(self):
        import subprocess
        original = subprocess.Popen
        with patch('backend.adapters.speech.subprocess.Popen', wraps=original) as spawn:
            text = self.adapter.transcribe(wav(), 'ur', threading.Event())
        self.assertEqual(text, 'find files clinic')
        args, options = spawn.call_args
        self.assertIn('--no-gpu', args[0]); self.assertEqual(args[0][args[0].index('--language') + 1], 'ur')
        self.assertNotIn('shell', options); self.assertTrue(options['start_new_session'])
        self.assertEqual(set(options['env']), {'PATH', 'LANG', 'OMP_NUM_THREADS'})
        self.assertFalse(Path(options['cwd']).exists())

    def test_digest_drift_low_memory_and_missing_runtime_never_spawn(self):
        with patch('backend.adapters.speech.subprocess.Popen') as spawn:
            self.model.write_bytes(b'changed fixture')
            with self.assertRaisesRegex(ResearchError, 'SHA-256'): self.adapter.transcribe(wav(), 'en', threading.Event())
            self.assertFalse(spawn.called)
        self.model.write_bytes(b'fictional model fixture, not weights')
        with patch('backend.adapters.speech.profile_hardware', return_value={'memory': {'effective_available_bytes': GIB}}), patch('backend.adapters.speech.subprocess.Popen') as spawn:
            with self.assertRaisesRegex(ResearchError, 'RAM'): self.adapter.transcribe(wav(), 'en', threading.Event())
            self.assertFalse(spawn.called)
        self.cli.unlink(); self.assertFalse(self.adapter.status()['available'])

    def test_cancel_and_timeout_terminate_the_child_and_remove_audio(self):
        import subprocess
        original = subprocess.Popen
        self.write_cli('import time\ntime.sleep(10)\n')
        for mode in ('cancel', 'timeout'):
            with self.subTest(mode=mode), patch('backend.adapters.speech.subprocess.Popen', wraps=original) as spawn:
                event = threading.Event()
                timer = threading.Timer(.15, event.set) if mode == 'cancel' else None
                if timer: timer.start(); self.addCleanup(timer.cancel)
                with patch('backend.adapters.speech.TIMEOUT', .05 if mode == 'timeout' else 90):
                    with self.assertRaises(SpeechCancelled if mode == 'cancel' else ResearchError):
                        self.adapter.transcribe(wav(), 'auto', event)
                self.assertFalse(Path(spawn.call_args.kwargs['cwd']).exists())

    def test_failed_oversized_and_invalid_utf8_output_are_not_transcripts(self):
        for code in ("raise SystemExit(3)\n", "from pathlib import Path\nimport sys\np=Path(sys.argv[sys.argv.index('--output-file')+1]+'.txt')\np.write_bytes(b'x'*16001)\n", "from pathlib import Path\nimport sys\nPath(sys.argv[sys.argv.index('--output-file')+1]+'.txt').write_bytes(b'\\xff')\n"):
            self.write_cli(code)
            with self.assertRaises((ResearchError, UnicodeError)):
                self.adapter.transcribe(wav(), 'en', threading.Event())

    def test_disabled_config_and_model_size_are_explicit(self):
        self.assertFalse(WhisperAdapter(SpeechConfig(), self.root).status()['available'])
        with patch('backend.adapters.speech.MAX_MODEL_BYTES', 1):
            self.assertFalse(self.adapter.status()['available'])
        event = threading.Event(); event.set()
        with self.assertRaises(SpeechCancelled): self.adapter.transcribe(wav(), 'en', event)


class VoiceInputTests(unittest.TestCase):
    def test_pcm_duration_silence_and_untrusted_note_text(self):
        self.assertEqual(validate_audio(wav(seconds=30, silent=True))['seconds'], 30)
        self.assertTrue(validate_audio(wav(silent=True))['silent'])
        self.assertFalse(validate_audio(wav())['silent'])
        with self.assertRaises(ResearchError): validate_audio(wav(seconds=30.1))
        plan = prepare_command(VoiceCommand(transcript='remember <script>untrusted fixture</script>', scope='fixture'))
        self.assertEqual(plan['operation']['note']['content'], '<script>untrusted fixture</script>')
