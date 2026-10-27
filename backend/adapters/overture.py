"""Overture Maps places (free, CDLA-Permissive-2.0 with per-source licences) read with DuckDB.

The public GeoParquet release on Amazon S3 is read anonymously, filtered to one
bounding box, and the area is cached locally as Parquet so later searches in the
same area run offline. Only called on an explicit, consented user request.
"""
import hashlib
import re
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from backend.domain.errors import ResearchError

STAC = 'https://stac.overturemaps.org/catalog.json'
COLLECTION = 'https://stac.overturemaps.org/{release}/places/place/collection.json'
FALLBACK_RELEASE = '2026-10-21.0'
BUCKET = 's3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*'
FILE_HOST = 'https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/release/'
MAX_SPAN = 0.30  # degrees per side (~33 km); larger areas are cut to a window around their centre
MAX_ROWS = 60_000
COLUMNS = '''id, names.primary AS name, basic_category, taxonomy.primary AS category, taxonomy.hierarchy AS hierarchy,
  confidence, operating_status, websites, phones, emails, socials, addresses[1].freeform AS address,
  addresses[1].locality AS locality, addresses[1].country AS country, brand.names.primary AS brand,
  list_distinct([s.dataset FOR s IN sources]) AS datasets, list_max([s.update_time FOR s IN sources]) AS updated,
  bbox.xmin AS lon, bbox.ymin AS lat'''


def window(south, north, west, east):
    """Clamp an area to MAX_SPAN per side around its centre; round so nearby searches share a cache."""
    lat, lon = (south + north) / 2, (west + east) / 2
    half_lat, half_lon = min(north - south, MAX_SPAN) / 2, min(east - west, MAX_SPAN) / 2
    half_lat, half_lon = max(half_lat, 0.015), max(half_lon, 0.015)  # at least ~3 km across
    r = lambda v: round(v, 3)
    return r(lat - half_lat), r(lat + half_lat), r(lon - half_lon), r(lon + half_lon)


class OvertureClient:
    def __init__(self, cache_dir: Path, connect=None, http: httpx.Client | None = None):
        self.cache_dir = Path(cache_dir)
        self._connect = connect
        self.http = http or httpx.Client(trust_env=False, follow_redirects=False, timeout=httpx.Timeout(15, connect=5))
        self.lock = threading.Lock()
        self.con = None
        self._release = None

    def connection(self):
        if self.con is None:
            if self._connect is not None:
                self.con = self._connect()
            else:
                try:
                    import duckdb
                except ImportError:
                    raise ResearchError('Overture needs the duckdb package. Run ./scripts/setup.sh again.', status=503) from None
                self.con = duckdb.connect()
                self.con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2'; "
                                 "SET enable_http_metadata_cache=true; SET parquet_metadata_cache=true;")
        return self.con

    def release(self):
        """Latest release from the official STAC catalogue, re-checked at most daily; a pinned fallback otherwise."""
        if self._release and time.time() - self._release[1] < 86400:
            return self._release[0]
        value = FALLBACK_RELEASE
        try:
            response = self.http.get(STAC)
            latest = response.json().get('latest') if response.status_code == 200 else None
            if isinstance(latest, str) and len(latest) < 20 and latest.replace('-', '').replace('.', '').isdigit():
                value = latest
        except (httpx.HTTPError, ValueError):
            pass
        self._release = (value, time.time())
        return value

    def files(self, release):
        """The release's place files with their bounding boxes, from the STAC catalogue (cached on disk per release).

        Reading only the file(s) covering the search area avoids downloading every file's index: about 9 s instead of
        two minutes on a slow link. Falls back to the whole-release glob if the catalogue cannot be read.
        """
        path = self.cache_dir / release / 'files.json'
        if path.exists():
            return json.loads(path.read_text())
        try:
            links = [l['href'] for l in self.http.get(COLLECTION.format(release=release)).json()['links'] if l.get('rel') == 'item']
            with ThreadPoolExecutor(max_workers=8) as pool:
                items = list(pool.map(lambda url: self.http.get(url).json(), links[:64]))
            files = [{'bbox': [float(v) for v in item['bbox']], 'href': item['assets']['aws']['href']} for item in items]
            safe = re.compile(re.escape(FILE_HOST + release + '/') + r'[A-Za-z0-9=_./-]+\.parquet')
            if not files or not all(safe.fullmatch(f['href']) for f in files):
                return None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(files))
        return files

    def sources(self, release, box):
        south, north, west, east = box
        files = self.files(release)
        if files is None:
            return f"'{BUCKET.format(release=release)}'", 'all files (catalogue unavailable)'
        hits = [f['href'] for f in files if f['bbox'][0] <= east and f['bbox'][2] >= west and f['bbox'][1] <= north and f['bbox'][3] >= south]
        return '[' + ', '.join(f"'{h}'" for h in hits) + ']', f'{len(hits)} of {len(files)} files'

    def cache_path(self, release, box):
        digest = hashlib.sha256(json.dumps([release, box, COLUMNS]).encode()).hexdigest()[:20]  # new columns -> new cache
        return self.cache_dir / release / f'{digest}.parquet'

    def area(self, south, north, west, east):
        """All places in the (clamped) box, from cache when available. Returns (rows, meta)."""
        box = window(south, north, west, east)
        with self.lock:
            release = self.release()
            path = self.cache_path(release, box)
            con = self.connection()
            started, cached, read = time.monotonic(), path.exists(), 'local cache'
            if not cached:
                path.parent.mkdir(parents=True, exist_ok=True)
                s, n, w, e = box
                temp = path.with_suffix('.tmp')
                source, read = self.sources(release, box)
                if source == '[]':
                    con.execute(f"COPY (SELECT NULL::VARCHAR AS id LIMIT 0) TO '{temp}' (FORMAT parquet)")
                    temp.replace(path)
                    source = None
                try:
                    if source:
                        con.execute(f"COPY (SELECT {COLUMNS} FROM read_parquet({source}, hive_partitioning=0) "
                                    f"WHERE bbox.xmin BETWEEN {w} AND {e} AND bbox.ymin BETWEEN {s} AND {n} LIMIT {MAX_ROWS}) "
                                    f"TO '{temp}' (FORMAT parquet)")
                except Exception as error:  # duckdb raises its own IO/HTTP exception types
                    temp.unlink(missing_ok=True)
                    raise ResearchError(f'Overture Maps could not be read ({type(error).__name__}). Check your internet connection and retry.',
                                        retryable=True, status=502) from None
                if source:
                    temp.replace(path)
            cursor = con.execute(f"SELECT * FROM read_parquet('{path}')")
            names = [d[0] for d in cursor.description]
            rows = [dict(zip(names, row)) for row in cursor.fetchall() if row[0] is not None]
        return rows, {'release': release, 'files_read': None if cached else read, 'box': {'south': box[0], 'north': box[1], 'west': box[2], 'east': box[3]},
                      'cached': cached, 'seconds': round(time.monotonic() - started, 1), 'rows': len(rows),
                      'truncated': len(rows) >= MAX_ROWS}

    def close(self):
        if self.con is not None:
            self.con.close()
