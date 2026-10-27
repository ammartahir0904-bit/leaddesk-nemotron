"""Turn web search results about one business into evidence-linked findings.

Deterministic: classify each result (own website, social page, link-in-bio
page, directory), check that the result names this business and, when a search
context is given, that it also mentions the business's place, type or a phone
number of its country. Results without that context may be a same-named business
elsewhere: they are listed, but give no contacts or pages until the user
confirms them. Then a few result pages are opened and read in full (robots
policy respected). Every finding keeps its source URL and the page text it came from.
Search snippets are third-party text and may be stale; nothing is assumed.
"""
import re
import unicodedata
from urllib.parse import urlsplit

import phonenumbers

from backend.domain.errors import ResearchError
from backend.domain.extract import EMAIL, PHONE, extract

SOCIAL = {'facebook.com': 'Facebook', 'fb.com': 'Facebook', 'instagram.com': 'Instagram', 'linkedin.com': 'LinkedIn',
          'tiktok.com': 'TikTok', 'x.com': 'X', 'twitter.com': 'X', 'youtube.com': 'YouTube', 'pinterest.com': 'Pinterest',
          'threads.net': 'Threads', 'wa.me': 'WhatsApp', 'whatsapp.com': 'WhatsApp'}
DIRECTORIES = {'google.com', 'maps.google.com', 'goo.gl', 'tripadvisor.com', 'yelp.com', 'zomato.com', 'foodpanda.pk', 'foodpanda.com',
               'justdial.com', 'yellowpages.com', 'yell.com', 'foursquare.com', 'wikipedia.org', 'wikidata.org', 'openstreetmap.org',
               'mapcarta.com', 'waze.com', 'apple.com', 'bing.com', 'trustpilot.com', 'glassdoor.com', 'indeed.com', 'olx.com.pk',
               'daraz.pk', 'amazon.com', 'ubereats.com', 'deliveroo.co.uk', 'talabat.com', 'careem.com', 'cybo.com', 'pakbiz.com',
               'hotfrog.com', 'cylex.net', 'wanderlog.com', 'restaurantguru.com', 'menu.pk', 'eatoye.pk', 'rozee.pk', 'scribd.com'}
# Link-in-bio pages: a business's own list of links (WhatsApp, phone, email, menu). Read like their own page.
LINK_HUBS = {'linktr.ee': 'Linktree', 'beacons.ai': 'Beacons', 'bio.link': 'bio.link', 'taplink.cc': 'Taplink', 'lnk.bio': 'lnk.bio',
             'linkin.bio': 'Linkin.bio'}
GENERIC = {'cafe', 'café', 'coffee', 'restaurant', 'the', 'and', 'shop', 'store', 'bakery', 'house', 'company', 'co', 'ltd', 'pvt',
           'limited', 'services', 'center', 'centre', 'bar', 'grill', 'hotel', 'salon', 'clinic', 'of', 'tea', 'kitchen'}


def fold(text):
    text = re.sub(r"(?<=\w)['\u2019`](?=\w)", '', text)  # "Freddy's" and "Freddys" are the same name
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().casefold()
    return re.findall(r'[a-z0-9]+', text)


def host(url):
    url = url if '://' in url else 'https://' + url
    name = (urlsplit(url).hostname or '').casefold()
    return name[4:] if name.startswith('www.') else name


def registrable(name):
    for known in list(SOCIAL) + list(LINK_HUBS) + list(DIRECTORIES):
        if name == known or name.endswith('.' + known):
            return known
    return name


def classify(url):
    base = registrable(host(url))
    if base in SOCIAL:
        return 'social', SOCIAL[base]
    if base in LINK_HUBS:
        return 'link_hub', LINK_HUBS[base]
    if base in DIRECTORIES or base.startswith('google.'):
        return 'directory', base
    return 'website', base


