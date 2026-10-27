"""Read a business website properly: home, Contact/About/offer pages, structured data and need signals.

Deterministic and bounded. Every signal keeps the page URL and the text that
triggered it. "not_found" means not seen on the pages read, never "they lack it".
"""
import hashlib
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from backend.domain.enrichment import classify, fold, host
from backend.domain.errors import ResearchError
from backend.domain.extract import VisiblePage, extract
from backend.domain.prospecting import words
from backend.domain.site_health import health
from backend.domain.site_layout import analyse as analyse_layout, challenge, finding, placeholder, thin

MAX_EXTRA_PAGES = 5
MAX_RENDERS = 4  # Chrome renders per site read (home counts as one), only for pages whose source is nearly empty
MAX_JSONLD = 20
PAGE_KINDS = {
    'contact': re.compile(r'contact|reach[- ]?us|get[- ]in[- ]touch|find[- ]us|visit[- ]us|location|branches|stores?[- ]locator|imprint|impressum', re.I),
    'about': re.compile(r'about|our[- ]story|who[- ]we[- ]are|company|history', re.I),
    'offer': re.compile(r'menu|order|shop|store|products?|services?|pricing|prices|book|reserv|appointments?|catalog|listings?|properties', re.I),
    'reviews': re.compile(r'reviews?|testimonials?|what[- ]clients[- ]say', re.I),
    'gallery': re.compile(r'gallery|portfolio|our[- ]work|projects|photos', re.I),
    'team': re.compile(r'our[- ]team|team|doctors|staff|agents|meet[- ]the', re.I),
}
SKIP_EXT = re.compile(r'\.(pdf|jpe?g|png|gif|webp|svg|zip|docx?|xlsx?|mp4|mp3)$', re.I)
NON_BUSINESS = {'WebSite', 'WebPage', 'BreadcrumbList', 'ListItem', 'ImageObject', 'SearchAction', 'ReadAction', 'Person', 'Article',
                'BlogPosting', 'NewsArticle', 'CollectionPage', 'ItemList', 'SiteNavigationElement', 'PostalAddress', 'GeoCoordinates',
                'OpeningHoursSpecification', 'ContactPoint', 'Offer', 'AggregateOffer', 'Product', 'Review', 'AggregateRating', 'Rating',
                'FAQPage', 'Question', 'Answer', 'VideoObject', 'Event', 'Menu', 'MenuSection', 'MenuItem', 'EntryPoint', 'Place',
                'WPHeader', 'WPFooter', 'WPSideBar', 'ProfilePage', 'AboutPage', 'ContactPage', 'Brand', 'HowTo', 'Recipe'}
ORDERING_TEXT = re.compile(r"\b(order (?:online|now|here|food|delivery|pickup)|online order(?:ing|s)?|add to (?:cart|basket|bag)|checkout|"
                           r"shop now|buy now|place (?:an |your )?order|view cart|my cart)\b", re.I)
ORDERING_HOSTS = ('foodpanda', 'ubereats', 'deliveroo', 'doordash', 'grubhub', 'talabat', 'careem', 'swiggy', 'zomato', 'toasttab',
                  'order.online', 'square.site', 'myshopify', 'chownow', 'slicelife', 'menufy', 'gloriafood', 'just-eat', 'justeat', 'wolt')
BOOKING_TEXT = re.compile(r"\b(book (?:now|online|a table|an appointment|your|a session|a consultation)|reserve (?:a table|now|online|your)|"
                          r"make a reservation|reservations?|schedule (?:an |a )?(?:appointment|call|visit|consultation)|appointment booking)\b", re.I)
BOOKING_HOSTS = ('calendly', 'opentable', 'resy', 'setmore', 'fresha', 'booksy', 'simplybook', 'acuityscheduling', 'sevenrooms',
                 'tablein', 'eatapp', 'zocdoc', 'vagaro', 'mindbody', 'square.site/book', 'squareup.com/appointments', 'tidycal', 'youcanbook')
