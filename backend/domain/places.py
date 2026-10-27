"""Overture places → prospect candidates, merged with OpenStreetMap, plus website status and opportunity score.

Deterministic. Business types chosen from the OSM-based catalogue are matched to
Overture's category taxonomy by their English names and tag values. A merged
business keeps which source supplied each field. Scores are transparent points
(published weights, every reason listed), never a probability of buying.
"""
import math
import re
from difflib import SequenceMatcher
from urllib.parse import urlsplit

from backend.domain.enrichment import classify, fold, host, name_match
from backend.domain.prospecting import BUSINESS_KEYS, CATALOGUE, CATEGORIES, SELLER_WORDS, STOPWORDS

OVERTURE_LICENCE = 'CDLA-Permissive-2.0 (Overture Maps Foundation; some sources CC0 or Apache-2.0)'
# Taxonomy words too broad to pick a business type on their own.
BROAD = SELLER_WORDS | STOPWORDS | {'store', 'shop', 'service', 'center', 'centre', 'place', 'food', 'drink', 'house', 'room',
                                    'goods', 'supply', 'supplies', 'repair', 'rental', 'school', 'club', 'hall', 'studio', 'point'}
ITEMS = {item['id']: item for item in CATALOGUE['items']}
# OSM tag value -> Overture category words where the two vocabularies name the same business differently.
BRIDGE = {
    'dentist': ['dental', 'dentistry'], 'doctors': ['doctor', 'doctors_office', 'medical_center'], 'clinic': ['clinic', 'medical_center'],
    'lawyer': ['attorney', 'law_firm', 'legal_service', 'lawyer'], 'accountant': ['accountant', 'accounting', 'tax_service', 'bookkeeping'],
    'tax_advisor': ['tax_service', 'tax_advisor'], 'car_repair': ['automotive_repair', 'auto_repair', 'auto_body', 'automotive_service'],
    'car': ['car_dealer', 'automotive_dealer'], 'car_wash': ['car_wash', 'auto_detailing'], 'car_rental': ['car_rental'],
    'events_venue': ['event_venue', 'venue_and_event_space', 'banquet_hall', 'wedding_venue', 'party_and_event_planning'], 'hairdresser': ['hair_salon', 'barber'],
    'beauty': ['beauty_salon', 'nail_salon'], 'fitness_centre': ['gym', 'fitness', 'yoga', 'pilates'], 'estate_agent': ['real_estate'],
    'travel_agency': ['travel_agent', 'travel_service'], 'travel_agent': ['travel_agent', 'travel_service'], 'insurance': ['insurance'],
    'it': ['it_service', 'software_development', 'information_technology', 'web_design'], 'architect': ['architect'],
    'school': ['high_school', 'elementary_school', 'middle_school', 'private_school', 'school'], 'college': ['college'],
    'university': ['college_university', 'university'], 'kindergarten': ['preschool', 'kindergarten', 'day_care', 'child_care'],
    'childcare': ['day_care', 'child_care'], 'pharmacy': ['pharmacy', 'drugstore'], 'veterinary': ['veterinarian', 'animal_hospital'],
    'supermarket': ['supermarket', 'grocery'], 'convenience': ['convenience_store'], 'greengrocer': ['grocery', 'fruit_and_vegetable'],
    'clothes': ['clothing', 'fashion_boutique'], 'boutique': ['fashion_boutique'], 'shoes': ['shoe_store'], 'jewelry': ['jewelry'],
    'mobile_phone': ['mobile_phone'], 'computer': ['computer_store'], 'hardware': ['hardware_store'], 'florist': ['florist', 'flower'],
    'butcher': ['butcher', 'meat_shop'], 'bar': ['bar', 'lounge'], 'guest_house': ['guest_house', 'bed_and_breakfast'],
    'builder': ['building_or_construction_service', 'construction_service', 'general_contractor', 'home_developer'],
    'construction_company': ['building_or_construction_service', 'construction_service', 'general_contractor'],
    'plumber': ['plumbing'], 'hvac': ['hvac', 'heating_and_air_conditioning'], 'carpenter': ['carpentry'],
    'tailor': ['tailor', 'sewing_and_alterations'], 'photographer': ['photography'], 'company': ['corporate_or_business_office'],
    'ngo': ['non_profit', 'charity'], 'association': ['non_profit', 'association'], 'interior_decoration': ['interior_design'],
    'optician': ['optometrist', 'eyewear'], 'driving_school': ['driving_school'], 'language_school': ['language_school'],
}