def name_match(name, text):
    """'strong' when every distinctive name word appears, 'partial' for most, else 'none'."""
    wanted = [w for w in fold(name) if w not in GENERIC and len(w) > 1] or fold(name)
    found = set(fold(text))
    hits = sum(w in found for w in wanted)
    if wanted and hits == len(wanted):
        return 'strong'
    if wanted and hits / len(wanted) >= .6:
        return 'partial'
    return 'none'


POST_PATHS = {'videos', 'video', 'reel', 'reels', 'p', 'posts', 'post', 'popular', 'watch', 'explore', 'hashtag', 'stories', 'photo',
              'photos', 'events', 'groups', 'shorts', 'status', 'search', 'pulse', 'tv', 'share', 'story.php', 'permalink.php', 'tag'}


def distinctive(name):
    return [w for w in fold(name) if w not in GENERIC and len(w) >= 3] or [w for w in fold(name) if len(w) >= 3]


def handle_matches(name, handle):
    """A domain label or social handle that contains a distinctive name word (or the joined name)."""
    handle = ''.join(fold(handle))
    words = distinctive(name)
    joined = ''.join(words)
    return bool(handle) and (joined in handle or any(len(w) >= 4 and w in handle for w in words))


def profile_handle(url):
    parts = [p for p in urlsplit(url).path.split('/') if p]
    if not parts or parts[0].casefold() in POST_PATHS or (len(parts) > 1 and parts[1].casefold() in POST_PATHS):
        return None
    if parts[0].casefold() in {'pages', 'pg', 'company', 'in', 'c', 'channel', 'user'} and len(parts) > 1:
        return parts[1]
    return parts[0].lstrip('@') if len(parts) <= 2 else None


# Extra words a business's own handle may carry around its name ("cafecosta.lhr", "butlerspk", "freddyscafeofficial").
HANDLE_EXTRA = {'official', 'real', 'the', 'pk', 'uae', 'dxb', 'auh', 'lhr', 'khi', 'isb', 'ksa', 'uk', 'usa', 'hq', 'online', 'co', 'inc',
                'llc', 'ltd', 'pvt', 'page', 'app', 'by', 'and', 'n'}


def strip_words(text, allowed):
    """Remove allowed words and digits from the start of text until none fits; what remains is unexplained."""
    ordered = sorted(allowed, key=len, reverse=True)
    while text:
        if text[0].isdigit():
            text = text.lstrip('0123456789')
            continue
        word = next((w for w in ordered if w and text.startswith(w)), None)
        if not word:
            break
        text = text[len(word):]
    return text


def handle_quality(name, handle, context=None):
    """'clean' when the handle is the name plus only harmless extras (place, type, 'official'); 'loose' when the name is inside
    other words ("jci.sidi.mansour" for Sidi Mansour); None when the handle does not contain the name."""
    folded = ''.join(fold(handle))
    words = distinctive(name)
    joined = ''.join(words)
    if not folded or not joined:
        return None
    place = set((context or {}).get('location_tokens', ()))
    kinds = set((context or {}).get('category_tokens', ()))
    for token in [joined] + [w for w in words if len(w) >= 5 and w != joined]:
        index = folded.find(token)
        if index < 0:
            continue
        # The full name may sit next to type words ("cafecosta"); a single word of a longer name only next to place words.
        allowed = HANDLE_EXTRA | place | ((GENERIC | kinds) if token == joined else set())
        prefix, suffix = strip_words(folded[:index], allowed), strip_words(folded[index + len(token):], allowed)
        return 'clean' if not prefix and len(suffix) <= 2 else 'loose'
    return 'loose' if any(len(w) >= 4 and w in folded for w in words) else None


def valid_local_phone(value, region):
    """A valid number of the lead's own country (+216… is Tunisian even when the search is in the UAE)."""
    try:
        number = phonenumbers.parse(value, region)
    except phonenumbers.NumberParseException:
        return False
    return phonenumbers.is_valid_number(number) and phonenumbers.region_code_for_number(number) == region


