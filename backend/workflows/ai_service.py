"""Selected model for lead analysis: a local Ollama model, or (opt-in) an NVIDIA Nemotron model on Nebius Token Factory.

One run at a time; nothing is downloaded. A Token Factory model is used only after the user selects it, and only when
NEBIUS_API_KEY is set; LeadDesk then sends the prompt it built (public business facts and the user's product text)."""
import json
import threading
import time

from backend.adapters.hardware import GIB
from backend.adapters.local_model import LocalModelError, OllamaAdapter
from backend.adapters.model_probe import ollama_models
from backend.domain.errors import ResearchError
from backend.storage.repository import now


class AIService:
    def __init__(self, repository, data_dir, adapter_factory=None, list_models=ollama_models, cloud=None, default_cloud_model=''):
        self.repository, self.data_dir, self.list_models = repository, data_dir, list_models
        self.adapter_factory = adapter_factory or self._adapter
        self.cloud = cloud  # TokenFactoryClient, or None
        # Set by whoever runs a public demo (LEADDESK_DEMO_MODEL): their explicit choice, used until a user picks another.
        self.default_cloud_model = default_cloud_model
        self.lock = threading.Lock()

    def cloud_status(self):
        if self.cloud is None or not self.cloud.configured:
            return {'configured': False, 'models': [], 'problem': None,
                    'message': 'Set NEBIUS_API_KEY and restart LeadDesk to use NVIDIA Nemotron models on Nebius Token Factory.'}
        try:
            models = self.cloud.models()
        except ResearchError as error:
            return {'configured': True, 'models': [], 'problem': str(error), 'message': str(error)}
        return {'configured': True, 'models': models, 'problem': None,
                'message': f'{len(models)} NVIDIA model(s) available on Nebius Token Factory.' if models else
                           'The key works, but it lists no NVIDIA Nemotron models.'}

    def _adapter(self, model, max_tokens=512):
        size = model.get('size_bytes') or 2 * GIB
        # 6k context fits the Sprint 21 evidence pack (site pages, checks, web findings) with room for the answer.
        return OllamaAdapter(model['name'], model['digest'], self.data_dir, context=6144, max_output_tokens=max_tokens,
                             cpu_only=False, num_thread=None, keep_alive='5m',
                             min_available_bytes=min(3 * GIB, size + 3 * GIB // 4), request_seconds=600)

    def selected(self):
        with self.repository.connect() as db:
            row = db.execute("SELECT value_json FROM ai_setting WHERE key='model'").fetchone()
        if row:
            return json.loads(row[0])
        if self.default_cloud_model and self.cloud is not None:
            return {'name': self.default_cloud_model, 'digest': None, 'size_bytes': None, 'provider': 'token_factory',
                    'consented_at': 'set by the demo operator (LEADDESK_DEMO_MODEL)'}
        return None

    def status(self):
        found = self.list_models()
        local = [m for m in found['models'] if not m['remote'] and not m['name'].endswith(':cloud')]
        cloud = self.cloud_status()
        selected = self.selected()
        provider = (selected or {}).get('provider', 'ollama')
        problem = None
        if provider == 'token_factory':
            current = next((m for m in cloud['models'] if selected and m['name'] == selected['name']), None)
            if not cloud['configured']:
                problem = 'The selected Nemotron model runs on Nebius Token Factory, but NEBIUS_API_KEY is not set. Set it and restart LeadDesk.'
            elif cloud['problem']:
                problem = cloud['problem']
            elif not current:
                problem = 'The selected Token Factory model is no longer offered. Choose another.'
        else:
            current = next((m for m in local if selected and m['name'] == selected['name']), None)
            if not found['running'] and not (cloud['configured'] and cloud['models']):
                problem = 'Cannot reach Ollama at 127.0.0.1:11434. Start it with scripts/ollama.sh start (Docker) or ollama serve (native install), then refresh.'
            elif not local and not cloud['models']:
                problem = ('Ollama is running but has no local models. Install one with scripts/ollama.sh pull llama3.2:3b (Docker) or '
                           'ollama pull llama3.2:3b (native install), or set NEBIUS_API_KEY for NVIDIA Nemotron on Nebius Token Factory.')
            elif selected and not current:
                problem = 'The selected model is no longer installed. Choose another.'
            elif selected and current['digest'] != selected['digest']:
                problem = 'The selected model changed (new download). Select it again to accept the new version.'
        if not selected and not problem:
            problem = 'Choose a model in "AI models and hardware" and click "Use this model" to enable AI rewording.'
        return {'ollama': {'installed': found['installed'], 'running': found['running']}, 'models': local, 'token_factory': cloud,
                'selected': selected, 'ready': bool(selected and current and not problem), 'problem': problem}

    def select(self, name, provider='ollama'):
        if provider == 'token_factory':
            model = next((m for m in self.cloud_status()['models'] if m['name'] == name), None)
            if model is None:
                raise ResearchError('That model is not offered to your Nebius Token Factory key.', status=404)
            # Choosing a cloud model is the explicit opt-in; the time is recorded.
            value = {'name': name, 'digest': None, 'size_bytes': None, 'provider': 'token_factory', 'consented_at': now()}
        else:
            model = next((m for m in self.status()['models'] if m['name'] == name), None)
            if model is None or len(model['digest']) != 64:
                raise ResearchError('That model is not installed in local Ollama. Install it with "ollama pull", then retry.', status=404)
            value = {'name': model['name'], 'digest': model['digest'], 'size_bytes': model['size_bytes'], 'provider': 'ollama'}
        with self.repository.connect() as db:
            db.execute("INSERT OR REPLACE INTO ai_setting VALUES('model',?,?)", (json.dumps(value), now()))
        return self.status()

    def run(self, prompt, max_tokens=512):
        state = self.status()
        if not state['ready']:
            raise ResearchError(state['problem'] or 'Choose an installed Ollama model in "AI models and hardware" first.', status=409)
        if not self.lock.acquire(blocking=False):
            raise ResearchError('Another AI analysis is running. Retry shortly.', retryable=True, status=429)
        try:
            started = time.perf_counter()
            if state['selected'].get('provider') == 'token_factory':
                response = self.cloud.generate(state['selected']['name'], prompt, max_tokens)
                return {'text': response['response'], 'model': state['selected']['name'], 'model_digest': None,
                        'provider': 'Nebius Token Factory', 'seconds': round(time.perf_counter() - started, 2),
                        'tokens': response.get('eval_count'), 'prompt_tokens': response.get('prompt_eval_count')}
            adapter = self.adapter_factory(state['selected'] | {'size_bytes': state['selected'].get('size_bytes')}, max_tokens)
            try:
                response = adapter.generate(prompt)
            except LocalModelError as error:
                raise ResearchError(str(error), retryable=True, status=503) from None
            finally:
                close = getattr(adapter, 'close', None)
                if close:
                    close()
            return {'text': response['response'], 'model': state['selected']['name'], 'model_digest': state['selected']['digest'],
                    'provider': 'local Ollama', 'seconds': round(time.perf_counter() - started, 2),
                    'tokens': response.get('eval_count'), 'prompt_tokens': response.get('prompt_eval_count')}
        finally:
            self.lock.release()
