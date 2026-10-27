"""Overture Maps places: category mapping, merge with OSM, website status, opportunity score and the search API.

No network: the client reads a local fixture Parquet file written with DuckDB in the Overture schema shape.
"""
import tempfile
import unittest
from pathlib import Path

import httpx

from backend.adapters import overture as overture_module
from backend.adapters.osm import OSMClient
from backend.adapters.overture import OvertureClient, window
from backend.api.app import create_app
from backend.domain.places import (category_matches, from_overture, merge, opportunity, overture_terms, pitch_line,
                                   website_status)
from backend.settings import Settings
from tests import test_prospecting as fixtures
from tests.support import TOKEN


def row(ident, name, category, basic=None, lat=31.5, lon=74.3, **extra):
    return {'id': ident, 'name': name, 'category': category, 'basic_category': basic or category, 'hierarchy': [],
            'confidence': 0.9, 'operating_status': None, 'websites': [], 'phones': [], 'emails': [], 'socials': [],
            'address': None, 'brand': None, 'datasets': ['meta'], 'lat': lat, 'lon': lon} | extra


ROWS = [
    row('a1', 'Hyde Park Realty', 'real_estate_agent', 'real_estate_service', phones=['+924235770048'],
        emails=['info@hydepark.example'], websites=['http://hydepark.example/'], socials=['https://www.facebook.com/123']),
    row('a2', 'Garden Homes', 'home_developer', 'real_estate_service', websites=['https://www.facebook.com/gardenhomes']),
    row('a3', 'Smile Dental', 'dental_clinic', 'dental_clinic', phones=['+923001112223']),
    row('a4', 'Closed Estates', 'real_estate_agent', operating_status='permanently_closed'),
    row('a5', 'Maybe Estates', 'real_estate_agent', confidence=0.2),
    row('a6', 'Fictional Bean', 'cafe', phones=['+92 300 0000001'], emails=['bean@fictional.example'], lat=31.5, lon=74.3),
    row('a7', 'Health Shop', 'health_food_store'),
]


class MappingTests(unittest.TestCase):
    def test_business_types_map_to_overture_categories(self):
        estate = overture_terms(['office/estate_agent'])
        self.assertEqual(category_matches(ROWS[0], estate), 'real_estate_agent')  # exact match first
        self.assertEqual(category_matches(ROWS[1], estate), 'real_estate')
        self.assertIsNone(category_matches(ROWS[2], estate))
        # Vocabulary bridge: OSM "dentist" is Overture "dental_clinic".
        self.assertEqual(category_matches(ROWS[2], overture_terms(['dentist'])), 'dental')
        # Single-word synonyms ("health" for gyms) only match exactly, so a health-food store is not a gym.
        self.assertIsNone(category_matches(ROWS[6], overture_terms(['fitness'])))
        self.assertEqual(category_matches(row('g', 'Iron Gym', 'gym'), overture_terms(['fitness'])), 'gym')

    def test_candidates_skip_closed_and_low_confidence(self):
        items, counts = from_overture(ROWS, '2026-10-21.0', ['real_estate'], None)
        self.assertEqual([i['name'] for i in items], ['Hyde Park Realty', 'Garden Homes'])
        self.assertEqual(counts, {'overture_matched': 2, 'overture_closed_skipped': 1, 'overture_low_confidence_skipped': 1,
                                  'overture_duplicates_merged': 0})
        hyde, garden = items
        self.assertEqual((hyde['id'], hyde['phone'], hyde['email'], hyde['website']),
                         ('overture/a1', '+924235770048', 'info@hydepark.example', 'http://hydepark.example/'))
        self.assertEqual(hyde['evidence']['record_id'], 'a1')
        self.assertEqual(hyde['evidence']['release'], '2026-10-21.0')
        self.assertIn('CDLA', hyde['evidence']['licence'])
        self.assertTrue(garden['website_is_social'])
        named, _ = from_overture(ROWS, 'r', [], 'dental')
        self.assertEqual([i['name'] for i in named], ['Smile Dental'])

    def test_near_duplicates_from_different_sources_are_merged(self):
        twins = [row('d1', 'Elmaphue Medical and Dental Clinic', 'dental_clinic', phones=['+254700000001'], confidence=0.8),
                 row('d2', 'Elmaphus Medical and Dental Clinic', 'dental_clinic', emails=['elma@clinic.example'], lat=31.5004, confidence=0.7),
                 row('d3', 'Other Dental', 'dental_clinic', phones=['+254 700 000001'], lat=31.501, confidence=0.6),
                 row('d4', 'Smile Dental Studio', 'dental_clinic', lat=31.5005, confidence=0.5)]
        items, counts = from_overture(twins, 'r', ['dentist'], None)
        self.assertEqual(counts['overture_duplicates_merged'], 2)  # near-identical name nearby; same phone
        first = items[0]
        self.assertEqual((first['name'], first['email'], first['evidence']['duplicates']),
                         ('Elmaphue Medical and Dental Clinic', 'elma@clinic.example', ['d2', 'd3']))
        self.assertEqual([i['name'] for i in items][1:], ['Smile Dental Studio'])

    def test_merge_fills_missing_osm_fields_with_their_source(self):
        osm, _ = fixtures.rank(fixtures.ELEMENTS, 'web_presence', ['cafe'], 10, 'stamp')
        extra, _ = from_overture(ROWS, 'r', ['cafe'], None)
        merged, counts = merge(osm, extra)
        self.assertEqual(counts, {'merged_same_business': 1})
        bean = next(m for m in merged if m['name'] == 'Fictional Bean')
        self.assertEqual(bean['sources'], ['OpenStreetMap', 'Overture Maps'])
        self.assertEqual((bean['email'], bean['field_sources']), ('bean@fictional.example', {'email': 'Overture Maps'}))
        self.assertEqual(bean['phone'], '+92 300 0000001')  # OSM value kept
        self.assertEqual(len(merged), 2)
        # Same name far away is a different branch or business: not merged.
        far = [dict(extra[0], lat=31.6, phone=None, id='overture/far')]
        self.assertEqual(merge(osm, far)[1], {'merged_same_business': 0})