def without_name(context, name):
    """Drop place and type words that are part of the business name ("Cafe Costa", "Lahore Broast"): naming the business
    already contains them, so they say nothing about where or what it is."""
    own = set(fold(name))
    return context | {key: [t for t in context.get(key, ()) if not set(t.split()) <= own] for key in ('location', 'category')}


def context_hits(text, context):
    """Which place words, business-type words or country phone numbers a result mentions."""
    joined = ' ' + ' '.join(fold(text)) + ' '
    places = sorted(w for w in context.get('location', ()) if f' {w} ' in joined)
    kinds = sorted(w for w in context.get('category', ()) if f' {w} ' in joined)
    region = context.get('region')
    phone = bool(region) and any(valid_local_phone(v, region) for kind, v in snippet_contacts(text) if kind == 'phone')
    return {'location': places[:4], 'category': kinds[:4], 'phone': phone}


def snippet_contacts(text):
    found = []
    for match in EMAIL.finditer(text):
        found.append(('email', match.group()))
    for match in PHONE.finditer(text):
        value = match.group().strip()
        if 7 <= len(re.sub(r'\D', '', value)) <= 15 and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            found.append(('phone', value))
    return found


def enrich(name, listed_website, results, context=None):
    """context: {'location': folded place phrases, 'category': folded type phrases, 'region': 'PK', ...} from
    search_context.build(). Without it (older saved searches), results are judged by name only."""
    rows, contacts, seen = [], [], set()
    listed = registrable(host(listed_website)) if listed_website else None
    if context is not None:
        context = without_name(context, name)
        known = {u.casefold().rstrip('/') for u in context.get('known_urls', ())}
    for result in results:
        kind, label = classify(result['url'])
        text = f"{result['title']} {result['snippet']} {urlsplit(result['url']).path.replace('-', ' ').replace('_', ' ')}"
        match = name_match(name, text)
        is_listed = bool(listed and kind == 'website' and label == listed)
        hits = context_hits(text, context) if context else None
        in_context = hits is None or bool(hits['location'] or hits['category'] or hits['phone'])
        quality = None
        if kind == 'website' and not is_listed and not handle_matches(name, label.split('.')[0]):
            kind = 'mention'  # an article, blog, directory or marketplace that mentions the business
        if kind in {'social', 'link_hub'}:
            handle = profile_handle(result['url'])
            quality = handle_quality(name, handle, context) if handle else None
            if context is None:
                if not handle or not handle_matches(name, handle):
                    kind = 'mention'  # a post, video or someone else's page
            elif quality == 'clean' and in_context and match != 'none':
                pass  # their own profile: the handle is their name and the result mentions their place or type
            elif result['url'].casefold().rstrip('/') in known:
                pass  # the map data or their own website links to this profile
            elif quality or (handle and handle.isdigit() and match == 'strong' and in_context):
                kind = 'possible_social'  # may be theirs; the user confirms with "Is this them?"
            else:
                kind = 'mention'
        if context is not None and kind in {'website', 'mention', 'directory'} and not is_listed and not in_context:
            kind = 'unconfirmed'  # names the business but nothing places it here: possibly a same-named business elsewhere
        row = result | {'kind': kind, 'label': label, 'name_match': match, 'is_listed_website': is_listed}
        if hits is not None:
            row['context'] = hits
        if quality:
            row['handle_quality'] = quality
        rows.append(row)
        if match == 'none':
            continue  # Contacts next to another business's name are not attributed.
        if kind == 'mention' and registrable(host(result['url'])) in SOCIAL:
            continue  # A post or video on someone else's social page: its numbers usually belong to the poster.
        own = kind in {'website', 'social', 'link_hub', 'possible_social'}
        found = []
        for kind_, value in snippet_contacts(f"{result['title']} {result['snippet']}"):
            found.append({'type': kind_, 'value': value, 'source_url': result['url'], 'source_title': result['title'],
                          'origin': 'search_result_snippet', 'name_match': match,
                          'confidence': 'own_page' if own else 'mention',
                          'confidence_note': 'From their own website or profile.' if own else
                          'From another page that mentions this name. It may belong to a similarly named business; verify before use.'})
        if kind in {'unconfirmed', 'possible_social'}:
            row['held_contacts'] = found  # released only if the user confirms this page is theirs
            continue
        for contact in found:
            # Same number written differently (+92 42…, 042…) shares its last 9 digits.
            key = contact_key(contact)
            if key in seen:
                continue
            seen.add(key)
            contacts.append(contact)
    websites, socials, mentions, possible = [], {}, [], []
    for row in rows:
        if row['kind'] == 'website' and row['name_match'] != 'none' and len(websites) < 3 and \
                row['label'] not in {w['label'] for w in websites}:
            websites.append({'url': row['url'], 'label': row['label'], 'title': row['title'], 'name_match': row['name_match'],
                             'is_listed_website': row['is_listed_website']})
        if row['kind'] in {'social', 'link_hub'} and row['name_match'] != 'none' and row['label'] not in socials:
            socials[row['label']] = {'platform': row['label'], 'url': row['url'], 'title': row['title'], 'name_match': row['name_match']}
        if row['kind'] in {'mention', 'directory'} and row['name_match'] != 'none' and len(mentions) < 5 and \
                row['url'] not in {m['url'] for m in mentions} and sum(m['label'] == row['label'] for m in mentions) < 2:
            mentions.append({'url': row['url'], 'label': row['label'], 'title': row['title']})
        # Posts, videos and place pages on social sites never give contacts, so they are not offered for confirmation.
        post = row['kind'] == 'unconfirmed' and registrable(host(row['url'])) in SOCIAL
        if row['kind'] in {'possible_social', 'unconfirmed'} and not post and row['name_match'] != 'none' and len(possible) < 8:
            possible.append({'url': row['url'], 'label': row['label'], 'title': row['title'], 'kind': row['kind'],
                             'reason': possible_reason(row)})
    notes = ['Found through web search results. Snippets are third-party text and may be outdated; open the source to confirm.',
             'Only results that name this business are used. Similar names in the same city can still be a different business.',
             'Social pages are linked, not scraped: Facebook and Instagram require login and restrict automated access.']
    if context is not None:
        notes.insert(1, 'Results must also mention ' + context_summary(context) +
                     '. Others are listed under "Possibly a different business" and give no contacts unless you confirm them.')
    return {'results': rows, 'website_candidates': websites, 'social_pages': list(socials.values()), 'mentions': mentions,
            'possible_pages': possible, 'contacts': sorted(contacts, key=lambda c: c['confidence'] != 'own_page')[:10], 'notes': notes}


