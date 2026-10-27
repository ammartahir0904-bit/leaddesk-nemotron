"""Sprint 23: Chrome rendering (opt-in), layout findings, reading report and cross-host redirects."""
import http.server
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from backend.adapters.browser_render import ChromeRenderer, Rendered, Session, find_chrome
from backend.adapters.fetch import CrossHostRedirect, Page
from backend.domain.errors import ResearchError
from backend.domain.site_layout import analyse, outline, thin
from backend.domain.site_reader import advice, read_site

PLAIN = ('<!doctype html><html><head><title>Fictional Bean Cafe</title><meta name="viewport" content="width=device-width"></head><body>'
         '<header><nav><a href="/">Home</a><a href="/menu">Menu</a><a href="/contact">Contact</a></nav></header>'
         '<section id="hero"><h1>Fictional Bean Cafe</h1><a href="tel:+924211112222">Call us</a></section>'
         '<section class="testimonials"><h2>What our customers say</h2><p>Lovely coffee and friendly staff every single time we visit.</p></section>'
         + '<p>We roast our own beans and bake fresh cakes, breads and pastries in our kitchen every morning.</p>' * 6 +
         '<a href="/files/menu-2019.pdf">Download our menu</a><iframe src="https://www.google.com/maps/embed?pb=1"></iframe>'
         '<footer><p>© 2026 Fictional Bean</p></footer></body></html>')
SHELL = '<!doctype html><html><head><title>Fictional Bean</title></head><body><div id="root"></div><script src="/app.js"></script></body></html>'
DRAWN = ('<html><head><title>Fictional Bean</title></head><body><div id="root"><h1>Fictional Bean</h1>'
         '<p>Visit us at Main Boulevard, Gulberg, Lahore. Call 0300 1234567 or email hello@fictionalbean.example for orders and bookings.</p>'
         + '<p>Fresh coffee, cakes and sandwiches made every morning in our own kitchen for you.</p>' * 4 + '</div></body></html>')
DESKTOP = {'nav': ['Home', 'Menu'], 'headings': [{'level': 1, 'text': 'Fictional Bean', 'y': 120}],
           'actions': [{'kind': 'menu', 'text': 'Menu', 'href': '/menu', 'y': 60, 'first_screen': True, 'w': 60, 'h': 30}],
           'sections': {'hero': {'heading': 'Fictional Bean', 'y': 120}, 'footer': {'heading': '', 'y': 2000}}, 'iframes': [], 'pdf_links': [],
           'overflow': False, 'tiny_text': 0, 'text_sampled': 40, 'small_taps': 0, 'taps_checked': 12, 'broken_images': 2, 'images': 9,
           'sticky_header': True, 'page_height': 2400, 'words': 300, 'title': 'Fictional Bean', 'viewport': {'w': 1366, 'h': 768}}
PHONE = DESKTOP | {'overflow': True, 'tiny_text': 15, 'text_sampled': 40, 'small_taps': 9, 'taps_checked': 12,
                   'actions': [{'kind': 'call', 'text': 'Call', 'href': 'tel:+923001234567', 'y': 1900, 'first_screen': False, 'w': 20, 'h': 20}],
                   'viewport': {'w': 390, 'h': 844}}