def snake(text):
    return '_'.join(re.findall(r'[a-z0-9]+', text.casefold()))


def overture_terms(categories):
    """Overture category words for the chosen types -> 'strong' or 'exact'.

    Strong (may match a more specific Overture category by prefix/suffix): the English name, the OSM tag value and
    multi-word synonyms. Single-word synonyms ("health", "garage") only match an Overture category exactly.
    """
    terms = {}
    for key in categories:
        items = [ITEMS[key]] if key in ITEMS else [
            item for item in CATALOGUE['items'] if len(item['tags']) == 1 and next(iter(item['tags'].items())) in
            [next(iter(f.items())) for f in CATEGORIES[key][2]]]
        for item in items:
            values = [v for k, v in item['tags'].items() if k in BUSINESS_KEYS]
            strong = [item['english'][0]] + values + [w for w in item['english'][1:] if ' ' in w.strip()] + \
                [b for v in values for b in BRIDGE.get(v, [])]
            for word, kind in [(w, 'strong') for w in strong] + [(w, 'exact') for w in item['english'][1:] if ' ' not in w.strip()]:
                value = snake(word)
                if len(value) >= 3 and value not in BROAD and terms.get(value) != 'strong':
                    terms[value] = kind
    return terms


def category_matches(row, terms):
    """The matching term, or None. Hierarchy entries must match exactly."""
    values = [v for v in (row.get('category'), row.get('basic_category')) if v]
    for value in values:
        if value in terms:
            return value
    for value in values:
        for term, kind in terms.items():
            if kind == 'strong' and (value.startswith(term + '_') or value.endswith('_' + term)):
                return term
    hierarchy = set(row.get('hierarchy') or [])
    return next((t for t in terms if t in hierarchy), None)


def distance_m(a_lat, a_lon, b_lat, b_lon):
    if None in (a_lat, a_lon, b_lat, b_lon):
        return math.inf
    x = math.radians(b_lon - a_lon) * math.cos(math.radians((a_lat + b_lat) / 2))
    return 6_371_000 * math.hypot(x, math.radians(b_lat - a_lat))


def digits(value):
    return re.sub(r'\D', '', value or '')[-9:]


def overture_candidate(row, release, matched_term, label):
    websites = [w for w in row.get('websites') or [] if isinstance(w, str) and w.startswith(('http://', 'https://'))]
    socials = [s for s in row.get('socials') or [] if isinstance(s, str) and s.startswith(('http://', 'https://'))]
    own = next((w for w in websites if classify(w)[0] == 'website'), None)
    website = own or (websites[0] if websites else None)
    lat, lon = row.get('lat'), row.get('lon')
    datasets = [d for d in row.get('datasets') or [] if d]
    return {
        'id': f"overture/{row['id']}", 'name': row['name'].strip(), 'category': None, 'category_label': label,
        'overture_category': row.get('category') or row.get('basic_category'),
        'address': row.get('address') or None, 'phone': (row.get('phones') or [None])[0], 'email': (row.get('emails') or [None])[0],
        'website': website, 'website_is_social': bool(website) and classify(website)[0] != 'website',
        'phones': list(dict.fromkeys(row.get('phones') or []))[:5], 'emails': list(dict.fromkeys(row.get('emails') or []))[:5],
        'websites': websites[:5], 'socials': socials[:5], 'opening_hours': None, 'lat': lat, 'lon': lon,
        'need_signals': [], 'priority_points': 0, 'priority_reasons': [],
        'budget': None, 'budget_reason': 'Budget is unknown; nothing public establishes what this business can afford.',
        'budget_signals': [f"Part of a brand or chain ({row['brand']})."] if row.get('brand') else [],
        'sources': ['Overture Maps'], 'field_sources': {},
        'evidence': {'source': 'Overture Maps', 'record_id': row['id'], 'release': release, 'datasets': datasets,
                     'updated': str(row['updated'])[:10] if row.get('updated') else None,
                     'confidence': round(row['confidence'], 2) if row.get('confidence') is not None else None,
                     'matched_category': matched_term,
                     'url': f'https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}#map=19/{lat:.6f}/{lon:.6f}' if lat and lon else None,
                     'licence': OVERTURE_LICENCE},
    }


