"""Tavily web search (opt-in) and the SearXNG/Tavily switch, against a fake Tavily server."""
import json
import unittest

import httpx

from backend.adapters.tavily import TavilyClient, WebSearch
from backend.domain.errors import ResearchError


class FakeTavily:
    def __init__(self, status=200):
        self.status, self.bodies = status, []

    def __call__(self, request):
        self.bodies.append(json.loads(request.content))
        if self.status != 200:
            return httpx.Response(self.status, json={'detail': 'x'})
        return httpx.Response(200, json={'results': [
            {'url': 'https://www.facebook.com/fictionalbean', 'title': 'Fictional Bean | Lahore', 'content': 'Call 0300 7654322'},
            {'url': 'javascript:alert(1)', 'title': 'bad'}], 'usage': {'credits': 1}})


class LocalSearch:
    def __init__(self):
        self.queries, self.last_unresponsive, self.base_url = [], [], 'http://127.0.0.1:8888'

    def search(self, query, limit=10):
        self.queries.append(query)
        return []

    def status(self):
        return {'reachable': True, 'json_enabled': True, 'message': 'Ready.'}


class TavilyTests(unittest.TestCase):
    def test_site_operator_becomes_domain_filter_and_results_are_cached(self):
        fake = FakeTavily()
        client = TavilyClient('tvly-test', httpx.MockTransport(fake))
        rows = client.search('site:facebook.com "Fictional Bean" Lahore', 10)
        self.assertEqual(rows, [{'url': 'https://www.facebook.com/fictionalbean', 'title': 'Fictional Bean | Lahore',
                                 'snippet': 'Call 0300 7654322', 'engine': 'tavily'}])
        self.assertEqual((fake.bodies[0]['query'], fake.bodies[0]['include_domains']), ('"Fictional Bean" Lahore', ['facebook.com']))
        client.search('site:facebook.com "Fictional Bean" Lahore', 10)
        self.assertEqual((len(fake.bodies), client.credits), (1, 1))

    def test_limits_and_bad_keys(self):
        for status, words in ((401, 'refused the API key'), (432, 'usage limit'), (500, 'HTTP 500')):
            with self.subTest(status=status), self.assertRaises(ResearchError) as caught:
                TavilyClient('k', httpx.MockTransport(FakeTavily(status))).search('q')
            self.assertIn(words, str(caught.exception))

    def test_switch_is_opt_in(self):
        stored = {}
        local, tavily = LocalSearch(), TavilyClient('tvly-test', httpx.MockTransport(FakeTavily()))
        web = WebSearch(local, tavily, lambda: stored.get('v'), lambda value: stored.update(v=value))
        web.search('q')
        self.assertEqual(local.queries, ['q'])  # local search until the user turns Tavily on
        self.assertEqual(web.choose('tavily')['provider'], 'tavily')
        self.assertTrue(stored['v']['chosen_at'])
        self.assertEqual(web.search('"Fictional Bean"')[0]['engine'], 'tavily')
        self.assertEqual(web.choose('searxng')['provider'], 'searxng')
        no_key = WebSearch(local, None, lambda: {'provider': 'tavily'}, lambda v: None)
        self.assertEqual(no_key.status()['provider'], 'searxng')
        with self.assertRaises(ResearchError):
            no_key.choose('tavily')


if __name__ == '__main__':
    unittest.main()