class LayoutTests(unittest.TestCase):
    def test_html_outline_and_unmeasured_phone_checks(self):
        value = outline(PLAIN)
        self.assertEqual(value['nav'], ['Home', 'Menu', 'Contact'])
        self.assertEqual({a['kind'] for a in value['actions']}, {'call', 'menu', 'enquire'})
        self.assertLessEqual({'hero', 'reviews', 'footer', 'map'}, set(value['sections']))
        layout = analyse('https://bean.example/', html=PLAIN)
        found = {f['id']: f for f in layout['findings']}
        self.assertEqual(found['call_or_whatsapp_button']['state'], 'yes')
        self.assertTrue(found['pdf_menu']['gap'])
        self.assertIn('menu-2019.pdf', found['pdf_menu']['evidence']['text'])
        self.assertNotIn('phone_first_screen_contact', found)  # needs Chrome: not guessed
        self.assertIn('first phone screen', layout['unmeasured'])
        self.assertEqual(layout['source'], 'html')

    def test_rendered_phone_findings_with_measurements(self):
        layout = analyse('https://bean.example/', DESKTOP, PHONE, screens={'desktop': 'x-desktop'})
        found = {f['id']: f for f in layout['findings']}
        self.assertEqual(found['phone_first_screen_contact']['state'], 'no')
        self.assertTrue(found['phone_sideways_scroll']['gap'])
        self.assertIn('15 of 40', found['phone_tiny_text']['detail'])
        self.assertIn('9 of 12', found['phone_small_buttons']['detail'])
        self.assertIn('2 image', found['broken_images']['detail'])
        self.assertEqual(layout['unmeasured'], [])
        self.assertEqual(layout['source'], 'rendered')

    def test_thin_detection(self):
        self.assertTrue(thin(SHELL, 1))
        self.assertTrue(thin('<p>hello</p>', 5))
        self.assertFalse(thin(DRAWN, 120))


class FakeRender:
    def __init__(self, html=DRAWN, fail=None):
        self.html, self.fail, self.calls = html, fail, []

    def __call__(self, url, phone=False, screenshots=False):
        self.calls.append((url, phone, screenshots))
        if self.fail:
            raise ResearchError(self.fail, status=502)
        return Rendered(url=url, html=self.html, layout=DESKTOP, phone_layout=PHONE if phone else None,
                        screens={'desktop': 'a-desktop', 'phone': 'a-phone'} if screenshots else {}, seconds=1.5)


class ReaderTests(unittest.TestCase):
    def fetch(self, url):
        raise ResearchError("The website's robots policy disallows this page.", status=403)

    def test_javascript_site_is_read_from_chrome(self):
        render = FakeRender()
        site = read_site(Page('https://bean.example/', SHELL.encode(), SHELL), self.fetch, 'websites for cafes', 'web_presence', 2026,
                         render=render)
        self.assertEqual(render.calls[0], ('https://bean.example/', True, True))
        self.assertIn('0300 1234567', [c['value'] for c in site['contacts']])
        self.assertTrue(site['pages'][0]['rendered'])
        self.assertEqual(site['layout']['source'], 'rendered')
        self.assertEqual(site['reading']['rendered_pages'], 1)
        self.assertTrue(site['reading']['chrome_used'])
        self.assertIn('phone_sideways_scroll', [i['check'] for i in site['health']['issues']])
        self.assertNotIn('phone layout', site['health']['unmeasured'])

    def test_without_chrome_the_reading_report_says_why(self):
        site = read_site(Page('https://bean.example/', SHELL.encode(), SHELL), self.fetch, 'websites for cafes', 'web_presence', 2026)
        problem = site['reading']['problems'][0]
        self.assertEqual(problem['status'], 'thin')
        self.assertIn('JavaScript', problem['reason'])
        self.assertIn('Chrome', problem['next_step'])
        self.assertEqual(site['contacts'], [])

    def test_render_failure_falls_back_to_source(self):
        site = read_site(Page('https://bean.example/', PLAIN.encode(), PLAIN), self.fetch, 'websites', 'web_presence', 2026,
                         render=FakeRender(fail='Chrome did not answer in time.'))
        self.assertEqual(site['layout']['source'], 'html')
        self.assertEqual(site['reading']['problems'][0]['status'], 'render_failed')
        self.assertIn('call', site['layout']['action_kinds'])  # a tel: link labelled "Call us" is a button, not a shown number

    def test_advice_for_failed_pages(self):
        self.assertIn('respects', advice("The website's robots policy disallows this page.")['reason'])
        self.assertIn('does not get around', advice('The website returned HTTP 403. Try another public page')['next_step'])
        self.assertIn('forwards', advice('The page redirects to another host.')['reason'])
        self.assertIn('3 MB', advice('The page exceeds the 3 MB research limit.')['reason'])


