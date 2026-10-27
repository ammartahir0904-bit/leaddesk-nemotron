"""What the seller offers vs. what this business's website has, and a rules-first pitch (offer_fit_v1, pitch_v1).

Deterministic. Each feature is Has / Missing / Not seen with the page text or measurement it rests on. "Not seen"
means LeadDesk could not tell (not read, not measured), never "they lack it". The pitch is assembled from templates
filled with those facts; every sentence cites evidence IDs. A local model may only reword the opening message
(pitch_polish), and its wording is rejected if it adds facts, numbers, names or claims of earlier contact.
"""
import json
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.domain.ai_analysis import PRIOR_CONTACT, unsupported_terms
from backend.domain.enrichment import host
from backend.domain.errors import ResearchError
from backend.domain.prospecting import CATALOGUE, CURATED, words

ITEMS = {item['id']: item for item in CATALOGUE['items']}
TRADES = {
    'food': ({'Food and drink', 'Food shops'}, r'cafe|coffee|restaurant|fast.?food|bakery|bar|pub|food|kitchen|grill|pizza|burger|takeaway|ice.?cream'),
    'health': ({'Health'}, r'dentist|dental|clinic|doctor|hospital|pharmac|physio|medical|health|optician|veterinar'),
    'beauty': ({'Beauty and wellness', 'Sport and leisure'}, r'beauty|salon|hair|barber|spa|nail|gym|fitness|yoga|massage'),
    'lodging': ({'Hospitality and tourism', 'Hospitality'}, r'hotel|guest.?house|hostel|motel|travel|tour'),
    'real_estate': (set(), r'estate|property|properties|realt|letting|housing'),
    'retail': ({'Retail'}, r'shop|store|boutique|clothes|jewel|furniture|electronics|florist|grocery|supermarket'),
    'education': ({'Education'}, r'school|college|academy|training|tuition|university|institute'),
    'services': ({'Professional services', 'Professional', 'Crafts and trades', 'Construction and trades', 'Services', 'Finance',
                  'Cars and vehicles', 'Community and services'}, r'lawyer|law|account|architect|insurance|builder|plumb|electric|repair|agency|consult'),
}
TRADE_LABEL = {'food': 'cafés and restaurants', 'health': 'clinics and health practices', 'beauty': 'salons, spas and gyms',
               'lodging': 'hotels and travel', 'real_estate': 'real estate agencies', 'retail': 'shops', 'education': 'schools and training',
               'services': 'service businesses', 'general': 'local businesses'}

