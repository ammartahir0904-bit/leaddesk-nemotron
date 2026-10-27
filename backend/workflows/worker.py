"""One bounded page per lease, inside the local coordinator process."""
import asyncio
import logging
import threading
import time
from pathlib import Path
from uuid import uuid4

from backend.adapters.discovery import discover_links
from backend.adapters.fetch import Page, fetch_page
from backend.domain.errors import ResearchError
from backend.domain.extract import extract
from backend.domain.jobs import DEMO_SOURCE
from backend.storage.jobs import JobRepository

FIXTURES = Path(__file__).resolve().parents[2] / "tests/fixtures"
logger = logging.getLogger(__name__)


def synthetic_page(url: str) -> Page:
    if url == DEMO_SOURCE:
        body = (FIXTURES / "fictional_directory.html").read_bytes()
        return Page(url, body, body.decode())
    examples = {
        "https://fictional-north.example/": ('Fictional Workshop · North', 'north@fictional-workshop.example', '+1 202-555-0148'),
        "https://fictional-south.example/": ('Fictional Workshop · South', 'south@fictional-workshop.example', '+1 202-555-0199'),
    }
    if url not in examples:
        raise ResearchError("Unknown synthetic page; no real network fallback is allowed.")
    name, email, phone = examples[url]
    html = f"<h1>{name}</h1><p>SYNTHETIC DEMO · Fictional details only.</p><p>{email}</p><p>{phone}</p>"
    return Page(url, html.encode(), html)


class WorkflowWorker:
    def __init__(self, jobs: JobRepository, execution_lock, *, fetcher=None):
        self.jobs, self.execution_lock = jobs, execution_lock
        self.fetcher = fetcher or (lambda url, remaining: fetch_page(url, budget_seconds=remaining))
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread = None

    def wake(self):
        self.wake_event.set()

    def run_once(self) -> bool:
        if self.stop_event.is_set() or not self.execution_lock.acquire(blocking=False):
            return False
        try:
            owner = str(uuid4())
            job = self.jobs.claim(owner)
            if job is None:
                return False
            started = time.monotonic()
            try:
                step = job["active_step"]
                remaining = job["input"]["time_budget_seconds"] - job["active_seconds"]
                if not self.jobs.heartbeat(job["id"], owner):
                    return True
                page = synthetic_page(step["url"]) if job["input"]["synthetic"] else self.fetcher(step["url"], remaining)
                if step["kind"] == "source":
                    discovery = discover_links(page, job["input"]["candidate_limit"])
                    self.jobs.complete(job["id"], owner, time.monotonic() - started, discovery=discovery)
                else:
                    extracted = extract(page.html)
                    self.jobs.complete(job["id"], owner, time.monotonic() - started, page=page, extracted=extracted)
            except ResearchError as error:
                self.jobs.fail(job["id"], owner, error, time.monotonic() - started)
            except Exception as error:
                # Never persist a traceback, raw HTML or provider response body.
                logger.error("Workflow page failed: %s", type(error).__name__)
                self.jobs.fail(job["id"], owner, ResearchError("An internal page-processing error stopped this step.", status=500),
                               time.monotonic() - started)
            return True
        finally:
            self.execution_lock.release()

    def _loop(self):
        while not self.stop_event.is_set():
            self.wake_event.clear()
            try:
                worked = self.run_once()
            except Exception as error:
                logger.error("Workflow scheduler failed: %s", type(error).__name__)
                worked = False
            self.wake_event.wait(.1 if worked else .5)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="leaddesk-workflow", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake()
        if self.thread:
            self.thread.join(timeout=35)
            if self.thread.is_alive():
                raise RuntimeError("Workflow worker did not finish its bounded page before shutdown.")

    async def aclose(self):
        self.stop_event.set()
        self.wake()
        deadline = time.monotonic() + 35
        while self.thread and self.thread.is_alive():
            if time.monotonic() >= deadline:
                raise RuntimeError("Workflow worker did not finish its bounded page before shutdown.")
            await asyncio.sleep(.05)