class RendererSafetyTests(unittest.TestCase):
    def test_requests_are_refused_unless_public_http(self):
        def check_host(host, port):
            if host in {'127.0.0.1', 'router.local'}:
                raise ResearchError('Only public internet websites can be researched.', status=403)
        session = Session(pipe=None, check_host=check_host)
        self.assertIsNone(session.refuse('https://bean.example/app.js', 'Script'))
        self.assertIn('public', session.refuse('http://127.0.0.1:8765/v1/secret', 'XHR'))
        self.assertIn('public', session.refuse('http://router.local/', 'Image'))
        self.assertEqual(session.refuse('file:///etc/passwd', 'Document'), 'not a web address')
        self.assertEqual(session.refuse('https://cdn.example/video.mp4', 'Media'), 'video or audio skipped')
        session.requests = 400
        self.assertEqual(session.refuse('https://bean.example/more.js', 'Script'), 'request limit reached')

    def test_screenshots_are_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            renderer = ChromeRenderer(directory, lambda h, p: None, chrome='')
            self.assertFalse(renderer.status()['installed'])
            renderer.screens_dir.mkdir(parents=True)
            fresh = renderer.save('11111111-1111-1111-1111-111111111111-phone', b'jpeg')
            old = renderer.save('22222222-2222-2222-2222-222222222222-desktop', b'jpeg')
            stale = time.time() - 25 * 3600
            os.utime(renderer.screens_dir / f'{old}.jpg', (stale, stale))
            self.assertIsNotNone(renderer.screen_path(fresh))
            self.assertIsNone(renderer.screen_path(old))
            self.assertIsNone(renderer.screen_path('../../leaddesk.sqlite3'))
            renderer.expire_screens()
            self.assertFalse((renderer.screens_dir / f'{old}.jpg').exists())
            renderer.delete_screens([fresh])
            self.assertIsNone(renderer.screen_path(fresh))
            with self.assertRaises(ResearchError):
                renderer.render('https://bean.example/')


