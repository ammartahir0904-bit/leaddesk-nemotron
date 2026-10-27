"""Model recommendations from fake hardware; no installs, downloads or real probes."""
import subprocess
import unittest
import unittest.mock

import httpx

from backend.adapters.model_probe import nvidia_gpus, ollama_models
from backend.domain.model_advisor import GIB, recommend
from tests.support import APITestCase


def profile(total_gib, available_gib=None, disk_gib=100):
    return {'memory': {'total_bytes': total_gib * GIB, 'effective_available_bytes': (available_gib or total_gib / 2) * GIB},
            'disk': {'free_bytes': disk_gib * GIB}}


class AdvisorTests(unittest.TestCase):
    def test_tiers(self):
        laptop = recommend(profile(7.5, 3), [], [], False)
        self.assertEqual((laptop['tier'], laptop['main_model'], laptop['embedding_model']), ('Light laptop (CPU only)', 'llama3.2:3b', 'nomic-embed-text'))
        self.assertIn('Install Ollama', laptop['next_steps'][0])
        self.assertTrue(any('NVIDIA GPU' in note for note in laptop['notes']))
        self.assertTrue(any('Close other apps' in note for note in laptop['notes']))
        cpu = recommend(profile(32), [], [], True)
        self.assertEqual((cpu['tier'], cpu['main_model']), ('Strong CPU-only computer', 'llama3.1:8b'))
        gpu = recommend(profile(32), [{'name': 'Fictional RTX', 'vram_bytes': 12 * GIB}], [{'name': 'qwen2.5:14b'}], True)
        self.assertEqual((gpu['main_model'], gpu['tier']), ('qwen2.5:14b', 'GPU computer (12 GB GPU memory)'))
        self.assertEqual(gpu['next_steps'], ['Run: ollama pull nomic-embed-text'])
        big = {r['tag']: r for r in gpu['models']}
        self.assertEqual((big['qwen2.5:14b']['fit'], big['qwen2.5:32b']['fit'], big['qwen2.5:14b']['installed']), ('fits_gpu', 'fits_cpu', True))
        tiny = recommend(profile(4, disk_gib=0.2), [], [], True)
        self.assertEqual({r['fit'] for r in tiny['models']} - {'too_big'}, {'no_disk'})
        self.assertIsNone(tiny['main_model'])

    def test_probes_parse_bounded_output(self):
        ok = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout='NVIDIA GeForce RTX 3060, 12288, 550.1\nbad line\n')
        with unittest.mock.patch('shutil.which', return_value='/usr/bin/nvidia-smi'):
            self.assertEqual(nvidia_gpus(ok), [{'name': 'NVIDIA GeForce RTX 3060', 'vram_bytes': 12288 * 1024 * 1024, 'driver': '550.1', 'source': 'nvidia-smi'}])
            def fail(*a, **k):
                raise subprocess.TimeoutExpired('nvidia-smi', 5)
            self.assertEqual(nvidia_gpus(fail), [])
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json={'models': [{'name': 'qwen2.5:7b', 'size': 4}, 'junk']}))
        self.assertEqual(ollama_models(transport)['models'], [{'name': 'qwen2.5:7b', 'size_bytes': 4, 'digest': '', 'remote': False}])
        down = ollama_models(httpx.MockTransport(lambda r: httpx.Response(500)))
        self.assertFalse(down['running'])


class AdvisorAPITests(APITestCase):
    async def test_route_uses_probe_and_requires_auth(self):
        from backend.api.app import create_app
        from backend.settings import Settings
        from tests.support import TOKEN
        await self.client.aclose()
        self.app = create_app(Settings(self.directory, TOKEN), model_probe=lambda: {'gpus': [{'name': 'Fictional GPU', 'vram_bytes': 8 * GIB}],
                                                                                    'ollama': {'installed': True, 'running': True, 'models': []}})
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://testserver', headers={'Authorization': f'Bearer {TOKEN}'})
        response = await self.send('POST', '/v1/hardware/advisor')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['advice']['main_model'], 'llama3.1:8b')
        self.assertEqual((await self.client.post('/v1/hardware/advisor', headers={'Authorization': 'Bearer wrong'})).status_code, 401)


if __name__ == '__main__':
    unittest.main()
