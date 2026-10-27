"""Cross-check the map entry, its website and web findings so similarly named businesses are not merged.

Each field is compared independently and keeps its sources. Disagreement is
reported, not resolved: an outdated phone and another branch look the same.
"""
import re
from urllib.parse import urlsplit

from backend.domain.enrichment import GENERIC, distinctive, fold, host, name_match, profile_handle

ADDRESS_GENERIC = GENERIC | {'road', 'street', 'avenue', 'block', 'phase', 'sector', 'town', 'city', 'main', 'near', 'floor', 'plaza',
                             'market', 'lane', 'colony', 'society', 'district', 'pakistan', 'india', 'united', 'kingdom', 'states'}


def phone_keys(values):
    keys = set()
    for value in values:
        for part in re.split(r'[;,/]', value or ''):
            digits = re.sub(r'\D', '', part)
            if len(digits) >= 7:
                keys.add(digits[-9:])
    return keys


def address_words(text):
    return {w for w in fold(text or '') if len(w) >= 4 and not w.isdigit() and w not in ADDRESS_GENERIC}


def names_match(name, text):
    """name_match plus spacing variants: "Lal Qila" and "Lalqila" are the same name."""
    level = name_match(name, text)
    joined = ''.join(distinctive(name))
    if level != 'strong' and len(joined) >= 6 and (joined in fold(text) or joined == ''.join(fold(text))):
        return 'strong'
    return level


def check(field, status, detail, sources):
    return {'field': field, 'status': status, 'detail': detail, 'sources': sources}


