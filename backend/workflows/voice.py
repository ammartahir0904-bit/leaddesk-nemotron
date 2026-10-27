"""Ephemeral dictation jobs. Audio is never stored in the application database."""
import hashlib
import asyncio
import threading
import time

from backend.adapters.speech import SpeechCancelled
from backend.domain.errors import ResearchError
from backend.domain.voice import validate_audio

TTL = 300
MAX_JOBS = 32


class VoiceService:
    def __init__(self, adapter, execution_lock):
        self.adapter, self.execution_lock = adapter, execution_lock
        self.guard = threading.RLock()
        self.jobs = {}
        self.closed = False

    @staticmethod
    def public(job):
        return {key: job[key] for key in ("id", "state", "transcript", "message", "seconds", "language")}

    def prune(self):
        for key, job in list(self.jobs.items()):
            if job["state"] in {"completed", "failed", "cancelled"} and time.monotonic() - job["finished"] > TTL:
                del self.jobs[key]

    def submit(self, job_id, body, language):
        audio = validate_audio(body)
        digest = hashlib.sha256(body + language.encode()).hexdigest()
        with self.guard:
            self.prune()
            if self.closed:
                raise ResearchError("Voice service is stopping.", status=503)
            if job_id in self.jobs:
                job = self.jobs[job_id]
                if job["digest"] is not None and job["digest"] != digest:
                    raise ResearchError("Recording ID was already used for different audio or language.", status=409)
                return self.public(job)
            if not self.adapter.status()["available"]:
                raise ResearchError("Local speech recognition is not configured. Use typed commands or configure the local runtime.", status=503)
            if len(self.jobs) >= MAX_JOBS:
                raise ResearchError("Voice session limit reached. Wait five minutes for old sessions to expire.", status=429)
            if not self.execution_lock.acquire(blocking=False):
                raise ResearchError("Another research, benchmark or voice task is running. Retry after it finishes.", status=429, retryable=True)
            job = {"id": job_id, "digest": digest, "state": "running", "transcript": None, "message": None,
                   "seconds": audio["seconds"], "language": language, "event": threading.Event(), "finished": None}
            self.jobs[job_id] = job
            thread = threading.Thread(target=self.run, args=(job, body, audio["silent"]), daemon=True, name="leaddesk-voice")
            job["thread"] = thread
            try:
                thread.start()
            except RuntimeError:
                del self.jobs[job_id]
                self.execution_lock.release()
                raise ResearchError("Could not start local transcription. Retry shortly.", status=503) from None
            return self.public(job)

    def run(self, job, body, silent):
        text, message = None, None
        state = "failed"
        try:
            text = "" if silent else self.adapter.transcribe(body, job["language"], job["event"])
            if not isinstance(text, str) or len(text) > 1000 or "\x00" in text:
                raise ResearchError("The speech runtime returned invalid transcript text.")
            state = "completed"
            message = "No speech detected. Type a command or try another recording." if not text else "Review and correct this transcript before preparing an action."
        except SpeechCancelled:
            state = "cancelled"
        except ResearchError as error:
            message = str(error)
        except Exception:
            # Never expose or log captured audio, transcript text, private paths
            # or raw runtime diagnostics on an adapter/decoder failure.
            message = "Local transcription failed. Typed commands remain available."
        finally:
            body = None
            with self.guard:
                cancelled = job["event"].is_set() or state == "cancelled"
                job.update(state="cancelled" if cancelled else state, transcript=None if cancelled or state != "completed" else text,
                           message="Recording cancelled and transcript discarded." if cancelled else message, finished=time.monotonic())
            self.execution_lock.release()

    def get(self, job_id):
        with self.guard:
            self.prune()
            if job_id not in self.jobs:
                raise ResearchError("Voice session expired or was lost after restart. Record again or type the command.", status=404)
            return self.public(self.jobs[job_id])

    def cancel(self, job_id):
        with self.guard:
            self.prune()
            job = self.jobs.get(job_id)
            if not job:
                if len(self.jobs) >= MAX_JOBS:
                    raise ResearchError("Voice session limit reached; no new recording can be accepted yet.", status=429)
                # A cancellation can beat an in-flight upload to this server.
                # Keep a short tombstone so that late audio never starts work.
                job = {"id": job_id, "digest": None, "state": "cancelled", "transcript": None, "message": None,
                       "seconds": None, "language": None, "event": threading.Event(), "finished": time.monotonic(), "thread": None}
                self.jobs[job_id] = job
            if job:
                job["event"].set()
                job.update(state="cancelled", transcript=None, message="Recording cancelled and transcript discarded.", finished=time.monotonic())
        return {"id": job_id, "state": "cancelled"}

    def request_close(self):
        with self.guard:
            self.closed = True
            jobs = list(self.jobs.values())
            for job in jobs:
                job["event"].set()
                job["transcript"] = None
            return jobs

    def close(self):
        jobs = self.request_close()
        for job in jobs:
            if job["thread"]:
                job["thread"].join(timeout=3)
        with self.guard:
            self.jobs.clear()

    async def aclose(self):
        jobs = self.request_close()
        deadline = time.monotonic() + 5
        while any(job["thread"] and job["thread"].is_alive() for job in jobs):
            if time.monotonic() >= deadline:
                raise RuntimeError("Voice runtime did not stop within its shutdown budget.")
            await asyncio.sleep(.05)
        with self.guard:
            self.jobs.clear()
