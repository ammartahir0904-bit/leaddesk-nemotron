"""Product-led discovery with a fake OpenStreetMap transport; no real network."""
import unittest

import httpx

from backend.adapters.fetch import Page
from backend.adapters.osm import OSMClient
from backend.api.app import create_app
from backend.domain.prospecting import (CATALOGUE, CATEGORIES, ProspectSearchInput, category_of, nominatim_filters, overpass_query,
                                        profile_offer, rank, search_categories)
from backend.settings import Settings
from tests.support import TOKEN, APITestCase

ELEMENTS = [
    {'type': 'node', 'id': 1, 'lat': 31.5, 'lon': 74.3, 'tags': {'amenity': 'cafe', 'name': 'Fictional Bean', 'phone': '+92 300 0000001'}},
    {'type': 'way', 'id': 2, 'center': {'lat': 31.51, 'lon': 74.31}, 'tags': {'amenity': 'cafe', 'name': 'Fictional Brew House',
     'website': 'fictional-brew.example', 'email': 'hello@fictional-brew.example', 'brand': 'Fictional Brew'}},
    {'type': 'node', 'id': 3, 'lat': 31.52, 'lon': 74.32, 'tags': {'amenity': 'cafe'}},
    {'type': 'node', 'id': 4, 'lat': 31.5, 'lon': 74.3, 'tags': {'amenity': 'cafe', 'name': 'Fictional Bean', 'phone': '+92 300 0000001'}},
]
PLACE = [{'display_name': 'Fictional Town, Fictional Country', 'osm_type': 'relation', 'osm_id': 42, 'lat': '31.5', 'lon': '74.3',
          'boundingbox': ['31.4', '31.6', '74.2', '74.4'], 'address': {'country_code': 'pk'}}]
POIS = [{'category': 'amenity', 'type': 'cafe', 'osm_type': 'node', 'osm_id': 7, 'lat': '31.5', 'lon': '74.3', 'name': 'Fictional Corner Cafe',
         'extratags': {'phone': '+92 300 0000007'}, 'address': {'road': 'Fictional Road', 'city': 'Fictional Town'}},
        {'category': 'shop', 'type': 'bakery', 'osm_type': 'node', 'osm_id': 8, 'lat': '31.5', 'lon': '74.3', 'name': 'Wrong Type Bakery'}]
SITE = '<html><head><title>Fictional Brew House</title></head><body><h1>Fictional Brew House</h1><p>Order coffee online. Contact: hello@fictional-brew.example</p></body></html>'


