"""Deterministic email/phone analysis. Signals only; never proof a person will answer.

Email: syntax, generic role vs named mailbox, free-mail vs own domain, whether the
domain matches the business website, and whether it publishes mail servers (MX).
Phone: international (E.164) form from the search country, mobile hints for a
few numbering plans, and a WhatsApp link (only works if the number uses WhatsApp).
"""
import re

from backend.domain.extract import EMAIL
from backend.domain.learning import domain_group

FREE_MAIL = {'gmail.com', 'googlemail.com', 'yahoo.com', 'yahoo.co.uk', 'ymail.com', 'outlook.com', 'hotmail.com', 'live.com',
             'msn.com', 'icloud.com', 'me.com', 'aol.com', 'proton.me', 'protonmail.com', 'gmx.com', 'gmx.de', 'mail.com',
             'yandex.com', 'yandex.ru', 'zoho.com', 'qq.com', '163.com', 'rediffmail.com'}
DISPOSABLE = {'mailinator.com', 'guerrillamail.com', '10minutemail.com', 'tempmail.com', 'yopmail.com', 'trashmail.com'}
ROLE = {'info', 'contact', 'hello', 'sales', 'office', 'admin', 'support', 'enquiries', 'enquiry', 'inquiries', 'inquiry',
        'bookings', 'booking', 'reservations', 'orders', 'help', 'team', 'mail', 'marketing', 'hr', 'jobs', 'careers',
        'accounts', 'billing', 'service', 'customerservice', 'reception', 'general'}
NO_REPLY = re.compile(r'^(no-?reply|do-?not-?reply|mailer-daemon|postmaster)$', re.I)
# ISO 3166 alpha-2 -> calling code, plus trunk prefix ('' where none) for common markets.
CALLING = {'pk': ('92', '0'), 'in': ('91', '0'), 'ae': ('971', '0'), 'sa': ('966', '0'), 'gb': ('44', '0'), 'us': ('1', '1'),
           'ca': ('1', '1'), 'au': ('61', '0'), 'nz': ('64', '0'), 'de': ('49', '0'), 'fr': ('33', '0'), 'nl': ('31', '0'),
           'es': ('34', ''), 'it': ('39', ''), 'pt': ('351', ''), 'ie': ('353', '0'), 'tr': ('90', '0'), 'eg': ('20', '0'),
           'ng': ('234', '0'), 'ke': ('254', '0'), 'za': ('27', '0'), 'bd': ('880', '0'), 'lk': ('94', '0'), 'my': ('60', '0'),
           'sg': ('65', ''), 'id': ('62', '0'), 'ph': ('63', '0'), 'qa': ('974', ''), 'kw': ('965', ''), 'om': ('968', ''),
           'bh': ('973', ''), 'jp': ('81', '0'), 'cn': ('86', '0'), 'br': ('55', '0'), 'mx': ('52', ''), 'se': ('46', '0'),
           'no': ('47', ''), 'dk': ('45', ''), 'ch': ('41', '0'), 'at': ('43', '0'), 'be': ('32', '0'), 'pl': ('48', '')}
# National significant number patterns that identify mobiles (others: unknown).
MOBILE = {'pk': r'3\d{9}', 'in': r'[6-9]\d{9}', 'ae': r'5\d{8}', 'sa': r'5\d{8}', 'gb': r'7\d{9}', 'tr': r'5\d{9}',
          'eg': r'1\d{9}', 'ng': r'[789]\d{9}', 'bd': r'1\d{9}', 'au': r'4\d{8}', 'de': r'1[5-7]\d{8,9}'}


# Valid national significant number lengths where well known (others: 8–15 total digits).
NATIONAL_LENGTH = {'pk': {9, 10}, 'in': {10}, 'ae': {8, 9}, 'sa': {8, 9}, 'gb': {9, 10}, 'us': {10}, 'ca': {10}, 'au': {9},
                   'tr': {10}, 'eg': {9, 10}, 'bd': {10}, 'ng': {8, 10}}


def website_group(url):
    return domain_group(url) if url else None


