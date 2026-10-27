"""Web enrichment from a fake SearXNG; no real network."""
import unittest

import httpx

from backend.adapters.web_search import SearxClient, loopback
from backend.adapters.fetch import Page
from backend.domain.enrichment import classify, enrich, name_match, queries, read_result_pages, readable
from backend.domain.errors import ResearchError
from tests import test_prospecting as fixtures

RESULTS = [
    {'url': 'https://www.facebook.com/fictionalbean', 'title': 'Fictional Bean - Gulberg | Facebook', 'snippet': 'Call 0300 1234567 for orders', 'engine': 'bing'},
    {'url': 'https://fictionalbean.example/', 'title': 'Fictional Bean Coffee', 'snippet': 'Email hello@fictionalbean.example', 'engine': 'google'},
    {'url': 'https://www.tripadvisor.com/x', 'title': 'Fictional Bean, Lahore - Tripadvisor', 'snippet': 'Phone +92 42 35785577', 'engine': 'google'},
    {'url': 'https://other.example/', 'title': 'Different Brew Lahore', 'snippet': 'Call 0300 9999999', 'engine': 'google'},
    {'url': 'https://instagram.com/fictional.bean', 'title': 'fictional bean (@fictional.bean)', 'snippet': '', 'engine': 'bing'},
]


class DomainTests(unittest.TestCase):
    def test_own_pages_vs_mentions(self):
        rows = [{'url': 'https://www.facebook.com/foodblogger/videos/uncle-tetsu-review/1', 'title': 'Uncle Tetsu review', 'snippet': '', 'engine': ''},
                {'url': 'https://www.instagram.com/reel/abc/', 'title': 'Uncle Tetsu cheesecake', 'snippet': '', 'engine': ''},
                {'url': 'https://www.facebook.com/uncletetsupk/', 'title': 'Uncle Tetsu Pakistan', 'snippet': '', 'engine': ''},
                {'url': 'https://www.uncletetsu.pk/', 'title': 'Uncle Tetsu', 'snippet': '', 'engine': ''},
                {'url': 'https://someblog.wordpress.com/uncle-tetsu', 'title': 'Trying Uncle Tetsu', 'snippet': 'call 0300 1111111', 'engine': ''},
                {'url': 'https://www.zameen.com/guide', 'title': 'Uncle Tetsu in Gulberg', 'snippet': '', 'engine': ''}]
        value = enrich('Uncle Tetsu', None, rows)
        self.assertEqual([w['url'] for w in value['website_candidates']], ['https://www.uncletetsu.pk/'])
        self.assertEqual([p['url'] for p in value['social_pages']], ['https://www.facebook.com/uncletetsupk/'])
        self.assertEqual(len(value['mentions']), 4)
        self.assertEqual(value['contacts'][0]['confidence'], 'mention')

    def test_contacts_in_other_peoples_social_posts_are_not_attributed(self):
        post = {'url': 'https://www.facebook.com/100083203125038/posts/other-foods', 'engine': 'g',
                'title': 'Other Foods', 'snippet': 'Near Fictional Bean. Order now 0333 4801333'}
        value = enrich('Fictional Bean', None, [post])
        self.assertEqual((value['results'][0]['kind'], value['contacts']), ('mention', []))

    def test_apostrophes_do_not_split_names(self):
        self.assertEqual(name_match('Freddys Cafe', 'Freddy\u2019s Cafe Restaurant Menu in Lahore'), 'strong')
        self.assertEqual(name_match("Freddy's Cafe", 'Freddys Cafe Lahore'), 'strong')

    def test_classify_and_match(self):
        self.assertEqual(classify('https://m.facebook.com/page'), ('social', 'Facebook'))
        self.assertEqual(classify('https://www.google.com/maps/place/x'), ('directory', 'google.com'))
        self.assertEqual(classify('https://shop.example/'), ('website', 'shop.example'))
        self.assertEqual(name_match('Café Barbera', 'Cafe Barbera Lahore'), 'strong')
        self.assertEqual(name_match('Fictional Bean Cafe', 'Some other cafe'), 'none')
        self.assertEqual(name_match('Drip Coffee Brewery Bakery', 'Drip Brewery Lahore Bakery'), 'strong')
        self.assertEqual(queries('Fictional Bean', 'Gulberg, Lahore, Pakistan', 'cafe', 'Lahore', 'fictionalbean.example'),
                         ['"Fictional Bean" cafe Lahore', '"Fictional Bean" Lahore phone OR contact OR whatsapp',
                          'site:facebook.com "Fictional Bean" Lahore', 'site:instagram.com "Fictional Bean" Lahore', '"fictionalbean.example"'])
        # Without a lead city, the first two typed parts, as before.
        self.assertEqual(queries('Fictional Bean', 'Gulberg, Lahore, Pakistan')[0], '"Fictional Bean" Gulberg, Lahore')

    def test_enrich_keeps_sources_and_skips_other_businesses(self):
        value = enrich('Fictional Bean', None, RESULTS)
        self.assertEqual([w['url'] for w in value['website_candidates']], ['https://fictionalbean.example/'])
        self.assertEqual([p['platform'] for p in value['social_pages']], ['Facebook', 'Instagram'])
        contacts = {(c['type'], c['value']): (c['source_url'], c['confidence']) for c in value['contacts']}
        self.assertEqual(contacts, {('phone', '0300 1234567'): ('https://www.facebook.com/fictionalbean', 'own_page'),
                                    ('email', 'hello@fictionalbean.example'): ('https://fictionalbean.example/', 'own_page'),
                                    ('phone', '+92 42 35785577'): ('https://www.tripadvisor.com/x', 'mention')})
        self.assertEqual(value['contacts'][-1]['confidence'], 'mention')
        self.assertEqual([m['label'] for m in value['mentions']], ['tripadvisor.com'])
        self.assertNotIn('0300 9999999', str(value['contacts']))
        listed = enrich('Fictional Bean', 'fictionalbean.example', RESULTS)
        self.assertTrue(listed['website_candidates'][0]['is_listed_website'])


