"""Website health report card: 0–100 score, A–F grade, plain-English issues with evidence.

Modelled on public website-audit lead tools: six categories, each with a cap so
related checks cannot drown the others. Every site starts at 100. A check that
could not be measured deducts nothing and is listed as unmeasured. Only the pages
LeadDesk read are judged, so "not found" means not seen there.
"""
import re

CAPS = {'security': 25, 'mobile': 25, 'freshness': 25, 'performance': 20, 'seo': 20, 'contact': 15}
LABELS = {'security': 'Security and trust', 'mobile': 'Mobile experience', 'freshness': 'Freshness and tech debt',
          'performance': 'Speed', 'seo': 'Search (SEO) basics', 'contact': 'Easy to contact'}
PLACEHOLDER_TITLES = re.compile(r'^(home|homepage|untitled|index|welcome|my (?:wordpress )?(?:site|blog)|just another wordpress site|'
                                r'coming soon|site title|new page)$', re.I)
JQUERY = re.compile(r'jquery[.-]?(\d)\.(\d+)', re.I)
WP_VERSION = re.compile(r'wordpress\s+(\d+)\.(\d+)', re.I)


def grade(score):
    return 'A' if score >= 90 else 'B' if score >= 75 else 'C' if score >= 60 else 'D' if score >= 40 else 'F'


# Layout findings (site_layout_v1) that cost points: category and points.
LAYOUT_POINTS = {'phone_sideways_scroll': ('mobile', 8), 'phone_tiny_text': ('mobile', 5), 'phone_small_buttons': ('mobile', 4),
                 'phone_first_screen_contact': ('contact', 4), 'pdf_menu': ('mobile', 3), 'broken_images': ('freshness', 4),
                 'placeholder_site': ('freshness', 25)}