def analyse_email(value, website=None, mx=None):
    value = value.strip()
    result = {'value': value, 'type': 'email', 'signals': [], 'warnings': []}
    if not EMAIL.fullmatch(value):
        return result | {'quality': 'invalid', 'warnings': ['Not a valid email address format.']}
    local, domain = value.rsplit('@', 1)
    domain = domain.casefold()
    site = website_group(website)
    own = domain_group('https://' + domain)
    result.update(domain=domain, mailbox='role' if local.casefold().replace('.', '') in ROLE else 'no_reply' if NO_REPLY.match(local) else 'named',
                  provider='disposable' if domain in DISPOSABLE else 'free_mail' if domain in FREE_MAIL else 'own_domain',
                  matches_website=None if site is None else own == site)
    if result['mailbox'] == 'role':
        result['signals'].append('Generic business inbox (e.g. info@). Usually monitored, but not a named decision-maker.')
    elif result['mailbox'] == 'named':
        result['signals'].append('Looks like a named or personal mailbox.')
    else:
        result['warnings'].append('No-reply address: replies are not read.')
    if result['provider'] == 'free_mail':
        result['signals'].append('Free email provider. Common for small businesses; ownership is not proven by the domain.')
    elif result['provider'] == 'disposable':
        result['warnings'].append('Disposable email domain.')
    if result['matches_website'] is True:
        result['signals'].append('Same domain as the business website.')
    elif result['matches_website'] is False and result['provider'] == 'own_domain':
        result['warnings'].append('Domain differs from the business website. Check it belongs to this business, not a web agency or directory.')
    status = mx(domain) if mx else 'unknown'
    result['mail_server'] = status
    if status == 'has_mx':
        result['signals'].append('Domain publishes mail servers (MX), so it can receive email. The mailbox itself is not verified.')
    elif status in {'no_mx', 'null_mx', 'no_domain', 'invalid'}:
        result['warnings'].append({'no_mx': 'Domain publishes no mail servers (MX); email will probably bounce.',
                                   'null_mx': 'Domain explicitly accepts no email (null MX).',
                                   'no_domain': 'Domain does not exist in DNS.', 'invalid': 'Domain name is invalid.'}[status])
    bad = status in {'no_mx', 'null_mx', 'no_domain', 'invalid'} or result['provider'] == 'disposable' or result['mailbox'] == 'no_reply'
    result['quality'] = 'unusable' if bad else 'good' if status == 'has_mx' else 'unchecked'
    return result


def analyse_phone(value, country=None):
    raw = value.strip()
    result = {'value': raw, 'type': 'phone', 'signals': [], 'warnings': [], 'e164': None, 'line': 'unknown', 'whatsapp_link': None}
    digits = re.sub(r'\D', '', raw)
    country = (country or '').casefold() or None
    code, trunk = CALLING.get(country, (None, None))
    if raw.startswith('+') or raw.startswith('00'):
        international = digits[2:] if raw.startswith('00') else digits
    elif code and digits.startswith(code) and len(digits) - len(code) in NATIONAL_LENGTH.get(country, set()):
        international = digits  # country code written without the plus sign
    elif code == '1' and len(digits) == 10:
        international = '1' + digits
    elif code and trunk and digits.startswith(trunk) and len(digits) - len(trunk) >= 7:
        international = code + digits[len(trunk):]
    elif code and not trunk and len(digits) >= 7:
        international = code + digits
    elif code and country in MOBILE and re.fullmatch(MOBILE[country], digits):
        international = code + digits
        result['signals'].append('Written without the leading 0; read as a national mobile number.')
    else:
        international = None
        result['warnings'].append('No country prefix and the number could not be placed safely. Check the area code before calling.'
                                  if code else 'Country unknown, so the international format could not be determined.')
    plan = max((c for c, (cc, _) in CALLING.items() if international and international.startswith(cc) and c in NATIONAL_LENGTH),
               key=lambda c: len(CALLING[c][0]), default=None)
    if plan and len(international) - len(CALLING[plan][0]) not in NATIONAL_LENGTH[plan]:
        result['warnings'].append('Wrong number of digits for this country. It may be two numbers joined together or a typo.')
        international = None
    elif international is not None and not 8 <= len(international) <= 15:
        result['warnings'].append('Unusual length for an international number. It may be incomplete or mistyped.')
        international = None
    if international:
        result['e164'] = '+' + international
        # Judge the line type by the number's own country code (longest match), not the search country.
        plan = max((c for c, (cc, _) in CALLING.items() if international.startswith(cc) and c in MOBILE),
                   key=lambda c: len(CALLING[c][0]), default=None)
        if plan and not (CALLING[plan][0] == '1'):
            national = international[len(CALLING[plan][0]):]
            result['line'] = 'mobile' if re.fullmatch(MOBILE[plan], national) else 'landline_or_other'
        if result['line'] == 'mobile':
            result['signals'].append('Mobile number pattern. Can receive calls, SMS and possibly WhatsApp.')
        elif result['line'] == 'landline_or_other':
            result['signals'].append('Landline or office number pattern. Best for calls during opening hours.')
        if result['line'] != 'landline_or_other':
            result['whatsapp_link'] = f'https://wa.me/{international}'
    result['quality'] = 'good' if result['e164'] else 'needs_check'
    return result


def analyse_contacts(email=None, phone=None, website=None, country=None, mx=None):
    found = []
    for value in [v.strip() for v in re.split(r'[;,]', email or '') if v.strip()][:3]:
        found.append(analyse_email(value, website, mx))
    for value in [v.strip() for v in re.split(r'[;,/]', phone or '') if v.strip()][:3]:
        found.append(analyse_phone(value, country))
    usable = [c for c in found if c['quality'] in {'good', 'unchecked'}]
    best = 'email and phone' if {'email', 'phone'} <= {c['type'] for c in usable} else (usable[0]['type'] if usable else None)
    return {'items': found, 'reachable_by': best,
            'summary': f'Reachable by {best}.' if best else 'No usable contact listed. Find one by checking the website or visiting.'}


def contact_points(analysis):
    """Extra priority points for verified-looking contacts (transparent)."""
    points, reasons = 0, []
    if any(c['type'] == 'email' and c['quality'] == 'good' for c in analysis['items']):
        points += 1
        reasons.append('email domain can receive mail')
    if any(c['type'] == 'phone' and c['line'] == 'mobile' for c in analysis['items']):
        points += 1
        reasons.append('mobile number')
    return points, reasons
