"""Contact review gate (contact_review_v1): every phone and email is approved, needs review or rejected, with reasons.

Built on contact verification (sources, numbering plan, mailbox checks) and adds what people get wrong when they publish
contacts: temporary-email domains, placeholder and fake values, no-reply and platform addresses, numbers shared by many
unrelated businesses, and the owner's own corrections and approved rules.

- rejected: a hard failure. Hidden from lists, messages and exports; shown with its reason and an override.
- needs_review: plausible but not proven (one source, catch-all mailbox, premium number, email domain not theirs).
- approved: valid, no warning, and a strong source (their own website or profile, two independent sources, or a mailbox
  accepted by its mail server), or confirmed by the owner.
Approval says the contact looks genuine and current from public evidence. It never proves that someone will answer.
"""
import re
from functools import lru_cache
from pathlib import Path

import phonenumbers
from phonenumbers import PhoneNumberType

from backend.domain.contact_analysis import FREE_MAIL, NO_REPLY
from backend.domain.enrichment import fold, host
from backend.domain.extract import EMAIL
from backend.domain.verification import phone_key, verify

DATA = Path(__file__).with_name('data') / 'disposable_domains.txt'
EXTRA_DISPOSABLE = {'mailinator.com', 'guerrillamail.com', '10minutemail.com', 'tempmail.com', 'yopmail.com', 'trashmail.com',
                    'temp-mail.org', 'tempmailo.com', 'emailondeck.com', 'getnada.com', 'sharklasers.com', 'dispostable.com'}
# Addresses that belong to website platforms, tools or examples, not to the business.
PLATFORM_DOMAINS = {'wix.com', 'wixpress.com', 'sentry.io', 'sentry-next.wixpress.com', 'wordpress.com', 'wordpress.org',
                    'godaddy.com', 'squarespace.com', 'shopify.com', 'weebly.com', 'jimdo.com', 'webflow.io', 'example.com', 'example.org',
                    'example.net', 'domain.com', 'email.com', 'yourdomain.com', 'yoursite.com', 'website.com', 'company.com', 'test.com',
                    'schema.org', 'w3.org', 'cloudflare.com', 'google.com', 'facebook.com', 'sentry.wixpress.com', 'mysite.com', 'site.com'}
PLACEHOLDER_LOCAL = re.compile(r'^(?:test|testing|example|sample|demo|user|username|yourname|your\.?name|name|email|youremail|'
                               r'your\.?email|someone|somebody|me|abc|xyz|asdf|qwerty|john\.?doe|jane\.?doe|first\.?last|firstname|'
                               r'lastname|address|mail|xxx+|null|none|na|n/a)$', re.I)
FILE_TLDS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico', 'css', 'js', 'pdf', 'mp4', 'webm', 'avif'}
STRONG = {'confirmed', 'corroborated'}
RANK = {'approved': 0, 'needs_review': 1, 'rejected': 2}
LABEL = {'approved': 'Approved', 'needs_review': 'Needs review', 'rejected': 'Rejected'}


@lru_cache(maxsize=1)
def disposable_domains():
    """The local disposable-domain list (scripts/update_disposable_domains.py) and its header facts."""
    domains, facts = set(EXTRA_DISPOSABLE), {}
    try:
        for line in DATA.read_text(encoding='utf-8').splitlines():
            if line.startswith('#'):
                key, _, value = line[1:].partition(':')
                facts[key.strip()] = value.strip()
            elif line:
                domains.add(line)
    except OSError:
        facts['missing'] = 'The disposable-domain list file is missing; only built-in domains are checked.'
    return frozenset(domains), facts


def domain_parts(domain):
    """example.co.uk and its parent domains, so mail.yopmail.com matches yopmail.com."""
    labels = domain.split('.')
    return {'.'.join(labels[i:]) for i in range(len(labels) - 1)}


def value_key(kind, value, country):
    return phone_key(value, country) if kind == 'phone' else value.strip().casefold()