class ScoreTests(unittest.TestCase):
    def test_website_status_and_opportunity(self):
        base = {'name': 'X Realty', 'website': None, 'websites': [], 'phones': [], 'phone': None, 'email': None}
        cases = [({}, 'none', 80), ({'website': 'https://www.instagram.com/x'}, 'social_only', 75),
                 ({'website': 'https://x.business.site/'}, 'dead_builder', 70), ({'website': 'https://x.wixsite.com/home'}, 'free_subdomain', 50),
                 ({'website': 'https://x.example/'}, 'unchecked', 0)]
        for change, status, points in cases:
            value = opportunity(base | change, 'web_presence')
            self.assertEqual((value['website_status'], value['score']), (status, points), change)
        reachable = opportunity(base | {'phone': '+92300', 'email': 'a@b.example', 'socials': ['https://facebook.com/x']}, 'web_presence')
        self.assertEqual((reachable['score'], reachable['band']), (100, 'hot'))
        self.assertEqual(reachable['reasons'], ['+80 No website listed in the map sources.', '+10 phone number known (not verified)',
                                                '+5 email known (not verified)', '+5 social profile known'])
        self.assertEqual(opportunity(base, 'general')['score'], 0)  # no website is not a need for non-web offers
        down = base | {'website': 'https://x.example/', 'check': {'unreachable': True, 'checked_at': '2026-10-24T00:00'}}
        self.assertEqual(website_status(down, down['check'])[0], 'unreachable')
        health = {'score': 40, 'grade': 'D', 'issues': [{'plain': 'it is not secure (no HTTPS)'}]}
        checked = base | {'website': 'https://x.example/', 'check': {'site': {}}}
        self.assertEqual(opportunity(checked, 'web_presence', health)['score'], 42)
        self.assertEqual(pitch_line(checked, None, 'ok', health), "X Realty's website: it is not secure (no HTTPS).")
        self.assertIsNone(pitch_line(checked, None, 'ok', None))


