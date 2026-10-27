"""Sprint 23: targeted web searches, same-named businesses elsewhere, link-in-bio pages and user confirmations."""
import unittest

from backend.adapters.fetch import Page
from backend.domain.enrichment import apply_feedback, enrich, handle_quality, read_result_pages
from backend.domain.errors import ResearchError
from backend.domain.extract import extract
from backend.domain.search_context import build, category_word, lead_city
from tests import test_enrichment as web_fixtures

QATAR = {'display_name': 'United Arab Emirates', 'country_code': 'ae'}
LAHORE = {'display_name': 'Gulberg, Lahore, Punjab, Pakistan', 'country_code': 'pk'}
SIDI = {'name': 'Sidi Mansour', 'category': 'restaurant', 'category_label': 'Restaurants', 'address': 'Sheikh Zayed Road, Al Barsha, Dubai'}
# Real shapes seen on 26 October 2026 (fictionalised URLs): a song page, a different organisation's Instagram and the real profile.
SIDI_RESULTS = [
    {'url': 'https://www.patreon.com/someone/posts/origin-of-sidi-mansour', 'title': 'Origin of Sidi Mansour', 'snippet': 'The Tunisian folk song…', 'engine': 'g'},
    {'url': 'https://en.wikipedia.org/wiki/Sidi_Mansour_(song)', 'title': 'Sidi Mansour (song) - Wikipedia', 'snippet': 'A Tunisian song', 'engine': 'g'},
    {'url': 'https://www.instagram.com/jci.sidi.mansour/', 'title': 'JCI Sidi Mansour (@jci.sidi.mansour)', 'snippet': 'Junior chamber', 'engine': 'g'},
    {'url': 'https://www.instagram.com/sidimansour.dubai/', 'title': 'Sidi Mansour Restaurant (@sidimansour.dubai)',
     'snippet': 'Tunisian restaurant in Al Barsha, Dubai. WhatsApp +971 50 123 4567', 'engine': 'g'},
    {'url': 'https://www.talabat.com/uae/sidi-mansour', 'title': 'Sidi Mansour Restaurant Delivery Menu | Dubai', 'snippet': 'Call 04 321 4567', 'engine': 'g'},
]


