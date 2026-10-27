"""Shared in-process API fixture; no live source requests or server sockets."""
import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx

from backend.adapters.fetch import Page
from backend.api.app import create_app
from backend.settings import Settings

TOKEN = 'test-only-not-a-real-access-token-0123456789'
HTML = ('<h1>Synthetic North Branch</h1><p>North reception: +1 202-555-0148</p>'
        '<footer>Directory support: help@directory.example</footer>')


class APITestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.calls = []
        self.failure = None

        def fetcher(url):
            self.calls.append(url)
            if self.failure:
                raise self.failure
            return Page(url, HTML.encode(), HTML)

        self.app = create_app(Settings(self.directory, TOKEN), fetcher=fetcher)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url='http://testserver',
            headers={'Authorization': f'Bearer {TOKEN}'},
        )
        # Keep this sandbox's loop awake when thread wakeup writes are blocked.
        # This changes no application behavior and is unnecessary on a desktop.
        async def ticker():
            while True:
                await asyncio.sleep(.01)

        self.ticker = asyncio.create_task(ticker())

    async def asyncTearDown(self):
        await self.client.aclose()
        self.ticker.cancel()
        try:
            await self.ticker
        except asyncio.CancelledError:
            pass
        self.temp.cleanup()

    async def send(self, method, path, **kwargs):
        return await asyncio.wait_for(self.client.request(method, path, **kwargs), timeout=5)

    async def research(self, key='first', url='https://synthetic.example/', **extra):
        return await self.send('POST', '/v1/research', json={
            'url': url, 'product': 'Generic scheduling offer', 'location': 'Target city', **extra,
        }, headers={'Idempotency-Key': key})