# id, label, trades ('all' or a set), weight (how much it matters in a pitch), topic words that make it relevant to a non-web offer,
# what we would build.
FEATURES = [
    ('own_website', 'Their own website', 'all', 10, {'website', 'websites', 'web'}, 'A fast website of their own, on their own domain'),
    ('mobile_layout', 'Works well on phones', 'all', 7, {'mobile', 'responsive'}, 'Mobile-first design that fits every phone screen'),
    ('contact_first_screen', 'Call/WhatsApp on the first phone screen', 'all', 6, {'leads', 'calls', 'whatsapp'},
     'Call and WhatsApp buttons visible on the first screen'),
    ('click_to_call', 'Tap-to-call button', 'all', 5, {'calls', 'leads'}, 'Tap-to-call button'),
    ('whatsapp_button', 'WhatsApp chat button', 'all', 5, {'whatsapp', 'chat', 'chatbot', 'messaging'}, 'WhatsApp chat button'),
    ('https', 'Secure (HTTPS)', 'all', 6, {'security', 'ssl', 'hosting'}, 'Secure HTTPS hosting'),
    ('contact_form', 'Enquiry form', 'all', 4, {'leads', 'forms', 'crm', 'enquiries'}, 'Enquiry form that sends leads to email or WhatsApp'),
    ('online_ordering', 'Online ordering', {'food', 'retail'}, 6, {'order', 'ordering', 'orders', 'delivery', 'ecommerce', 'shop', 'cart', 'pos'},
     'Online ordering with their own menu and prices'),
    ('online_booking', 'Online booking', {'food', 'health', 'beauty', 'lodging', 'services', 'education'}, 6,
     {'booking', 'bookings', 'appointment', 'appointments', 'reservation', 'reservations', 'scheduling'}, 'Online booking or reservations'),
    ('menu_page', 'Menu as a web page', {'food'}, 5, {'menu', 'menus'}, 'Menu as a fast web page (not a PDF)'),
    ('listings', 'Property listings', {'real_estate'}, 7, {'listings', 'property', 'properties', 'portal'}, 'Property listings with photos and search'),
    ('services_list', 'Services and prices', {'health', 'beauty', 'services', 'education', 'lodging'}, 4, {'services', 'pricing'},
     'Clear services and prices pages'),
    ('reviews', 'Reviews or testimonials', 'all', 3, {'reviews', 'reputation', 'testimonials'}, 'Reviews and testimonials section'),
    ('gallery', 'Photo gallery', {'food', 'beauty', 'lodging', 'real_estate', 'services', 'retail'}, 2, {'photos', 'gallery'}, 'Photo gallery'),
    ('map_directions', 'Map and directions', 'all', 3, {'maps', 'local', 'directions'}, 'Map with directions'),
    ('opening_hours', 'Opening hours', {'food', 'health', 'beauty', 'retail', 'lodging', 'services'}, 3, {'hours', 'local'}, 'Opening hours'),
    ('social_links', 'Links to their social pages', 'all', 2, {'social', 'instagram', 'facebook', 'marketing'}, 'Links to their Instagram and Facebook'),
    ('search_basics', 'Google basics (title, description, business data)', 'all', 3, {'seo', 'google', 'search', 'ranking', 'visibility'},
     'Google-ready titles, descriptions and business data'),
    ('up_to_date', 'Looks up to date', 'all', 3, {'redesign', 'maintenance', 'content', 'refresh'}, 'Fresh, maintained content'),
]
FEATURE = {f[0]: f for f in FEATURES}
HOURS = re.compile(r'opening hours|open (?:daily|every day|from)|timings|\b(?:mon|monday)\s*(?:-|–|to)\s*(?:fri|sat|sun)', re.I)
SEARCHABLE = re.compile(r'search (?:properties|listings)|property search|find (?:a|your) (?:home|property)|for sale|for rent|listings', re.I)
NO_SITE = {'none', 'social_only', 'dead_builder', 'unreachable'}


def trade_of(item):
    category, label = item.get('category'), item.get('category_label') or ''
    group = (ITEMS.get(category) or {}).get('group') or (CURATED.get(category) or (None, None))[1]
    text = f"{category or ''} {label}".casefold()
    if re.search(TRADES['real_estate'][1], text):
        return 'real_estate'
    for trade, (groups, pattern) in TRADES.items():
        if re.search(pattern, text):
            return trade
    for trade, (groups, _) in TRADES.items():
        if group in groups:
            return trade
    return 'general'


def applies(feature, trade):
    trades = FEATURE[feature][2]
    return trades == 'all' or trade in trades


def relevant(feature, offer_kind, offer_words):
    return offer_kind == 'web_presence' or bool(FEATURE[feature][4] & offer_words)