class ContextTests(unittest.TestCase):
    def test_lead_city_prefers_its_own_address(self):
        self.assertEqual(lead_city('MM Alam Road, Gulberg, 54660', 'Gulberg, Lahore, Pakistan', LAHORE['display_name']), 'Gulberg, Lahore')
        self.assertEqual(lead_city('Circular Road, Urdu Bazaar, Lahore, 54100', 'Gulberg, Lahore, Pakistan', LAHORE['display_name']), 'Lahore')
        # Country-wide search: the lead's own city, not "UAE".
        self.assertEqual(lead_city('Marasi Drive, Business Bay, Dubai', 'Uae', QATAR['display_name']), 'Dubai')
        self.assertEqual(lead_city('Hub Dam Road, Karachi Division', 'Sindh', 'Sindh, Pakistan'), 'Karachi')
        # No usable address: what the user typed, as before.
        self.assertEqual(lead_city(None, 'Westlands, Nairobi, Kenya', 'Westlands, Nairobi, Nairobi County, Kenya'), 'Westlands, Nairobi')
        self.assertEqual(category_word('cafe', 'Cafés and coffee shops'), 'cafe')
        self.assertEqual(category_word(None, 'Dentists'), 'dentist')
        self.assertEqual(category_word(None, 'Named business'), '')

    def test_same_named_results_elsewhere_give_nothing(self):
        context = build(SIDI, 'Uae', QATAR)
        value = enrich('Sidi Mansour', None, SIDI_RESULTS, context)
        kinds = {r['url']: r['kind'] for r in value['results']}
        self.assertEqual(kinds['https://www.patreon.com/someone/posts/origin-of-sidi-mansour'], 'unconfirmed')
        self.assertEqual(kinds['https://www.instagram.com/jci.sidi.mansour/'], 'possible_social')
        self.assertEqual([p['url'] for p in value['social_pages']], ['https://www.instagram.com/sidimansour.dubai/'])
        self.assertEqual({c['value'] for c in value['contacts']}, {'+971 50 123 4567', '04 321 4567'})
        self.assertIn('Dubai', value['notes'][1])
        possible = {p['url']: p['reason'] for p in value['possible_pages']}
        self.assertIn('other words around this name', possible['https://www.instagram.com/jci.sidi.mansour/'])
        self.assertNotIn('Tunisian folk', str(value['contacts']))

    def test_name_words_are_not_context(self):
        # "Fictional" is both the town and the business name: a page naming the business is not thereby in that town.
        context = build({'name': 'Fictional Bean', 'category': 'cafe', 'category_label': 'Cafés', 'address': None}, 'Fictional Town',
                        {'display_name': 'Fictional Town, Fictional Country', 'country_code': 'pk'})
        rows = [{'url': 'https://instagram.com/fictional.bean', 'title': 'fictional bean (@fictional.bean)', 'snippet': '', 'engine': 'b'}]
        self.assertEqual(enrich('Fictional Bean', None, rows, context)['results'][0]['kind'], 'possible_social')
        # Known from the map data or their website: accepted without further context.
        known = build({'name': 'Fictional Bean', 'category': 'cafe', 'category_label': 'Cafés', 'address': None,
                       'socials': ['https://instagram.com/fictional.bean/']}, 'Fictional Town', {'display_name': 'Fictional Town', 'country_code': 'pk'})
        self.assertEqual(enrich('Fictional Bean', None, rows, known)['social_pages'][0]['url'], 'https://instagram.com/fictional.bean')

    def test_handle_quality(self):
        context = build({'name': 'Freddys Cafe', 'category': 'cafe', 'category_label': 'Cafés', 'address': 'MM Alam Road, Gulberg, Lahore'},
                        'Gulberg, Lahore', LAHORE)
        self.assertEqual(handle_quality('Freddys Cafe', 'FreddysCafeLahore', context), 'clean')
        self.assertEqual(handle_quality('Cafe Costa', 'cafecosta.lhr', context), 'clean')
        self.assertEqual(handle_quality('Butlers Chocolate Café', 'butlerspk', context), 'clean')
        self.assertEqual(handle_quality('Sidi Mansour', 'jci.sidi.mansour', context), 'loose')
        # One word of a longer name next to a type word is someone else ("Mansour Bakery").
        self.assertEqual(handle_quality('Sidi Mansour', 'mansourbakery', context), 'loose')
        self.assertIsNone(handle_quality('Sidi Mansour', 'goldenspoon', context))

    def test_feedback_releases_or_removes(self):
        context = build(SIDI, 'Uae', QATAR)
        value = enrich('Sidi Mansour', None, SIDI_RESULTS + [
            {'url': 'https://www.facebook.com/sidimansour', 'title': 'Sidi Mansour | Facebook', 'snippet': 'Call +216 71 234 567', 'engine': 'g'}], context)
        # A Tunisian number does not place the page in the UAE: held back until the user confirms.
        self.assertNotIn('+216 71 234 567', str(value['contacts']))
        confirmed = apply_feedback(value, {'https://www.facebook.com/sidimansour': 'yes', 'https://www.talabat.com/uae/sidi-mansour': 'no'})
        self.assertIn('https://www.facebook.com/sidimansour', [p['url'] for p in confirmed['social_pages']])
        self.assertIn('+216 71 234 567', [c['value'] for c in confirmed['contacts']])
        self.assertNotIn('04 321 4567', [c['value'] for c in confirmed['contacts']])
        self.assertNotIn('https://www.facebook.com/sidimansour', [p['url'] for p in confirmed['possible_pages']])


