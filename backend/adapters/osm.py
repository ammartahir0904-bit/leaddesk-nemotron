"""Public OpenStreetMap lookups: Nominatim geocoding and Overpass business queries.

Fixed hosts only (no user-supplied URLs), no proxies or redirects, bounded
responses, an identifying User-Agent and at most one Nominatim call per second,
following the services' usage policies. Called only on an explicit user request.
"""
import json
import threading
import time

import httpx

from backend.domain.errors import ResearchError

NOMINATIM = 'https://nominatim.openstreetmap.org/search'
# The main Overpass instance answers quickly (502) when full. Public mirrors were
# too slow in testing, so a failure falls back to per-type Nominatim searches.
OVERPASS = ('https://overpass-api.de/api/interpreter',)
OVERPASS_SECONDS = 30
NOMINATIM_MAX_QUERIES = 12
USER_AGENT = 'LeadDesk/0.1 (self-hosted local prospect research)'
MAX_BYTES = 8_000_000


class OSMClient:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(trust_env=False, follow_redirects=False, transport=transport,
                                   headers={'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Accept-Language': 'en'},
                                   timeout=httpx.Timeout(75, connect=8))
        self.lock = threading.Lock()
        self.last_geocode = 0.0
        self.requests = 0

    def close(self):
        self.client.close()

    def _json(self, method, url, **kwargs):
        self.requests += 1
        try:
            with self.client.stream(method, url, **kwargs) as response:
                if response.status_code == 429:
                    raise ResearchError('OpenStreetMap is rate-limiting requests. Wait a minute and retry.', retryable=True, status=429)
                if response.status_code in {504, 503}:
                    raise ResearchError('OpenStreetMap search timed out. Try a smaller area or fewer business types.', retryable=True, status=504)
                if response.status_code != 200:
                    raise ResearchError(f'OpenStreetMap returned HTTP {response.status_code}. Retry later.', retryable=True, status=502)
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise ResearchError('OpenStreetMap returned too much data. Use a smaller area or fewer business types.', status=413)
            return json.loads(body)
        except httpx.HTTPError:
            raise ResearchError('OpenStreetMap could not be reached. Check your internet connection and retry.', retryable=True, status=502) from None
        except ValueError:
            raise ResearchError('OpenStreetMap returned malformed data. Retry later.', retryable=True, status=502) from None

    def _nominatim(self, params):
        # Usage policy: at most one request per second from this client.
        with self.lock:
            wait = 1.1 - (time.monotonic() - self.last_geocode)
            if wait > 0:
                time.sleep(wait)
            try:
                return self._json('GET', NOMINATIM, params={'format': 'jsonv2'} | params)
            finally:
                self.last_geocode = time.monotonic()

    def geocode(self, location):
        rows = self._nominatim({'q': location, 'limit': 1, 'addressdetails': 1})
        if not isinstance(rows, list) or not rows:
            raise ResearchError('That location was not found on OpenStreetMap. Try "area, city, country".', status=404)
        row = rows[0]
        return {'display_name': str(row.get('display_name', ''))[:300], 'osm_type': row.get('osm_type'),
                'osm_id': int(row['osm_id']), 'lat': float(row['lat']), 'lon': float(row['lon']),
                'boundingbox': [float(v) for v in row.get('boundingbox', [])][:4],
                'country_code': str((row.get('address') or {}).get('country_code') or '').casefold() or None}

    def overpass(self, query):
        """Returns (elements, server). Falls back only on retryable failures."""
        error = None
        for server in OVERPASS:
            try:
                value = self._json('POST', server, data={'data': query}, timeout=httpx.Timeout(OVERPASS_SECONDS, connect=8))
            except ResearchError as failure:
                if not failure.retryable:
                    raise
                error = failure
                continue
            if not isinstance(value, dict) or not isinstance(value.get('elements'), list):
                error = ResearchError('OpenStreetMap returned malformed data. Retry later.', retryable=True, status=502)
                continue
            if 'runtime error' in str(value.get('remark', '')).casefold():
                error = ResearchError('OpenStreetMap search timed out. Try a smaller area or fewer business types.', retryable=True, status=504)
                continue
            return value['elements'], server
        raise error

    def nominatim_places(self, place, filters, name_keyword, limit):
        """Fallback: one bounded Nominatim search per (key, value) filter, max 40 each."""
        south, north, west, east = place['boundingbox'] or [place['lat']] * 2 + [place['lon']] * 2
        pad = 0.027  # ~3 km; points and tiny boxes get a usable search window
        if north - south < 2 * pad:
            south, north = min(south, place['lat'] - pad), max(north, place['lat'] + pad)
        if east - west < 2 * pad:
            west, east = min(west, place['lon'] - pad), max(east, place['lon'] + pad)
        box = f'{west},{north},{east},{south}'
        elements, seen = [], set()
        for key, value in filters[:NOMINATIM_MAX_QUERIES]:
            text = name_keyword if name_keyword and value is None else ' '.join(filter(None, [name_keyword, (value or '').replace('_', ' ')]))
            rows = self._nominatim({'q': text, 'limit': min(40, limit * 2), 'extratags': 1, 'addressdetails': 1,
                                    'viewbox': box, 'bounded': 1})
            for row in rows if isinstance(rows, list) else []:
                category, kind = row.get('category'), row.get('type')
                # Keep only results that really carry the requested tag.
                if category != key or (value is not None and kind != value):
                    continue
                if name_keyword and name_keyword.casefold() not in str(row.get('name', '')).casefold():
                    continue
                ident = (row.get('osm_type'), row.get('osm_id'))
                if ident in seen:
                    continue
                seen.add(ident)
                address = row.get('address') or {}
                tags = {k: str(v) for k, v in (row.get('extratags') or {}).items()} | {category: kind, 'name': row.get('name') or ''}
                for source, target in (('house_number', 'addr:housenumber'), ('road', 'addr:street'), ('suburb', 'addr:suburb'),
                                       ('city', 'addr:city'), ('postcode', 'addr:postcode')):
                    if address.get(source):
                        tags[target] = str(address[source])
                elements.append({'type': row.get('osm_type'), 'id': row.get('osm_id'), 'lat': float(row['lat']),
                                 'lon': float(row['lon']), 'tags': tags})
        return elements


def search_area(place):
    """Named areas (relations/ways) search inside the boundary; points search 3 km around."""
    if place['osm_type'] == 'relation':
        return ('area', 3_600_000_000 + place['osm_id'])
    if place['osm_type'] == 'way':
        return ('area', 2_400_000_000 + place['osm_id'])
    return ('around', place['lat'], place['lon'], 3000)
