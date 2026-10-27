"""Where and what a lead is, for targeted web searches and for telling it apart from same-named businesses elsewhere.

Built only from data LeadDesk already holds: the lead's own address, the geocoded search place, the typed location
and the business type from the catalogue. Nothing here is inferred about the business itself.
"""
import re

from backend.domain.enrichment import fold
from backend.domain.identity import ADDRESS_GENERIC
from backend.domain.prospecting import CATALOGUE, CURATED, singular

ITEMS = {item['id']: item for item in CATALOGUE['items']}
# Short names people write for some countries ("UAE", "KSA"); the geocoded country name covers the rest.
COUNTRY_ALIASES = {'ae': ('uae', 'emirates'), 'gb': ('uk', 'britain', 'england'), 'us': ('usa', 'america'), 'sa': ('ksa', 'saudi'),
                   'pk': ('pakistan',), 'in': ('india',)}
PLACE_GENERIC = ADDRESS_GENERIC | {'country', 'county', 'emirate', 'province', 'region', 'state', 'division', 'tehsil', 'governorate',
                                   'municipality', 'capital', 'territory', 'metropolitan', 'area', 'west', 'east', 'north', 'south'}


def parts(text):
    return [p.strip() for p in (text or '').split(',') if p.strip()]


def phrase(text):
    return ' '.join(fold(text))


def lead_city(address, location, place_name):
    """The lead's own city or area for search queries.

    Prefer the part of its address that names the searched place (address "…, Gulberg III, Lahore" → "Lahore"). For a
    country-wide search ("UAE") use the last part of its own address ("…, Business Bay, Dubai" → "Dubai"). Otherwise the
    first two parts of what the user typed, as before."""
    own = [p for p in parts(address) if not re.search(r'\d', p)]
    typed = parts(location)
    known = {phrase(p) for p in parts(place_name) + typed}
    country = phrase(parts(place_name)[-1]) if parts(place_name) else ''
    for part in reversed(own):
        if phrase(part) in known:
            # "Gulberg" typed as "Gulberg, Lahore, Pakistan": keep the next typed part unless it is the country.
            folded = [phrase(t) for t in typed]
            index = folded.index(phrase(part)) if phrase(part) in folded else -1
            nxt = folded[index + 1] if 0 <= index < len(folded) - 1 else ''
            aliases = {a for names in COUNTRY_ALIASES.values() for a in names}
            return f'{part}, {typed[index + 1]}' if nxt and nxt != country and nxt not in aliases else part
    if len(parts(place_name)) <= 2 and len(own) >= 2:
        # A country- or province-wide search: the lead's own city says more than "UAE" or "Sindh".
        return ' '.join(w for w in own[-1].split() if w.casefold() not in PLACE_GENERIC) or own[-1]
    return ', '.join(typed[:2])


def category_word(category, label):
    """The plain business-type word for a query: "Restaurants" → "restaurant", "Cafés and coffee shops" → "cafe"."""
    if category in ITEMS:
        label = ITEMS[category]['label']
    first = re.split(r'\s+(?:and|&|or)\s+|[/(,]', label or '')[0].strip()
    if not first or first.casefold() == 'named business':
        return ''
    words_ = fold(first)
    return ' '.join(words_[:-1] + [singular(words_[-1])]) if words_ else ''


def category_terms(category, label):
    """English words and phrases that say what kind of business this is, for the context check."""
    terms = set()
    word = category_word(category, label)
    if word:
        terms.add(word)
    item = ITEMS.get(category)
    if item:
        terms |= {phrase(t) for t in item.get('english', [])}
    if category in CURATED:
        terms |= {phrase(value.replace('_', ' ')) for _, value in CURATED[category][2]}
    for w in fold(label or ''):
        if len(w) >= 4 and w not in {'and', 'shops', 'shop', 'stores', 'store', 'other', 'named', 'business', 'services', 'service'}:
            terms.add(singular(w))
    return {t for t in terms if len(t) >= 3}


def build(item, location, place):
    """Search context for one lead: {'city', 'category_word', 'location', 'category', 'region', ...}."""
    place = place or {}
    place_name = place.get('display_name') or ''
    country = (place.get('country_code') or '').casefold() or None
    labels, location_terms = [], set()
    for text in parts(item.get('address')) + parts(place_name) + parts(location):
        if re.search(r'\d', text):
            continue
        folded = phrase(text)
        if folded and folded not in PLACE_GENERIC and len(folded) >= 3:
            location_terms.add(folded)
            labels.append(text)
        for w in fold(text):
            if len(w) >= 4 and w not in PLACE_GENERIC:
                location_terms.add(w)
    if country:
        location_terms |= set(COUNTRY_ALIASES.get(country, ()))
    city = lead_city(item.get('address'), location, place_name)
    kinds = category_terms(item.get('category'), item.get('category_label'))
    site = ((item.get('check') or {}).get('site') or {})
    known = list(item.get('socials') or []) + list(site.get('social_links') or []) + [s['url'] for s in item.get('site_socials') or []]
    return {
        'known_urls': known[:30],
        'city': city, 'category_word': category_word(item.get('category'), item.get('category_label')),
        'location': sorted(location_terms), 'category': sorted(kinds), 'region': country.upper() if country else None,
        # Single tokens a social handle may add around the name ("freddyscafelahore").
        'location_tokens': sorted({w for t in location_terms for w in t.split() if len(w) >= 3}),
        'category_tokens': sorted({w for t in kinds for w in t.split() if len(w) >= 3}),
        'location_labels': list(dict.fromkeys([city] + labels))[:4], 'category_labels': sorted(kinds, key=len)[:2],
    }