def health(pages, structured, contacts, signals, year, home_seconds=None, layout=None):
    home, issues, unmeasured = pages[0], [], []
    scan = home['scan']
    found = {s['id']: s for s in signals}

    def issue(check, category, points, plain, evidence=None):
        issues.append({'check': check, 'category': category, 'points': points, 'plain': plain,
                       'evidence': evidence or {'url': home['url'], 'text': ''}})

    # Security and trust
    if not home['url'].startswith('https://'):
        issue('no_https', 'security', 25, 'it is not secure (no HTTPS): browsers show "Not secure"', {'url': home['url'], 'text': home['url']})
    elif scan.insecure:
        issue('mixed_content', 'security', 8, 'it loads files over insecure HTTP on a secure page', {'url': home['url'], 'text': scan.insecure[0]})
    # Mobile experience
    viewport = scan.meta.get('viewport', '').replace(' ', '').casefold()
    if 'width=device-width' not in viewport:
        issue('not_mobile', 'mobile', 12, 'it is probably not built for phones (no mobile viewport)',
              {'url': home['url'], 'text': f'viewport: {viewport or "missing"}'})
    elif 'user-scalable=no' in viewport or 'maximum-scale=1' in viewport.replace('.0', ''):
        issue('zoom_blocked', 'mobile', 4, 'it stops visitors zooming on phones', {'url': home['url'], 'text': f'viewport: {viewport}'})
    if scan.images >= 3 and scan.images_without_alt / scan.images > .5:
        issue('images_no_alt', 'mobile', 3, f'{scan.images_without_alt} of {scan.images} images have no description (alt text)')
    # Freshness and tech debt
    stale = found.get('stale')
    if stale and stale['state'] == 'no':
        latest = int(re.search(r'\d{4}', stale['detail']).group())
        points = 10 if year - latest >= 5 else 5
        issue('stale_copyright', 'freshness', points, f'it still says © {latest}, so it looks unmaintained', stale['evidence'])
    elif not stale or stale['state'] == 'unknown':
        unmeasured.append('copyright year')
    if any(p['scan'].flash for p in pages):
        issue('flash', 'freshness', 10, 'it uses Flash, which no browser runs any more')
    generator = scan.meta.get('generator', '')
    wp = WP_VERSION.search(generator)
    if wp and (int(wp.group(1)), int(wp.group(2))) < (6, 0):
        issue('old_wordpress', 'freshness', 8, f'it runs an old WordPress ({wp.group(1)}.{wp.group(2)}), a security risk',
              {'url': home['url'], 'text': generator})
    jq = next((JQUERY.search(src) for src in scan.srcs if JQUERY.search(src)), None)
    if jq and int(jq.group(1)) < 3:
        issue('old_jquery', 'freshness', 5, f'it uses an outdated jQuery {jq.group(1)}.{jq.group(2)}', {'url': home['url'], 'text': jq.group(0)})
    if not scan.doctype:
        issue('quirks_mode', 'freshness', 6, 'it has no HTML doctype, a sign of very old code')
    if scan.legacy_tags or scan.tables >= 4:
        issue('legacy_markup', 'freshness', 6, 'it is built with old-fashioned HTML (layout tables or <font>/<center> tags)',
              {'url': home['url'], 'text': f'{scan.tables} tables, {scan.legacy_tags} legacy tags'})
    # Speed (only what this reader measures: server response and HTML size)
    if home_seconds is None:
        unmeasured.append('response time')
    elif home_seconds > 3:
        issue('slow_response', 'performance', 8, f'the home page took {home_seconds:.1f} s to load', {'url': home['url'], 'text': f'{home_seconds:.1f} s'})
    elif home_seconds > 1.5:
        issue('slowish_response', 'performance', 4, f'the home page took {home_seconds:.1f} s to load', {'url': home['url'], 'text': f'{home_seconds:.1f} s'})
    kb = home['bytes'] / 1024
    if kb > 600:
        issue('heavy_html', 'performance', 6, f'the home page HTML alone is {kb:.0f} KB', {'url': home['url'], 'text': f'{kb:.0f} KB'})
    if len([s for s in scan.srcs if s.endswith('.js') or '.js?' in s]) > 25:
        issue('many_scripts', 'performance', 4, 'it loads more than 25 script files')
    # Search (SEO) basics
    robots = scan.meta.get('robots', '').casefold()
    if 'noindex' in robots:
        issue('noindex', 'seo', 12, 'it tells Google not to list it (noindex)', {'url': home['url'], 'text': f'robots: {robots}'})
    title = ' '.join(''.join(scan.title).split())
    if not title:
        issue('no_title', 'seo', 8, 'the home page has no title')
    elif PLACEHOLDER_TITLES.match(title):
        issue('placeholder_title', 'seo', 6, f'the page title is just "{title}"', {'url': home['url'], 'text': title})
    if not scan.meta.get('description', '').strip():
        issue('no_description', 'seo', 4, 'it has no search description (meta description)')
    if not structured:
        issue('no_structured_data', 'seo', 3, 'it gives Google no business details (schema.org)')
    # Easy to contact
    kinds = {c['type'] for c in contacts}
    if not kinds & {'phone', 'whatsapp'}:
        issue('no_phone', 'contact', 7, f"no phone number is shown on the {len(pages)} page{'s' if len(pages) != 1 else ''} read")
    has_form = found.get('contact_form', {}).get('state') == 'yes'
    if not any(p['kind'] == 'contact' for p in pages) and not has_form:
        issue('no_contact_page', 'contact', 7, 'there is no contact page or enquiry form')
    if 'email' not in kinds and not has_form:
        issue('no_email', 'contact', 4, 'there is no email address or form to write to')

    # Layout: what a visitor sees on a phone (only when measured in Chrome; otherwise listed as unmeasured).
    for item in (layout or {}).get('findings', []):
        if item['gap'] and item['id'] in LAYOUT_POINTS:
            category, points = LAYOUT_POINTS[item['id']]
            issue(item['id'], category, points, item['detail'][0].lower() + item['detail'][1:].rstrip('.'), item['evidence'])
    if layout is None or layout.get('unmeasured'):
        unmeasured.append('phone layout')

    lost = {}
    for item in issues:
        lost[item['category']] = lost.get(item['category'], 0) + item['points']
    categories = [{'id': key, 'label': LABELS[key], 'lost': min(lost.get(key, 0), cap), 'max': cap} for key, cap in CAPS.items()]
    score = 100 - sum(c['lost'] for c in categories)
    issues.sort(key=lambda i: -i['points'])
    return {'score': score, 'grade': grade(score), 'categories': categories, 'issues': issues, 'unmeasured': unmeasured,
            'method': 'site_health_v1',
            'note': f"Judged from the {len(pages)} page{'s' if len(pages) != 1 else ''} read"
                    + (', with the phone view measured in Chrome. ' if layout and layout.get('source') == 'rendered' else ', without running scripts. ')
                    + 'Speed covers server response and HTML size only, not images or full load time.'}