def detect(item, status):
    """{feature: (state, detail, evidence)} from the saved website check. Nothing is inferred beyond what was read."""
    check = item.get('check') or {}
    site, identity = check.get('site'), check.get('identity')
    trusted = site and (not identity or identity['verdict'] in {'confirmed', 'probably_same', 'name_only'})
    found = {}
    if status in NO_SITE:
        why = {'none': 'No website listed on the map or found online.', 'social_only': 'Their only "website" is a social page.',
               'dead_builder': 'Their listed website is a builder page that no longer works.',
               'unreachable': 'Their listed website did not load when checked.'}[status]
        evidence = {'url': (check.get('unreachable') or {}).get('url') or item.get('website') or item['evidence']['url'], 'text': why}
        found['own_website'] = ('missing', why, evidence)
        return found, True
    if not trusted:
        return found, False
    home = site['pages'][0]['url']
    placeholder = any(f['id'] == 'placeholder_site' for f in (site.get('layout') or {}).get('findings', []))
    words_ = site['pages'][0].get('words')
    if not placeholder and words_ is not None and words_ < 30 and not site['pages'][0].get('rendered') and \
            any(p.get('status') == 'thin' for p in (site.get('reading') or {}).get('problems', [])):
        # The page source was nearly empty and Chrome did not draw it: nothing can be judged from it.
        found['own_website'] = ('has', f'Has a website: {host(home)}.', {'url': home, 'text': home})
        why = 'Not judged: the page source is nearly empty (a JavaScript site). Check it again with Chrome reading on.'
        for feature in FEATURE:
            if feature != 'own_website':
                found[feature] = ('not_seen', why, None)
        return found, True
    signals = {s['id']: s for s in site['signals']}
    layout = site.get('layout') or {}
    lf = {f['id']: f for f in layout.get('findings', [])}
    if 'placeholder_site' in lf:
        found['own_website'] = ('missing', lf['placeholder_site']['detail'], lf['placeholder_site']['evidence'])
    else:
        found['own_website'] = ('has', f'Has a website: {host(home)}.', {'url': home, 'text': home})
    sections = {s['id'] for s in layout.get('sections', [])}
    kinds = set(layout.get('action_kinds', []))

    def from_signal(feature, signal_id):
        s = signals.get(signal_id)
        if not s or s['state'] == 'unknown':
            return
        state = 'has' if s['state'] in {'yes', 'info'} else 'missing'
        found[feature] = (state, s['detail'], s.get('evidence') or {'url': home, 'text': s['detail']})

    from_signal('https', 'https')
    from_signal('contact_form', 'contact_form')
    from_signal('online_ordering', 'online_ordering')
    from_signal('online_booking', 'online_booking')
    from_signal('up_to_date', 'stale')
    mobile = signals.get('mobile')
    if 'phone_sideways_scroll' in lf and lf['phone_sideways_scroll']['gap']:
        found['mobile_layout'] = ('missing', lf['phone_sideways_scroll']['detail'], lf['phone_sideways_scroll']['evidence'])
    elif mobile:
        found['mobile_layout'] = ('has' if mobile['state'] == 'yes' else 'missing', mobile['detail'], mobile.get('evidence'))
    if 'phone_first_screen_contact' in lf:
        f = lf['phone_first_screen_contact']
        found['contact_first_screen'] = ('missing' if f['gap'] else 'has', f['detail'], f['evidence'])
    else:
        found['contact_first_screen'] = ('not_seen', 'Not measured: needs the phone view in Chrome.', None)
    call = 'call' in kinds or any(c['type'] == 'phone' for c in site.get('contacts', []) if c.get('origin') == 'visible_text' and c['page_kind'] == 'home')
    found['click_to_call'] = ('has', 'Has a tap-to-call link.', {'url': home, 'text': 'tel: link'}) if 'call' in kinds else \
        ('missing', 'No tap-to-call (tel:) link on the home page.' + (' The number is shown as plain text.' if call else ''),
         {'url': home, 'text': 'No tel: link'})
    whatsapp = signals.get('whatsapp')
    found['whatsapp_button'] = ('has', 'Has a WhatsApp link.', (whatsapp or {}).get('evidence')) if 'whatsapp' in kinds or \
        (whatsapp and whatsapp['state'] == 'yes') else ('missing', (whatsapp or {}).get('detail') or 'No WhatsApp link found.', {'url': home, 'text': 'No WhatsApp link'})
    pages = site.get('pages', [])
    if 'pdf_menu' in lf:
        found['menu_page'] = ('missing', lf['pdf_menu']['detail'], lf['pdf_menu']['evidence'])
    elif 'menu' in sections or any(p['kind'] == 'offer' and 'menu' in p['url'].casefold() and p['status'] == 'read' for p in pages):
        page = next((p['url'] for p in pages if 'menu' in p['url'].casefold()), home)
        found['menu_page'] = ('has', 'Has a menu on a web page.', {'url': page, 'text': 'Menu page'})
    text = ' '.join(e['text'] for e in site.get('excerpts', []))
    if 'listings' in sections or SEARCHABLE.search(text) or any(re.search(r'listing|propert', p['url'], re.I) and p['status'] == 'read' for p in pages):
        found['listings'] = ('has', 'Shows property listings.', {'url': home, 'text': (SEARCHABLE.search(text) or [None])[0] or 'Listings page'})
    elif any(p['status'] == 'read' for p in pages):
        found['listings'] = ('missing', f"No property listings seen on the {len([p for p in pages if p['status'] == 'read'])} pages read.",
                             {'url': home, 'text': 'No listings page or section'})
    if {'services', 'pricing'} & sections or any(p['kind'] == 'offer' and p['status'] == 'read' for p in pages):
        found['services_list'] = ('has', 'Has a services or prices page/section.', {'url': home, 'text': 'Services section'})
    rating = next((s['rating'] for s in site.get('structured', []) if s.get('rating')), None)
    if 'reviews' in sections or rating or any(p['kind'] == 'reviews' and p['status'] == 'read' for p in pages):
        found['reviews'] = ('has', 'Shows reviews or testimonials.', {'url': home, 'text': 'Reviews section'})
    elif 'no_reviews_section' in lf:
        found['reviews'] = ('missing', lf['no_reviews_section']['detail'], lf['no_reviews_section']['evidence'])
    if 'gallery' in sections or any(p['kind'] == 'gallery' and p['status'] == 'read' for p in pages):
        found['gallery'] = ('has', 'Has a photo gallery or portfolio.', {'url': home, 'text': 'Gallery'})
    if 'map' in sections:
        found['map_directions'] = ('has', 'Shows a map.', {'url': home, 'text': 'Embedded map'})
    hours = any(s.get('opening_hours') for s in site.get('structured', [])) or HOURS.search(text)
    if hours:
        found['opening_hours'] = ('has', 'Shows opening hours.', {'url': home, 'text': HOURS.search(text).group(0) if HOURS.search(text) else 'schema.org openingHours'})
    found['social_links'] = ('has', 'Links to social pages.', {'url': home, 'text': site['social_links'][0]}) if site.get('social_links') else \
        ('missing', 'No links to Instagram, Facebook or other social pages.', {'url': home, 'text': 'No social links'})
    seo, data = signals.get('seo_basics'), signals.get('structured_data')
    if seo and data:
        ok = seo['state'] == 'yes' and data['state'] == 'yes'
        found['search_basics'] = ('has' if ok else 'missing', seo['detail'] if seo['state'] != 'yes' else data['detail'], seo.get('evidence'))
    return found, True


