"""Public demo mode: fictional data, internet and file actions off, AI rewording capped, demo key shared on purpose."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import httpx

from backend.api.app import create_app
from backend.settings import Settings
from tests.support import TOKEN


class DemoTests(unittest.IsolatedAsyncioTestCase):
    async def client(self, demo, host='http://testserver', **extra):
        settings = replace(Settings(Path(tempfile.mkdtemp()), TOKEN), demo=demo, public_host='demo.leaddesk.example', **extra)
        app = create_app(settings, fetcher=lambda url: (_ for _ in ()).throw(AssertionError('no fetch in demo')))
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=host, headers={'Authorization': f'Bearer {TOKEN}'})

    async def test_demo_key_only_in_demo_mode(self):
        async with await self.client(False) as client:
            self.assertEqual((await client.get('/v1/demo-info')).json(), {'demo': False})
            self.assertEqual((await client.get('/', headers={'host': 'demo.leaddesk.example'})).status_code, 400)
        async with await self.client(True) as client:
            self.assertEqual((await client.get('/v1/demo-info')).json(), {'demo': True, 'key': TOKEN})

    async def test_internet_and_file_actions_blocked_corrections_allowed(self):
        async with await self.client(True, host='http://demo.leaddesk.example') as client:
            blocked = ['/v1/prospecting/searches', '/v1/prospecting/searches/x/candidates/node/1/enrich',
                       '/v1/prospecting/searches/x/candidates/node/1/check', '/v1/prospecting/site-analyses', '/v1/research',
                       '/v1/prospecting/web-search/provider', '/v1/prospecting/searches/x/verify']
            for path in blocked:
                response = await client.post(path, json={})
                self.assertEqual(response.status_code, 403, path)
                self.assertIn('public demo', response.json()['message'])
            self.assertEqual((await client.delete('/v1/prospecting/searches/x')).status_code, 403)
            allowed = await client.post('/v1/prospecting/searches/x/candidates/node/1/contact-correction',
                                        json={'type': 'phone', 'value': '020 7946 0101', 'verdict': 'wrong', 'reason': 'fake'})
            self.assertEqual(allowed.status_code, 404)  # reached the app (the search does not exist), not blocked

    async def test_ai_rewording_is_capped(self):
        async with await self.client(True, demo_ai_per_hour=2) as client:
            path = '/v1/prospecting/searches/x/candidates/node/1/analyse'
            codes = [(await client.post(path)).status_code for _ in range(3)]
            self.assertNotEqual(codes[0], 429)
            self.assertEqual(codes[2], 429)


if __name__ == '__main__':
    unittest.main()