def contact_key(contact):
    value = contact['value']
    return (contact['type'] if contact['type'] != 'whatsapp' else 'phone',
            re.sub(r'\D', '', value)[-9:] if contact['type'] in {'phone', 'whatsapp'} else value.casefold())


def possible_reason(row):
    if row['kind'] == 'possible_social':
        if row.get('handle_quality') == 'loose':
            return 'The profile name has other words around this name; it may be a different page.'
        if row.get('context') and not any(row['context'].values()):
            return 'The profile does not mention this place or type of business.'
        return 'The profile address does not show the name; confirm it is theirs.'
    return 'Names this business but does not mention its place, type or a local phone number: possibly a same-named business elsewhere.'


def context_summary(context):
    places = [w for w in context.get('location_labels', ()) if w][:3]
    kinds = [w for w in context.get('category_labels', ()) if w][:2]
    parts = []
    if places:
        parts.append(' or '.join(places))
    if kinds:
        parts.append('a type word such as ' + ' or '.join(f'"{k}"' for k in kinds))
    if context.get('region'):
        parts.append(f"a {context['region']} phone number")
    return ', '.join(parts) or 'the business\'s place or type'


def tidy(result):
    """Older saved results: social-site posts never give contacts, so they are not offered for confirmation."""
    if result and result.get('possible_pages'):
        result['possible_pages'] = [p for p in result['possible_pages']
                                    if not (p['kind'] == 'unconfirmed' and registrable(host(p['url'])) in SOCIAL)]
    return result