def email_flags(value, website, mail_server):
    """(rejections, warnings) for one email address."""
    rejected, review = [], []
    local, _, domain = value.strip().rpartition('@')
    domain = domain.casefold()
    if domain.rsplit('.', 1)[-1] in FILE_TLDS or re.search(r'@\d+x\.', value):
        return ['It is an image or file name on the page (for example logo@2x.png), not an email address.'], []
    if PLACEHOLDER_LOCAL.match(local) or domain in {'example.com', 'example.org', 'example.net', 'domain.com', 'email.com',
                                                     'yourdomain.com', 'yoursite.com', 'website.com', 'mysite.com', 'site.com'}:
        rejected.append(f'Placeholder address ("{value}"), the kind a website template ships with.')
    if NO_REPLY.match(local):
        rejected.append('No-reply address: nobody reads replies to it.')
    disposable, _ = disposable_domains()
    if domain_parts(domain) & disposable:
        rejected.append(f'{domain} is a temporary (disposable) email service.')
    elif domain_parts(domain) & PLATFORM_DOMAINS:
        rejected.append(f'{domain} belongs to a website platform or tool, not to this business.')
    if mail_server in {'no_mx', 'null_mx', 'no_domain', 'invalid'}:
        rejected.append({'no_mx': f'{domain} has no mail servers, so email to it bounces.', 'null_mx': f'{domain} accepts no email.',
                         'no_domain': f'{domain} does not exist.', 'invalid': f'{domain} is not a valid domain.'}[mail_server])
    site = host(website) if website else None
    if site and domain not in FREE_MAIL and domain != site and not domain.endswith('.' + site) and not site.endswith('.' + domain):
        review.append(f'The email domain ({domain}) is not their website ({site}): it may be a web designer, agency or directory.')
    return rejected, review


def phone_flags(value, country):
    rejected, review = [], []
    digits = re.sub(r'\D', '', value)
    number = None
    try:
        number = phonenumbers.parse(value, (country or '').upper() or None)
        national = str(number.national_number)
    except phonenumbers.NumberParseException:
        national = digits
    # The subscriber part (last 7 digits) all one digit or a straight run: 0300 0000000, 042 1234567. Vanity numbers
    # such as 050 555 5555 keep their area or mobile prefix varied, so they are not caught.
    subscriber = national[-7:]
    if len(subscriber) == 7 and (subscriber == '0000000' or subscriber in '0123456789' or subscriber in '9876543210'):
        rejected.append(f'{value} looks like a placeholder number (the last 7 digits are {subscriber}).')
    elif len(subscriber) == 7 and len(set(subscriber)) == 1:
        # 555 5555 may be a placeholder or a paid vanity number: never hidden on this alone.
        review.append(f'The last 7 digits are all {subscriber[0]}: either a vanity number or a placeholder. Confirm before use.')
    if re.search(r'(?:^|\D)1?\s*\(?555\)?[\s.-]*01\d\d', value) or re.fullmatch(r'1?1234567890', digits):
        rejected.append(f'{value} is a reserved example number.')
    if number is not None:
        kind = phonenumbers.number_type(number)
        if kind in {PhoneNumberType.PREMIUM_RATE, PhoneNumberType.SHARED_COST}:
            review.append('Premium-rate or shared-cost number: calling it costs extra; check it is their main line.')
        elif kind == PhoneNumberType.TOLL_FREE:
            review.append('Toll-free number: usually a head-office or chain line, not the local branch.')
    return rejected, review


def business_key(item, location=''):
    """The same business across searches: its map id, else its folded name and city."""
    ident = item.get('id') or ''
    if re.match(r'^(node|way|relation|overture)/', ident):
        return ident
    city = (location or '').split(',')[0]
    return 'name:' + ' '.join(fold(item.get('name') or '')) + '|' + ' '.join(fold(city))


