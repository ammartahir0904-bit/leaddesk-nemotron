"""Build the public demo's data: fictional cafés in Camden, London, run through LeadDesk's real pipeline offline.

Every business, website, page and search result below is invented. Websites use the reserved .example domain and phone
numbers come from Ofcom's ranges reserved for drama (020 7946 0xxx, 0161 496 0xxx), so no real business or person is
contacted or described. Nothing here touches the network: map search, web search, website reading and mail checks are
served by the fakes below. AI rewording is not pre-filled; on the hosted demo it runs live on Nebius Token Factory.

Usage: .venv/bin/python scripts/build_demo_data.py demo-data
Then:  LEADDESK_DATA_DIR=demo-data LEADDESK_DEMO=1 ./launch.sh
"""
import json
import shutil
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.adapters.fetch import Page  # noqa: E402
from backend.adapters.osm import OSMClient  # noqa: E402
from backend.api.app import create_app  # noqa: E402
from backend.domain.errors import ResearchError  # noqa: E402
from backend.settings import Settings  # noqa: E402

PLACE = [{'display_name': 'Camden Town, London Borough of Camden, London, England, United Kingdom', 'osm_type': 'relation', 'osm_id': 1,
          'lat': '51.5390', 'lon': '-0.1426', 'boundingbox': ['51.530', '51.548', '-0.155', '-0.130'], 'address': {'country_code': 'gb'}}]


def cafe(ident, name, lat, lon, **tags):
    return {'type': 'node', 'id': ident, 'lat': lat, 'lon': lon,
            'tags': {'amenity': 'cafe', 'name': name, 'addr:street': tags.pop('street', 'Parkway'), 'addr:city': 'London'} | tags}


ELEMENTS = [
    cafe(9001, 'Harbor Bean Café', 51.5391, -0.1430, website='http://harborbean.example', phone='020 7946 0101',
         email='hello@harborbean.example', street='Jamestown Road'),
    cafe(9002, 'Juniper & Oak Coffee', 51.5395, -0.1421, website='https://juniperoak.example', phone='020 7946 0202', street='Parkway'),
    cafe(9003, 'Little Fern Bakery Café', 51.5388, -0.1440, street='Inverness Street'),
    cafe(9004, 'Copper Kettle Tea Room', 51.5402, -0.1418, website='https://copperkettle.example', phone='020 7946 0404', street='Camden High Street'),
    cafe(9005, 'Moonbeam Espresso', 51.5385, -0.1412, website='https://moonbeam.example', phone='020 7946 0505', street='Arlington Road'),
    cafe(9006, 'Saffron Street Café', 51.5380, -0.1435, phone='020 0000 0000', email='saffron.street@mailinator.com', street='Delancey Street'),
    cafe(9007, 'Pebble Lane Café', 51.5398, -0.1445, phone='020 7946 0999', street='Pratt Street'),
    cafe(9008, 'Ivy Corner Café', 51.5377, -0.1424, phone='020 7946 0999', street='Bayham Street'),
    cafe(9009, 'Riverside Roasters', 51.5405, -0.1432, phone='020 7946 0999', email='hello@riversideroasters.example', street='Oval Road'),
]

