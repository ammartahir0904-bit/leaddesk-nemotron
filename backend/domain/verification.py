"""Is each phone number and email still current? Evidence-based status per contact.

Statuses (strongest first), each with the reasons and dates behind it:
  confirmed      shown on the business's own website read on that date, or the mail server accepted the mailbox
  corroborated   the same value from two or more independent sources
  single_source  only one source; may be outdated
  likely_wrong   not a valid number in its country's numbering plan, the mailbox was rejected, or the domain takes no mail
Nothing here proves that a person will answer; free methods cannot test whether a phone line is switched on.
"""
import re

import phonenumbers
from phonenumbers import PhoneNumberType, carrier

from backend.domain.extract import EMAIL

TYPES = {PhoneNumberType.MOBILE: 'mobile', PhoneNumberType.FIXED_LINE: 'landline', PhoneNumberType.FIXED_LINE_OR_MOBILE: 'landline or mobile',
         PhoneNumberType.VOIP: 'internet (VoIP)', PhoneNumberType.TOLL_FREE: 'toll-free', PhoneNumberType.SHARED_COST: 'shared-cost',
         PhoneNumberType.PREMIUM_RATE: 'premium-rate', PhoneNumberType.UAN: 'business (UAN)', PhoneNumberType.PERSONAL_NUMBER: 'personal',
         PhoneNumberType.PAGER: 'pager'}
RANK = {'confirmed': 0, 'corroborated': 1, 'single_source': 2, 'likely_wrong': 3}
LABEL = {'confirmed': 'Confirmed', 'corroborated': 'Corroborated', 'single_source': 'Single source', 'likely_wrong': 'Likely wrong'}


def phone_key(value, country):
    """E.164 when it parses, else the last 9 digits (so the same number written differently matches)."""
    try:
        number = phonenumbers.parse(value, (country or '').upper() or None)
        return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        return '~' + re.sub(r'\D', '', value)[-9:]


def phone_facts(value, country):
    try:
        number = phonenumbers.parse(value, (country or '').upper() or None)
    except phonenumbers.NumberParseException:
        return {'valid': False, 'e164': None, 'line': None, 'network': None,
                'problem': 'Cannot be read as a phone number for this country.'}
    valid = phonenumbers.is_valid_number(number)
    e164 = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    line = TYPES.get(phonenumbers.number_type(number))
    network = carrier.name_for_number(number, 'en') or None
    problem = None
    if not valid:
        problem = ('Not a valid number in the numbering plan of ' + (phonenumbers.region_code_for_number(number) or 'its country') +
                   ': it may be an old-format number (for example from before a city added a digit), mistyped or incomplete.')
    return {'valid': valid, 'e164': e164 if valid else None, 'line': line, 'network': network, 'problem': problem}


def sightings(item):
    """Every place a contact value was seen: (type, raw value, source family, label, url, date)."""
    seen = []
    record = item.get('evidence') or {}
    map_sources = item.get('sources') or ['OpenStreetMap']
    # 'Overture' in the dataset list is Overture's own conflation step, not a separate source.
    datasets = ', '.join(d for d in record.get('datasets') or (item.get('also') or {}).get('datasets') or [] if d.casefold() != 'overture')
    updated = record.get('updated') or (item.get('also') or {}).get('updated')
    overture_only = item.get('id', '').startswith('overture/')
    overture_label = f'Overture Maps ({datasets})' if datasets else 'Overture Maps'
    for kind, single, many in (('phone', item.get('phone'), item.get('phones')), ('email', item.get('email'), item.get('emails'))):
        # On an OpenStreetMap record the main value is OSM's (unless filled from Overture); the lists come from Overture.
        filled = (item.get('field_sources') or {}).get(kind) == 'Overture Maps'
        entries = [(single, 'overture' if overture_only or filled else 'osm')] + [(v, 'overture') for v in many or []]
        for value, family in entries:
            if not value:
                continue
            for part in [p.strip() for p in re.split(r'[;,]' if kind == 'email' else r'[;,/]', value) if p.strip()]:
                label = overture_label if family == 'overture' else 'OpenStreetMap'
                url = record.get('url') if family == 'overture' or not overture_only else None
                seen.append((kind, part, family, label, url, updated if family == 'overture' else None))
    check = item.get('check') or {}
    site = check.get('site') or {}
    for contact in site.get('contacts') or []:
        if contact['type'] in {'phone', 'whatsapp', 'email'}:
            seen.append(('email' if contact['type'] == 'email' else 'phone', contact['value'], 'own_website',
                         'their own website', contact.get('page_url'), (check.get('checked_at') or '')[:10] or None))
    for contact in (item.get('enrichment') or {}).get('contacts') or []:
        kind = 'email' if contact['type'] == 'email' else 'phone'
        own = contact.get('confidence') == 'own_page'
        host = re.sub(r'^https?://(www\.)?', '', contact.get('source_url') or '').split('/')[0]
        seen.append((kind, contact['value'], 'own_website' if own else f'web:{host}', 'their own page online' if own else host,
                     contact.get('source_url'), (item['enrichment'].get('enriched_at') or '')[:10] or None))
    return seen


