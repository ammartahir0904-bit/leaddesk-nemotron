import json
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.adapters.browser_render import ChromeRenderer
from backend.adapters.token_factory import TokenFactoryClient
from backend.adapters.tavily import TavilyClient, WebSearch
from backend.adapters.fetch import Page, fetch_page, public_addresses, validate_url
from backend.adapters.hardware import profile_hardware
from backend.api.jobs import job_router
from backend.api.assessments import assessment_router
from backend.api.leads import lead_router
from backend.api.quality import quality_router
from backend.api.files import files_router
from backend.api.voice import voice_router
from backend.api.screen import screen_router
from backend.api.learning import learning_router
from backend.api.pc_worker import pc_worker_router
from backend.api.correspondence import correspondence_router
from backend.api.experiments import experiments_router
from backend.api.prospecting import prospecting_router
from backend.adapters.osm import OSMClient
from backend.adapters.overture import OvertureClient
from backend.adapters.smtp_probe import SMTPProbe
from backend.adapters.dns_mx import MXLookup
from backend.adapters.web_search import SearxClient
from backend.adapters import model_probe as model_probes
from backend.domain.model_advisor import recommend
from backend.adapters.speech import WhisperAdapter
from backend.domain.voice import MAX_AUDIO_BYTES
from backend.domain.briefs import BriefEdit, OfferInput, edited_document, rules_draft
from backend.domain.errors import ResearchError
from backend.domain.extract import extract
from backend.evaluation.runner import run_parser_benchmark
from backend.settings import ROOT, Settings
from backend.storage.benchmarks import BenchmarkRepository
from backend.storage.assessments import AssessmentRepository
from backend.storage.briefs import BriefRepository
from backend.storage.jobs import JobRepository
from backend.storage.leads import LeadRepository
from backend.storage.quality import QualityRepository
from backend.storage.files import FileRepository
from backend.storage.memories import MemoryRepository
from backend.storage.learning import LearningRepository
from backend.storage.pc_worker import PCWorkerRepository
from backend.storage.correspondence import CorrespondenceRepository
from backend.storage.experiments import ExperimentRepository
from backend.storage.prospecting import ProspectRepository
from backend.storage.repository import Repository, now as now_iso, request_hash
from backend.workflows.worker import WorkflowWorker
from backend.workflows.voice import VoiceService
from backend.workflows.ai_service import AIService


class ResearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=8, max_length=2048)
    product: str | None = Field(default=None, min_length=3, max_length=2000)
    location: str | None = Field(default=None, min_length=2, max_length=300)
    brief_id: str | None = Field(default=None, min_length=1, max_length=100)
    brief_revision: int | None = Field(default=None, ge=1, strict=True)

    @field_validator("url", "product", "location", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("url")
    @classmethod
    def url_policy(cls, value):
        return validate_url(value)

    @model_validator(mode="after")
    def context_source(self):
        if self.brief_id is not None:
            if self.brief_revision is None or self.product is not None or self.location is not None:
                raise ValueError("Supply a brief ID and revision, or a manual product and location.")
        elif self.brief_revision is not None or self.product is None or self.location is None:
            raise ValueError("Supply both product and location, or select a saved brief revision.")
        return self


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contact_id: str = Field(min_length=1, max_length=100)
    category: Literal["wrong_contact", "wrong_business", "wrong_branch", "stale", "invalid"]
    comment: str = Field(default="", max_length=2000)
    expected_value: str | None = Field(default=None, max_length=300)


class DemoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief_id: str | None = Field(default=None, min_length=1, max_length=100)
    brief_revision: int | None = Field(default=None, ge=1, strict=True)

    @model_validator(mode="after")
    def paired_reference(self):
        if (self.brief_id is None) != (self.brief_revision is None):
            raise ValueError("Supply both brief ID and revision.")
        return self


class ParserBenchmarkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_count: int = Field(default=20, ge=2, le=200, strict=True)


# Public demo allow-list: corrections and reviews of the fictional data, the offer checklist, rules and AI rewording.
DEMO_ALLOWED = [re.compile(p) for p in (r'/contact-correction$', r'/feature-override$', r'/message-review$', r'/web-feedback$',
                                        r'/offer-pack$', r'^/v1/prospecting/rules(/[\w-]+)?$', r'/ai-verdict$', r'^/v1/ai/model$')]
DEMO_AI = re.compile(r'^/v1/prospecting/(searches/[\w-]+/(candidates/[\w]+/[\w.:-]+/)?analyse|site-analyses/[\w-]+/polish)$')


def create_app(settings: Settings | None = None, fetcher=fetch_page, speech_adapter=None, osm_client=None, mx_lookup=None, model_probe=None, web_search=None, ai_service=None, overture_client=None, smtp_probe=None, renderer=None):
    settings = settings or Settings.load()
    repository = Repository(settings.data_dir / "leaddesk.sqlite3")
    benchmarks = BenchmarkRepository(repository)
    briefs = BriefRepository(repository)
    jobs = JobRepository(repository)
    lock = threading.Lock()
    files = FileRepository(repository, settings.data_dir)
    memories = MemoryRepository(repository)
    voice = VoiceService(speech_adapter or WhisperAdapter(settings.speech, settings.data_dir), lock)
    job_fetcher = None if fetcher is fetch_page else lambda url, remaining: fetcher(url)
    worker = WorkflowWorker(jobs, lock, fetcher=job_fetcher)

    @asynccontextmanager
    async def lifespan(app):
        worker.start()
        try:
            yield
        finally:
            try:
                await voice.aclose()
            finally:
                await worker.aclose()

    app = FastAPI(title="LeadDesk", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.workflow_worker = worker
    app.state.voice_service = voice
    hosts = ["127.0.0.1", "localhost", "testserver"] + ([settings.public_host] if settings.demo and settings.public_host else [])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    demo_ai_calls = []

    @app.middleware("http")
    async def public_demo(request: Request, call_next):
        """Public demo: only edits of the fictional data and capped AI rewording; nothing that reaches the internet or files."""
        if not settings.demo or request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)
        path = request.url.path
        if DEMO_AI.search(path):
            hour_ago = time.monotonic() - 3600
            demo_ai_calls[:] = [t for t in demo_ai_calls if t > hour_ago]
            if len(demo_ai_calls) >= settings.demo_ai_per_hour:
                return JSONResponse({"message": "The public demo's AI limit for this hour is used up. Try again later, or run LeadDesk yourself.",
                                     "retryable": True}, status_code=429)
            demo_ai_calls.append(time.monotonic())
            return await call_next(request)
        if not any(pattern.search(path) for pattern in DEMO_ALLOWED):
            return JSONResponse({"message": "Not available in the public demo (it would reach the internet or your files). "
                                            "Run LeadDesk on your own computer to use it.", "retryable": False}, status_code=403)
        return await call_next(request)

    @app.get("/v1/demo-info")
    def demo_info():
        # Unauthenticated on purpose, and only in demo mode: the demo's key is meant to be public.
        return {"demo": True, "key": settings.token} if settings.demo else {"demo": False}

    @app.exception_handler(ResearchError)
    async def research_error(request, error):
        return JSONResponse({"message": str(error), "retryable": error.retryable}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        if request.url.path == '/v1/experiments' or request.url.path.startswith('/v1/experiments/'):
            # Invalid JSON text can contain unpaired surrogates. Preserve validation
            # details as escaped JSON instead of failing while encoding the 422.
            return Response(json.dumps({'detail': jsonable_encoder(error.errors())}, ensure_ascii=True),
                            status_code=422, media_type='application/json')
        return await request_validation_exception_handler(request, error)

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        # No cookies or CORS: all data APIs require an unguessable bearer token.
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"message": "Cross-origin access is disabled.", "retryable": False}, status_code=403)
        if request.method in {"POST", "PUT", "PATCH"}:
            audio_upload = request.method == "PUT" and request.url.path.startswith("/v1/voice/transcriptions/")
            body_limit = MAX_AUDIO_BYTES if audio_upload else (128 * 1024 if request.url.path.startswith("/v1/quality/baselines/") and request.url.path.endswith("/audit") else 16000)
            try:
                if int(request.headers.get("content-length", "0")) > body_limit:
                    return JSONResponse({"message": "Request is too large."}, status_code=413)
            except ValueError:
                return JSONResponse({"message": "Invalid request length."}, status_code=400)
            # Audio is streamed and bounded by its authenticated endpoint. Do
            # not collect a chunked upload before checking its actual length.
            if not audio_upload:
                body = await request.body()
                if len(body) > body_limit:
                    return JSONResponse({"message": "Request is too large."}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob: https://tile.openstreetmap.org; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    def authenticate(authorization: str = Header(default="")):
        if not secrets.compare_digest(authorization, "Bearer " + settings.token):
            raise ResearchError("Unlock LeadDesk with your local access key.", status=401)

    app.include_router(job_router(jobs, worker, authenticate))
    app.include_router(assessment_router(AssessmentRepository(repository), authenticate))
    app.include_router(lead_router(LeadRepository(repository), authenticate))
    app.include_router(quality_router(QualityRepository(repository), authenticate))
    app.include_router(files_router(files, memories, authenticate))
    app.include_router(voice_router(voice, files, memories, authenticate))
    app.include_router(screen_router(files, memories, authenticate))
    app.include_router(learning_router(LearningRepository(repository), authenticate))
    app.include_router(pc_worker_router(PCWorkerRepository(repository), authenticate))
    app.include_router(correspondence_router(CorrespondenceRepository(repository), authenticate))
    app.include_router(experiments_router(ExperimentRepository(repository), authenticate))

    @app.get("/v1/health")
    def health():
        with repository.connect() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok", "storage": "sqlite", "version": "0.1.0", "model": "not enabled"}

    @app.get("/v1/research", dependencies=[Depends(authenticate)])
    def recent():
        return repository.recent()

    @app.get("/v1/research/{research_id}", dependencies=[Depends(authenticate)])
    def get_research(research_id: str):
        return repository.get(research_id)

    def require_key(key: str):
        if not key or len(key) > 100:
            raise ResearchError("An Idempotency-Key of at most 100 characters is required.")

    @app.get("/v1/briefs", dependencies=[Depends(authenticate)])
    def recent_briefs():
        return briefs.recent()

    @app.get("/v1/briefs/{brief_id}", dependencies=[Depends(authenticate)])
    def get_brief(brief_id: str):
        return briefs.get(brief_id)

    @app.get("/v1/briefs/{brief_id}/revisions", dependencies=[Depends(authenticate)])
    def brief_history(brief_id: str):
        return briefs.history(brief_id)

    @app.post("/v1/briefs", dependencies=[Depends(authenticate)])
    def create_brief(payload: OfferInput, idempotency_key: str = Header(default="")):
        require_key(idempotency_key)
        digest = request_hash({"operation": "create_brief", "input": payload.model_dump()})
        return briefs.create(rules_draft(payload), idempotency_key, digest)

    @app.patch("/v1/briefs/{brief_id}", dependencies=[Depends(authenticate)])
    def edit_brief(brief_id: str, payload: BriefEdit, idempotency_key: str = Header(default="")):
        require_key(idempotency_key)
        digest = request_hash({"operation": "edit_brief", "id": brief_id, "edit": payload.model_dump()})
        return briefs.update(brief_id, payload.expected_revision, edited_document(payload), idempotency_key, digest)

    @app.post("/v1/hardware/profile", dependencies=[Depends(authenticate)])
    def hardware_profile():
        return profile_hardware(settings.data_dir)

    @app.post("/v1/hardware/advisor", dependencies=[Depends(authenticate)])
    def model_advisor():
        profile = profile_hardware(settings.data_dir)
        found = (model_probe or model_probes.probe)()
        vendors = {'0x8086': 'Intel graphics (integrated, shares system RAM)', '0x10de': 'NVIDIA GPU (install drivers for nvidia-smi)',
                   '0x1002': 'AMD GPU', '0x1a03': 'Server display adapter'}
        sysfs = [{'name': vendors.get(d['vendor_id'], f"PCI {d['vendor_id']}:{d['device_id']}"), 'vram_bytes': d['vram_bytes'], 'driver': d['driver'], 'source': 'sysfs'}
                 for d in profile['gpu']['devices']]
        gpus = found['gpus'] or sysfs
        return {'hardware': profile, 'gpus': gpus, 'ollama': found['ollama'],
                'advice': recommend(profile, gpus, found['ollama']['models'], found['ollama']['installed'])}

    @app.get("/v1/benchmarks", dependencies=[Depends(authenticate)])
    def recent_benchmarks():
        return benchmarks.recent()

    @app.get("/v1/benchmarks/{run_id}", dependencies=[Depends(authenticate)])
    def get_benchmark(run_id: str):
        return benchmarks.get(run_id)

    @app.post("/v1/benchmarks/parser", dependencies=[Depends(authenticate)])
    def parser_benchmark(payload: ParserBenchmarkInput, idempotency_key: str = Header(default="")):
        if not idempotency_key or len(idempotency_key) > 100:
            raise ResearchError("An Idempotency-Key of at most 100 characters is required.")
        if not lock.acquire(blocking=False):
            raise ResearchError("Another research or benchmark task is running. Retry shortly.", retryable=True, status=429)
        try:
            digest = request_hash(payload.model_dump())
            cached = benchmarks.cached(idempotency_key, digest)
            if cached:
                return cached
            report = run_parser_benchmark(profile_hardware(settings.data_dir), payload.sample_count)
            return benchmarks.save(report, key=idempotency_key, request_hash=digest)
        finally:
            lock.release()

    def research(payload, key, synthetic, page=None):
        require_key(key)
        if not lock.acquire(blocking=False):
            raise ResearchError("Another research task is running. Retry shortly.", retryable=True, status=429)
        try:
            values = payload.model_dump(exclude_none=True) | {"synthetic": synthetic}
            digest = request_hash(values)
            cached = repository.cached(key, digest)
            if cached:
                return cached
            snapshot = None
            if payload.brief_id:
                snapshot = briefs.get(payload.brief_id)
                if snapshot["revision"] != payload.brief_revision:
                    raise ResearchError("This brief changed. Reopen it and select the latest revision before research.", status=409)
                inputs = snapshot["document"]["input"]
                values = values | {"product": inputs["offer"], "location": inputs["target_geography"]}
            if synthetic:
                body = (ROOT / "tests/fixtures/fictional_business.html").read_bytes()
                page = Page("https://fictional-workshop.example/", body, body.decode())
            elif page is None:
                page = fetcher(payload.url)
            return repository.save(values, key, page, extract(page.html), synthetic,
                                   brief_snapshot=snapshot, digest=digest)
        finally:
            lock.release()

    @app.post("/v1/research", dependencies=[Depends(authenticate)])
    def start_research(payload: ResearchInput, idempotency_key: str = Header(default="")):
        return research(payload, idempotency_key, False)

    ai = ai_service or AIService(repository, settings.data_dir,
                                 cloud=TokenFactoryClient(settings.nebius_api_key) if settings.nebius_api_key else None,
                                 default_cloud_model=settings.demo_model if settings.demo else '')

    class ModelChoice(BaseModel):
        model_config = ConfigDict(extra="forbid")
        model: str = Field(min_length=1, max_length=200)
        provider: Literal['ollama', 'token_factory'] = 'ollama'


    @app.get("/v1/ai/status", dependencies=[Depends(authenticate)])
    def ai_status():
        return ai.status() | {'reviewed': ProspectRepository(repository).ai_verdicts()}

    @app.post("/v1/ai/model", dependencies=[Depends(authenticate)])
    def ai_model(payload: ModelChoice):
        return ai.select(payload.model, payload.provider)

    def setting(name):
        with repository.connect() as db:
            row = db.execute('SELECT value_json FROM ai_setting WHERE key=?', (name,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_setting(name, value):
        with repository.connect() as db:
            db.execute('INSERT OR REPLACE INTO ai_setting VALUES(?,?,?)', (name, json.dumps(value), now_iso()))

    def research_website(url, product, location, key, page=None):
        return research(ResearchInput(url=url, product=product[:2000], location=location or None), key, False, page)

    app.include_router(prospecting_router(ProspectRepository(repository), osm_client or OSMClient(), fetcher,
                                          research_website, authenticate, mx_lookup or MXLookup(),
                                          web_search or WebSearch(SearxClient(settings.searxng_url),
                                                                  TavilyClient(settings.tavily_api_key) if settings.tavily_api_key else None,
                                                                  lambda: setting('web_search'), lambda value: save_setting('web_search', value)),
                                          ai, repository.get,
                                          overture_client or OvertureClient(settings.data_dir / 'overture'),
                                          smtp_probe or SMTPProbe(MXLookup().hosts),
                                          renderer or ChromeRenderer(settings.data_dir, lambda host, port: public_addresses(host, port, 3))))

    @app.post("/v1/demo", dependencies=[Depends(authenticate)])
    def demo(payload: DemoInput | None = None, idempotency_key: str = Header(default="")):
        context = payload.model_dump(exclude_none=True) if payload and payload.brief_id else {
            "product": "Appointment booking support", "location": "Synthetic city"}
        inputs = ResearchInput(url="https://fictional-workshop.example/", **context)
        return research(inputs, idempotency_key, True)

    @app.post("/v1/feedback", dependencies=[Depends(authenticate)])
    def feedback(payload: FeedbackInput):
        return repository.correct(payload.contact_id, payload.category, payload.comment, payload.expected_value)

    if settings.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")

    return app
