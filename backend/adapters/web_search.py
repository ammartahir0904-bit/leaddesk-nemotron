"""Client for a user-run SearXNG instance (loopback only). Used only on explicit request."""
import ipaddress
import threading
import time
from urllib.parse import urlsplit

import httpx

from backend.domain.errors import ResearchError

SETUP = 'Start the local search engine with: scripts/searxng.sh start (needs Docker), then retry.'


def loopback(url):
    parts = urlsplit(url)
    host = parts.hostname or ''
    try:
        ok = ipaddress.ip_address(host).is_loopback
    except ValueError:
        ok = host == 'localhost'
    if parts.scheme not in {'http', 'https'} or not ok:
        raise ValueError('LEADDESK_SEARXNG_URL must point to this computer (127.0.0.1 or localhost).')
    return url.rstrip('/')


class SearxClient:
    def __init__(self, base_url, transport=None):
        self.base_url = loopback(base_url)
        self.client = httpx.Client(base_url=self.base_url, trust_env=False, follow_redirects=False, transport=transport,
                                   timeout=httpx.Timeout(20, connect=3), headers={'Accept': 'application/json'})
        self.requests = 0
        # Engines SearXNG reported as failing on the last search (e.g. "Suspended: too many requests").
        self.last_unresponsive = []
        # Recent answers, so a retry does not send the same queries to rate-limited engines again.
        self.cache, self.cache_lock = {}, threading.Lock()

    CACHE_SECONDS = 6 * 3600

    def search(self, query, limit=10):
        key = (query, limit)
        with self.cache_lock:
            hit = self.cache.get(key)
            if hit and time.monotonic() - hit[0] < self.CACHE_SECONDS:
                self.last_unresponsive = []
                return [dict(r) for r in hit[1]]
        self.requests += 1
        try:
            response = self.client.get('/search', params={'q': query, 'format': 'json', 'language': 'all', 'safesearch': 0})
        except httpx.HTTPError:
            raise ResearchError('The local search engine (SearXNG) is not running. ' + SETUP, retryable=True, status=503) from None
        if response.status_code == 403:
            raise ResearchError('SearXNG refused JSON results. Start it with scripts/searxng.sh so LeadDesk\'s settings are used.', status=503)
        if response.status_code == 429:
            raise ResearchError('Search engines are rate-limiting. Wait a minute and retry.', retryable=True, status=429)
        if response.status_code != 200:
            raise ResearchError(f'Local search returned HTTP {response.status_code}. Retry later.', retryable=True, status=502)
        try:
            body = response.json()
            rows = body.get('results', [])
            failing = body.get('unresponsive_engines') or []
        except (ValueError, AttributeError):
            raise ResearchError('Local search returned malformed data.', retryable=True, status=502) from None
        self.last_unresponsive = [[str(e[0])[:40], str(e[1])[:120]] for e in failing if isinstance(e, list) and len(e) == 2][:20]
        results = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not isinstance(row.get('url'), str) or not row['url'].startswith(('http://', 'https://')):
                continue
            results.append({'url': row['url'][:2048], 'title': str(row.get('title') or '')[:300],
                            'snippet': str(row.get('content') or '')[:1000], 'engine': str(row.get('engine') or '')[:40]})
            if len(results) >= limit:
                break
        if results or not self.last_unresponsive:
            with self.cache_lock:
                if len(self.cache) > 2000:
                    self.cache.clear()
                self.cache[key] = (time.monotonic(), [dict(r) for r in results])
        return results

    def status(self):
        try:
            response = self.client.get('/search', params={'q': 'test', 'format': 'json'}, timeout=5)
        except httpx.HTTPError:
            return {'url': self.base_url, 'reachable': False, 'json_enabled': False, 'message': 'Not running. ' + SETUP}
        return {'url': self.base_url, 'reachable': True, 'json_enabled': response.status_code == 200,
                'message': 'Ready.' if response.status_code == 200 else f'Reachable but returned HTTP {response.status_code}. Use scripts/searxng.sh.'}