def cross_check(item, site, enrichment, location):
    """status per field: match | partial | differs | conflict | not_comparable."""
    osm = item['evidence']['url']
    site_url = site['pages'][0]['url']
    checks = []
    names = [n for n in [*site['names']['structured'], site['names']['site_name'], site['names']['heading'], site['names']['title']] if n]
    levels = {n: names_match(item['name'], n) for n in names}
    best = next((n for n in names if levels[n] == 'strong'), None) or next((n for n in names if levels[n] == 'partial'), None)
    if not names:
        checks.append(check('name', 'not_comparable', 'The website shows no business name LeadDesk could read.', [site_url]))
    elif best and levels[best] == 'strong':
        checks.append(check('name', 'match', f'The website names "{best}".', [osm, site_url]))
    elif best:
        checks.append(check('name', 'partial', f'The website name "{best}" only partly matches "{item["name"]}".', [osm, site_url]))
    else:
        checks.append(check('name', 'conflict', f'The website names "{names[0]}", not "{item["name"]}".', [osm, site_url]))

    site_phones = phone_keys(c['value'] for c in site['contacts'] if c['type'] in {'phone', 'whatsapp'})
    osm_phones = phone_keys([item.get('phone')])
    if osm_phones and site_phones:
        same = osm_phones & site_phones
        checks.append(check('phone', 'match' if same else 'differs',
                            'The map phone number also appears on the website.' if same else
                            'The map phone number is not on the website. It may be outdated, another branch or another business.',
                            [osm, site_url]))
    else:
        checks.append(check('phone', 'not_comparable', 'A phone number is missing on the map or the website.', []))

    site_emails = {c['value'].casefold() for c in site['contacts'] if c['type'] == 'email'}
    email = (item.get('email') or '').split(';')[0].strip().casefold()
    if email and (email in site_emails or email.rsplit('@', 1)[-1] == host(site_url)):
        checks.append(check('email', 'match', 'The map email is on the website or uses its domain.', [osm, site_url]))
    elif email and site_emails:
        checks.append(check('email', 'differs', 'The map email does not appear on the website.', [osm, site_url]))
    else:
        checks.append(check('email', 'not_comparable', 'An email is missing on the map or the website.', []))

    if item.get('website'):
        same = host(item['website']) == host(site_url)
        checks.append(check('website', 'match' if same else 'differs',
                            'The map entry links to this website.' if same else
                            f"The map entry links to {host(item['website'])}, not {host(site_url)}.", [osm, site_url]))
    else:
        checks.append(check('website', 'not_comparable', 'The map entry has no website; this one was found by web search.', [site_url]))

    wanted = address_words(item.get('address')) - set(fold(item['name']))  # the name is not an address match
    found = address_words(site['address_text'])
    if wanted and found:
        hits = wanted & found
        # One shared word ("garden") is weak; need two, or the only distinctive word.
        agree = len(hits) >= min(2, len(wanted)) and len(hits) / len(wanted) >= .5
        checks.append(check('address', 'match' if agree else 'differs',
                            f"Map address words found on the website: {', '.join(sorted(hits)) or 'none'} (of {', '.join(sorted(wanted))}).",
                            [osm, site_url]))
    else:
        place = address_words(', '.join(location.split(',')[:2]))
        hit = place & found
        checks.append(check('address', 'partial' if hit else 'not_comparable',
                            f"The website mentions {', '.join(sorted(hit))} (your search area); no street to compare." if hit else
                            'No address to compare on the map or the website.', [site_url] if hit else []))

    handles = {''.join(fold(profile_handle(u) or '')) for u in site['social_links']} - {''}
    web_social = [(p['url'], ''.join(fold(profile_handle(p['url']) or ''))) for p in (enrichment or {}).get('social_pages', [])]
    linked = [u for u, h in web_social if h and h in handles]
    if linked:
        checks.append(check('social', 'match', 'The website links to the social profile found by web search.', [site_url, linked[0]]))
    elif web_social and handles:
        checks.append(check('social', 'differs', 'The website links to different social profiles than web search found.', [site_url]))
    else:
        checks.append(check('social', 'not_comparable', 'No social profile to compare.', []))

    branches = {a.casefold() for s in site['structured'] for a in s['addresses']}
    sections = site.get('branch_sections') or []
    multi = len(branches) > 1 or len(sections) >= 2 or bool(re.search(r'\b(our )?(branches|locations|outlets)\b', site['address_text'], re.I))
    redirect = site.get('redirect') or {}
    by = {c['field']: c['status'] for c in checks}
    support = [f for f in ('phone', 'email', 'website', 'address', 'social') if by[f] == 'match']
    if multi:
        # Website, email domain and social pages are shared by every branch; only phone or street pick out this one.
        support = [f for f in support if f in {'phone', 'address'}]
    if redirect.get('lost_words'):
        checks.append(check('branch_page', 'differs', f"The map links {redirect['from']}, which now redirects to {redirect['to']} "
                            f"(dropped: {', '.join(redirect['lost_words'])}). That branch page may no longer exist.", [osm, redirect['to']]))
    against = [f for f in ('phone', 'email', 'website', 'address', 'social') if by[f] == 'differs']
    lost = redirect.get('lost_words') or []
    # The reader may still have found the right branch page (it prefers pages naming the searched area).
    recovered = bool(lost) and any(set(lost) <= set(fold(urlsplit(p['url']).path)) for p in site['pages'] if p['status'] == 'read')
    if lost and multi and not support and not recovered:
        verdict, summary = 'possible_other_branch', (f"The map's branch page now redirects to another branch ({redirect['to']}). "
                                                     "Details on this site may belong to a different branch; they are not used.")
    elif multi and not support and by['name'] in {'match', 'partial'}:
        verdict, summary = 'possible_other_branch', ('The website covers several branches' + (f" ({', '.join(sections[:5])})" if sections else '') +
                                                     ' and no phone or street matched this map entry. Its details may belong to another branch; they are not used.')
    elif by['name'] == 'conflict' and ('website' in support or len(support) >= 2):
        verdict, summary = 'probably_same', f"Probably the same business under another name (brand or branch?): {', '.join(support)} agree."
    elif by['name'] == 'conflict' and not multi:
        verdict, summary = 'different_business', 'This website appears to belong to a different business. Its details are not used.'
    elif by['name'] == 'conflict' or (not support and len(against) >= 2):
        verdict = 'possible_other_branch' if multi else 'different_business'
        summary = ('The website lists several branches and its details differ from the map entry: check which branch this is.' if multi else
                   'Name or details disagree with the map entry. This may be a different business; its details are not used.')
    elif support and by['name'] == 'match':
        verdict, summary = 'confirmed', f"Same business: name plus {', '.join(support)} agree across sources."
    elif support:
        verdict, summary = 'probably_same', f"Probably the same business: {', '.join(support)} agree but the name only partly matches."
    elif by['name'] in {'match', 'partial'}:
        verdict, summary = 'name_only', 'Only the name matches; nothing else could be cross-checked. A similarly named business is possible.'
    else:
        verdict, summary = 'unverified', 'Not enough shared details to tell whether this is the same business.'
    if against and verdict in {'confirmed', 'probably_same'}:
        summary += f" Differs: {', '.join(against)} (outdated listing or another branch?)."
    return {'verdict': verdict, 'summary': summary, 'multi_branch': multi, 'branch_sections': sections, 'checks': checks, 'method': 'identity_cross_check_v1'}


TRUSTED = {'confirmed', 'probably_same', 'name_only'}