def offer_fit(item, offer, offer_kind, status, chosen=None, overrides=None, rules=None):
    """Feature-by-feature comparison for one lead. chosen: the feature ids the user delivers (None = defaults).

    overrides: {feature: {'state', 'note', 'created_at'}}, the owner's corrections for this business; they replace detection.
    rules: approved learned rules; 'detector_off' (value "trade:feature") stops a detector the owner found unreliable."""
    trade = trade_of(item)
    offer_words = set(words(offer)) | set(re.findall(r'[a-z]+', offer.casefold()))
    detected, read = detect(item, status)
    off = {r['value'] for r in rules or [] if r['kind'] == 'detector_off'}
    for feature in list(detected):
        if f'{trade}:{feature}' in off and feature != 'own_website':
            detected[feature] = ('not_seen', 'Not judged: an approved rule switched this check off for this type of business.', None)
    no_site = status in NO_SITE
    rows = []
    for id_, label, _, weight, _, build in FEATURES:
        if not applies(id_, trade):
            continue
        default = relevant(id_, offer_kind, offer_words)
        enabled = (id_ in chosen) if chosen is not None else default
        if id_ in detected:
            state, detail, evidence = detected[id_]
        elif no_site and id_ != 'own_website':
            state, detail, evidence = 'missing', 'No website, so nothing like this online yet.', None
        elif not read:
            state, detail, evidence = 'not_seen', 'Website not read yet: use Check website.', None
        else:
            state, detail, evidence = 'not_seen', 'Not seen on the pages read (that does not prove they lack it).', None
        detected_state, override = state, (overrides or {}).get(id_)
        if override:
            # The owner's correction wins over detection, and says what LeadDesk had found.
            state = override['state']
            detail = (f"You said they {'have it' if state == 'has' else 'do not have it'}"
                      + (f": {override['note']}" if override.get('note') else '') + f". LeadDesk had found: {detail}")
            evidence = {'url': (evidence or {}).get('url') or item['evidence']['url'], 'text': f"Your correction ({override['created_at'][:10]})"}
        rows.append({'id': id_, 'label': label, 'state': state, 'detail': detail, 'evidence': evidence, 'weight': weight,
                     'build': build, 'enabled': enabled, 'default': default, 'detected_state': detected_state,
                     'corrected': bool(override)})
    competitors = (item.get('competitors') or {}).get('findings') or []
    return {'method': 'offer_fit_v1', 'trade': trade, 'trade_label': TRADE_LABEL[trade], 'website_read': read and not no_site,
            'no_website': no_site, 'features': rows, 'competitor_findings': [f['text'] for f in competitors[:3]],
            'counts': {s: sum(r['state'] == s and r['enabled'] for r in rows) for s in ('has', 'missing', 'not_seen')},
            'note': '"Not seen" means LeadDesk could not tell, not that they lack it. Untick what you do not deliver.'}