LOREM = '<p>We roast our own beans and bake every morning in our Camden kitchen, with seasonal cakes, breakfast and lunch.</p>' * 3
SITES = {
    # An old site: plain HTTP, no mobile layout, PDF menu, no WhatsApp or tap-to-call, copyright 2019.
    'http://harborbean.example/': ('<html><head><title>Harbor Bean Cafe</title></head><body><table><tr><td><h1>Harbor Bean Café</h1>'
                                   '<font size="2">Coffee and cake on Jamestown Road since 2011.</font></td></tr></table>' + LOREM +
                                   '<p><a href="/menu-2019.pdf">Download our menu</a> · <a href="/contact">Contact</a></p>'
                                   '<p>Call 020 7946 0101 · hello@harborbean.example</p><p>© 2019 Harbor Bean</p></body></html>'),
    'http://harborbean.example/contact': ('<html><head><title>Contact - Harbor Bean Cafe</title></head><body><h1>Contact</h1>'
                                          '<p>Harbor Bean Café, 12 Jamestown Road, London. Call 020 7946 0101.</p></body></html>'),
    # A modern site: ordering, booking, WhatsApp, reviews. A weak prospect for a website seller.
    'https://juniperoak.example/': ('<!doctype html><html><head><title>Juniper & Oak Coffee | Camden</title>'
                                    '<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="description" content="Specialty coffee in Camden">'
                                    '<script type="application/ld+json">{"@type": "CafeOrCoffeeShop", "name": "Juniper & Oak Coffee", "telephone": "+44 20 7946 0202",'
                                    '"openingHours": "Mo-Su 07:00-18:00", "aggregateRating": {"ratingValue": "4.8", "reviewCount": "212"}}</script></head><body>'
                                    '<header><nav><a href="/">Home</a><a href="/menu">Menu</a><a href="/order">Order online</a><a href="/book">Book a table</a></nav></header>'
                                    '<h1>Juniper & Oak Coffee</h1><a href="tel:+442079460202">Call us</a> <a href="https://wa.me/442079460202">WhatsApp us</a>'
                                    '<section class="reviews"><h2>What our customers say</h2><p>Best flat white in Camden.</p></section>' + LOREM +
                                    '<form><input type="email"><textarea></textarea></form><p>© 2026 Juniper & Oak</p></body></html>'),
    # A placeholder.
    'https://copperkettle.example/': ('<!doctype html><html><head><title>Copper Kettle Tea Room: Coming Soon</title></head><body>'
                                      '<h1>Coming soon</h1><p>Our new website is on its way.</p></body></html>'),
    # A JavaScript app: almost nothing in the page source.
    'https://moonbeam.example/': ('<!doctype html><html><head><title>Moonbeam Espresso</title></head><body><div id="root"></div>'
                                  '<script src="/app.js"></script></body></html>'),
    # Pages found online for Little Fern (no website of its own).
    'https://directory.example/london/little-fern-bakery-cafe': ('<html><head><title>Little Fern Bakery Café, Camden - Directory</title></head><body>'
                                                                 '<h1>Little Fern Bakery Café</h1><p>Inverness Street, Camden, London. Phone: 020 7946 0303</p></body></html>'),
    # A site analysed with "Analyse a business website".
    'https://brightsmile-dental.example/': ('<!doctype html><html><head><title>Bright Smile Dental | Camden</title><meta name="viewport" content="width=device-width">'
                                            '<script type="application/ld+json">{"@type": "Dentist", "name": "Bright Smile Dental", "telephone": "+44 20 7946 0707"}</script>'
                                            '</head><body><header><nav><a href="/">Home</a><a href="/services">Services</a><a href="/contact">Contact</a></nav></header>'
                                            '<h1>Bright Smile Dental</h1><p>Family dentistry in Camden. Call 020 7946 0707 to make an appointment.</p>'
                                            + '<p>Check-ups, hygiene, whitening and Invisalign for adults and children in a calm clinic.</p>' * 4 +
                                            '<p>© 2021 Bright Smile Dental</p></body></html>'),
}