def apply_feedback(result, feedback):
    """The user's "Is this them?" answers, applied on every read so a correction takes effect at once.

    feedback: {url: 'yes' | 'no'}. 'no' removes the page and every contact taken from it; 'yes' adds a held page as theirs."""
    if not result or not feedback:
        return result
    seen = {contact_key(c) for c in result['contacts']}
    for row in result.get('results', []):
        verdict = feedback.get(row['url'])
        if not verdict:
            continue
        row['user_verdict'] = verdict
        if verdict == 'no':
            for key in ('website_candidates', 'social_pages', 'mentions', 'possible_pages'):
                result[key] = [p for p in result.get(key, []) if p['url'] != row['url']]
            result['contacts'] = [c for c in result['contacts'] if c['source_url'] != row['url']]
            continue
        result['possible_pages'] = [p for p in result.get('possible_pages', []) if p['url'] != row['url']]
        kind, label = classify(row['url'])
        if kind in {'social', 'link_hub'} and row['url'] not in {p['url'] for p in result['social_pages']}:
            result['social_pages'] = [p for p in result['social_pages'] if p['platform'] != label] + [
                {'platform': label, 'url': row['url'], 'title': row['title'], 'name_match': row['name_match'], 'confirmed_by_user': True}]
        elif kind == 'website' and row['url'] not in {w['url'] for w in result['website_candidates']}:
            result['website_candidates'].append({'url': row['url'], 'label': label, 'title': row['title'], 'name_match': row['name_match'],
                                                 'is_listed_website': row['is_listed_website'], 'confirmed_by_user': True})
        for contact in row.get('held_contacts', []):
            if contact_key(contact) not in seen:
                seen.add(contact_key(contact))
                result['contacts'].append(contact | {'confirmed_by_user': True})
    return result


def queries(name, location, category='', city='', domain=None):
    """Targeted searches: the name with its type and city, its contact details, and its Facebook and Instagram pages.

    city: the lead's own city or area (search_context.lead_city); falls back to the first two parts of the typed location."""
    city = city or (', '.join(part.strip() for part in location.split(',')[:2]) if location else '')
    found = [f'"{name}" {category} {city}', f'"{name}" {city} phone OR contact OR whatsapp',
             f'site:facebook.com "{name}" {city}', f'site:instagram.com "{name}" {city}']
    if domain:
        found.append(f'"{domain}"')
    return [' '.join(q.split()) for q in found]


def handle_guesses(name, context=None):
    """Handles a business often uses: freddyscafe, freddys.cafe, freddyscafelahore (only for searching, never assumed)."""
    words = [w for w in fold(name) if len(w) > 1]
    if not words:
        return []
    city = next((t for t in (context or {}).get('location_tokens', ()) if t in fold((context or {}).get('city', ''))), '')
    guesses = [''.join(words), '.'.join(words), ''.join(words) + city if city else '']
    return [g for g in dict.fromkeys(guesses) if g and len(g) >= 5][:3]


def fallback_queries(name, context=None):
    """Extra searches when the first pass found no Instagram or Facebook profile: without the city, and by likely handle."""
    found = [f'"{name}" instagram', f'"{name}" facebook']
    found += [f'"{h}" instagram OR facebook' for h in handle_guesses(name, context)[:2]]
    return found


# Pages never opened: login walls, maps, encyclopaedias and job boards rarely show a business's own contacts.
NO_READ = {'google.com', 'maps.google.com', 'goo.gl', 'openstreetmap.org', 'wikipedia.org', 'wikidata.org', 'waze.com',
           'apple.com', 'bing.com', 'amazon.com', 'scribd.com', 'indeed.com', 'glassdoor.com', 'rozee.pk', 'mapcarta.com'}