def verify(item, country, probes=None):
    """probes: {email(lower): smtp result} for emails checked with the mail server (optional)."""
    probes = probes or {}
    groups = {}
    for kind, value, family, label, url, date in sightings(item):
        if kind == 'email':
            if not EMAIL.fullmatch(value):
                continue
            key = ('email', value.casefold())
        else:
            key = ('phone', phone_key(value, country))
        entry = groups.setdefault(key, {'type': kind, 'value': value, 'seen_in': [], 'families': set()})
        if (label, url) not in {(s['source'], s['url']) for s in entry['seen_in']}:
            entry['seen_in'].append({'source': label, 'url': url, 'date': date})
        entry['families'].add(family)
    out = []
    for (kind, _), entry in groups.items():
        reasons, status = [], None
        families = entry.pop('families')
        on_site = 'own_website' in families
        if kind == 'phone':
            facts = phone_facts(entry['value'], country)
            entry.update(facts)
            if not facts['valid']:
                status = 'likely_wrong'
                reasons.append(facts['problem'])
            else:
                reasons.append(f"Valid {facts['line'] or 'phone'} number{' on ' + facts['network'] if facts['network'] else ''} "
                               '(numbering plan check; it cannot show whether the line is switched on).')
        else:
            probe = probes.get(entry['value'].casefold())
            entry['mailbox_check'] = probe
            if probe and probe['result'] in {'rejected', 'no_mail_server'}:
                status = 'likely_wrong'
                reasons.append('The mail server says this mailbox does not exist.' if probe['result'] == 'rejected' else probe['detail'])
            elif probe and probe['result'] == 'accepted':
                status = 'confirmed'
                reasons.append(f"The mail server ({probe['server']}) accepted this mailbox on {probe['checked_at'][:10]}; no email was sent.")
            elif probe and probe['result'] == 'catch_all':
                reasons.append('The mail server accepts any address at this domain, so the mailbox itself could not be confirmed.')
            elif probe:
                reasons.append({'blocked': 'The mail server refused the check from this network.',
                                'unreachable': probe['detail'], 'unknown': 'The mail server gave no clear answer; retry later.',
                                'full': 'The mailbox exists but is full.'}.get(probe['result'], probe['detail']))
        if status is None:
            if on_site:
                status = 'confirmed'
                date = next((s['date'] for s in entry['seen_in'] if s['source'].startswith('their own') and s['date']), None)
                reasons.append(f"Shown on their own website{' (read ' + date + ')' if date else ''}.")
            elif len(families) >= 2:
                status = 'corroborated'
                reasons.append(f'Found in {len(families)} independent sources: ' + ', '.join(s['source'] for s in entry['seen_in']) + '.')
            else:
                status = 'single_source'
                reasons.append(f"Only one source ({entry['seen_in'][0]['source']}); it may be outdated.")
        dated = sorted(s['date'] for s in entry['seen_in'] if s['date'])
        if dated:
            reasons.append(f'Latest source date: {dated[-1]}.')
        out.append(entry | {'status': status, 'label': LABEL[status], 'reasons': reasons})
    out.sort(key=lambda c: (RANK[c['status']], c['type'] != 'phone'))
    best = next((c for c in out if c['status'] in {'confirmed', 'corroborated'}), None)
    return {'contacts': out, 'counts': {s: sum(c['status'] == s for c in out) for s in RANK},
            'best': {'type': best['type'], 'value': best.get('e164') or best['value'], 'status': best['status']} if best else None,
            'method': 'contact_verification_v1',
            'note': 'Confirmed means shown on their own website or accepted by their mail server; it does not prove someone will answer.'}