SEARCH = {
    'Little Fern Bakery Café': [
        {'url': 'https://www.facebook.com/littlefernbakerycamden', 'title': 'Little Fern Bakery Café | Camden, London | Facebook',
         'snippet': 'Little Fern Bakery Café, Camden. Sourdough, pastries and coffee. Call 020 7946 0303.', 'engine': 'demo'},
        {'url': 'https://www.instagram.com/littlefernbakery/', 'title': 'Little Fern Bakery (@littlefernbakery) • Instagram',
         'snippet': 'Bakery café in Camden, London. Fresh bakes daily.', 'engine': 'demo'},
        {'url': 'https://directory.example/london/little-fern-bakery-cafe', 'title': 'Little Fern Bakery Café, Camden - Directory',
         'snippet': 'Little Fern Bakery Café on Inverness Street, Camden. Phone 020 7946 0303.', 'engine': 'demo'},
        {'url': 'https://www.instagram.com/littlefern.weddings/', 'title': 'Little Fern Weddings (@littlefern.weddings)',
         'snippet': 'Wedding flowers and styling.', 'engine': 'demo'},
    ],
    'Harbor Bean Café': [
        {'url': 'http://harborbean.example/', 'title': 'Harbor Bean Cafe', 'snippet': 'Coffee and cake on Jamestown Road, Camden.', 'engine': 'demo'},
        {'url': 'https://www.facebook.com/harborbeancamden', 'title': 'Harbor Bean Café | Camden | Facebook',
         'snippet': 'Harbor Bean Café, Camden, London. Café.', 'engine': 'demo'},
    ],
    'Saffron Street Café': [
        {'url': 'https://directory.example/london/saffron-street', 'title': 'Saffron Street Café, Camden - Directory',
         'snippet': 'Saffron Street Café, Delancey Street, Camden. saffron.street@mailinator.com', 'engine': 'demo'},
    ],
}


class DemoWeb:
    def __init__(self):
        self.last_unresponsive, self.base_url = [], 'demo'

    def search(self, query, limit=10):
        return [dict(r) for name, rows in SEARCH.items() if f'"{name}"' in query for r in rows][:limit]

    def status(self):
        return {'url': 'demo', 'reachable': True, 'json_enabled': True, 'message': 'Fictional search results (demo).'}


def fetch(url):
    key = url if url in SITES else url.rstrip('/') + '/' if url.rstrip('/') + '/' in SITES else url
    if key not in SITES:
        raise ResearchError('The website returned HTTP 404. Try another public page or retry later.', status=422)
    return Page(key, SITES[key].encode(), SITES[key])


def osm(request):
    if request.url.host == 'nominatim.openstreetmap.org':
        return httpx.Response(200, json=PLACE)
    return httpx.Response(200, json={'elements': ELEMENTS})


def main(target):
    target = Path(target)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    settings = Settings(target, 'demo-build-' + 'x' * 32)
    app = create_app(settings, fetcher=fetch, osm_client=OSMClient(httpx.MockTransport(osm)), web_search=DemoWeb(),
                     mx_lookup=lambda domain: 'has_mx')
    with TestClient(app, base_url='http://testserver') as client:
        client.headers['Authorization'] = 'Bearer ' + settings.token
        search = client.post('/v1/prospecting/searches', headers={'Idempotency-Key': 'demo-cafes'}, json={
            'offer': 'We design modern websites for cafés', 'location': 'Camden Town, London', 'categories': ['cafe'],
            'limit': 20, 'use_public_osm': True, 'use_overture': False}).json()
        base = f"/v1/prospecting/searches/{search['id']}"
        for lead in search['candidates']:
            path = f"{base}/candidates/{lead['id']}"
            client.post(f'{path}/enrich')
            if lead['website']:
                client.post(f'{path}/check', headers={'Idempotency-Key': f"check-{lead['id']}"}, json={})
            client.post(f'{path}/verify', json={'check_mailboxes': False, 'read_website': False})
        harbor = next(c for c in search['candidates'] if c['name'] == 'Harbor Bean Café')
        client.post(f"{base}/candidates/{harbor['id']}/compare", json={'limit': 3})
        client.post('/v1/prospecting/site-analyses', headers={'Idempotency-Key': 'demo-dental'}, json={
            'url': 'https://brightsmile-dental.example/', 'offer': 'Online booking websites for dental clinics', 'location': 'Camden, London'})
        final = client.get(base).json()
    (target / 'access-token').unlink(missing_ok=True)  # each demo start makes its own key
    review = [c['contact_review']['counts'] for c in final['candidates']]
    print(f"Demo data in {target}: {len(final['candidates'])} fictional cafés; contact review totals "
          f"{ {k: sum(r[k] for r in review) for k in ('approved', 'needs_review', 'rejected')} }")


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'demo-data')