class ResultPageTests(unittest.TestCase):
    PAGES = {
        'https://fictionalbean.example/': '<html><head><title>Fictional Bean Coffee</title></head><body><p>Call us: +92 42 1111 2222</p>'
                                          '<p>Email orders@fictionalbean.example</p></body></html>',
        # A directory listing of many cafes: only the number written next to this name is attributable.
        'https://www.tripadvisor.com/x': '<html><head><title>Fictional Bean, Lahore - Tripadvisor</title></head><body>'
                                         + ''.join(f'<p>Other Cafe {i}: 042 3000 00{i}{i}</p>' for i in range(5))
                                         + '<p>Fictional Bean: 042 3578 5599</p></body></html>',
    }

    def fetch(self, url):
        self.fetched.append(url)
        if url not in self.PAGES:
            raise ResearchError("The website's robots policy disallows this page.", status=403)
        return Page(url, b'', self.PAGES[url])

    def setUp(self):
        self.fetched = []

    def test_reads_own_site_and_named_pages_with_excerpts(self):
        rows = RESULTS + [{'url': 'https://blocked.example/fictional-bean', 'title': 'Fictional Bean menu', 'snippet': '', 'engine': 'x'}]
        value = read_result_pages('Fictional Bean', enrich('Fictional Bean', None, rows), self.fetch)
        # Never social pages; own site first; at most three pages.
        self.assertEqual(self.fetched, ['https://fictionalbean.example/', 'https://www.tripadvisor.com/x', 'https://blocked.example/fictional-bean'])
        own = next(c for c in value['contacts'] if c['value'] == '+92 42 1111 2222')
        self.assertEqual((own['origin'], own['confidence'], own['source_url']), ('result_page', 'own_page', 'https://fictionalbean.example/'))
        self.assertIn('+92 42 1111 2222', own['excerpt'])
        listed = [c for c in value['contacts'] if c['source_url'] == 'https://www.tripadvisor.com/x' and c['origin'] == 'result_page']
        self.assertEqual([(c['value'], c['confidence']) for c in listed], [('042 3578 5599', 'mention')])
        self.assertNotIn('Other Cafe', listed[0]['excerpt'].split('Fictional Bean')[-1])
        self.assertEqual(value['page_reads'][2], {'url': 'https://blocked.example/fictional-bean', 'status': 'failed',
                                                  'message': "The website's robots policy disallows this page.", 'added': 0})
        self.assertIn('only contacts written next to this name', value['page_reads'][1]['message'])
        # The snippet phone already found on Tripadvisor is not duplicated; own-page contacts sort first.
        self.assertEqual(sum(c['value'].replace(' ', '').endswith('35785577') for c in value['contacts']), 1)
        self.assertEqual(value['contacts'][0]['confidence'], 'own_page')

    def test_pages_not_naming_the_business_are_not_attributed(self):
        rows = [{'url': 'https://www.tripadvisor.com/x', 'title': 'Fictional Bean, Lahore', 'snippet': '', 'engine': 'g'}]
        self.PAGES = {'https://www.tripadvisor.com/x': '<title>Different Brew</title><p>Call 0300 7654321</p>'}
        value = read_result_pages('Fictional Bean', enrich('Fictional Bean', None, rows), self.fetch)
        self.assertEqual(value['contacts'], [])
        self.assertIn('does not name this business', value['page_reads'][0]['message'])

    def test_readable_skips_maps_social_and_unnamed(self):
        rows = enrich('Fictional Bean', None, RESULTS + [
            {'url': 'https://www.google.com/maps/place/x', 'title': 'Fictional Bean', 'snippet': '', 'engine': 'g'},
            {'url': 'https://blog.example/post', 'title': 'Best cafes', 'snippet': 'Fictional', 'engine': 'g'},
            {'url': 'https://www.facebook.com/FictionalBean/posts/fictional-bean-is-open', 'title': 'Fictional Bean is open', 'snippet': '', 'engine': 'g'}])['results']
        self.assertEqual([r['url'] for r in readable(rows)], ['https://fictionalbean.example/', 'https://www.tripadvisor.com/x'])


