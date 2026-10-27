"""Website layout: what a visitor sees and where, as evidence-backed findings (site_layout_v1).

Two sources:
- rendered: measurements from Chrome at desktop (1366 px) and phone (390 px) width (adapters/browser_render.LAYOUT_JS);
- html: an outline from the page source only, when Chrome is off or unavailable. Anything that needs positions or
  sizes (first screen, sideways scrolling, text and button sizes) is then "unmeasured", never guessed.
Each finding carries the page URL and the visible text or measurement it rests on.
"""
import re
from html.parser import HTMLParser

ACTION_WORDS = (
    ('call', re.compile(r'\b(call( us| now)?|phone)\b', re.I)),
    ('whatsapp', re.compile(r'whatsapp', re.I)),
    ('book', re.compile(r'\b(book|reserve|reservation|appointment|schedule)\b', re.I)),
    ('order', re.compile(r'\b(order|add to cart|cart|buy|shop now|checkout)\b', re.I)),
    ('enquire', re.compile(r'\b(contact|enquir\w*|inquir\w*|get a quote|quote|message us|email us)\b', re.I)),
    ('menu', re.compile(r'\bmenu\b', re.I)),
)
SECTION_WORDS = {
    'menu': re.compile(r'\bmenu\b|our food|dishes'), 'services': re.compile(r'\bservices?\b|what we do|treatments|solutions'),
    'products': re.compile(r'\bproducts?\b|\bshop\b|collection'), 'gallery': re.compile(r'gallery|portfolio|photos|our work|projects'),
    'reviews': re.compile(r'reviews?|testimonials?|what (our )?(clients|customers|patients) say|ratings'),
    'pricing': re.compile(r'pricing|prices|packages|\bplans\b'), 'faq': re.compile(r'\bfaq\b|frequently asked'),
    'team': re.compile(r'\bteam\b|our doctors|our staff|meet the|agents'), 'about': re.compile(r'about|our story|who we are'),
    'contact': re.compile(r'contact|get in touch|find us|visit us'), 'listings': re.compile(r'listings|properties|for sale|for rent'),
    'booking': re.compile(r'\bbook|appointment|reservation'), 'hours': re.compile(r'opening hours|timings|\bhours\b'),
}
SECTION_LABELS = {'hero': 'Top banner (hero)', 'menu': 'Menu', 'services': 'Services', 'products': 'Products / shop', 'gallery': 'Gallery / portfolio',
                  'reviews': 'Reviews / testimonials', 'pricing': 'Prices / packages', 'faq': 'FAQ', 'team': 'Team', 'about': 'About',
                  'contact': 'Contact', 'listings': 'Listings', 'booking': 'Booking', 'hours': 'Opening hours', 'map': 'Map', 'footer': 'Footer'}
ACTION_LABELS = {'call': 'Call', 'whatsapp': 'WhatsApp', 'book': 'Book', 'order': 'Order', 'enquire': 'Enquire / contact', 'menu': 'Menu'}
MAP_SRC = re.compile(r'google\.[a-z.]+/maps|maps\.google|openstreetmap', re.I)