def from_overture(rows, release, categories, name_keyword, min_confidence=0.45):
    """Candidates from cached Overture rows for the chosen types (or name keyword). Returns (items, counts)."""
    terms = overture_terms(categories) if categories else set()
    labels = {key: CATEGORIES[key][0] for key in categories}
    out, closed, weak = [], 0, 0
    for row in rows:
        name = (row.get('name') or '').strip()
        if not name:
            continue
        if name_keyword and name_keyword.casefold() not in name.casefold():
            continue
        term = category_matches(row, terms) if terms else None
        if terms and term is None:
            continue
        if row.get('operating_status') in {'permanently_closed', 'temporarily_closed'}:
            closed += 1
            continue
        if (row.get('confidence') or 0) < min_confidence:
            weak += 1
            continue
        label = next((labels[k] for k in categories if term and term in overture_terms([k])), None) or \
            (row.get('category') or row.get('basic_category') or 'Business').replace('_', ' ').capitalize()
        out.append(overture_candidate(row, release, term, label))
    out, duplicates = dedupe(out)
    return out, {'overture_matched': len(out), 'overture_closed_skipped': closed, 'overture_low_confidence_skipped': weak,
                 'overture_duplicates_merged': duplicates}


def near_duplicate(a, b):
    """Overture conflates several sources, so one business can appear twice ("Elmaphue"/"Elmaphus" Dental Clinic)."""
    if a.get('phone') and b.get('phone') and len(digits(a['phone'])) >= 7 and digits(a['phone']) == digits(b['phone']):
        return distance_m(a['lat'], a['lon'], b['lat'], b['lon']) < 500
    names = ' '.join(fold(a['name'])), ' '.join(fold(b['name']))
    return distance_m(a['lat'], a['lon'], b['lat'], b['lon']) < 150 and SequenceMatcher(None, *names).ratio() >= .9


def dedupe(items):
    kept, merged = [], 0
    for item in sorted(items, key=lambda i: -(i['evidence'].get('confidence') or 0)):
        twin = next((k for k in kept if near_duplicate(k, item)), None)
        if twin is None:
            kept.append(item)
            continue
        merged += 1
        twin['evidence'].setdefault('duplicates', []).append(item['evidence']['record_id'])
        for field in ('phones', 'emails', 'websites', 'socials'):
            twin[field] = list(dict.fromkeys(twin[field] + item[field]))[:5]
        for field in ('phone', 'email', 'website', 'address'):
            if not twin.get(field) and item.get(field):
                twin[field] = item[field]
        if not twin.get('website') and item.get('website'):
            twin['website_is_social'] = item['website_is_social']
    return kept, merged


def same_business(a, b):
    if a.get('phone') and b.get('phone') and digits(a['phone']) == digits(b['phone']) and len(digits(a['phone'])) >= 7:
        return distance_m(a['lat'], a['lon'], b['lat'], b['lon']) < 2_000
    close = distance_m(a['lat'], a['lon'], b['lat'], b['lon']) < 250
    return close and (name_match(a['name'], b['name']) == 'strong' or name_match(b['name'], a['name']) == 'strong')