def mail_servers(item):
    """MX answers LeadDesk already saved for this business's emails (no network on read)."""
    found = {}
    for contact in (item.get('enrichment') or {}).get('contacts') or []:
        status = (contact.get('analysis') or {}).get('mail_server')
        if contact['type'] == 'email' and status:
            found[contact['value'].casefold()] = status
    for analysis in (item.get('check') or {}).get('contact_analysis') or []:
        if analysis.get('type') == 'email' and analysis.get('mail_server'):
            found[analysis['value'].casefold()] = analysis['mail_server']
    for analysis in (item.get('contact_analysis') or {}).get('items') or []:
        if analysis.get('type') == 'email' and analysis.get('mail_server'):
            found.setdefault(analysis['value'].casefold(), analysis['mail_server'])
    return found


def whatsapp_keys(item, country):
    keys = set()
    for contact in ((item.get('check') or {}).get('site') or {}).get('contacts') or []:
        if contact['type'] == 'whatsapp':
            keys.add(phone_key(contact['value'], country))
    for contact in (item.get('enrichment') or {}).get('contacts') or []:
        if contact['type'] == 'whatsapp':
            keys.add(phone_key(contact['value'], country))
    return keys


def source_hosts(entry):
    return sorted({host(s['url']) for s in entry.get('seen_in', []) if s.get('url')})


def brand_of(item):
    website = item.get('website')
    if website and '://' in website:
        return host(website)
    return ' '.join(fold(item.get('name') or ''))


def shared_values(candidates, country):
    """{(type, key): distinct brands} across one search, to spot directory or agency contacts reused for many businesses."""
    from backend.domain.verification import sightings
    owners = {}
    for item in candidates:
        brand = brand_of(item)
        for kind, value, *_ in sightings(item):
            if kind == 'email' and not EMAIL.fullmatch(value):
                continue
            owners.setdefault((kind, value_key(kind, value, country)), set()).add(brand)
    return {key: brands for key, brands in owners.items() if len(brands) >= 3}