@unittest.skipUnless(find_chrome(), 'Google Chrome or Chromium is not installed')
class RealChromeTests(unittest.TestCase):
    """Renders a local JavaScript page in the installed Chrome. Loopback is allowed only by this test's host check."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        (root / 'index.html').write_text('<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>JS Bean</title></head>'
                                         '<body><div id="root"></div><img src="http://10.0.0.1/tracker.gif"><script src="app.js"></script></body></html>')
        (root / 'app.js').write_text("document.getElementById('root').innerHTML = '<h1>JS Bean</h1><p>Call 0300 1234567</p>"
                                     "<a href=\"https://wa.me/923001234567\">WhatsApp us</a>' + '<p>Fresh coffee every day.</p>'.repeat(30);")
        handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(root), **k)
        http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.directory.cleanup()

    def test_renders_javascript_and_blocks_private_requests(self):
        allowed = {'127.0.0.1'}

        def check_host(host, port):
            if host not in allowed:
                raise ResearchError('not a public address', status=403)
        renderer = ChromeRenderer(self.directory.name, check_host)
        # A busy server has many files open, so the pipes get numbers above 9 (sh could not redirect those).
        held = [os.open(os.devnull, os.O_RDONLY) for _ in range(20)]
        try:
            result = renderer.render(f'http://127.0.0.1:{self.server.server_port}/')
        finally:
            for fd in held:
                os.close(fd)
        self.assertIn('0300 1234567', result.html)
        self.assertEqual(result.layout['headings'][0]['text'], 'JS Bean')
        self.assertIn('whatsapp', {a['kind'] for a in result.phone_layout['actions']})
        self.assertIn('10.0.0.1', ' '.join(b['url'] for b in result.blocked))
        self.assertTrue(renderer.screen_path(result.screens['phone']))


class CrossHostAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_listed_site_forwarding_to_another_host_is_read_and_recorded(self):
        from tests import test_prospecting as fixtures
        import httpx
        from backend.adapters.osm import OSMClient
        from backend.api.app import create_app
        from backend.settings import Settings
        from tests.support import TOKEN
        self.directory = tempfile.mkdtemp()
        calls = []

        def fetcher(url):
            calls.append(url)
            if 'fictional-brew.example' in url and 'pk' not in url:
                raise CrossHostRedirect('The page redirects to another host. Enter that website URL directly to research it.',
                                        'https://fictional-brew.pk/')
            return Page(url, fixtures.SITE.encode(), fixtures.SITE)

        def osm(request):
            if request.url.host == 'nominatim.openstreetmap.org':
                return httpx.Response(200, json=fixtures.PLACE)
            return httpx.Response(200, json={'elements': fixtures.ELEMENTS})
        app = create_app(Settings(Path(self.directory), TOKEN), fetcher=fetcher, osm_client=OSMClient(httpx.MockTransport(osm)),
                         mx_lookup=lambda d: 'has_mx')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver',
                                     headers={'Authorization': f'Bearer {TOKEN}'}) as client:
            search = (await client.post('/v1/prospecting/searches', headers={'Idempotency-Key': 'x'}, json={
                'offer': 'We build websites for coffee shops', 'location': 'Fictional Town', 'categories': ['cafe'],
                'limit': 10, 'use_public_osm': True})).json()
            brew = next(c for c in search['candidates'] if c['website'])
            response = await client.post(f"/v1/prospecting/searches/{search['id']}/candidates/{brew['id']}/check", headers={'Idempotency-Key': 'c'})
            self.assertEqual(response.status_code, 200, response.text)
            site = response.json()['check']['site']
            self.assertEqual(site['cross_host_redirect'], {'from': 'https://fictional-brew.example', 'to': 'https://fictional-brew.pk/'})
            self.assertIn('https://fictional-brew.pk/', calls)
            status = (await client.get('/v1/prospecting/browser/status')).json()
            self.assertIn('installed', status)
            missing = await client.get('/v1/prospecting/screens/11111111-1111-1111-1111-111111111111-phone')
            self.assertEqual(missing.status_code, 404)


if __name__ == '__main__':
    unittest.main()


class PhoneOnlyButtonTests(unittest.TestCase):
    def test_button_shown_only_on_phones_counts(self):
        phone = PHONE | {'actions': [{'kind': 'whatsapp', 'text': 'Chat on WhatsApp', 'href': 'https://wa.me/923001234567', 'y': 700,
                                      'first_screen': True, 'w': 60, 'h': 60}]}
        layout = analyse('https://bean.example/', DESKTOP, phone)
        found = {f['id']: f['state'] for f in layout['findings']}
        self.assertEqual((found['call_or_whatsapp_button'], found['phone_first_screen_contact']), ('yes', 'yes'))
        self.assertIn('whatsapp', layout['action_kinds'])


class BotCheckTests(unittest.TestCase):
    def test_bot_check_page_is_never_used_as_the_site(self):
        check = ('<html><head><title>Just a moment...</title></head><body><h1>Checking your browser before accessing bean.example</h1>'
                 '<p>Please wait</p></body></html>')
        render = FakeRender(html=check)
        site = read_site(Page('https://bean.example/', PLAIN.encode(), PLAIN), ReaderTests().fetch, 'websites', 'web_presence', 2026, render=render)
        self.assertEqual(site['layout']['source'], 'html')  # measurements of the check page are discarded
        problem = site['reading']['problems'][0]
        self.assertEqual(problem['status'], 'bot_check')
        self.assertIn('does not get around', problem['reason'])
        self.assertEqual(site['reading']['discard_screens'], ['a-desktop', 'a-phone'])
        self.assertNotIn('phone_sideways_scroll', [i['check'] for i in site['health']['issues']])
