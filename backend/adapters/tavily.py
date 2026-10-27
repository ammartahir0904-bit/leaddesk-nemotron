"""Tavily web search (opt-in) and the switch between Tavily and the local SearXNG.

Tavily is used only when TAVILY_API_KEY is set AND the user turns it on in Find clients; that choice is stored with its
time. What is sent: the search queries LeadDesk builds (business name, type, city). The key is never stored by LeadDesk.
Free search engines behind SearXNG often block automated searches; Tavily is a search API built for this use.
"""
import json
import re
import threading
import time

import httpx

from backend.domain.errors import ResearchError

SITE = re.compile(r'\bsite:([a-z0-9.-]+\.[a-z]{2,})\s*', re.I)


class TavilyClient:
    CACHE_SECONDS = 6 * 3600

    def __init__(self, api_key, transport=None):
        self.api_key = (api_key or '').strip()
        self.client = httpx.Client(base_url='https://api.tavily.com', trust_env=False, follow_redirects=False, transport=transport,
                                   timeout=httpx.Timeout(30, connect=10),
                                   headers={'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'})
        self.requests, self.last_unresponsive, self.credits = 0, [], 0
        self.cache, self.cache_lock = {}, threading.Lock()

    @property
    def configured(self):
        return bool(self.api_key)

    def search(self, query, limit=10):
        key = (query, limit)
        with self.cache_lock:
            hit = self.cache.get(key)
            if hit and time.monotonic() - hit[0] < self.CACHE_SECONDS:
                self.last_unresponsive = []
                return [dict(r) for r in hit[1]]
        # Tavily filters by domain with include_domains rather than the site: operator.
        domains = [d.casefold() for d in SITE.findall(query)]
        text = SITE.sub('', query).strip() or query
        payload = {'query': text[:400], 'max_results': max(1, min(limit, 20)), 'search_depth': 'basic', 'include_answer': False}
        if domains:
            payload['include_domains'] = domains
        self.requests += 1
        try:
            response = self.client.post('/search', content=json.dumps(payload))
        except httpx.HTTPError:
            raise ResearchError('Cannot reach Tavily. Check the internet connection.', retryable=True, status=503) from None
        if response.status_code == 401:
            raise ResearchError('Tavily refused the API key. Check TAVILY_API_KEY and restart LeadDesk.', status=502)
        if response.status_code in {429, 432, 433}:
            self.last_unresponsive = [['tavily', 'usage limit or rate limit reached']]
            raise ResearchError('Tavily usage limit or rate limit reached. Wait, or switch Find online back to local search.',
                                retryable=True, status=429)
        if response.status_code != 200:
            raise ResearchError(f'Tavily returned HTTP {response.status_code}. Retry later.', retryable=True, status=502)
        try:
            body = response.json()
            rows = body.get('results') or []
        except (ValueError, AttributeError):
            raise ResearchError('Tavily returned malformed data.', retryable=True, status=502) from None
        self.credits += int((body.get('usage') or {}).get('credits') or 1)
        results = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not str(row.get('url', '')).startswith(('http://', 'https://')):
                continue
            results.append({'url': row['url'][:2048], 'title': str(row.get('title') or '')[:300],
                            'snippet': ' '.join(str(row.get('content') or '').split())[:1000], 'engine': 'tavily'})
            if len(results) >= limit:
                break
        self.last_unresponsive = []
        with self.cache_lock:
            if len(self.cache) > 2000:
                self.cache.clear()
            self.cache[key] = (time.monotonic(), [dict(r) for r in results])
        return results

    def status(self):
        if not self.configured:
            return {'reachable': False, 'json_enabled': False, 'message': 'Set TAVILY_API_KEY and restart LeadDesk to use Tavily.'}
        return {'reachable': True, 'json_enabled': True, 'message': 'Tavily key set.'}


class WebSearch:
    """Find online's search: Tavily when the user turned it on (and its key is set), otherwise local SearXNG."""

    def __init__(self, searxng, tavily, load_choice, save_choice):
        self.searxng, self.tavily, self.load_choice, self.save_choice = searxng, tavily, load_choice, save_choice

    @property
    def active(self):
        choice = self.load_choice() or {}
        if choice.get('provider') == 'tavily' and self.tavily is not None and self.tavily.configured:
            return self.tavily
        return self.searxng

    @property
    def last_unresponsive(self):
        return self.active.last_unresponsive

    def search(self, query, limit=10):
        return self.active.search(query, limit)

    def choose(self, provider):
        if provider == 'tavily' and (self.tavily is None or not self.tavily.configured):
            raise ResearchError('Set TAVILY_API_KEY and restart LeadDesk before turning on Tavily.', status=409)
        self.save_choice({'provider': provider, 'chosen_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
        return self.status()

    def status(self):
        using_tavily = self.active is self.tavily
        base = self.tavily.status() if using_tavily else self.searxng.status()
        return base | {'provider': 'tavily' if using_tavily else 'searxng',
                       'tavily_configured': bool(self.tavily and self.tavily.configured),
                       'tavily_credits_used': self.tavily.credits if self.tavily else 0,
                       'url': getattr(self.searxng, 'base_url', None)}