class LinkHubTests(unittest.TestCase):
    def test_link_in_bio_page_is_read_as_their_own(self):
        context = build({'name': 'Fictional Bean', 'category': 'cafe', 'category_label': 'Cafés', 'address': 'Main Boulevard, Gulberg, Lahore'},
                        'Gulberg, Lahore', LAHORE)
        rows = [{'url': 'https://linktr.ee/fictionalbean', 'title': 'Fictional Bean Lahore | Linktree', 'snippet': 'Menu, WhatsApp, Instagram', 'engine': 'g'}]
        pages = {'https://linktr.ee/fictionalbean': '<title>Fictional Bean | Linktree</title><a href="https://wa.me/923001234567">WhatsApp us</a>'
                                                    '<p>bookings [at] fictionalbean [dot] pk</p>'}
        fetched = []

        def fetch(url):
            fetched.append(url)
            return Page(url, b'', pages[url])
        value = read_result_pages('Fictional Bean', enrich('Fictional Bean', None, rows, context), fetch)
        self.assertEqual(fetched, ['https://linktr.ee/fictionalbean'])
        self.assertEqual(value['social_pages'][0]['platform'], 'Linktree')
        found = {(c['type'], c['value']): c['confidence'] for c in value['contacts']}
        self.assertEqual(found, {('whatsapp', '+923001234567'): 'own_page', ('email', 'bookings@fictionalbean.pk'): 'own_page'})

    def test_unconfirmed_pages_are_not_opened_and_parse_failures_are_recorded(self):
        context = build(SIDI, 'Uae', QATAR)
        rows = SIDI_RESULTS + [{'url': 'https://big.example/sidi-mansour-dubai', 'title': 'Sidi Mansour Dubai', 'snippet': '', 'engine': 'g'}]
        fetched = []

        def fetch(url):
            fetched.append(url)
            if 'big.example' in url:
                return Page(url, b'', '<div>' * 140 + '</div>' * 140)
            raise ResearchError("The website's robots policy disallows this page.", status=403)
        value = read_result_pages('Sidi Mansour', enrich('Sidi Mansour', None, rows, context), fetch)
        self.assertNotIn('https://www.patreon.com/someone/posts/origin-of-sidi-mansour', fetched)
        self.assertNotIn('https://en.wikipedia.org/wiki/Sidi_Mansour_(song)', fetched)
        failed = next(r for r in value['page_reads'] if 'big.example' in r['url'])
        self.assertEqual(failed['status'], 'failed')
        self.assertIn('too complex', failed['message'])


class ExtractorTests(unittest.TestCase):
    def test_protected_and_written_out_emails_and_whatsapp(self):
        # Cloudflare encodes "hello@bean.pk" with key 0x2a.
        hexed = '2a' + ''.join(f'{ord(c) ^ 0x2a:02x}' for c in 'hello@bean.pk')
        html = (f'<p>Email: <a href="/cdn-cgi/l/email-protection#{hexed}"><span class="__cf_email__" data-cfemail="{hexed}">[email&#160;protected]</span></a></p>'
                '<p>Orders: orders (at) bean (dot) pk</p><p>WhatsApp: 0300-7654321</p>'
                '<a href="https://api.whatsapp.com/send?phone=923001112233&text=Hi">Chat</a><a href="whatsapp://send?phone=%2B971501234567">WA</a>'
                '<p>Meet us at the cafe (at noon) for coffee.</p>')
        found = {(c['type'], c['normalised_value']) for c in extract(html).contacts}
        self.assertLessEqual({('email', 'hello@bean.pk'), ('email', 'orders@bean.pk'), ('whatsapp', '+923001112233'),
                              ('whatsapp', '+971501234567')}, found)
        self.assertIn('0300-7654321', {c['raw_value'] for c in extract(html).contacts if c['type'] == 'whatsapp'})
        self.assertNotIn('noon', str(found))
        # A malformed protected value is left as it was.
        self.assertEqual(extract('<span data-cfemail="zz">[email protected]</span>').contacts, [])