class DomainTests(unittest.TestCase):
    def test_profile_suggests_buyers_from_offer_and_website(self):
        coffee = profile_offer('We build websites for coffee shops')
        self.assertEqual(coffee['offer_kind'], 'web_presence')
        self.assertEqual(coffee['suggested_categories'][:2], ['cafe', 'bakery'])
        self.assertFalse(coffee['model_used'])
        tender = profile_offer('Software that finds public tenders, deadlines and estimated contract values')
        self.assertEqual(tender['offer_kind'], 'general')
        self.assertIn('builder', tender['suggested_categories'])
        page = Page('https://seller.example/', b'', '<title>Tender alerts</title><meta name="description" content="Procurement bids for contractors"><script>secret()</script><p>Daily tenders</p>')
        site = profile_offer('Our product', page)
        self.assertEqual(site['website']['title'], 'Tender alerts')
        self.assertIn('tenders', site['keywords'])
        self.assertNotIn('secret', site['keywords'])

    def test_catalogue_covers_many_business_types_and_languages(self):
        self.assertGreaterEqual(len(CATALOGUE['items']), 500)
        self.assertIn('ur', CATALOGUE['languages'])
        ids = {item['id'] for item in CATALOGUE['items']}
        for wanted in ('office/estate_agent', 'craft/tailor', 'amenity/events_venue', 'amenity/school', 'shop/car_repair', 'healthcare/physiotherapist'):
            self.assertIn(wanted, ids)
        for street_furniture in ('amenity/bench', 'amenity/toilets', 'leisure/park', 'amenity/parking'):
            self.assertNotIn(street_furniture, ids)
        self.assertTrue(all(len(f) >= 1 for _, _, filters in CATEGORIES.values() for f in filters))

    def test_category_search_any_language(self):
        first = lambda q: search_categories(q)[0]['id']
        self.assertEqual(first('tailor'), 'craft/tailor')
        self.assertIn('amenity/events_venue', [i['id'] for i in search_categories('wedding hall')])
        self.assertIn('amenity/events_venue', [i['id'] for i in search_categories('weddings')])
        self.assertIn('office/estate_agent', [i['id'] for i in search_categories('مكتب عقاري')])
        self.assertIn('craft/tailor', [i['id'] for i in search_categories('خياط')])
        self.assertEqual(search_categories('x'), [])
        self.assertLessEqual(len(search_categories('shop')), 30)

    def test_offer_suggestions_use_catalogue_names_not_loose_words(self):
        spanish = profile_offer('Creamos páginas web para inmobiliarias y restaurantes')['suggested_categories']
        self.assertEqual(spanish, ['office/estate_agent', 'amenity/restaurant'])
        trades = profile_offer('Websites for car repair garages, plumbers and electricians')['suggested_categories']
        self.assertEqual(trades, ['car_services', 'craft/electrician', 'craft/plumber'])
        # "estate" alone is a synonym of other presets (notary); "store builder" describes the seller.
        estate = profile_offer('We build websites for real estate agents')['suggested_categories']
        self.assertEqual(estate, ['real_estate'])
        self.assertNotIn('builder', profile_offer('Online store builder for tailors')['suggested_categories'])
        # Dutch "coffee shop" is a cannabis shop; in English it is a coffeehouse.
        self.assertNotIn('shop/cannabis', profile_offer('Websites for coffee shops')['suggested_categories'])
        self.assertLessEqual(len(profile_offer('apps for ' + ', '.join(i['label'] for i in CATALOGUE['items'][:40]))['suggested_categories']), 12)

    def test_multi_tag_presets_query_and_match(self):
        query = overpass_query(('area', 1), ['amenity/doctors/cardiology', 'cafe'], None, 5)
        self.assertIn('nwr["amenity"="doctors"]["healthcare:speciality"="cardiology"]["name"](area.a);', query)
        tags = {'amenity': 'doctors', 'healthcare:speciality': 'cardiology', 'name': 'Heart Care'}
        self.assertEqual(category_of(tags, []), 'amenity/doctors/cardiology')  # the most specific match
        self.assertEqual(category_of({'amenity': 'cafe'}, ['cafe', 'amenity/cafe']), 'cafe')
        self.assertEqual(nominatim_filters(['amenity/doctors/cardiology', 'bakery']),
                         [('amenity', 'doctors'), ('shop', 'bakery'), ('shop', 'pastry')])
        base = {'offer': 'x' * 3, 'location': 'Town', 'use_public_osm': True}
        ProspectSearchInput(**base, categories=['office/estate_agent', 'real_estate'])
        with self.assertRaises(ValueError):
            ProspectSearchInput(**base, categories=['office/spaceport'])
        with self.assertRaises(ValueError):
            ProspectSearchInput(**base, categories=[i['id'] for i in CATALOGUE['items'][:13]])

    def test_query_is_bounded_and_rank_is_transparent(self):
        query = overpass_query(('area', 3600000042), ['cafe', 'bakery'], "Joe's", 10)
        self.assertIn('area(3600000042)->.a;', query)
        self.assertIn('nwr["shop"="pastry"]["name"~"Joe.s",i](area.a);', query)
        self.assertTrue(query.endswith('out center tags 30;'))
        around = overpass_query(('around', 31.5, 74.3, 3000), [], 'coffee', 5)
        self.assertIn('nwr["office"]["name"~"coffee",i](around:3000,31.5,74.3);', around)
        items, counts = rank(ELEMENTS, 'web_presence', ['cafe'], 10, 'stamp')
        self.assertEqual(counts, {'returned_elements': 4, 'unnamed_skipped': 1, 'kept': 2, 'over_limit': 0})
        first, second = items
        # No listed website counts as a possible need for a website offer, never as proof.
        self.assertEqual((first['name'], first['priority_points']), ('Fictional Bean', 3))
        self.assertIn('possible need', first['need_signals'][0])
        self.assertEqual(second['website'], 'https://fictional-brew.example')
        self.assertEqual(second['budget_signals'], ['Part of a brand or chain (Fictional Brew).'])
        self.assertIsNone(second['budget'])
        self.assertEqual(second['evidence']['url'], 'https://www.openstreetmap.org/way/2')
        general, _ = rank(ELEMENTS, 'general', ['cafe'], 1, 'stamp')
        self.assertEqual(general[0]['name'], 'Fictional Brew House')
        self.assertEqual(general[0]['need_signals'], [])