PLATFORMS = (('wp-content', 'WordPress'), ('wordpress', 'WordPress'), ('wixstatic', 'Wix'), ('wix.com', 'Wix'), ('cdn.shopify', 'Shopify'),
             ('squarespace', 'Squarespace'), ('webflow', 'Webflow'), ('wsimg.com', 'GoDaddy Website Builder'), ('weebly', 'Weebly'),
             ('blogger.com', 'Blogger'), ('joomla', 'Joomla'), ('drupal', 'Drupal'), ('framer', 'Framer'), ('godaddy', 'GoDaddy Website Builder'))
COPYRIGHT = re.compile(r"(?:©|\(c\)|copyright)\s*(?:\d{4}\s*[-–]\s*)?((?:19|20)\d{2})", re.I)
# Words in the user's product description that make a signal relevant to them.
TOPICS = {
    'https': {'website', 'websites', 'web', 'security', 'ssl', 'hosting', 'seo', 'cybersecurity'},
    'mobile': {'website', 'websites', 'web', 'mobile', 'responsive', 'design', 'seo', 'app', 'apps'},
    'online_ordering': {'order', 'ordering', 'orders', 'delivery', 'ecommerce', 'e-commerce', 'shop', 'store', 'cart', 'pos', 'menu',
                        'menus', 'checkout', 'payments', 'takeaway'},
    'online_booking': {'booking', 'bookings', 'appointment', 'appointments', 'reservation', 'reservations', 'schedule', 'scheduling',
                       'calendar'},
    'contact_form': {'leads', 'lead', 'crm', 'forms', 'form', 'chat', 'chatbot', 'enquiries', 'inquiries'},
    'whatsapp': {'whatsapp', 'chat', 'chatbot', 'messaging', 'crm', 'support'},
    'structured_data': {'seo', 'google', 'search', 'ranking', 'rankings', 'local', 'listing', 'listings', 'maps', 'marketing', 'visibility'},
    'seo_basics': {'seo', 'google', 'search', 'ranking', 'rankings', 'marketing', 'visibility', 'content'},
    'stale': {'website', 'websites', 'web', 'redesign', 'design', 'maintenance', 'content', 'refresh'},
}
WEB_BASICS = {'https', 'mobile', 'stale', 'seo_basics', 'structured_data'}