class UserWebsiteAndFeedbackAPITests(web_fixtures.EnrichmentAPITests):
    async def test_feedback_and_user_supplied_website(self):
        result = await self.search()
        base = f"/v1/prospecting/searches/{result['id']}"
        bean = result['candidates'][0]
        await self.send('POST', f"{base}/candidates/{bean['id']}/enrich")
        instagram = 'https://instagram.com/fictional.bean'
        answer = await self.send('POST', f"{base}/candidates/{bean['id']}/web-feedback", json={'url': instagram, 'verdict': 'yes'})
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertIn(instagram, [p['url'] for p in answer.json()['enrichment']['social_pages']])
        facebook = 'https://www.facebook.com/fictionalbean'
        rejected = (await self.send('POST', f"{base}/candidates/{bean['id']}/web-feedback", json={'url': facebook, 'verdict': 'no'})).json()
        self.assertNotIn(facebook, [p['url'] for p in rejected['enrichment']['social_pages']])
        self.assertNotIn('0300 1234567', [c['value'] for c in rejected['enrichment']['contacts']])
        cleared = (await self.send('POST', f"{base}/candidates/{bean['id']}/web-feedback", json={'url': facebook, 'verdict': 'clear'})).json()
        self.assertIn(facebook, [p['url'] for p in cleared['enrichment']['social_pages']])
        unknown = await self.send('POST', f"{base}/candidates/{bean['id']}/web-feedback", json={'url': 'https://elsewhere.example/', 'verdict': 'yes'})
        self.assertEqual(unknown.status_code, 404)
        # "Add website": the user's own URL is read; without the flag an arbitrary URL is still refused.
        social = await self.send('POST', f"{base}/candidates/{bean['id']}/check", json={'url': facebook, 'user_supplied': True},
                                 headers={'Idempotency-Key': 'user-social'})
        self.assertEqual(social.status_code, 409)
        typed = await self.send('POST', f"{base}/candidates/{bean['id']}/check", json={'url': 'typed-bean.example', 'user_supplied': True},
                                headers={'Idempotency-Key': 'user-typed'})
        self.assertEqual(typed.status_code, 200, typed.text)
        check = typed.json()['check']
        self.assertEqual((check['website_url'], check['website_source']), ('https://typed-bean.example/', 'user_supplied'))
        # The fixture site names another business: the identity cross-check says so rather than hiding it.
        self.assertNotEqual(check['identity']['verdict'], 'confirmed')


for name in [n for n in vars(web_fixtures.EnrichmentAPITests) if n.startswith('test_')]:
    setattr(UserWebsiteAndFeedbackAPITests, name, None)

if __name__ == '__main__':
    unittest.main()


class BlockedWeb(web_fixtures.FakeWeb):
    """Search engines refusing automated searches, as SearXNG reports them."""

    def __init__(self, mode):
        super().__init__()
        self.mode, self.last_unresponsive = mode, []

    def search(self, query, limit=10):
        self.queries.append(query)
        self.last_unresponsive = [['google cse', 'Suspended: too many requests']]
        if self.mode == 'all':
            return []
        rows = [r for r in web_fixtures.RESULTS if 'facebook' not in r['url'] and 'instagram' not in r['url']]
        return rows if 'Fictional Bean' in query else []


class EngineReportTests(web_fixtures.EnrichmentAPITests):
    async def test_blocked_engines_never_look_like_nothing_found(self):
        result = await self.search()
        base = f"/v1/prospecting/searches/{result['id']}"
        bean = result['candidates'][0]
        # The app holds this fake engine; switch it to blocked mode.
        self.web.__class__, self.web.mode, self.web.last_unresponsive = BlockedWeb, 'all', []
        refused = await self.send('POST', f"{base}/candidates/{bean['id']}/enrich")
        self.assertEqual(refused.status_code, 429)
        self.assertIn('Nothing was saved', refused.json()['message'])
        self.assertIsNone((await self.send('GET', base)).json()['candidates'][0]['enrichment'])
        self.web.mode, partial = 'partial', self.web
        value = (await self.send('POST', f"{base}/candidates/{bean['id']}/enrich")).json()
        self.assertFalse(value['engine_report']['complete'])
        self.assertIn('may be incomplete', value['notes'][0])
        # No Instagram or Facebook in the first pass: the extra searches ran (without the city, and by handle).
        self.assertIn('"Fictional Bean" instagram', partial.queries)
        self.assertIn('"fictionalbean" instagram OR facebook', partial.queries)