NO_SITE_OPENERS = {
    'none': lambda c: f"I looked for {c['name']} online{c['where']} and found {c['found_on']}, but no website of your own.",
    'social_only': lambda c: f"I looked for {c['name']} online{c['where']} and your {c['social']} page is the only site listed for you.",
    'dead_builder': lambda c: f"The website listed for {c['name']} ({c['listed']}) is a builder page that no longer works.",
    'unreachable': lambda c: f"I tried to open the website listed for {c['name']} ({c['listed']}) and it did not load.",
    # A site was read but is only a placeholder.
    'ok': lambda c: f"I opened {c['domain']} and it only shows a \"{c['placeholder']}\" page so far.",
}
OPENERS = {
    'own_website': lambda c: NO_SITE_OPENERS.get(c['status'], NO_SITE_OPENERS['none'])(c),
    'contact_first_screen': lambda c: f"I opened {c['domain']} on a phone and there is no Call or WhatsApp button until you scroll.",
    'mobile_layout': lambda c: (f"I opened {c['domain']} on a phone and the page scrolls sideways, so it does not fit the screen."
                                if c['mobile_measured'] else f"{c['domain']} is not set up for phones (it has no mobile layout setting)."),
    'menu_page': lambda c: f"Your menu on {c['domain']} is a PDF, which is hard to read on a phone.",
    'online_ordering': lambda c: f"I could not find a way to order online on {c['domain']}.",
    'online_booking': lambda c: f"I could not find a way to book online on {c['domain']}.",
    'listings': lambda c: f"I could not find your property listings on {c['domain']}.",
    'https': lambda c: f"Browsers show {c['domain']} as \"Not secure\".",
    'whatsapp_button': lambda c: f"There is no WhatsApp button on {c['domain']}.",
    'click_to_call': lambda c: f"Visitors to {c['domain']} cannot tap to call you.",
    'contact_form': lambda c: f"I could not find an enquiry form on {c['domain']}, so visitors can only call or email.",
    'reviews': lambda c: f"{c['domain']} does not show any customer reviews or testimonials.",
    'gallery': lambda c: f"{c['domain']} has no photo gallery of your work or place.",
    'map_directions': lambda c: f"{c['domain']} has no map or directions to find you.",
    'opening_hours': lambda c: f"I could not find your opening hours on {c['domain']}.",
    'social_links': lambda c: f"{c['domain']} does not link to your social pages.",
    'search_basics': lambda c: f"{c['domain']} is missing basic details Google uses to show your business.",
    'up_to_date': lambda c: f"{c['domain']} looks out of date (an old copyright year).",
    'services_list': lambda c: f"I could not find a clear list of your services and prices on {c['domain']}.",
}
# Questions about an existing website are not asked of a business that has none.
SITE_QUESTIONS = {'contact_first_screen', 'click_to_call', 'mobile_layout', 'https', 'search_basics', 'up_to_date', 'whatsapp_button', 'contact_form'}
QUESTIONS = {
    'own_website': 'How do new customers find you online today?',
    'contact_first_screen': 'How do most customers contact you now: calls, WhatsApp or walk-ins?',
    'click_to_call': 'How do most customers contact you now: calls, WhatsApp or walk-ins?',
    'whatsapp_button': 'Do customers already message you on WhatsApp?',
    'mobile_layout': 'Have customers mentioned the site is hard to use on a phone?',
    'online_ordering': 'How do customers order from you today, and do you use delivery apps?',
    'online_booking': 'How do customers book today, and how much staff time does that take?',
    'menu_page': 'How often do your menu or prices change?',
    'listings': 'How do you share new properties with buyers today?',
    'reviews': 'Do you collect reviews from happy customers?',
    'https': 'Who looks after your website at the moment?',
    'search_basics': 'Who looks after your website at the moment?',
    'up_to_date': 'Who looks after your website at the moment?',
    'contact_form': 'How do enquiries reach you today?',
}


