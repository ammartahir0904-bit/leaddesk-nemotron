"""Nebius Token Factory (NVIDIA Nemotron) provider, against a fake OpenAI-compatible server: no real key or network."""
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from backend.adapters.token_factory import TokenFactoryClient, is_nvidia_open_model, strip_reasoning
from backend.domain.errors import ResearchError
from backend.storage.repository import Repository
from backend.workflows.ai_service import AIService

MODELS = {'data': [{'id': 'nvidia/Example-Nemotron-Super'}, {'id': 'nvidia/Example-Nemotron-Nano'}, {'id': 'other-lab/Some-Model'}]}


class FakeFactory:
    def __init__(self, status=200, content='{"message": "Hello Fictional Bean"}'):
        self.status, self.content, self.requests = status, content, []

    def __call__(self, request):
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={'error': 'x'})
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json=MODELS)
        body = json.loads(request.content)
        return httpx.Response(200, json={'model': body['model'], 'choices': [{'message': {'content': self.content}}],
                                         'usage': {'completion_tokens': 12, 'prompt_tokens': 300}})


class ClientTests(unittest.TestCase):
    def test_lists_only_nvidia_models_and_sends_json_requests(self):
        fake = FakeFactory()
        client = TokenFactoryClient('test-key', httpx.MockTransport(fake))
        self.assertEqual([m['name'] for m in client.models()], ['nvidia/Example-Nemotron-Nano', 'nvidia/Example-Nemotron-Super'])
        answer = client.generate('nvidia/Example-Nemotron-Super', 'prompt text', 200)
        self.assertEqual((answer['response'], answer['eval_count']), ('{"message": "Hello Fictional Bean"}', 12))
        sent = json.loads(fake.requests[-1].content)
        self.assertEqual((sent['response_format'], sent['temperature'], sent['max_tokens']), ({'type': 'json_object'}, 0, 200))
        self.assertEqual(fake.requests[-1].headers['authorization'], 'Bearer test-key')
        self.assertIn('untrusted', sent['messages'][0]['content'])

    def test_errors_are_named(self):
        for status, words in ((401, 'refused the API key'), (429, 'rate-limiting'), (402, 'no credit'), (500, 'HTTP 500')):
            with self.subTest(status=status), self.assertRaises(ResearchError) as caught:
                TokenFactoryClient('k', httpx.MockTransport(FakeFactory(status))).generate('nvidia/x', 'p')
            self.assertIn(words, str(caught.exception))
        self.assertEqual(TokenFactoryClient('').models(), [])

    def test_reasoning_and_fences_are_removed(self):
        self.assertEqual(strip_reasoning('<think>long thoughts</think>\n{"a": 1}'), '{"a": 1}')
        self.assertEqual(strip_reasoning('```json\n{"a": 1}\n```'), '{"a": 1}')
        self.assertTrue(is_nvidia_open_model('nvidia/Llama-Nemotron'))
        self.assertFalse(is_nvidia_open_model('deepseek-ai/DeepSeek-R1'))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.no_ollama = lambda: {'installed': False, 'running': False, 'models': []}

    def service(self, fake=None, key='test-key'):
        cloud = TokenFactoryClient(key, httpx.MockTransport(fake or FakeFactory())) if key else None
        return AIService(Repository(self.directory / 'leaddesk.sqlite3'), self.directory, list_models=self.no_ollama, cloud=cloud)

    def test_opt_in_select_and_run_on_nemotron(self):
        service = self.service()
        state = service.status()
        self.assertFalse(state['ready'])  # nothing is sent until a model is chosen
        self.assertEqual(len(state['token_factory']['models']), 2)
        with self.assertRaises(ResearchError):
            service.select('other-lab/Some-Model', 'token_factory')
        state = service.select('nvidia/Example-Nemotron-Super', 'token_factory')
        self.assertTrue(state['ready'])
        self.assertTrue(state['selected']['consented_at'])
        run = service.run('{"instruction": "x"}')
        self.assertEqual((run['provider'], run['model'], run['model_digest']), ('Nebius Token Factory', 'nvidia/Example-Nemotron-Super', None))

    def test_demo_operator_default_model(self):
        service = AIService(Repository(self.directory / 'demo.sqlite3'), self.directory, list_models=self.no_ollama,
                            cloud=TokenFactoryClient('k', httpx.MockTransport(FakeFactory())), default_cloud_model='nvidia/Example-Nemotron-Nano')
        self.assertTrue(service.status()['ready'])
        self.assertIn('demo operator', service.selected()['consented_at'])
        self.assertEqual(service.run('{}')['model'], 'nvidia/Example-Nemotron-Nano')

    def test_missing_key_after_selection_is_explained(self):
        self.service().select('nvidia/Example-Nemotron-Super', 'token_factory')
        state = self.service(key='').status()
        self.assertFalse(state['ready'])
        self.assertIn('NEBIUS_API_KEY', state['problem'])
        with self.assertRaises(ResearchError):
            self.service(key='').run('x')


if __name__ == '__main__':
    unittest.main()
