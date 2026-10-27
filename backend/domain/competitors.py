"""Compare a business with its nearest same-type competitors from the same search.

Deterministic. Competitors are businesses in this search with the same business
type (or Overture category) within a radius, nearest first. The matrix uses only
what LeadDesk has collected (map data, website checks, web search); a feature a
competitor shows and this business does not becomes a finding that names the
competitors and the page it was seen on. "Not seen" never means "they lack it"
unless their website was read.
"""
from backend.domain.places import distance_m, website_status

RADIUS_M = 3000
LIMIT = 5
FEATURES = [('online_booking', 'online booking'), ('online_ordering', 'online ordering or shop'), ('whatsapp', 'a WhatsApp chat link'),
            ('contact_form', 'a contact form'), ('mobile', 'a mobile-friendly site'), ('https', 'a secure (HTTPS) site'),
            ('structured_data', 'business details for Google (schema.org)')]
OWN_SITE = {'ok', 'unchecked'}


def peers(lead, candidates, radius=RADIUS_M, limit=LIMIT):
    def same_type(other):
        # The business type chosen for the search groups competitors (an estate agent and a property developer
        # found by "Real estate agents" compete); without one, fall back to the map category.
        if lead.get('category_label') and other.get('category_label'):
            return lead['category_label'] == other['category_label']
        return bool(lead.get('overture_category')) and lead.get('overture_category') == other.get('overture_category')
    found = []
    for other in candidates:
        if other['id'] == lead['id'] or not same_type(other):
            continue
        metres = distance_m(lead.get('lat'), lead.get('lon'), other.get('lat'), other.get('lon'))
        if metres <= radius:
            found.append((metres, other))
    found.sort(key=lambda pair: pair[0])
    return found[:limit]


def profile(item):
    status, _ = website_status(item, item.get('check'))
    check = item.get('check') or {}
    site, health = check.get('site'), check.get('health')
    signals = {s['id']: s for s in (site or {}).get('signals', [])}
    socials = set()
    for url in list(item.get('socials') or []) + [p['url'] for p in (item.get('enrichment') or {}).get('social_pages', [])]:
        for host, name in (('facebook.', 'Facebook'), ('instagram.', 'Instagram'), ('linkedin.', 'LinkedIn'), ('tiktok.', 'TikTok'),
                           ('youtube.', 'YouTube')):
            if host in url:
                socials.add(name)
    return {'id': item['id'], 'name': item['name'], 'website_status': status, 'own_website': status in OWN_SITE,
            'grade': (health or {}).get('grade'), 'health': (health or {}).get('score'), 'website_read': bool(site),
            'features': {key: (signals[key]['state'] if key in signals else None) for key, _ in FEATURES},
            'evidence': {key: signals[key].get('evidence') for key in signals if signals[key].get('evidence')},
            'socials': sorted(socials), 'website': item.get('website') if status in OWN_SITE else None}


def compare(lead, candidates):
    nearby = peers(lead, candidates)
    if not nearby:
        return None
    me = profile(lead)
    rows = [profile(other) | {'distance_m': round(metres)} for metres, other in nearby]
    findings = []
    with_site = [r for r in rows if r['own_website']]
    if not me['own_website'] and with_site:
        verb = 'has' if len(with_site) == 1 else 'have'
        findings.append({'kind': 'website', 'text': f"{len(with_site)} of {len(rows)} nearby competitors {verb} their own website "
                         f"({', '.join(r['name'] for r in with_site[:3])}); {lead['name']} does not.", 'competitors': [r['id'] for r in with_site]})
    graded = sorted([r for r in rows if r['health'] is not None], key=lambda r: -r['health'])
    if graded and (me['health'] is None or graded[0]['health'] > me['health']):
        best = graded[0]
        mine = f"{lead['name']}'s is {me['grade']} ({me['health']})" if me['health'] is not None else \
            f"{lead['name']} has {'no working website' if not me['own_website'] else 'an unchecked website'}"
        findings.append({'kind': 'quality', 'text': f"Best website nearby: {best['name']}, grade {best['grade']} ({best['health']}/100); {mine}.",
                         'competitors': [best['id']]})
    gaps = [(key, label, [r for r in rows if r['features'][key] == 'yes']) for key, label in FEATURES if me['features'][key] != 'yes']
    gaps = [g for g in gaps if g[2]]
    if gaps and not me['own_website']:
        # Without a website every feature is missing; one line lists what competitors' sites offer.
        names = sorted({r['name'] for _, _, have in gaps for r in have})
        findings.append({'kind': 'feature', 'feature': 'all',
                         'text': f"Competitor websites nearby offer {', '.join(label for _, label, _ in gaps)} "
                                 f"({', '.join(names[:3])}); {lead['name']} has none of these without a website.",
                         'competitors': sorted({r['id'] for _, _, have in gaps for r in have}),
                         'evidence': [have[0]['evidence'].get(key) for key, _, have in gaps[:3]]})
    else:
        for key, label, have in gaps:
            known = 'not found on its website' if me['website_read'] else 'not checked'
            findings.append({'kind': 'feature', 'feature': key,
                             'text': f"{len(have)} competitor{'s' if len(have) != 1 else ''} nearby offer{'s' if len(have) == 1 else ''} {label} "
                                     f"({', '.join(r['name'] for r in have[:3])}); {lead['name']}: {known}.",
                             'competitors': [r['id'] for r in have], 'evidence': [r['evidence'].get(key) for r in have[:3]]})
    social = {name for r in rows for name in r['socials']} - set(me['socials'])
    for name in sorted(social):
        have = [r for r in rows if name in r['socials']]
        if len(have) >= 2:
            findings.append({'kind': 'social', 'text': f"{len(have)} nearby competitors are on {name}; no {name} page found for {lead['name']}.",
                             'competitors': [r['id'] for r in have]})
    unchecked = [r for r in rows if r['own_website'] and not r['website_read']]
    return {'me': me, 'competitors': rows, 'findings': findings, 'unchecked_websites': [r['id'] for r in unchecked],
            'radius_m': RADIUS_M, 'method': 'competitors_v1',
            'note': f'Nearest {len(rows)} businesses of the same type within {RADIUS_M // 1000} km in this search. '
                    'Features count only when seen on a website LeadDesk read.'}


def competitor_line(lead, comparison):
    """A pitch sentence from the strongest competitor finding, or None."""
    if not comparison:
        return None
    order = {'website': 0, 'feature': 1, 'quality': 2, 'social': 3}
    best = sorted(comparison['findings'], key=lambda f: order[f['kind']])
    return best[0]['text'] if best else None