def review(item, country, probes=None, shared=None, corrections=None, blocked=None, rules=None, extra=None):
    """Review every contact of one business.

    corrections: {(type, key): correction row} for this business; blocked: {(kind, key)}; rules: active learned rules;
    extra: user-added contacts [{'type', 'value'}]."""
    corrections, blocked, rules, shared = corrections or {}, blocked or set(), rules or [], shared or {}
    base = verify(item, country, probes)['contacts']
    servers, whatsapp = mail_servers(item), whatsapp_keys(item, country)
    website = item.get('website') if item.get('website') and not item.get('website_is_social') else \
        ((item.get('check') or {}).get('website_url'))
    blocked_domains = {v for k, v in blocked if k == 'email_domain'} | {r['value'] for r in rules if r['kind'] == 'block_email_domain'}
    distrusted = {r['value'] for r in rules if r['kind'] == 'distrust_source_host'}
    blocked_phones = {r['value'] for r in rules if r['kind'] == 'block_phone'}
    out = []
    for entry in base:
        kind, value = entry['type'], entry['value']
        key = entry.get('e164') or value_key(kind, value, country) if kind == 'phone' else value.casefold()
        rejected, warnings = [], []
        if kind == 'email':
            r, w = email_flags(value, website, servers.get(value.casefold()))
            rejected += r
            warnings += w
            domain = value.rpartition('@')[2].casefold()
            if domain_parts(domain) & blocked_domains:
                rejected.append(f'You blocked the email domain {domain}.')
        else:
            r, w = phone_flags(value, country)
            rejected += r
            warnings += w
            if key in blocked_phones:
                rejected.append('An approved rule marks this number as fake.')
        if entry['status'] == 'likely_wrong':
            rejected += [r for r in entry['reasons'] if r not in rejected][:1]
        if (kind, key) in blocked:
            rejected.append('You marked this value as fake or temporary.')
        hosts = source_hosts(entry)
        if hosts and set(hosts) <= distrusted:
            rejected.append(f"Only found on {', '.join(hosts)}, which an approved rule marks as unreliable for contacts.")
        brands = shared.get((kind, key)) or shared.get((kind, value_key(kind, value, country)))
        if brands and brand_of(item) in brands and len(brands) >= 3:
            rejected.append(f'The same {kind} appears for {len(brands)} different businesses in this search: probably a directory, '
                            'agency or marketplace contact, not theirs.')
        probe = entry.get('mailbox_check')
        if probe and probe['result'] in {'catch_all', 'blocked', 'unknown', 'unreachable'}:
            warnings.append({'catch_all': 'Their mail server accepts any address, so this mailbox could not be confirmed.',
                             'blocked': 'Their mail server refused the mailbox check from this network.',
                             'unknown': 'The mailbox check gave no clear answer.',
                             'unreachable': 'Their mail server could not be reached for the mailbox check.'}[probe['result']])
        correction = corrections.get((kind, key)) or corrections.get((kind, value_key(kind, value, country)))
        if correction and correction['verdict'] == 'wrong':
            verdict = 'rejected'
            rejected.insert(0, {'not_theirs': 'You said this is not their contact.', 'disconnected': 'You said this number or mailbox no longer works.',
                                'fake': 'You marked this as fake.', 'temporary': 'You marked this as a temporary address.'}[correction['reason']])
        elif correction and correction['verdict'] in {'correct', 'added'}:
            verdict = 'approved'
        elif rejected:
            verdict = 'rejected'
        elif warnings or entry['status'] not in STRONG:
            verdict = 'needs_review'
        else:
            verdict = 'approved'
        why = list(dict.fromkeys(rejected + warnings))
        if verdict == 'needs_review' and entry['status'] not in STRONG:
            source = entry['seen_in'][0]
            why.append(f"Only one source: {source['source']}{' (' + source['date'] + ')' if source.get('date') else ''}. "
                       'Approve it after you confirm it, or find a second source.')
        if verdict == 'approved':
            why = ['You confirmed this contact.'] if correction else [r for r in entry['reasons'] if r][:2]
        is_whatsapp = kind == 'phone' and (key in whatsapp)
        out.append({'type': kind, 'value': value, 'key': key, 'e164': entry.get('e164'), 'line': entry.get('line'),
                    'network': entry.get('network'), 'whatsapp': is_whatsapp,
                    'whatsapp_link': f"https://wa.me/{entry['e164'].lstrip('+')}" if kind == 'phone' and entry.get('e164') and
                    (is_whatsapp or entry.get('line') == 'mobile') else None,
                    'verdict': verdict, 'label': LABEL[verdict], 'reasons': why, 'verification_status': entry['status'],
                    'seen_in': entry['seen_in'], 'source_hosts': hosts, 'mailbox_check': entry.get('mailbox_check'),
                    'correction': {k: correction[k] for k in ('verdict', 'reason', 'created_at')} if correction else None})
    for added in extra or []:
        key = value_key(added['type'], added['value'], country)
        if any(c['key'] == key and c['type'] == added['type'] for c in out):
            continue
        out.append({'type': added['type'], 'value': added['value'], 'key': key, 'e164': key if added['type'] == 'phone' and key.startswith('+') else None,
                    'line': None, 'network': None, 'whatsapp': False, 'whatsapp_link': None, 'verdict': 'approved', 'label': 'Added by you',
                    'reasons': ['Added by you; LeadDesk has not verified it.'], 'verification_status': 'user_added', 'seen_in': [],
                    'source_hosts': [], 'mailbox_check': None, 'correction': {'verdict': 'added', 'reason': 'added', 'created_at': added['created_at']}})
    out.sort(key=lambda c: (RANK[c['verdict']], not c['whatsapp'], c['type'] != 'phone', c['line'] != 'mobile'))
    usable = [c for c in out if c['verdict'] != 'rejected']
    _, facts = disposable_domains()
    return {'method': 'contact_review_v1', 'contacts': out,
            'counts': {v: sum(c['verdict'] == v for c in out) for v in RANK},
            'best_phone': next((c for c in usable if c['type'] == 'phone'), None),
            'best_email': next((c for c in usable if c['type'] == 'email'), None),
            'disposable_list': {'entries': facts.get('entries'), 'retrieved': facts.get('retrieved'), 'source_sha256': facts.get('source_sha256')},
            'note': 'Approved means it looks genuine and current from public evidence; it does not prove someone will answer. '
                    'Rejected contacts are hidden from lists, messages and exports.'}