def offer_sentence(offer, name):
    """The user's own words: "We design websites for cafes" stays as written; "Modern websites for cafes" gets "I work on"."""
    text = ' '.join(offer.strip().rstrip('.').split())
    first = text.split(' ', 1)[0].casefold() if text else ''
    if first in {'we', 'i', 'our', 'my'}:
        return f"{text[0].upper() + text[1:]}; happy to show what that could look like for {name}."
    return f"I work on {text[0].lower() + text[1:]}; happy to show what that could look like for {name}."


def pitch(item, offer, fit, location='', status=None):
    """Rules-first pitch: fit with points, top gaps, what we would build, opening line and questions, all cited."""
    evidence, ids = [], {}

    def cite(key, text, url):
        if key not in ids:
            ids[key] = f'E{len(evidence) + 1}'
            evidence.append({'id': ids[key], 'text': text[:300], 'url': url})
        return ids[key]

    gaps = [r for r in fit['features'] if r['enabled'] and r['state'] == 'missing']
    gaps.sort(key=lambda r: -r['weight'])
    for r in gaps:
        cite(r['id'], f"{r['label']}: {r['detail']}" + (f" ({r['evidence']['text']})" if r.get('evidence') and r['evidence'].get('text') else ''),
             (r.get('evidence') or {}).get('url') or item['evidence']['url'])
    points, reasons = 0, []
    if fit['no_website'] and any(r['id'] == 'own_website' for r in gaps):
        points += 3
        reasons.append({'text': 'No website of their own (+3)', 'evidence_ids': [ids['own_website']]})
    for r in [g for g in gaps if g['id'] != 'own_website'][:5]:
        add = 2 if r['weight'] >= 5 else 1
        points += add
        reasons.append({'text': f"Missing: {r['label'].lower()} (+{add})", 'evidence_ids': [ids[r['id']]]})
    review = item.get('contact_review')
    reachable = bool(review['best_phone'] or review['best_email']) if review else \
        bool(item.get('phone') or item.get('phones') or item.get('email') or (item.get('enrichment') or {}).get('contacts'))
    if reachable:
        points += 1
        reasons.append({'text': 'Has a phone or email that passed the contact review (+1)', 'evidence_ids': []})
    if not fit['website_read'] and not fit['no_website']:
        verdict = 'unknown'
        summary = 'Their website has not been read yet, so LeadDesk cannot say what is missing. Use Check website.'
    elif fit['no_website']:
        verdict = 'likely' if points >= 3 else 'possible'
        summary = ('No working website of their own, so everything you deliver would be new for them: '
                   + ', '.join(r['label'].lower() for r in gaps if r['id'] != 'own_website')[:200] + '.')
    else:
        verdict = 'likely' if points >= 4 else 'possible' if points >= 2 else 'unlikely'
        summary = (f"{len(gaps)} of the {sum(r['enabled'] for r in fit['features'])} things you deliver are missing: "
                   + ', '.join(r['label'].lower() for r in gaps[:4]) + '.') if gaps else 'Nothing you deliver is clearly missing on the pages read.'
    competitor = (fit.get('competitor_findings') or [None])[0]
    if competitor:
        cite('competitors', competitor, item['evidence']['url'])
    site = (item.get('check') or {}).get('site') or {}
    home = site['pages'][0]['url'] if site.get('pages') else None
    socials = [s['platform'] for s in item.get('site_socials') or []] + [p['platform'] for p in (item.get('enrichment') or {}).get('social_pages', [])]
    socials += [host(u).split('.')[0].title() for u in item.get('socials') or []]
    found_on = (f'your {socials[0]} page' if socials else 'your map listing')
    listed = (item.get('check') or {}).get('unreachable', {}).get('url') or item.get('website') or ''
    social = 'Facebook' if 'facebook' in listed or 'fb.com' in listed else 'Instagram' if 'instagram' in listed else (socials or ['social'])[0]
    context = {'name': item['name'], 'domain': host(home) if home else 'your website', 'found_on': found_on, 'status': status or 'none',
               'mobile_measured': any(f['id'] == 'phone_sideways_scroll' and f['gap'] for f in (site.get('layout') or {}).get('findings', [])),
               'listed': host(listed) if listed else 'your website', 'social': social,
               'placeholder': next((f['evidence']['text'] for f in (site.get('layout') or {}).get('findings', []) if f['id'] == 'placeholder_site'), 'coming soon'),
               'where': f" in {location.split(',')[0].strip()}" if location else ''}
    lead_gap = next((g for g in gaps if g['id'] in OPENERS), None)
    sentences = []
    if lead_gap:
        sentences.append({'text': OPENERS[lead_gap['id']](context), 'evidence_ids': [ids[lead_gap['id']]]})
        if competitor:
            sentences.append({'text': competitor.rstrip('.') + '.', 'evidence_ids': [ids['competitors']]})
        sentences.append({'text': offer_sentence(offer, item['name']), 'evidence_ids': []})
    questions, seen = [], set()
    for g in gaps:
        q = QUESTIONS.get(g['id'])
        if fit['no_website'] and g['id'] in SITE_QUESTIONS:
            continue
        if q and q not in seen:
            seen.add(q)
            questions.append({'text': q, 'evidence_ids': [ids[g['id']]]})
        if len(questions) == 3:
            break
    plan = [{'id': r['id'], 'label': r['label'], 'action': {'has': 'keep', 'missing': 'add' if r['id'] != 'mobile_layout' or fit['no_website'] else 'fix',
                                                            'not_seen': 'check'}[r['state']], 'build': r['build'],
             'evidence_ids': [ids[r['id']]] if r['id'] in ids else []}
            for r in sorted(fit['features'], key=lambda r: -r['weight']) if r['enabled']]
    if any(r['id'] == 'menu_page' and r['state'] == 'missing' and 'PDF' in r['detail'] for r in fit['features']):
        for step in plan:
            if step['id'] == 'menu_page':
                step['action'] = 'fix'
    message = ' '.join(s['text'] for s in sentences)
    return {'method': 'pitch_v1', 'fit': verdict, 'points': points, 'reasons': reasons, 'summary': summary,
            'top_gaps': [{'id': g['id'], 'label': g['label'], 'detail': g['detail'], 'evidence_ids': [ids[g['id']]]} for g in gaps[:3]],
            'build_plan': plan, 'opening': sentences, 'message': message, 'questions': questions, 'evidence': evidence,
            'note': 'Written by LeadDesk from the checks above, not by AI. Every sentence cites what it rests on; check before sending.'}