class ClientTests(unittest.TestCase):
    def test_window_clamps_large_areas(self):
        self.assertEqual(window(31.0, 32.0, 74.0, 75.0), (31.35, 31.65, 74.35, 74.65))
        south, north, west, east = window(31.5, 31.5, 74.3, 74.3)
        self.assertAlmostEqual(north - south, 0.03, places=3)

    def test_catalogue_picks_only_files_covering_the_area(self):
        base = 'https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/release/r1/theme=places/type=place/'
        items = {'a': {'bbox': [60, 20, 80, 40], 'assets': {'aws': {'href': base + 'part-1.zstd.parquet'}}},
                 'b': {'bbox': [-10, 40, 5, 60], 'assets': {'aws': {'href': base + 'part-2.zstd.parquet'}}}}

        def answer(request):
            if request.url.path.endswith('collection.json'):
                return httpx.Response(200, json={'links': [{'rel': 'item', 'href': f'https://stac.example/{k}.json'} for k in items]})
            return httpx.Response(200, json=items[request.url.path.strip('/').removesuffix('.json')])
        with tempfile.TemporaryDirectory() as folder:
            client = OvertureClient(Path(folder), http=httpx.Client(transport=httpx.MockTransport(answer)))
            self.assertEqual(client.sources('r1', (31.4, 31.6, 74.2, 74.4)), (f"['{base}part-1.zstd.parquet']", '1 of 2 files'))
            self.assertTrue((Path(folder) / 'r1' / 'files.json').exists())
            items['a']['assets']['aws']['href'] = base + "x.parquet') ; DROP"
            evil = OvertureClient(Path(folder) / 'other', http=httpx.Client(transport=httpx.MockTransport(answer)))
            self.assertIsNone(evil.files('r1'))  # anything unexpected falls back to the fixed release glob

    def test_area_reads_release_and_caches_locally(self):
        import duckdb
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'places.parquet'
            duckdb.sql(f"""COPY (SELECT * FROM (VALUES
                ('a1', {{'primary': 'Hyde Park Realty'}}, 'real_estate_service', {{'primary': 'real_estate_agent', 'hierarchy': ['services_and_business', 'real_estate_service', 'real_estate_agent']}},
                 0.9, NULL, ['http://hydepark.example/'], ['+924235770048'], ['info@hydepark.example'], ['https://www.facebook.com/1'],
                 [{{'freeform': '19-E Gulberg', 'locality': 'Lahore', 'country': 'PK'}}], {{'names': {{'primary': NULL}}}},
                 [{{'dataset': 'meta', 'update_time': '2025-03-01T00:00:00Z'}}], {{'xmin': 74.3, 'xmax': 74.3, 'ymin': 31.5, 'ymax': 31.5}}),
                ('far', {{'primary': 'Elsewhere'}}, 'cafe', {{'primary': 'cafe', 'hierarchy': ['food_and_drink', 'cafe']}},
                 0.9, NULL, [], [], [], [], [], {{'names': {{'primary': NULL}}}}, [{{'dataset': 'meta', 'update_time': NULL}}],
                 {{'xmin': 10.0, 'xmax': 10.0, 'ymin': 10.0, 'ymax': 10.0}})
                ) t(id, names, basic_category, taxonomy, confidence, operating_status, websites, phones, emails, socials, addresses, brand, sources, bbox))
                TO '{source}' (FORMAT parquet)""")
            original = overture_module.BUCKET
            overture_module.BUCKET = str(source) + '?{release}'.replace('?{release}', '')
            stac = httpx.MockTransport(lambda request: httpx.Response(200, json={'latest': '2099-01-01.0'}))
            client = OvertureClient(Path(folder) / 'cache', connect=duckdb.connect, http=httpx.Client(transport=stac))
            try:
                rows, meta = client.area(31.49, 31.51, 74.29, 74.31)
                again, cached = client.area(31.49, 31.51, 74.29, 74.31)
            finally:
                overture_module.BUCKET = original
                client.close()
        self.assertEqual([r['name'] for r in rows], ['Hyde Park Realty'])
        self.assertEqual((rows[0]['category'], rows[0]['address'], rows[0]['datasets']), ('real_estate_agent', '19-E Gulberg', ['meta']))
        self.assertTrue(str(rows[0]['updated']).startswith('2025-03-01'))
        self.assertEqual((meta['release'], meta['cached'], cached['cached']), ('2099-01-01.0', False, True))
        self.assertEqual(again, rows)


class FakeOverture:
    def __init__(self):
        self.calls = []

    def area(self, south, north, west, east):
        self.calls.append((south, north, west, east))
        return ROWS, {'release': '2026-10-21.0', 'box': {'south': 31.4, 'north': 31.6, 'west': 74.2, 'east': 74.4},
                      'cached': False, 'seconds': 1.0, 'rows': len(ROWS), 'truncated': False}


class OvertureAPITests(fixtures.ProspectingAPITests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.client.aclose()
        self.overture = FakeOverture()
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=fixtures.PLACE)
                                        if request.url.host == 'nominatim.openstreetmap.org' else httpx.Response(502, json={}))
        self.app = create_app(Settings(self.directory, TOKEN), fetcher=lambda url: fixtures.Page(url, b'', fixtures.SITE),
                              osm_client=OSMClient(transport), mx_lookup=lambda d: 'has_mx', overture_client=self.overture)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://testserver',
                                        headers={'Authorization': f'Bearer {TOKEN}'})

    async def test_overture_search_ranks_by_opportunity(self):
        result = await self.search(categories=['real_estate'], use_overture=True, offer='We build websites for real estate agents')
        self.assertEqual(self.overture.calls, [(31.4, 31.6, 74.2, 74.4)])
        names = [c['name'] for c in result['candidates']]
        # Social-only website (75) ranks above a business with its own unchecked site (contacts only).
        self.assertEqual(names, ['Garden Homes', 'Hyde Park Realty'])
        self.assertEqual(result['candidates'][0]['opportunity']['website_status'], 'social_only')
        self.assertEqual(result['sources']['overture']['businesses'], 2)
        self.assertEqual(result['method'], 'osm_overture_v2')
        self.assertTrue(any('Overture Maps release 2026-10-21.0' in note for note in result['coverage']))
        saved = await self.send('GET', f"/v1/prospecting/searches/{result['id']}")
        self.assertEqual(saved.json()['candidates'][0]['pitch'][:12], 'Garden Homes')
        hyde = saved.json()['candidates'][1]
        self.assertEqual(hyde['contact_analysis']['items'][0]['type'], 'email')

    async def test_overture_needs_consent_and_osm_stays_optional(self):
        result = await self.search(categories=['dentist'], key='osm-only')
        self.assertEqual(self.overture.calls, [])
        self.assertNotIn('overture', result['sources'])


for name in [n for n in vars(fixtures.ProspectingAPITests) if n.startswith('test_')]:
    setattr(OvertureAPITests, name, None)

if __name__ == '__main__':
    unittest.main()