class ProspectingAPITests(APITestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.osm_calls, self.overpass_status = [], [200]

        def handler(request):
            self.osm_calls.append(request)
            if request.url.host == 'nominatim.openstreetmap.org':
                if 'viewbox' in request.url.params:
                    return httpx.Response(200, json=POIS)
                return httpx.Response(200, json=[] if 'Nowhere' in str(request.url) else PLACE)
            status = self.overpass_status.pop(0) if len(self.overpass_status) > 1 else self.overpass_status[0]
            return httpx.Response(status, json={'elements': ELEMENTS} if status == 200 else {})

        def fetcher(url):
            self.calls.append(url)
            return Page(url, SITE.encode(), SITE)

        await self.client.aclose()
        self.mx_calls = []
        def mx(domain):
            self.mx_calls.append(domain)
            return 'has_mx' if domain == 'fictional-brew.example' else 'no_domain'
        self.app = create_app(Settings(self.directory, TOKEN), fetcher=fetcher, osm_client=OSMClient(httpx.MockTransport(handler)), mx_lookup=mx)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://testserver',
                                        headers={'Authorization': f'Bearer {TOKEN}'})

    def body(self, **changes):
        return {'offer': 'We build websites for coffee shops', 'location': 'Fictional Town', 'categories': ['cafe'],
                'limit': 10, 'use_public_osm': True, **changes}

    async def search(self, key='search', status=200, **changes):
        response = await self.send('POST', '/v1/prospecting/searches', json=self.body(**changes), headers={'Idempotency-Key': key})
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    async def test_search_saves_ranked_candidates_with_evidence_and_replays(self):
        result = await self.search()
        self.assertEqual([c['name'] for c in result['candidates']], ['Fictional Bean', 'Fictional Brew House'])
        self.assertEqual(result['place']['country_code'], 'pk')
        bean, brew = result['candidates']
        self.assertEqual(bean['contact_analysis']['items'][0]['e164'], '+923000000001')
        self.assertIn('mobile number', bean['priority_reasons'])
        self.assertEqual(brew['contact_analysis']['items'][0]['quality'], 'good')
        self.assertIn('email domain can receive mail', brew['priority_reasons'])
        self.assertEqual(set(self.mx_calls), {'fictional-brew.example'})
        self.assertEqual(result['place']['display_name'], 'Fictional Town, Fictional Country')
        self.assertEqual(result['overpass_server'], 'https://overpass-api.de/api/interpreter')
        self.assertIn('area(3600000042)', result['query'])
        self.assertEqual(len(self.osm_calls), 2)
        self.assertEqual(self.osm_calls[0].headers['user-agent'], 'LeadDesk/0.1 (self-hosted local prospect research)')
        self.assertEqual((await self.search())['id'], result['id'])
        self.assertEqual(len(self.osm_calls), 2)
        await self.search(status=409, location='Other town')
        # Second search reuses the cached geocode (Nominatim policy) and runs only Overpass.
        await self.search(key='again')
        self.assertEqual([r.url.host for r in self.osm_calls[2:]], ['overpass-api.de'])
        listing = (await self.send('GET', '/v1/prospecting/searches')).json()
        self.assertEqual(listing['total'], 2)
        self.assertEqual((await self.send('GET', f"/v1/prospecting/searches/{result['id']}")).json()['candidates'][0]['check'], None)
        self.assertEqual(self.calls, [])

    async def test_busy_overpass_falls_back_to_bounded_nominatim(self):
        self.overpass_status = [502]
        result = await self.search()
        self.assertEqual(result['overpass_server'], 'nominatim (fallback: Overpass busy)')
        # Only results carrying the requested tag are kept; addresses are mapped.
        self.assertEqual([c['name'] for c in result['candidates']], ['Fictional Corner Cafe'])
        self.assertEqual(result['candidates'][0]['address'], 'Fictional Road, Fictional Town')
        self.assertIn('Nominatim', result['coverage'][-1])
        lookup = [r for r in self.osm_calls if 'viewbox' in r.url.params][0]
        self.assertEqual((lookup.url.params['q'], lookup.url.params['bounded']), ('cafe', '1'))
        self.assertEqual(lookup.url.params['viewbox'], '74.2,31.6,74.4,31.4')

    async def test_validation_and_consent(self):
        await self.search(key='consent', status=422, use_public_osm=False)
        await self.search(key='string-consent', status=422, use_public_osm='true')
        await self.search(key='empty', status=422, categories=[])
        await self.search(key='unknown', status=422, categories=['spaceships'])
        await self.search(key='inject', status=422, categories=[], name_keyword='x"];out;')
        await self.search(key="limit", status=422, limit=301)
        await self.search(key='nowhere', status=404, location='Nowhere at all')
        self.assertEqual((await self.send('POST', '/v1/prospecting/searches', json=self.body())).status_code, 422)
        response = await self.client.post('/v1/prospecting/searches', json=self.body(), headers={'Authorization': 'Bearer wrong', 'Idempotency-Key': 'auth'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.osm_calls[-1].url.host, 'nominatim.openstreetmap.org')

    async def test_profile_reads_own_website(self):
        response = await self.send('POST', '/v1/prospecting/profile', json={'offer': 'Coffee shop websites', 'website': 'https://fictional-brew.example/'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['website']['title'], 'Fictional Brew House')
        self.assertEqual(self.calls, ['https://fictional-brew.example/'])
        self.assertEqual((await self.send('POST', '/v1/prospecting/profile', json={'offer': 'x', 'website': 'http://127.0.0.1/'})).status_code, 422)
        categories = (await self.send('GET', '/v1/prospecting/categories')).json()['items']
        listing = (await self.send('GET', '/v1/prospecting/categories')).json()
        self.assertIn({'id': 'cafe', 'label': 'Cafés and coffee shops', 'group': 'Food and drink', 'source': 'curated', 'osm_tags': ['amenity=cafe']}, categories)
        self.assertIn({'id': 'amenity/doctors/cardiology', 'label': 'Cardiologist', 'group': 'Health', 'source': 'osm_preset',
                       'osm_tags': ['amenity=doctors + healthcare:speciality=cardiology']}, categories)
        self.assertEqual((listing['max_selected'], listing['catalogue']['licence']), (12, 'ISC'))
        found = (await self.send('GET', '/v1/prospecting/categories/search?q=inmobiliaria')).json()['items']
        self.assertEqual([i['id'] for i in found][:2], ['real_estate', 'office/property_management'])
        self.assertEqual((await self.send('GET', '/v1/prospecting/categories/search?q=' + 'x' * 61)).status_code, 422)

    async def test_website_check_runs_research_and_links_result(self):
        result = await self.search()
        bean, brew = result['candidates']
        base = f"/v1/prospecting/searches/{result['id']}/candidates"
        response = await self.send('POST', f"{base}/{bean['id']}/check", headers={'Idempotency-Key': 'check-bean'})
        self.assertEqual(response.status_code, 409)
        response = await self.send('POST', f"{base}/{brew['id']}/check", headers={'Idempotency-Key': 'check-brew'})
        self.assertEqual(response.status_code, 200, response.text)
        check = response.json()
        self.assertEqual(self.calls, ['https://fictional-brew.example/'])
        self.assertEqual(check['research']['contacts'][0]['raw_value'], 'hello@fictional-brew.example')
        self.assertIn('coffee', check['check']['offer_keywords_found'])
        self.assertEqual(check['check']['contact_analysis'][0]['matches_website'], True)
        saved = (await self.send('GET', f"/v1/prospecting/searches/{result['id']}")).json()
        self.assertEqual(saved['candidates'][1]['check']['research_id'], check['research']['id'])
        self.assertEqual((await self.send('POST', f"{base}/node/999/check", headers={'Idempotency-Key': 'missing'})).status_code, 404)
        self.assertEqual((await self.send('DELETE', f"/v1/prospecting/searches/{result['id']}")).json()['research_preserved'], True)
        self.assertEqual((await self.send('GET', f"/v1/research/{check['research']['id']}")).status_code, 200)
        self.assertEqual((await self.send('GET', f"/v1/prospecting/searches/{result['id']}")).status_code, 404)


if __name__ == '__main__':
    unittest.main()