class Polished(BaseModel):
    model_config = ConfigDict(extra='ignore')
    message: str = Field(min_length=10, max_length=700)


FRIENDLY = set('''hello thanks quick idea happy glad would could love share show chat noticed visited checked looked help helps
simple small easier easily currently today honest friendly greetings regards really hours business''' .split())
BANNED = re.compile(r'seller|_\w+|\bE\d+\b|[{}]|follow(?:ing)? up|as discussed|previous', re.I)
# Promised results: allowed only when the facts or the user's own offer already say so.
PROMISES = re.compile(r'guarantee\w*|increas\w*|boost\w*|double\w*|revenue|sales|profit\w*|more customers|grow\w*', re.I)


def polish_prompt(item, offer, plan):
    """Only the facts of the template; no keys or ids the model could echo back."""
    facts = [s['text'] for s in plan['opening']] + [g['detail'] for g in plan['top_gaps']]
    return json.dumps({
        'instruction': ('Rewrite the draft as a short, friendly first message to a business owner, in 2 or 3 sentences. '
                        'Keep every fact. Do not add any new fact, number, name, price, result or promise. '
                        'Do not say you spoke before. Return JSON {"message": "..."} only.'),
        'business': item['name'], 'what_i_sell': offer[:300], 'draft': plan['message'], 'facts': facts,
    }, ensure_ascii=False)