class SiteScan(HTMLParser):
    """Metadata a visible-text parser ignores: title, meta tags, JSON-LD, links, forms, script hosts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.meta, self.jsonld, self.links, self.forms, self.srcs = [], {}, [], [], [], []
        self.in_title = self.in_jsonld = False
        self.buffer, self.link, self.form, self.events = [], None, None, 0
        # For the health report: images, legacy markup, plain-HTTP resources and the doctype.
        self.images, self.images_without_alt, self.tables, self.legacy_tags, self.flash, self.doctype = 0, 0, 0, 0, False, False
        self.insecure = []

    def handle_starttag(self, tag, attrs):
        self.events += 1
        if self.events > 180000:
            raise ResearchError('This HTML page is too complex to inspect within the research limit.')
        attrs = {k.casefold(): (v or '') for k, v in attrs}
        resource = attrs.get('src') or (attrs.get('href') if tag == 'link' else '')
        if resource.startswith('http://') and len(self.insecure) < 10:
            self.insecure.append(resource[:300])
        if tag == 'img':
            self.images += 1
            self.images_without_alt += 'alt' not in attrs
        elif tag == 'table':
            self.tables += 1
        elif tag in {'font', 'center', 'marquee', 'frameset', 'blink'}:
            self.legacy_tags += 1
        elif tag in {'embed', 'object'} and ('.swf' in (attrs.get('src') or attrs.get('data') or '').casefold()
                                            or 'flash' in attrs.get('type', '').casefold()):
            self.flash = True
        if tag == 'title':
            self.in_title = True
        elif tag == 'meta':
            name = (attrs.get('name') or attrs.get('property') or '').casefold()
            if name and name not in self.meta:
                self.meta[name] = attrs.get('content', '')[:500]
        elif tag == 'script':
            if attrs.get('type', '').casefold() == 'application/ld+json' and len(self.jsonld) < MAX_JSONLD:
                self.in_jsonld, self.buffer = True, []
            if attrs.get('src'):
                self.srcs.append(attrs['src'][:500])
        elif tag in {'iframe', 'link'} and (attrs.get('src') or attrs.get('href')):
            self.srcs.append((attrs.get('src') or attrs.get('href'))[:500])
        elif tag == 'a':
            self.link = {'href': attrs.get('href', '')[:1000], 'label': []}
        elif tag == 'form':
            self.form = {'action': attrs.get('action', '')[:300], 'fields': set()}
        elif tag in {'input', 'textarea', 'select'} and self.form is not None:
            self.form['fields'].add('textarea' if tag == 'textarea' else attrs.get('type', 'text').casefold())

    def handle_decl(self, decl):
        self.doctype = self.doctype or decl.casefold().startswith('doctype')

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        elif tag == 'script' and self.in_jsonld:
            self.in_jsonld = False
            self.jsonld.append(''.join(self.buffer)[:300_000])
        elif tag == 'a' and self.link is not None:
            self.links.append((self.link['href'], ' '.join(''.join(self.link['label']).split())[:200]))
            self.link = None
        elif tag == 'form' and self.form is not None:
            self.forms.append(self.form)
            self.form = None

    def handle_data(self, data):
        if self.in_jsonld:
            self.buffer.append(data)
        elif self.in_title:
            self.title.append(data)
        if self.link is not None:
            self.link['label'].append(data)


def text(value, limit=200):
    if isinstance(value, dict):
        value = value.get('name') or value.get('@id') or ''
    if isinstance(value, list):
        value = ', '.join(text(v, limit) for v in value[:5])
    return ' '.join(str(value or '').split())[:limit]


def as_list(value):
    return value if isinstance(value, list) else ([] if value in (None, '') else [value])


def postal(value):
    if isinstance(value, str):
        return text(value, 300)
    if isinstance(value, dict):
        parts = [value.get(k) for k in ('streetAddress', 'addressLocality', 'addressRegion', 'postalCode', 'addressCountry')]
        return ', '.join(text(p, 120) for p in parts if text(p, 120)) or None
    return None


def entities(value, depth=0):
    if depth > 4:
        return
    if isinstance(value, list):
        for item in value[:50]:
            yield from entities(item, depth + 1)
    elif isinstance(value, dict):
        if '@graph' in value:
            yield from entities(value['@graph'], depth + 1)
        if '@type' in value:
            yield value
        for key in ('department', 'subOrganization', 'location', 'branchOf', 'parentOrganization'):
            if key in value:
                yield from entities(value[key], depth + 1)


def structured_data(blocks):
    """schema.org business entities from JSON-LD. Self-published by the site: it says who it claims to be."""
    found, seen = [], set()
    for block in blocks:
        try:
            data = json.loads(block, strict=False)
        except (ValueError, RecursionError):
            continue
        for entity in entities(data):
            types = [t for t in as_list(entity.get('@type')) if isinstance(t, str)]
            if not types or all(t in NON_BUSINESS for t in types) or not text(entity.get('name')):
                continue
            points = as_list(entity.get('contactPoint'))
            phones = [text(p, 40) for p in as_list(entity.get('telephone')) + [c.get('telephone') for c in points if isinstance(c, dict)] if text(p, 40)]
            emails = [text(e, 120).removeprefix('mailto:') for e in as_list(entity.get('email')) + [c.get('email') for c in points if isinstance(c, dict)] if text(e, 120)]
            actions = [t for a in as_list(entity.get('potentialAction')) if isinstance(a, dict) for t in as_list(a.get('@type')) if isinstance(t, str)]
            rating = entity.get('aggregateRating') if isinstance(entity.get('aggregateRating'), dict) else {}
            item = {'types': types[:4], 'name': text(entity.get('name')), 'phones': phones[:5], 'emails': emails[:5],
                    'addresses': [a for a in (postal(x) for x in as_list(entity.get('address'))[:5]) if a],
                    'same_as': [text(u, 300) for u in as_list(entity.get('sameAs'))[:10] if isinstance(u, str)],
                    'url': text(entity.get('url'), 300) or None, 'price_range': text(entity.get('priceRange'), 40) or None,
                    'opening_hours': bool(entity.get('openingHours') or entity.get('openingHoursSpecification')),
                    'has_menu': bool(entity.get('hasMenu') or entity.get('menu')),
                    'accepts_reservations': entity.get('acceptsReservations') if isinstance(entity.get('acceptsReservations'), bool) else None,
                    'actions': actions[:5],
                    'rating': {'value': text(rating.get('ratingValue'), 10), 'count': text(rating.get('reviewCount') or rating.get('ratingCount'), 12)} if rating else None}
            key = (item['name'].casefold(), tuple(item['addresses']), tuple(item['phones']))
            if key not in seen and len(found) < 8:
                seen.add(key)
                found.append(item)
    return found


def same_site(a, b):
    return host(a) == host(b)


def discover(base_url, links, prefer=()):
    """Best same-site link for each of Contact, About and offer (menu/services/shop), by URL path and link text.

    prefer: words of the searched area. On multi-branch sites the page naming that area wins (Lahore, not Karachi)."""
    best = {}
    for href, label in links:
        if not href or href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
            continue
        try:
            url = urljoin(base_url, href)
            parts = urlsplit(url)
        except ValueError:
            continue
        if parts.scheme not in {'http', 'https'} or not same_site(url, base_url) or SKIP_EXT.search(parts.path):
            continue
        url = urlunsplit((parts.scheme, parts.netloc, parts.path or '/', '', ''))
        if url.rstrip('/') == base_url.split('#')[0].split('?')[0].rstrip('/'):
            continue
        haystack = f"{parts.path} {label}"
        for kind, pattern in PAGE_KINDS.items():
            if pattern.search(haystack):
                # Short paths ("/contact") beat deep ones ("/blog/2019/contact-tips").
                score = (2 if pattern.search(label or '') else 0) + (2 if pattern.search(parts.path) else 0) - parts.path.count('/')
                score += 5 if set(fold(haystack)) & set(prefer) else 0
                if kind not in best or score > best[kind][0]:
                    best[kind] = (score, url)
                break
    chosen = []
    for kind in ('contact', 'about', 'offer', 'reviews', 'gallery', 'team'):
        if kind in best and best[kind][1] not in {u for _, u in chosen}:
            chosen.append((kind, best[kind][1]))
    return chosen[:MAX_EXTRA_PAGES]


def read_page(page, kind, rendered=False):
    scan = SiteScan()
    scan.feed(page.html)
    visible = VisiblePage()
    visible.feed(page.html)
    visible.flush()
    return {'url': page.url, 'kind': kind, 'scan': scan, 'lines': visible.lines, 'extracted': extract(page.html),
            'content_sha256': hashlib.sha256(page.body or page.html.encode()).hexdigest(), 'bytes': len(page.body) or len(page.html.encode()),
            'words': sum(len(line.split()) for line in visible.lines), 'rendered': rendered, 'html': page.html}


ADVICE = (
    (re.compile(r'robots policy', re.I), 'The website asks automated readers not to read this page; LeadDesk respects that.',
     'Open it yourself in your browser.'),
    (re.compile(r'restricts automated access|HTTP 40[13]', re.I), 'The website blocks automated readers.',
     'Open it yourself in your browser. LeadDesk does not get around blocks.'),
    (re.compile(r'redirects to another host', re.I), 'The address forwards to a different website.',
     'Read the address it forwards to instead.'),
    (re.compile(r'exceeds', re.I), 'The page is larger than the 3 MB reading limit.', 'Open it yourself in your browser.'),
    (re.compile(r'not an HTML page', re.I), 'The link is a file (for example a PDF), not a web page.', 'Open the file yourself.'),
    (re.compile(r'timed out|did not answer|HTTP 5\d\d|could not be fetched', re.I), 'The website did not answer properly.', 'Retry later.'),
    (re.compile(r'HTTP 40[4]|HTTP 410', re.I), 'The page does not exist (HTTP 404).', 'Check the address.'),
    (re.compile(r'too complex', re.I), 'The page is too complex to read within the limit.', 'Open it yourself in your browser.'),
    (re.compile(r'security certificate', re.I), "The website's security certificate is invalid or incomplete.",
     'Visitors may see a security warning: that is itself a problem worth raising with them.'),
    (re.compile(r'dropped the connection|secure \(HTTPS\) connection', re.I), 'The website dropped the connection.', 'Retry later.'),
)


def advice(message):
    """A plain reason and next step for a page that could not be read."""
    for pattern, reason, step in ADVICE:
        if pattern.search(message or ''):
            return {'reason': reason, 'next_step': step}
    return {'reason': (message or 'Could not read this page.')[:200], 'next_step': 'Retry later or open it yourself.'}


def thin_page(page):
    return thin(page['html'], page['words'])


def snippet(line, match):
    start = max(0, match.start() - 80)
    return line[start:start + 200]


def find_feature(pages, text_pattern, hosts, path_pattern):
    for page in pages:
        for href, label in page['scan'].links:
            target = href.casefold()
            if any(h in target for h in hosts):
                return {'url': page['url'], 'text': f"Link to {host(href) or href}: {label or href}"[:200]}
            own = href.startswith('/') or (href.startswith('http') and same_site(href, page['url']))
            path = urlsplit(href).path if own else ''
            if (label and text_pattern.search(label)) or (path and path_pattern.search(path)):
                return {'url': page['url'], 'text': f"Link: {label or href}"[:200]}
        for src in page['scan'].srcs:
            if any(h in src.casefold() for h in hosts):
                return {'url': page['url'], 'text': f"Embedded widget from {host(src) or src}"[:200]}
        head = [' '.join(''.join(page['scan'].title).split()), page['scan'].meta.get('description', '')]
        for line in [h for h in head if h] + page['lines']:
            match = text_pattern.search(line)
            if match:
                return {'url': page['url'], 'text': snippet(line, match)}
    return None


def signal(id_, label, state, detail, evidence=None, gap=False):
    return {'id': id_, 'label': label, 'state': state, 'detail': detail, 'evidence': evidence, 'gap': gap}


def need_signals(pages, structured, year):
    home = pages[0]
    count = len(pages)
    seen = f"on the {count} page{'s' if count != 1 else ''} read"
    out = []
    secure = home['url'].startswith('https://')
    out.append(signal('https', 'HTTPS', 'yes' if secure else 'no',
                      'Served over HTTPS.' if secure else 'Not served over HTTPS: browsers mark the site "Not secure".',
                      {'url': home['url'], 'text': home['url']}, gap=not secure))
    viewport = home['scan'].meta.get('viewport', '')
    mobile = 'width=device-width' in viewport.replace(' ', '').casefold()
    out.append(signal('mobile', 'Mobile-friendly layout', 'yes' if mobile else 'no',
                      'Declares a mobile viewport (a sign of a responsive design; check on a phone).' if mobile else
                      'No mobile viewport tag: the site probably does not adapt to phones. Check on a phone.',
                      {'url': home['url'], 'text': f'<meta name="viewport" content="{viewport}">' if viewport else 'No viewport meta tag'}, gap=not mobile))
    ordering = find_feature(pages, ORDERING_TEXT, ORDERING_HOSTS, re.compile(r'/(order|cart|checkout|basket|shop)(/|$)', re.I))
    if not ordering:
        action = next((s for s in structured if {'OrderAction'} & set(s['actions'])), None)
        ordering = action and {'url': home['url'], 'text': f"Structured data declares an OrderAction for {action['name']}"}
    out.append(signal('online_ordering', 'Online ordering or shop', 'yes' if ordering else 'not_found',
                      'Online ordering, a cart or a delivery-app link was found.' if ordering else
                      f'No online ordering, cart or delivery-app link found {seen}. Not proof they have none.', ordering, gap=not ordering))
    booking = find_feature(pages, BOOKING_TEXT, BOOKING_HOSTS, re.compile(r'/(book|booking|reserve|reservations?|appointments?)(/|$)', re.I))
    if not booking:
        reserve = next((s for s in structured if s['accepts_reservations'] or {'ReserveAction'} & set(s['actions'])), None)
        booking = reserve and {'url': home['url'], 'text': f"Structured data says {reserve['name']} accepts reservations"}
    out.append(signal('online_booking', 'Online booking or reservations', 'yes' if booking else 'not_found',
                      'Booking, reservations or a scheduling widget was found.' if booking else
                      f'No online booking or reservation option found {seen}.', booking, gap=not booking))
    form = next(({'url': p['url'], 'text': 'Form with fields: ' + ', '.join(sorted(f['fields']))[:180]} for p in pages for f in p['scan'].forms
                 if f['fields'] & {'textarea', 'email'} and 'search' not in f['fields']), None)
    out.append(signal('contact_form', 'Contact or enquiry form', 'yes' if form else 'not_found',
                      'A contact or enquiry form was found.' if form else f'No contact form found {seen}.', form, gap=not form))
    whatsapp = next(({'url': p['url'], 'text': f'Link: {label or href}'[:200]} for p in pages for href, label in p['scan'].links
                     if 'wa.me/' in href or 'api.whatsapp.com' in href or 'whatsapp://' in href), None)
    out.append(signal('whatsapp', 'WhatsApp chat link', 'yes' if whatsapp else 'not_found',
                      'A WhatsApp chat link was found.' if whatsapp else f'No WhatsApp link found {seen}.', whatsapp, gap=not whatsapp))
    out.append(signal('structured_data', 'Business structured data (schema.org)', 'yes' if structured else 'no',
                      f"Publishes schema.org data for {structured[0]['name']} ({', '.join(structured[0]['types'])})." if structured else
                      'No schema.org business data on the pages read: search engines get less detail about the business.',
                      {'url': home['url'], 'text': 'JSON-LD: ' + ', '.join(t for s in structured for t in s['types'])[:180]} if structured else None,
                      gap=not structured))
    title = ' '.join(''.join(home['scan'].title).split())
    description = home['scan'].meta.get('description', '').strip()
    missing = [n for n, v in (('page title', title), ('meta description', description)) if not v]
    out.append(signal('seo_basics', 'Search basics (title and description)', 'no' if missing else 'yes',
                      f"Home page has no {' or '.join(missing)}." if missing else 'Home page has a title and a meta description.',
                      {'url': home['url'], 'text': f'Title: {title[:90]} | Description: {description[:90]}'}, gap=bool(missing)))
    years = [(int(m.group(1)), {'url': p['url'], 'text': snippet(line, m)}) for p in pages for line in p['lines'][-60:]
             for m in COPYRIGHT.finditer(line) if 1995 <= int(m.group(1)) <= year + 1]
    if years:
        latest, evidence = max(years, key=lambda y: y[0])
        stale = latest <= year - 2
        out.append(signal('stale', 'Recently updated', 'no' if stale else 'yes',
                          f'Copyright notice says {latest}: the site may not have been updated since.' if stale else
                          f'Copyright notice says {latest}.', evidence, gap=stale))
    else:
        out.append(signal('stale', 'Recently updated', 'unknown', 'No copyright year found to judge how current the site is.'))
    platform = next((name for page in pages for value in [page['scan'].meta.get('generator', '')] + page['scan'].srcs
                     for marker, name in PLATFORMS if marker in value.casefold()), None)
    out.append(signal('platform', 'Website platform', 'info' if platform else 'unknown',
                      f'Built with {platform}.' if platform else 'Website platform not identified.',
                      {'url': home['url'], 'text': platform} if platform else None))
    return out


def relevant(signals, offer, offer_kind):
    """Mark which gaps matter for the user's product: its words, or website basics for web/online offers."""
    offer_words = set(words(offer)) | set(re.findall(r'[a-z-]+', offer.casefold()))
    for item in signals:
        topics = TOPICS.get(item['id'], set())
        item['relevant'] = bool(topics & offer_words) or (offer_kind == 'web_presence' and item['id'] in WEB_BASICS)
    return signals


