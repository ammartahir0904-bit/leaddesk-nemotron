"""Quality report (lead_quality_v1): how good the results are, measured from the contact review and the owner's corrections.

Every rate comes with its sample count and the date range it covers. Counts describe the saved searches only.
"""
import re
from collections import Counter, defaultdict
from datetime import datetime


def source_label(source):
    if source.startswith('Overture Maps'):
        return 'Overture Maps'
    if source in {'their own website', 'their own page online'}:
        return 'Their own website or profile'
    return source  # OpenStreetMap, or the host of a web page


def week(stamp):
    try:
        year, number, _ = datetime.fromisoformat(stamp[:19]).isocalendar()
        return f'{year}-W{number:02d}'
    except ValueError:
        return 'unknown'


def rate(part, whole):
    return {'count': part, 'of': whole, 'percent': round(100 * part / whole) if whole else None}


def report(searches, corrections):
    sources = defaultdict(Counter)
    verdicts, reasons = Counter(), Counter()
    dates = []
    for search in searches:
        dates.append(search['created_at'])
        for item in search['candidates']:
            for contact in (item.get('contact_review') or {}).get('contacts', []):
                verdicts[contact['verdict']] += 1
                corrected = (contact.get('correction') or {}).get('verdict') == 'wrong'
                for label in {source_label(s['source']) for s in contact['seen_in']} or {'Added by you'}:
                    sources[label][contact['verdict']] += 1
                    sources[label]['total'] += 1
                    sources[label]['corrected'] += corrected
                if contact['verdict'] == 'rejected' and contact['reasons']:
                    reasons[re.sub(r'\d+|"[^"]*"|\S+@\S+|\+?\d[\d ()-]{5,}', '…', contact['reasons'][0])[:90]] += 1
    total = sum(verdicts.values())
    by_source = sorted(({'source': name, 'total': c['total'], 'approved': rate(c['approved'], c['total']),
                         'needs_review': rate(c['needs_review'], c['total']), 'rejected': rate(c['rejected'], c['total']),
                         'corrected_by_you': rate(c['corrected'], c['total'])} for name, c in sources.items()), key=lambda r: -r['total'])
    features = Counter((f['feature'], f['detected_state'] != f['state']) for f in corrections['features'])
    detector = [{'feature': name, 'corrections': features[(name, True)]} for name in sorted({f for f, _ in features}) if features[(name, True)]]
    messages = Counter(m['action'] for m in corrections['messages'])
    problems = Counter(m['problem'] for m in corrections['messages'] if m['problem'])
    ai_used = [m for m in corrections['messages'] if m['ai_used']]
    weekly = defaultdict(Counter)
    for c in corrections['contacts']:
        weekly[week(c['created_at'])]['contact_corrections'] += 1
    for m in corrections['messages']:
        weekly[week(m['created_at'])][f"messages_{m['action']}"] += 1
    for f in corrections['features']:
        weekly[week(f['created_at'])]['feature_corrections'] += 1
    for r in corrections['rules']:
        weekly[week(r['approved_at'])]['rules_approved'] += 1
    reviewed = sum(messages.values())
    return {
        'method': 'lead_quality_v1',
        'sample': {'searches': len(searches), 'contacts': total, 'from': min(dates)[:10] if dates else None, 'to': max(dates)[:10] if dates else None},
        'contacts': {'approved': rate(verdicts['approved'], total), 'needs_review': rate(verdicts['needs_review'], total),
                     'rejected': rate(verdicts['rejected'], total), 'by_source': by_source,
                     'top_rejection_reasons': [{'reason': r, 'count': n} for r, n in reasons.most_common(8)]},
        'features': {'corrections': len(corrections['features']), 'by_feature': detector},
        'messages': {'reviewed': reviewed, 'approved_unedited': rate(messages['approved'], reviewed), 'edited': rate(messages['edited'], reviewed),
                     'rejected': rate(messages['rejected'], reviewed), 'problems': dict(problems),
                     'ai_reworded_and_approved': rate(sum(m['action'] == 'approved' for m in ai_used), len(ai_used))},
        'rules': {'active': sum(r['status'] == 'active' for r in corrections['rules']), 'off': sum(r['status'] == 'off' for r in corrections['rules'])},
        'weekly': [{'week': w} | dict(c) for w, c in sorted(weekly.items())],
        'note': 'Measured on your saved searches and your own corrections. Small samples move a lot; read the counts, not only the percentages.',
    }