class ClientTests(unittest.TestCase):
    def test_loopback_only_and_errors(self):
        for bad in ('http://192.168.1.5:8888', 'http://searx.example', 'file:///etc'):
            with self.assertRaises(ValueError):
                loopback(bad)
        self.assertEqual(loopback('http://localhost:8888/'), 'http://localhost:8888')
        ok = SearxClient('http://127.0.0.1:8888', httpx.MockTransport(lambda r: httpx.Response(200, json={'results': [
            {'url': 'https://a.example', 'title': 'A', 'content': 'x'}, {'url': 'javascript:alert(1)'}, 'junk']})))
        self.assertEqual(ok.search('q'), [{'url': 'https://a.example', 'title': 'A', 'snippet': 'x', 'engine': ''}])
        for status, retry in ((403, False), (429, True), (500, True)):
            client = SearxClient('http://127.0.0.1:8888', httpx.MockTransport(lambda r, s=status: httpx.Response(s)))
            with self.assertRaises(Exception) as caught:
                client.search('q')
            self.assertEqual(caught.exception.retryable, retry)
        def down(request):
            raise httpx.ConnectError('refused')
        self.assertFalse(SearxClient('http://127.0.0.1:8888', httpx.MockTransport(down)).status()['reachable'])


class FakeWeb:
    def __init__(self):
        self.queries = []

    def search(self, query, limit=10):
        self.queries.append(query)
        return [r | {} for r in RESULTS] if 'Fictional Bean' in query else []

    def status(self):
        return {'url': 'http://127.0.0.1:8888', 'reachable': True, 'json_enabled': True, 'message': 'Ready.'}