def branch_sections(base_url, links):
    """First path segments of same-site contact/location links: /karachi/contact-us and /lahore/contact-us mean branches."""
    found = set()
    for href, label in links:
        try:
            url = urljoin(base_url, href)
        except ValueError:
            continue
        parts = [p for p in urlsplit(url).path.split('/') if p]
        if len(parts) >= 2 and same_site(url, base_url) and PAGE_KINDS['contact'].search(f"{'/'.join(parts[1:])} {label}"):
            found.add(parts[0].casefold())
    return sorted(found)[:12]


def lost_path_words(requested_url, final_url):
    """Words in the requested path that the redirect dropped, e.g. 'lahore' in /lahore/contact-us -> /karachi/contact-us."""
    if not requested_url:
        return []
    before, after = set(fold(urlsplit(requested_url).path)), set(fold(urlsplit(final_url).path))
    return sorted(w for w in before - after if len(w) >= 3)


def read_site(page, fetch, offer, offer_kind, year, requested_url=None, location='', home_seconds=None, render=None):
    """page: the already fetched home page. fetch(url) -> Page. Extra page failures are recorded, never fatal.

    render(url, phone, screenshots) -> browser_render.Rendered, optional: Chrome on this computer. The home page is always
    rendered for the layout and screenshots; other pages only when their source is nearly empty (a JavaScript site)."""
    from backend.adapters.fetch import Page
    pages, report, renders = [read_page(page, 'home')], [], {'count': 0, 'seconds': 0.0, 'blocked': 0, 'failed': None, 'discard': []}
    home_raw_thin = thin_page(pages[0])
    layout = None

    def rendered(url, phone=False, screenshots=False):
        if render is None or renders['count'] >= MAX_RENDERS:
            return None
        renders['count'] += 1
        try:
            result = render(url, phone=phone, screenshots=screenshots)
        except ResearchError as error:
            renders['failed'] = str(error)
            return None
        renders['seconds'] += result.seconds
        renders['blocked'] += len(result.blocked)
        blocked_by = challenge(result.html)
        if blocked_by:
            # The site showed Chrome a bot check instead of its content: nothing measured there is about the real site.
            renders['failed'] = (f'The website showed Chrome a "{blocked_by}" page instead of its content. LeadDesk does not get around '
                                 'such checks, so the phone layout was not measured.')
            renders['challenged'] = True
            renders['discard'] += [v for k, v in result.screens.items() if k in {'desktop', 'phone'} and v]
            return None
        return result

    home = rendered(page.url, phone=True, screenshots=True)
    if home is not None:
        layout = analyse_layout(page.url, home.layout, home.phone_layout, screens=home.screens)
        if home_raw_thin and same_site(home.url, page.url):
            # The source was nearly empty: read what the browser drew instead.
            pages[0] = read_page(Page(page.url, page.body, home.html), 'home', rendered=True)
    else:
        layout = analyse_layout(page.url, html=page.html)
    prefer = [w for w in fold(location) if len(w) >= 4]
    for kind, url in discover(page.url, pages[0]['scan'].links, prefer):
        try:
            extra = fetch(url)
        except ResearchError as error:
            report.append({'url': url, 'kind': kind, 'status': 'failed', 'error': str(error)} | advice(str(error)))
            continue
        if not same_site(extra.url, page.url):
            report.append({'url': url, 'kind': kind, 'status': 'failed', 'error': 'Redirected to another site; not read.'} |
                          advice('redirects to another host'))
            continue
        item = read_page(extra, kind)
        if thin_page(item):
            drawn = rendered(extra.url)
            if drawn is not None and same_site(drawn.url, page.url):
                item = read_page(Page(extra.url, extra.body, drawn.html), kind, rendered=True)
        pages.append(item)
    structured = structured_data([b for p in pages for b in p['scan'].jsonld])
    contacts, seen = [], set()
    for p in pages:
        for c in p['extracted'].contacts:
            key = (c['type'], re.sub(r'\D', '', c['raw_value'])[-9:] if c['type'] != 'email' else c['raw_value'].casefold())
            if key not in seen and len(contacts) < 30:
                seen.add(key)
                contacts.append({'type': c['type'], 'value': c['raw_value'], 'page_url': p['url'], 'page_kind': p['kind'],
                                 'excerpt': c['excerpt'], 'origin': 'visible_text'})
    for s in structured:
        for kind, values in (('phone', s['phones']), ('email', s['emails'])):
            for value in values:
                key = (kind, re.sub(r'\D', '', value)[-9:] if kind == 'phone' else value.casefold())
                if key not in seen and len(contacts) < 30:
                    seen.add(key)
                    contacts.append({'type': kind, 'value': value, 'page_url': page.url, 'page_kind': 'structured_data',
                                     'excerpt': f"schema.org data for {s['name']}", 'origin': 'structured_data'})
    social = []
    for p in pages:
        for href, _ in p['scan'].links:
            if href.startswith('http') and classify(href)[0] == 'social' and href not in social and len(social) < 10:
                social.append(href[:300])
    for s in structured:
        social += [u for u in s['same_as'] if u.startswith('http') and classify(u)[0] == 'social' and u not in social][:10 - len(social)]
    excerpts = []
    for p in pages:
        quota = 4 if p['kind'] == 'home' else 8
        for line in p['lines']:
            if len(line) >= 25 and quota and line[:400] not in {e['text'] for e in excerpts}:
                excerpts.append({'page_url': p['url'], 'page_kind': p['kind'], 'text': line[:400]})
                quota -= 1
    soon = placeholder(' '.join(''.join(pages[0]['scan'].title).split()), pages[0]['lines'])
    if soon and pages[0]['words'] < 400:
        # A placeholder is not a working website: a strong sign they need one.
        layout['findings'].insert(0, finding('placeholder_site', 'A working website', 'no',
                                             f'The website is only a "{soon}" page, not a working site yet.',
                                             {'url': page.url, 'text': soon}, gap=True))
    signals = relevant(need_signals(pages, structured, year), offer, offer_kind)
    report_card = health(pages, structured, contacts, signals, year, home_seconds, layout)
    reading = []
    if home_raw_thin and not pages[0]['rendered']:
        reading.append({'url': page.url, 'kind': 'home', 'status': 'thin',
                        'reason': f"The page source shows only about {pages[0]['words']} words: the site is probably built with JavaScript, "
                                  'so contacts and features may be missed.',
                        'next_step': 'Turn on "Read JavaScript websites with Chrome" and check again.' if render is None else
                                     f"Chrome could not draw it: {renders['failed'] or 'no content'}"})
    if renders['failed'] and not reading:
        reading.append({'url': page.url, 'kind': 'home', 'status': 'bot_check' if renders.get('challenged') else 'render_failed',
                        'reason': renders['failed'],
                        'next_step': 'The page source was read instead; the phone layout was not measured.'})
    home_scan = pages[0]['scan']
    h1 = pages[0]['extracted'].name
    return {
        'pages': [{'url': p['url'], 'kind': p['kind'], 'status': 'read', 'title': ' '.join(''.join(p['scan'].title).split())[:200],
                   'content_sha256': p['content_sha256'], 'words': p['words'], 'rendered': p['rendered']} for p in pages] + report,
        'layout': layout,
        'reading': {'rendered_pages': sum(p['rendered'] for p in pages), 'chrome_used': renders['count'] > 0,
                    'discard_screens': renders['discard'],
                    'chrome_seconds': round(renders['seconds'], 2), 'blocked_requests': renders['blocked'], 'problems': reading + [
                        {k: r[k] for k in ('url', 'kind', 'status', 'reason', 'next_step')} for r in report]},
        'names': {'title': ' '.join(''.join(home_scan.title).split())[:200] or None, 'site_name': home_scan.meta.get('og:site_name') or None,
                  'heading': h1, 'structured': [s['name'] for s in structured]},
        'structured': structured, 'signals': signals, 'health': report_card, 'contacts': contacts, 'social_links': social, 'excerpts': excerpts[:28],
        'address_text': ' '.join([a for s in structured for a in s['addresses']] +
                                 [line for p in pages if p['kind'] in {'home', 'contact'} for line in p['lines']])[:20000],
        'redirect': {'from': requested_url, 'to': page.url, 'lost_words': lost_path_words(requested_url, page.url)}
                    if requested_url and urlsplit(requested_url).path.rstrip('/').casefold() != urlsplit(page.url).path.rstrip('/').casefold() else None,
        'branch_sections': branch_sections(page.url, [l for p in pages for l in p['scan'].links]),
        'method': 'site_read_v2',
        'notes': [f"Read {len(pages)} page{'s' if len(pages) != 1 else ''} of this website, following its robots policy.",
                  '"Not found" means not seen on the pages read.' + (' Pages were drawn in Chrome where their source was nearly empty.'
                                                                     if renders['count'] else
                                                                     ' Sites built with JavaScript can hide content from this reader.')],
    }
