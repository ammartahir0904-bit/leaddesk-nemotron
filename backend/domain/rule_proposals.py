"""Rules learned from the owner's repeated corrections (rule_proposals_v1). Proposed, never applied, until approved.

A single correction never creates a rule. Each proposal lists the corrections it comes from and a preview of how many
current results it would change (evaluation on stored data), so the owner decides with evidence. Approved rules are
deterministic, versioned in learned_rule, and can be switched off (rollback). No model weights change.
"""
from collections import defaultdict

from backend.domain.contact_analysis import FREE_MAIL

MIN_CORRECTIONS = 3


def proposals(corrections, items, active):
    """corrections: storage.corrections(); items: every lead of every saved search; active: {(kind, value)} already approved."""
    found = []
    by_domain, by_host, by_detector = defaultdict(list), defaultdict(list), defaultdict(list)
    trusted_hosts = {h for c in corrections['contacts'] if c['verdict'] in {'correct', 'added'} for h in c['source_hosts']}
    for c in corrections['contacts']:
        if c['verdict'] != 'wrong':
            continue
        if c['type'] == 'email' and c['reason'] in {'fake', 'temporary', 'not_theirs'}:
            domain = c['value_key'].rpartition('@')[2]
            if domain not in FREE_MAIL:
                by_domain[domain].append(c)
        if c['reason'] in {'not_theirs', 'fake'}:
            for h in c['source_hosts']:
                by_host[h].append(c)
    for f in corrections['features']:
        if f['detected_state'] in {'has', 'missing'} and f['detected_state'] != f['state'] and f['trade']:
            by_detector[f"{f['trade']}:{f['feature']}"].append(f)

    def add(kind, value, description, evidence, preview):
        if (kind, value) not in active:
            found.append({'kind': kind, 'value': value, 'description': description, 'evidence': evidence, 'preview': preview})

    for domain, rows in by_domain.items():
        values = {r['value_key'] for r in rows}
        if len(values) >= MIN_CORRECTIONS:
            hits = [c for i in items for c in (i.get('contact_review') or {}).get('contacts', [])
                    if c['type'] == 'email' and c['value'].casefold().endswith('@' + domain) and c['verdict'] != 'rejected']
            add('block_email_domain', domain, f'Reject every email at {domain}: you marked {len(values)} addresses there as wrong.',
                [{'value': r['value'], 'business': r['business_name'], 'reason': r['reason'], 'date': r['created_at'][:10]} for r in rows],
                {'contacts_changed': len(hits), 'examples': [h['value'] for h in hits[:5]]})
    for h, rows in by_host.items():
        values = {(r['type'], r['value_key']) for r in rows}
        if len(values) >= MIN_CORRECTIONS and h not in trusted_hosts:
            hits = [c for i in items for c in (i.get('contact_review') or {}).get('contacts', [])
                    if c['source_hosts'] == [h] and c['verdict'] != 'rejected']
            add('distrust_source_host', h, f'Do not trust contacts found only on {h}: {len(values)} of its contacts were wrong.',
                [{'value': r['value'], 'business': r['business_name'], 'reason': r['reason'], 'date': r['created_at'][:10]} for r in rows],
                {'contacts_changed': len(hits), 'examples': [c['value'] for c in hits[:5]]})
    for key, rows in by_detector.items():
        if len({r['business_key'] for r in rows}) >= MIN_CORRECTIONS:
            trade, feature = key.split(':', 1)
            hits = [i['name'] for i in items for f in (i.get('offer_fit') or {}).get('features', [])
                    if (i.get('offer_fit') or {}).get('trade') == trade and f['id'] == feature and f['detected_state'] in {'has', 'missing'}
                    and not f.get('corrected')]
            wrong = rows[0]['detected_state']
            add('detector_off', key, f'Stop judging "{feature.replace("_", " ")}" for {trade.replace("_", " ")} businesses: you corrected it '
                                     f'{len(rows)} times (LeadDesk said "{wrong}").',
                [{'business': r['business_key'], 'detected': r['detected_state'], 'you_said': r['state'], 'note': r['note'],
                  'date': r['created_at'][:10]} for r in rows],
                {'features_changed': len(hits), 'examples': hits[:5]})
    return {'method': 'rule_proposals_v1', 'proposals': found, 'minimum': MIN_CORRECTIONS,
            'note': f'A rule is proposed only after {MIN_CORRECTIONS} or more corrections of the same kind. Nothing changes until you approve it.'}