def merge(osm_items, overture_items):
    """OSM first; an Overture record for the same business fills its missing fields (with their source)."""
    merged = [dict(item, sources=['OpenStreetMap'], field_sources={}) for item in osm_items]
    added, joined = [], 0
    for extra in overture_items:
        match = next((m for m in merged if same_business(m, extra)), None)
        if match is None:
            added.append(extra)
            continue
        joined += 1
        match['sources'] = match['sources'] + ['Overture Maps']
        match['also'] = {'overture_id': extra['evidence']['record_id'], 'release': extra['evidence']['release'],
                         'datasets': extra['evidence']['datasets'], 'updated': extra['evidence'].get('updated')}
        for field in ('phone', 'email', 'website', 'address'):
            if not match.get(field) and extra.get(field):
                match[field] = extra[field]
                match['field_sources'][field] = 'Overture Maps'
                if field == 'website':
                    match['website_is_social'] = extra['website_is_social']
        for field in ('phones', 'emails', 'websites', 'socials'):
            match[field] = list(dict.fromkeys((match.get(field) or []) + extra.get(field, [])))[:5]
    return merged + added, {'merged_same_business': joined}


# Hosts on which a "website" is a free builder subdomain, or a builder that has shut down.
FREE_HOSTS = ('wixsite.com', 'blogspot.com', 'wordpress.com', 'weebly.com', 'godaddysites.com', 'square.site', 'carrd.co',
              'webflow.io', 'jimdosite.com', 'site123.me', 'mystrikingly.com', 'strikingly.com', 'yolasite.com', 'webnode.page',
              'sites.google.com', 'netlify.app', 'vercel.app', 'github.io', 'business.page', 'ueniweb.com', 'linktr.ee')
DEAD_BUILDERS = ('business.site',)  # Google Business Profile websites, shut down in 2024


def website_status(item, check=None):
    """none, social_only, dead_builder, free_subdomain, unreachable, ok or unchecked, with the reason."""
    website = item.get('website')
    if check and check.get('unreachable'):
        return 'unreachable', f"The listed website could not be loaded ({check.get('checked_at', '')[:10]})."
    if not website:
        found = [w for w in item.get('websites') or [] if classify(w)[0] == 'website']
        site, identity = (check or {}).get('site'), (check or {}).get('identity')
        online = [w for w in (item.get('enrichment') or {}).get('website_candidates', []) if w['name_match'] == 'strong']
        if found:
            website = found[0]
        elif site and (not identity or identity['verdict'] in {'confirmed', 'probably_same', 'name_only'}):
            # Not on the map, but a website found online (or added by the user) was read and matches this business.
            website = check.get('website_url') or site['pages'][0]['url']
        elif online and not site:
            return 'unchecked', f"No website on the map, but {online[0]['label']} was found online; check it to confirm it is theirs."
        else:
            return 'none', 'No website listed in the map sources.' + (' The website checked appears to belong to another business.' if site else '')
    name = host(website)
    if classify(website)[0] != 'website':
        return 'social_only', f'Only a {classify(website)[1]} page is listed as the website.'
    if any(name == h or name.endswith('.' + h) for h in DEAD_BUILDERS):
        return 'dead_builder', 'The website is on Google Business Profile sites, which shut down in 2024.'
    if any(name == h or name.endswith('.' + h) for h in FREE_HOSTS):
        return 'free_subdomain', f'The website is a free builder address ({name}), not their own domain.'
    if check and check.get('site'):
        return 'ok', 'Their website loads.'
    return 'unchecked', 'A website is listed; check it to find its problems.'


NEED_POINTS = {'none': 80, 'social_only': 75, 'dead_builder': 70, 'unreachable': 70, 'free_subdomain': 50}