def check_polish(text, item, offer, plan):
    """Accepts the reworded message only if it adds nothing. Returns (message or None, reasons)."""
    try:
        message = Polished.model_validate_json(text).message.strip()
    except (ValidationError, ValueError):
        return None, ['The AI did not return a message in the requested format.']
    sources = [plan['message'], offer, item['name']] + [g['detail'] for g in plan['top_gaps']] + [e['text'] for e in plan['evidence']]
    problems = []
    added = [w for w in unsupported_terms(message, sources) if w not in FRIENDLY]
    if added:
        problems.append('adds words not in the facts: ' + ', '.join(added[:6]))
    known_numbers = set(re.findall(r'\d+', ' '.join(sources)))
    new_numbers = [n for n in re.findall(r'\d+', message) if n not in known_numbers]
    if new_numbers:
        problems.append('adds numbers: ' + ', '.join(new_numbers[:4]))
    if PRIOR_CONTACT.search(message) or BANNED.search(message):
        problems.append('implies earlier contact or contains field names')
    promised = [m.group(0) for m in PROMISES.finditer(message) if m.group(0).casefold() not in ' '.join(sources).casefold()]
    if promised:
        problems.append('promises results: ' + ', '.join(promised[:3]))
    if item['name'].casefold() not in message.casefold():
        problems.append('drops the business name')
    return (None if problems else message), problems


def polish_record(run, plan, message, problems):
    return {'method': 'ollama_pitch_polish_v1', 'status': 'proposal', 'accepted': message is not None,
            'message': message or plan['message'], 'template_message': plan['message'], 'rejected_reasons': problems,
            'model': run['model'], 'model_digest': run['model_digest'], 'provider': run.get('provider'), 'seconds': run['seconds'],
            'tokens': run.get('tokens'),
            'note': 'AI only reworded LeadDesk\'s message. ' + ('Its wording was checked against the facts.' if message else
                                                                 'Its wording was rejected, so LeadDesk\'s own wording is kept.')}


def require_plan(plan):
    if plan['fit'] == 'unknown':
        raise ResearchError('Check their website first, so the message rests on what it shows.', status=409)
    if not plan['opening']:
        raise ResearchError('Nothing you deliver is clearly missing for this business, so there is no message to write.', status=409)
