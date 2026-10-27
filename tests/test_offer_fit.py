"""Sprint 23: what the seller offers vs. what the business has, and the rules-first pitch."""
import json
import unittest

from backend.domain.offer_fit import check_polish, offer_fit, offer_sentence, pitch, require_plan, trade_of
from backend.domain.errors import ResearchError
from backend.domain.site_layout import analyse

EVIDENCE = {'source': 'OpenStreetMap', 'url': 'https://www.openstreetmap.org/node/1'}
CAFE = {'name': 'Fictional Bean', 'category': 'cafe', 'category_label': 'Cafés and coffee shops', 'website': None, 'phone': '+92 300 0000001',
        'evidence': EVIDENCE, 'socials': ['https://www.instagram.com/fictionalbean/']}
HOME = 'https://fictionalbean.example/'


def site(**overrides):
    layout = analyse(HOME, {'nav': [], 'headings': [], 'actions': [], 'sections': {}, 'iframes': [], 'pdf_links': [{'text': 'Our menu', 'href': '/menu.pdf'}],
                            'overflow': False, 'tiny_text': 0, 'text_sampled': 0, 'small_taps': 0, 'taps_checked': 0, 'broken_images': 0,
                            'images': 3, 'sticky_header': False, 'page_height': 900, 'words': 400, 'viewport': {'w': 1366, 'h': 768}},
                     {'actions': [], 'overflow': True, 'viewport': {'w': 390, 'h': 844}, 'text_sampled': 0, 'taps_checked': 0})
    signals = [{'id': i, 'label': i, 'state': st, 'detail': f'{i} {st}', 'evidence': {'url': HOME, 'text': f'{i} evidence'}, 'gap': st != 'yes'}
               for i, st in (('https', 'yes'), ('mobile', 'yes'), ('online_ordering', 'not_found'), ('online_booking', 'not_found'),
                             ('contact_form', 'yes'), ('whatsapp', 'not_found'), ('structured_data', 'no'), ('seo_basics', 'yes'), ('stale', 'yes'))]
    value = {'pages': [{'url': HOME, 'kind': 'home', 'status': 'read'}], 'signals': signals, 'layout': layout, 'structured': [],
             'contacts': [], 'social_links': [], 'excerpts': [{'text': 'Opening hours: 9am to 11pm daily', 'page_url': HOME, 'page_kind': 'home'}]}
    return value | overrides