def opportunity(item, offer_kind, health=None):
    """Transparent 0–100 opportunity score. Web offers: website gaps; any offer: reachability. Reasons list every point."""
    status, why = website_status(item, item.get('check'))
    points, reasons = 0, []
    if offer_kind == 'web_presence':
        if status in NEED_POINTS:
            points += NEED_POINTS[status]
            reasons.append(f'+{NEED_POINTS[status]} {why}')
        elif health and health.get('score') is not None:
            gap = round((100 - health['score']) * 0.7)
            if gap:
                points += gap
                reasons.append(f"+{gap} website health {health['grade']} ({health['score']}/100)")
    verified = (item.get('verification') or {}).get('contacts')
    reviewed = (item.get('contact_review') or {}).get('contacts')
    if reviewed is not None:
        # Only contacts that passed the review count; rejected ones earn nothing.
        for kind, full, label in (('phone', 10, 'phone'), ('email', 5, 'email')):
            verdicts = [c['verdict'] for c in reviewed if c['type'] == kind]
            if 'approved' in verdicts:
                points += full
                reasons.append(f'+{full} {label} approved by the contact review')
            elif 'needs_review' in verdicts:
                points += full // 2
                reasons.append(f'+{full // 2} {label} needs review (one source or a warning)')
            elif verdicts:
                reasons.append(f'+0 {label}: every {label} found was rejected by the contact review')
    elif verified is not None:
        # After verification, wrong contacts earn nothing and confirmed ones earn more than single-source ones.
        for kind, full, label in (('phone', 10, 'phone'), ('email', 5, 'email')):
            states = [c['status'] for c in verified if c['type'] == kind]
            if {'confirmed', 'corroborated'} & set(states):
                points += full
                reasons.append(f"+{full} {label} {'confirmed' if 'confirmed' in states else 'corroborated by two sources'}")
            elif 'single_source' in states:
                points += full // 2
                reasons.append(f'+{full // 2} {label} from a single source (not confirmed)')
            elif states:
                reasons.append(f'+0 {label}: every known {label} looks wrong')
    else:
        phones = [c for c in [item.get('phone')] + list(item.get('phones') or []) if c]
        web = item.get('enrichment') or {}
        if phones or any(c['type'] in {'phone', 'whatsapp'} for c in web.get('contacts', [])):
            points += 10
            reasons.append('+10 phone number known (not verified)')
        if item.get('email') or item.get('emails') or any(c['type'] == 'email' for c in web.get('contacts', [])):
            points += 5
            reasons.append('+5 email known (not verified)')
    if item.get('socials') or (item.get('enrichment') or {}).get('social_pages') or item.get('site_socials'):
        points += 5
        reasons.append('+5 social profile known')
    score = min(points, 100)
    band = 'hot' if score >= 70 else 'warm' if score >= 40 else 'cool'
    return {'score': score, 'band': band, 'reasons': reasons, 'website_status': status, 'website_status_reason': why,
            'method': 'opportunity_v1', 'note': 'Transparent points from public data, not a probability of buying.'}


def pitch_line(item, offer, status, health=None):
    """One sentence naming the specific gap; None when there is no evidence-backed gap."""
    name = item['name']
    if status == 'none':
        return f"{name} has no website listed on the maps we checked; customers searching online may not find them."
    if status == 'social_only':
        return f"{name} relies on a social page as its website; an own site would show services, prices and contact details in one place."
    if status in {'dead_builder', 'unreachable'}:
        return f"{name}'s listed website does not work, so people who click it from the map reach nothing."
    if status == 'free_subdomain':
        return f"{name}'s site is on a free builder address; an own domain looks more established and is easier to remember."
    if health and health.get('issues'):
        top = [i['plain'] for i in health['issues'][:2]]
        return f"{name}'s website: " + '; '.join(top) + '.'
    return None


def social_handles(item):
    """Platform -> URL for socials, from every source."""
    out = {}
    for url in [s['url'] for s in item.get('site_socials') or []] + list(item.get('socials') or []) + \
            ([item['website']] if item.get('website_is_social') else []):
        kind, label = classify(url)
        if kind == 'social' and label not in out:
            out[label] = url
    return out


def domain_of(url):
    try:
        return urlsplit(url if '://' in url else 'https://' + url).hostname
    except ValueError:
        return None