class EnrichmentAPITests(fixtures.ProspectingAPITests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        from backend.api.app import create_app
        from backend.adapters.osm import OSMClient
        from backend.settings import Settings
        from tests.support import TOKEN
        self.web = FakeWeb()
        await self.client.aclose()

        def osm(request):
            if request.url.host == 'nominatim.openstreetmap.org':
                return httpx.Response(200, json=fixtures.PLACE)
            return httpx.Response(200, json={'elements': fixtures.ELEMENTS})

        def fetcher(url):
            self.calls.append(url)
            return fixtures.Page(url, fixtures.SITE.encode(), fixtures.SITE)
        self.app = create_app(Settings(self.directory, TOKEN), fetcher=fetcher, osm_client=OSMClient(httpx.MockTransport(osm)),
                              mx_lookup=lambda d: 'has_mx', web_search=self.web)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://testserver', headers={'Authorization': f'Bearer {TOKEN}'})

    async def test_enrich_one_all_and_check_found_website(self):
        result = await self.search()
        base = f"/v1/prospecting/searches/{result['id']}"
        self.assertTrue((await self.send('GET', '/v1/prospecting/web-search/status')).json()['json_enabled'])
        bean = result['candidates'][0]
        response = await self.send('POST', f"{base}/candidates/{bean['id']}/enrich")
        self.assertEqual(response.status_code, 200, response.text)
        found = response.json()
        self.assertEqual(self.web.queries, ['"Fictional Bean" cafe Fictional Town', '"Fictional Bean" Fictional Town phone OR contact OR whatsapp',
                                            'site:facebook.com "Fictional Bean" Fictional Town', 'site:instagram.com "Fictional Bean" Fictional Town'])
        # Instagram's result does not mention the town, type or a local number: listed as possibly theirs, not used.
        self.assertEqual([(p['url'], p['kind']) for p in found['possible_pages']], [('https://instagram.com/fictional.bean', 'possible_social')])
        self.assertEqual(found['context']['category_word'], 'cafe')
        phone = next(c for c in found['contacts'] if c['value'] == '0300 1234567')
        self.assertEqual((phone['analysis']['e164'], phone['analysis']['line']), ('+923001234567', 'mobile'))
        saved = (await self.send('GET', base)).json()
        self.assertEqual(saved['candidates'][0]['enrichment']['social_pages'][0]['platform'], 'Facebook')
        self.assertEqual(saved['candidates'][0]['priority_points'], bean['priority_points'] + 3)
        self.assertIn('contact on their own page', saved['candidates'][0]['priority_reasons'])
        bulk = (await self.send('POST', f'{base}/enrich', json={'limit': 5})).json()
        self.assertEqual(bulk, {'enriched': 1, 'remaining': 0})
        self.assertEqual((await self.send('POST', f'{base}/enrich', json={'limit': 21})).status_code, 422)
        bad = await self.send('POST', f"{base}/candidates/{bean['id']}/check", json={'url': 'https://evil.example/'}, headers={'Idempotency-Key': 'bad'})
        self.assertEqual(bad.status_code, 409)
        check = await self.send('POST', f"{base}/candidates/{bean['id']}/check", json={'url': 'https://fictionalbean.example/'}, headers={'Idempotency-Key': 'found'})
        self.assertEqual(check.status_code, 200, check.text)
        # Find online opened their site and the Tripadvisor page (whose fixture body names another business, so
        # nothing was attributed from it), never Facebook or Instagram; then the check read the site.
        self.assertEqual(self.calls, ['https://fictionalbean.example/', 'https://www.tripadvisor.com/x', 'https://fictionalbean.example/'])
        reads = saved['candidates'][0]['enrichment']['page_reads']
        self.assertEqual([(r['url'], r['status']) for r in reads], [('https://fictionalbean.example/', 'read'), ('https://www.tripadvisor.com/x', 'read')])
        self.assertEqual(reads[1]['added'], 0)


for name in [n for n in vars(fixtures.ProspectingAPITests) if n.startswith('test_')]:
    setattr(EnrichmentAPITests, name, None)

if __name__ == '__main__':
    unittest.main()