class OfferFitTests(unittest.TestCase):
    def test_trade_of(self):
        self.assertEqual(trade_of(CAFE), 'food')
        self.assertEqual(trade_of({'category': 'real_estate', 'category_label': 'Real estate agents'}), 'real_estate')
        self.assertEqual(trade_of({'category': None, 'category_label': 'Dentists'}), 'health')
        self.assertEqual(trade_of({'category': None, 'category_label': 'Named business'}), 'general')

    def test_checked_site_has_missing_and_not_seen_with_evidence(self):
        item = CAFE | {'website': HOME, 'check': {'site': site(), 'identity': {'verdict': 'confirmed'}}}
        fit = offer_fit(item, 'We design modern websites for cafes', 'web_presence', 'ok')
        rows = {r['id']: r for r in fit['features']}
        self.assertEqual(rows['own_website']['state'], 'has')
        self.assertEqual(rows['mobile_layout']['state'], 'missing')  # measured: scrolls sideways on a phone
        self.assertIn('scrolls sideways', rows['mobile_layout']['detail'])
        self.assertEqual(rows['menu_page']['state'], 'missing')
        self.assertIn('PDF', rows['menu_page']['detail'])
        self.assertEqual(rows['opening_hours']['state'], 'has')
        self.assertEqual(rows['gallery']['state'], 'not_seen')
        self.assertNotIn('listings', rows)  # real-estate feature, not for a cafe
        for row in rows.values():
            if row['state'] != 'not_seen':
                self.assertTrue(row['evidence'] and row['evidence']['url'], row['id'])
        plan = pitch(item, 'We design modern websites for cafes', fit, 'Gulberg, Lahore', 'ok')
        self.assertEqual(plan['fit'], 'likely')
        first = plan['opening'][0]
        self.assertTrue(first['evidence_ids'])
        self.assertIn('fictionalbean.example', first['text'])
        self.assertTrue(all(q['evidence_ids'] for q in plan['questions']))
        self.assertIn(('menu_page', 'fix'), [(b['id'], b['action']) for b in plan['build_plan']])
        self.assertIn(('mobile_layout', 'fix'), [(b['id'], b['action']) for b in plan['build_plan']])

    def test_identity_mismatch_is_not_used(self):
        item = CAFE | {'website': HOME, 'check': {'site': site(), 'identity': {'verdict': 'different_business'}}}
        fit = offer_fit(item, 'websites for cafes', 'web_presence', 'ok')
        self.assertFalse(fit['website_read'])
        self.assertEqual(pitch(item, 'websites for cafes', fit, '', 'ok')['fit'], 'unknown')
        with self.assertRaises(ResearchError):
            require_plan(pitch(item, 'websites for cafes', fit, '', 'ok'))

    def test_no_website_variants(self):
        none = pitch(CAFE, 'Modern websites for cafes', offer_fit(CAFE, 'Modern websites for cafes', 'web_presence', 'none'), 'Gulberg, Lahore', 'none')
        self.assertIn('found your Instagram page, but no website of your own', none['message'])
        self.assertIn('I work on modern websites for cafes', none['message'])
        self.assertNotIn('phone', ' '.join(q['text'] for q in none['questions']).casefold().replace('calls', ''))
        self.assertTrue(all(b['action'] == 'add' for b in none['build_plan']))
        down = CAFE | {'website': 'https://bean-old.example/', 'check': {'unreachable': {'url': 'https://bean-old.example/', 'message': 'HTTP 502'}}}
        plan = pitch(down, 'websites', offer_fit(down, 'websites', 'web_presence', 'unreachable'), '', 'unreachable')
        self.assertIn('bean-old.example', plan['message'])
        self.assertIn('did not load', plan['message'])
        self.assertNotIn('no website of your own', plan['message'])

    def test_non_web_offer_only_marks_related_features(self):
        fit = offer_fit(CAFE, 'Online table booking software for restaurants', 'general', 'none')
        enabled = {r['id'] for r in fit['features'] if r['enabled']}
        self.assertIn('online_booking', enabled)
        self.assertNotIn('gallery', enabled)
        narrowed = offer_fit(CAFE, 'anything', 'web_presence', 'none', chosen={'whatsapp_button'})
        self.assertEqual({r['id'] for r in narrowed['features'] if r['enabled']}, {'whatsapp_button'})

    def test_offer_sentence(self):
        self.assertEqual(offer_sentence('We design websites for cafes.', 'Bean'), 'We design websites for cafes; happy to show what that could look like for Bean.')
        self.assertTrue(offer_sentence('Modern websites for cafes', 'Bean').startswith('I work on modern websites for cafes'))


class PolishTests(unittest.TestCase):
    def setUp(self):
        self.plan = pitch(CAFE, 'Modern websites for cafes', offer_fit(CAFE, 'Modern websites for cafes', 'web_presence', 'none'), 'Gulberg', 'none')

    def answer(self, text):
        return check_polish(json.dumps({'message': text}), CAFE, 'Modern websites for cafes', self.plan)

    def test_rewording_without_new_facts_is_accepted(self):
        message, problems = self.answer('Hello! ' + self.plan['message'])
        self.assertEqual(problems, [])
        self.assertTrue(message.startswith('Hello!'))

    def test_inventions_are_rejected(self):
        for text, reason in ((f"Hi Fictional Bean, as discussed last week we can help.", 'earlier contact'),
                             (f"Fictional Bean could get 300 more orders a month.", 'numbers'),
                             (f"Fictional Bean, our websites boost sales quickly.", 'promises'),
                             (f"Fictional Bean, seller_product is great.", 'field names'),
                             ('Your cafe has no website.', 'drops the business name'),
                             (f"Fictional Bean needs a blockchain loyalty platform.", 'adds words')):
            message, problems = self.answer(text)
            self.assertIsNone(message, text)
            self.assertTrue(any(reason in p for p in problems), (text, problems))
        self.assertIsNone(check_polish('not json', CAFE, 'x', self.plan)[0])

    def test_promise_words_from_the_users_own_offer_are_allowed(self):
        offer = 'Websites that boost sales for cafes'
        plan = pitch(CAFE, offer, offer_fit(CAFE, offer, 'web_presence', 'none'), '', 'none')
        self.assertIn('boost sales', plan['message'])
        message, problems = check_polish(json.dumps({'message': plan['message']}), CAFE, offer, plan)
        self.assertEqual(problems, [])