MAX_PAGE_READS = 5
LIST_PAGE_PHONES = 4  # more distinct numbers than this means a listing of several businesses


def readable(rows, limit=MAX_PAGE_READS):
    """Result pages worth opening: their own site and link-in-bio page first, then pages whose title names the business fully.
    Pages that may belong to a same-named business elsewhere are not opened."""
    picked = []
    ordered = sorted(rows, key=lambda r: (r['kind'] not in {'website', 'link_hub'}, r['name_match'] != 'strong'))
    for row in ordered:
        site = registrable(host(row['url']))
        # Social sites are never opened, including posts and videos classed as mentions.
        if site in SOCIAL or site in NO_READ or site.startswith('google.') or row['url'] in {p['url'] for p in picked}:
            continue
        if row['kind'] in {'unconfirmed', 'possible_social'} and row.get('user_verdict') != 'yes':
            continue
        if row['kind'] in {'website', 'link_hub'} and row['name_match'] != 'none' or row['name_match'] == 'strong':
            picked.append(row)
        if len(picked) >= limit:
            break
    return picked


def title_of(html):
    match = re.search(r'<title[^>]*>(.*?)</title>', html[:200_000], re.I | re.S)
    return ' '.join(match.group(1).split())[:300] if match else ''


def page_contacts(name, row, page):
    """Contacts on a fetched result page that can be attributed to this business, with their excerpt."""
    own = row['kind'] in {'website', 'link_hub'} or row.get('user_verdict') == 'yes'
    found = extract(page.html).contacts
    title = title_of(page.html)
    if not own and name_match(name, title) != 'strong':
        return [], 'The page title does not name this business, so its contacts were not attributed.'
    phones = {re.sub(r'\D', '', c['raw_value'])[-9:] for c in found if c['type'] == 'phone'}
    listing = not own and len(phones) > LIST_PAGE_PHONES
    out = []
    for c in found:
        if listing and name_match(name, c['excerpt']) != 'strong':
            continue  # On a page listing several businesses, only contacts written next to this name.
        out.append({'type': c['type'], 'value': c['raw_value'], 'source_url': page.url, 'source_title': title or row['title'],
                    'origin': 'result_page', 'excerpt': c['excerpt'], 'name_match': 'strong' if not own else row['name_match'],
                    'confidence': 'own_page' if own else 'mention',
                    'confidence_note': ('Read on their link-in-bio page.' if row['kind'] == 'link_hub' else 'Read on their own website.') if own else
                    'Read on another page whose title names this business. It may be outdated or belong to a similarly named business; verify before use.'})
    note = ('This page lists several businesses; only contacts written next to this name were kept.' if listing else None)
    return out, note


def read_result_pages(name, result, fetch, limit=MAX_PAGE_READS):
    """Open up to `limit` result pages, add attributable contacts to result['contacts'] and record each read."""
    key = contact_key
    seen = {key(c) for c in result['contacts']}
    reads = []
    for row in readable(result['results'], limit):
        try:
            page = fetch(row['url'])
        except ResearchError as failure:
            reads.append({'url': row['url'], 'status': 'failed', 'message': str(failure)[:300], 'added': 0})
            continue
        try:
            contacts, note = page_contacts(name, row, page)
        except ResearchError as failure:  # e.g. a page too complex to parse within the limit
            reads.append({'url': page.url, 'status': 'failed', 'message': str(failure)[:300], 'added': 0})
            continue
        added = 0
        for contact in contacts:
            if key(contact) in seen or len(result['contacts']) >= 20:
                continue
            seen.add(key(contact))
            result['contacts'].append(contact)
            added += 1
        reads.append({'url': page.url, 'status': 'read', 'message': note, 'added': added, 'kind': row['kind']})
    result['contacts'].sort(key=lambda c: c['confidence'] != 'own_page')
    result['page_reads'] = reads
    if reads:
        result['notes'].append('Result pages that name this business were opened and read in full (robots policy respected); '
                               'each contact shows the page text it came from.')
    return result