class Outline(HTMLParser):
    """Navigation, headings, sections and action links from HTML, without running scripts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nav, self.headings, self.actions, self.sections, self.iframes, self.pdf_links = [], [], [], {}, [], []
        self.stack, self.text, self.link, self.heading, self.blocks, self.events = [], [], None, None, [], 0

    def handle_starttag(self, tag, attrs):
        self.events += 1
        if self.events > 150000:
            return
        attrs = {k.casefold(): (v or '') for k, v in attrs}
        if tag in {'section', 'header', 'footer', 'article', 'div'} and (tag != 'div' or attrs.get('id')):
            label = f"{attrs.get('id', '')} {attrs.get('class', '')} {attrs.get('aria-label', '')}".casefold()
            self.blocks.append({'tag': tag, 'label': label, 'heading': None})
            if tag == 'footer':
                self.sections.setdefault('footer', {'heading': ''})
        if tag in {'nav', 'header'}:
            self.stack.append(tag)
        if tag in {'h1', 'h2', 'h3'}:
            self.heading = {'level': int(tag[1]), 'parts': []}
        elif tag in {'a', 'button'}:
            self.link = {'href': attrs.get('href', '')[:200], 'parts': [attrs.get('aria-label', '') or attrs.get('title', '')]}
        elif tag == 'iframe' and attrs.get('src') and len(self.iframes) < 10:
            self.iframes.append(attrs['src'][:300])

    def handle_endtag(self, tag):
        if tag in {'nav', 'header'} and tag in self.stack:
            self.stack.remove(tag)
        if tag in {'h1', 'h2', 'h3'} and self.heading:
            text = ' '.join(''.join(self.heading['parts']).split())[:80]
            if text and len(self.headings) < 40:
                self.headings.append({'level': self.heading['level'], 'text': text})
                for block in reversed(self.blocks[-5:]):
                    if block['heading'] is None:
                        block['heading'] = text
                        break
            self.heading = None
        elif tag in {'a', 'button'} and self.link:
            text = ' '.join(' '.join(self.link['parts']).split())[:80]
            href = self.link['href'].casefold()
            if self.stack and text and len(text) <= 40 and text not in self.nav and len(self.nav) < 15:
                self.nav.append(text)
            kind = action_kind(text, href)
            if kind and len(self.actions) < 60:
                self.actions.append({'kind': kind, 'text': text or href[:60], 'href': href})
            if href.split('?')[0].endswith('.pdf') and len(self.pdf_links) < 10:
                self.pdf_links.append({'text': text, 'href': self.link['href']})
            self.link = None

    def handle_data(self, data):
        if self.heading is not None:
            self.heading['parts'].append(data)
        if self.link is not None:
            self.link['parts'].append(data)

    def result(self):
        for block in self.blocks[:300]:
            label = f"{block['label']} {(block['heading'] or '').casefold()}"
            for kind, pattern in SECTION_WORDS.items():
                if kind not in self.sections and pattern.search(label):
                    self.sections[kind] = {'heading': block['heading'] or ''}
        if any(MAP_SRC.search(src) for src in self.iframes):
            self.sections.setdefault('map', {'heading': 'Map'})
        h1 = next((h for h in self.headings if h['level'] == 1), None)
        if h1:
            self.sections.setdefault('hero', {'heading': h1['text']})
        return {'nav': self.nav, 'headings': self.headings, 'actions': self.actions, 'sections': self.sections,
                'iframes': self.iframes, 'pdf_links': self.pdf_links}


def action_kind(text, href):
    if href.startswith('tel:'):
        return 'call'
    if 'wa.me' in href or 'whatsapp' in href:
        return 'whatsapp'
    if href.startswith('mailto:'):
        return 'enquire'
    for kind, pattern in ACTION_WORDS:
        if pattern.search(text or ''):
            if kind == 'menu' and re.search(r'\b(main menu|toggle|open menu|close)\b', text, re.I):
                return None
            return kind
    return None


def outline(html):
    parser = Outline()
    parser.feed(html[:3_000_000])
    return parser.result()


def finding(id_, label, state, detail, evidence, gap=False, measured=True):
    return {'id': id_, 'label': label, 'state': state, 'detail': detail, 'evidence': evidence, 'gap': gap, 'measured': measured}


def analyse(url, desktop=None, phone=None, html=None, screens=None, rendered_note=None):
    """Layout summary and findings. desktop/phone: rendered measurements; html: page source for the outline fallback."""
    rendered = desktop is not None
    base = desktop if rendered else outline(html or '')
    sections = [{'id': k, 'label': SECTION_LABELS.get(k, k), 'heading': v.get('heading') or '', 'y': v.get('y')}
                for k, v in base.get('sections', {}).items()]
    sections.sort(key=lambda s: (s['y'] is None, s['y'] or 0))
    actions = list(base.get('actions', []))
    # Some sites show buttons only in their phone layout (a floating WhatsApp button): count both views.
    seen_actions = {(a['kind'], a['text']) for a in actions}
    actions += [a for a in (phone or {}).get('actions', []) if (a['kind'], a['text']) not in seen_actions]
    kinds = {a['kind'] for a in actions}
    findings = []

    def ev(text):
        return {'url': url, 'text': text[:200]}

    reach = [a for a in actions if a['kind'] in {'call', 'whatsapp'}]
    findings.append(finding('call_or_whatsapp_button', 'Call or WhatsApp button', 'yes' if reach else 'not_found',
                            f"Has a {', '.join(sorted({ACTION_LABELS[a['kind']] for a in reach}))} button or link." if reach else
                            'No call (tel:) or WhatsApp button found on the home page.',
                            ev(f"{reach[0]['text']} → {reach[0]['href']}") if reach else ev('No tel: or WhatsApp link'), gap=not reach))
    if phone is not None:
        first = [a for a in phone.get('actions', []) if a['kind'] in {'call', 'whatsapp'} and a.get('first_screen')]
        findings.append(finding('phone_first_screen_contact', 'Call/WhatsApp visible on the first phone screen', 'yes' if first else 'no',
                                f"On a phone, \"{first[0]['text']}\" shows without scrolling." if first else
                                'On a phone, no Call or WhatsApp button shows without scrolling.',
                                ev(first[0]['text'] if first else f"Phone screen {PHONE_W} px wide, first {phone.get('viewport', {}).get('h', 844)} px"),
                                gap=not first))
        if phone.get('overflow'):
            findings.append(finding('phone_sideways_scroll', 'Fits a phone screen', 'no', 'The page scrolls sideways on a phone: something is wider than the screen.',
                                    ev(f"page wider than {PHONE_W} px"), gap=True))
        else:
            findings.append(finding('phone_sideways_scroll', 'Fits a phone screen', 'yes', 'No sideways scrolling on a phone.', ev(f'{PHONE_W} px wide')))
        sampled = phone.get('text_sampled') or 0
        if sampled >= 10 and phone.get('tiny_text', 0) / sampled > .2:
            findings.append(finding('phone_tiny_text', 'Readable text size on phones', 'no',
                                    f"{phone['tiny_text']} of {sampled} text blocks are smaller than 12 px on a phone.",
                                    ev(f"{phone['tiny_text']}/{sampled} under 12 px"), gap=True))
        taps = phone.get('taps_checked') or 0
        if taps >= 10 and phone.get('small_taps', 0) / taps > .3:
            findings.append(finding('phone_small_buttons', 'Buttons easy to tap', 'no',
                                    f"{phone['small_taps']} of {taps} links and buttons are smaller than 24 px, hard to tap.",
                                    ev(f"{phone['small_taps']}/{taps} under 24 px"), gap=True))
    booking = [a for a in actions if a['kind'] in {'book', 'order'}]
    if booking:
        findings.append(finding('booking_or_order_button', 'Book or order button', 'yes', f"Has \"{booking[0]['text']}\".",
                                ev(f"{booking[0]['text']} → {booking[0]['href']}")))
    menu_pdf = [p for p in base.get('pdf_links', []) if re.search(r'menu|price|rate|brochure|catalog', f"{p['text']} {p['href']}", re.I)]
    if menu_pdf:
        findings.append(finding('pdf_menu', 'Menu or prices as a web page', 'no',
                                f"The {menu_pdf[0]['text'] or 'menu'} is a PDF file, hard to read on a phone and invisible to Google.",
                                ev(f"{menu_pdf[0]['text']} → {menu_pdf[0]['href']}"), gap=True))
    if rendered:
        if desktop.get('broken_images'):
            findings.append(finding('broken_images', 'Images load', 'no', f"{desktop['broken_images']} image(s) fail to load.",
                                    ev(f"{desktop['broken_images']} of {desktop.get('images', '?')} images broken"), gap=True))
        if (desktop.get('words') or 0) < 60:
            findings.append(finding('little_text', 'Enough content', 'no', f"The home page shows only about {desktop.get('words', 0)} words.",
                                    ev(f"{desktop.get('words', 0)} words"), gap=True))
    if 'reviews' not in {s['id'] for s in sections}:
        findings.append(finding('no_reviews_section', 'Reviews or testimonials', 'not_found', 'No reviews or testimonials section seen on the home page.',
                                ev('No section named reviews/testimonials'), gap=True))
    unmeasured = [] if phone is not None else ['first phone screen', 'sideways scrolling', 'text size', 'button size']
    on_phone = {(a['kind'], a['text']) for a in (phone or {}).get('actions', []) if a.get('first_screen')}
    return {
        'method': 'site_layout_v1', 'source': 'rendered' if rendered else 'html',
        'note': (rendered_note or 'Measured in Chrome at desktop (1366 px) and phone (390 px) width.') if rendered else
                'Outline from the page source only. Turn on "Read JavaScript websites with Chrome" to measure the phone view.',
        'nav': base.get('nav', [])[:15], 'headings': base.get('headings', [])[:25], 'sections': sections,
        'actions': [{'kind': a['kind'], 'label': ACTION_LABELS[a['kind']], 'text': a['text'], 'href': a['href'],
                     'first_screen_phone': ((a['kind'], a['text']) in on_phone) if phone is not None else None} for a in actions[:20]],
        'action_kinds': sorted(kinds), 'sticky_header': desktop.get('sticky_header') if rendered else None,
        'page_height': desktop.get('page_height') if rendered else None, 'words': desktop.get('words') if rendered else None,
        'findings': findings, 'unmeasured': unmeasured, 'screens': screens or {}, 'url': url,
    }


PHONE_W = 390
# Pages a site shows automated browsers instead of its content. LeadDesk never tries to get past them.
CHALLENGE = re.compile(r'checking your browser|just a moment\.\.\.|attention required|verify (?:you are|that you are) (?:a )?human|'
                       r'are you a robot|ddos protection|cf-browser-verification|captcha|access denied|enable javascript and cookies to continue|'
                       r'request unsuccessful\. incapsula|pardon our interruption', re.I)


PLACEHOLDER = re.compile(r'coming soon|opening soon|launching soon|under construction|site is under maintenance|website is under maintenance|'
                         r'we(?:\'re| are) (?:launching|coming) soon|new website (?:is )?coming|domain (?:is )?for sale|this domain is parked', re.I)


def placeholder(title, lines):
    """'Coming soon', 'under construction' or parked-domain text on the home page, or None."""
    match = PLACEHOLDER.search(' '.join([title or ''] + list(lines[:30]))[:6000])
    return match.group(0) if match else None


def challenge(html):
    """The text of a bot-check page, or None."""
    text = re.sub(r'<script.*?</script>|<style.*?</style>|<[^>]+>', ' ', (html or '')[:200_000], flags=re.I | re.S)
    match = CHALLENGE.search(' '.join(text.split())[:5000])
    return match.group(0) if match else None


def thin(html, visible_words):
    """The page source shows almost nothing: a JavaScript app or site builder that draws the page in the browser."""
    shell = re.search(r'<div[^>]+id=["\'](?:root|app|__next|___gatsby|svelte)["\'][^>]*>\s*</div>', html or '', re.I)
    return visible_words < 80 or bool(shell and visible_words < 200)