if __name__ == '__main__':
    unittest.main()


class SiteAnalysisAPITests(unittest.IsolatedAsyncioTestCase):
    """The standalone "Analyse a website" box: any URL the user enters, compared with their offer."""
    PAGE = ('<!doctype html><html><head><title>Fictional Smiles Dental | Westlands</title><meta name="viewport" content="width=device-width">'
            '<script type="application/ld+json">{"@type": "Dentist", "name": "Fictional Smiles Dental", "telephone": "+254 700 000 001"}</script>'
            '</head><body><header><nav><a href="/">Home</a><a href="/contact">Contact</a></nav></header><h1>Fictional Smiles Dental</h1>'
            '<p>Gentle family dentistry in Westlands, Nairobi. Call +254 700 000 001 to make an appointment with our friendly team.</p>'
            + '<p>We offer check-ups, cleaning, whitening and braces for adults and children in a calm and modern clinic.</p>' * 4 +
            '</body></html>')

    async def asyncSetUp(self):
        import tempfile
        from pathlib import Path
        import httpx
        from backend.adapters.fetch import Page
        from backend.api.app import create_app
        from backend.settings import Settings
        from tests.support import TOKEN
        self.directory = Path(tempfile.mkdtemp())
        self.calls = []

        def fetcher(url):
            self.calls.append(url)
            if 'down.example' in url:
                raise ResearchError('The website returned HTTP 403. Try another public page or retry later.', status=422)
            return Page(url, self.PAGE.encode(), self.PAGE)
        self.app = create_app(Settings(self.directory, TOKEN), fetcher=fetcher, mx_lookup=lambda d: 'has_mx')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://testserver',
                                        headers={'Authorization': f'Bearer {TOKEN}'})

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_analyse_any_website(self):
        body = {'url': 'smiles.example', 'offer': 'Online booking websites for dental clinics', 'location': 'Westlands, Nairobi'}
        response = await self.client.post('/v1/prospecting/site-analyses', json=body, headers={'Idempotency-Key': 'a1'})
        self.assertEqual(response.status_code, 200, response.text)
        value = response.json()
        self.assertEqual(value['item']['name'], 'Fictional Smiles Dental')
        self.assertEqual((value['item']['category'], value['item']['category_source']), ('dentist', 'schema.org type Dentist'))
        self.assertEqual(value['offer_fit']['trade'], 'health')
        rows = {r['id']: r['state'] for r in value['offer_fit']['features']}
        self.assertEqual(rows['online_booking'], 'missing')
        self.assertIn('book online', value['pitch_plan']['message'])
        self.assertEqual(value['site']['layout']['source'], 'html')
        self.assertTrue(value['research_id'])
        # Same key and body: the saved analysis, nothing read again; same key with other inputs: refused.
        calls = len(self.calls)
        again = await self.client.post('/v1/prospecting/site-analyses', json=body, headers={'Idempotency-Key': 'a1'})
        self.assertEqual((again.json()['id'], len(self.calls)), (value['id'], calls))
        self.assertEqual((await self.client.post('/v1/prospecting/site-analyses', json=body | {'offer': 'Other'},
                                                 headers={'Idempotency-Key': 'a1'})).status_code, 409)
        listed = (await self.client.get('/v1/prospecting/site-analyses')).json()['items']
        self.assertEqual(listed[0]['name'], 'Fictional Smiles Dental')
        # Without a chosen model, AI rewording is refused; LeadDesk's own message stays.
        self.assertEqual((await self.client.post(f"/v1/prospecting/site-analyses/{value['id']}/polish")).status_code, 409)
        self.assertEqual((await self.client.delete(f"/v1/prospecting/site-analyses/{value['id']}")).status_code, 200)
        self.assertEqual((await self.client.get(f"/v1/prospecting/site-analyses/{value['id']}")).status_code, 404)

    async def test_refusals_explain_why(self):
        social = await self.client.post('/v1/prospecting/site-analyses', json={'url': 'https://www.instagram.com/bean/', 'offer': 'websites'},
                                        headers={'Idempotency-Key': 's1'})
        self.assertEqual(social.status_code, 409)
        blocked = await self.client.post('/v1/prospecting/site-analyses', json={'url': 'https://down.example/', 'offer': 'websites'},
                                         headers={'Idempotency-Key': 's2'})
        self.assertEqual(blocked.status_code, 422)
        self.assertIn('blocks automated readers', blocked.json()['message'])
        local = await self.client.post('/v1/prospecting/site-analyses', json={'url': 'http://127.0.0.1:8765/', 'offer': 'websites'},
                                       headers={'Idempotency-Key': 's3'})
        self.assertIn(local.status_code, {403, 422})


class WebsiteStatusTests(unittest.TestCase):
    def test_website_found_online_counts_once_read_as_theirs(self):
        from backend.domain.places import website_status
        online = {'website_candidates': [{'url': 'https://bean.example/', 'label': 'bean.example', 'name_match': 'strong'}]}
        self.assertEqual(website_status(CAFE | {'enrichment': online})[0], 'unchecked')
        read = {'site': {'pages': [{'url': 'https://bean.example/'}]}, 'identity': {'verdict': 'probably_same'}, 'website_url': 'https://bean.example/'}
        self.assertEqual(website_status(CAFE | {'enrichment': online}, read)[0], 'ok')
        other = read | {'identity': {'verdict': 'different_business'}}
        status, why = website_status(CAFE | {'enrichment': online}, other)
        self.assertEqual(status, 'none')
        self.assertIn('another business', why)
        self.assertEqual(website_status(CAFE)[0], 'none')


class PlaceholderTests(unittest.TestCase):
    def test_coming_soon_page_is_not_a_working_website(self):
        from backend.adapters.fetch import Page
        from backend.domain.site_reader import read_site
        html = '<html><head><title>Fictional Bean: Opening Soon!</title></head><body><h1>Opening soon</h1><p>Follow us on Instagram.</p></body></html>'

        def fetch(url):
            raise ResearchError("The website's robots policy disallows this page.", status=403)
        site = read_site(Page(HOME, html.encode(), html), fetch, 'websites for cafes', 'web_presence', 2026)
        self.assertEqual(site['layout']['findings'][0]['id'], 'placeholder_site')
        self.assertIn('placeholder_site', [i['check'] for i in site['health']['issues']])
        item = CAFE | {'website': HOME, 'check': {'site': site, 'identity': None}}
        fit = offer_fit(item, 'Modern websites for cafes', 'web_presence', 'ok')
        self.assertEqual(next(r for r in fit['features'] if r['id'] == 'own_website')['state'], 'missing')
        plan = pitch(item, 'Modern websites for cafes', fit, '', 'ok')
        self.assertIn('only shows a "Opening Soon" page', plan['message'])


class EmptySourceTests(unittest.TestCase):
    def test_javascript_shell_is_not_judged(self):
        from backend.adapters.fetch import Page
        from backend.domain.site_reader import read_site
        html = '<!doctype html><html><head><title>Fictional Bean</title></head><body><div id="root"></div></body></html>'

        def fetch(url):
            raise ResearchError("The website's robots policy disallows this page.", status=403)
        site = read_site(Page(HOME, html.encode(), html), fetch, 'websites for cafes', 'web_presence', 2026)
        item = CAFE | {'website': HOME, 'check': {'site': site, 'identity': None}}
        fit = offer_fit(item, 'Modern websites for cafes', 'web_presence', 'ok')
        states = {r['id']: r['state'] for r in fit['features']}
        self.assertEqual(states['own_website'], 'has')
        self.assertEqual({s for k, s in states.items() if k != 'own_website'}, {'not_seen'})
        self.assertNotIn('phone', pitch(item, 'Modern websites for cafes', fit, '', 'ok')['message'])
