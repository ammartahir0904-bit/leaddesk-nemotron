"""Built-in deterministic contact ranker candidate (contact_ranker_v1).

Reads only an example's reviewed input text and source domain group, never its
observed or expected output. Weights were fixed on fictional fixtures before any
real reviewed data; they are a transparent heuristic, not a calibrated probability.
"""
import re

from backend.domain.extract import EMAIL, PHONE
from backend.domain.learning import domain_group

NAME = 'contact_ranker_v1'
TASK = 'contact_attribution'
FREE_MAIL = {'gmail.com', 'googlemail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'live.com', 'icloud.com', 'proton.me', 'protonmail.com', 'aol.com'}
THIRD_PARTY = re.compile(r'\b(?:designed|developed|built|powered|hosted|maintained|managed|made)\s+by\b|\bweb\s*(?:design|development|site\s+by)\b'
                         r'|\bagency\b|\bdeveloper\b|\bcopyright\b|©', re.I)
OWNER_CUE = re.compile(r'\b(?:contact|enquir\w*|inquir\w*|reception|office|sales|bookings?|orders?|reservations?|customer|support|call|email|e-mail|phone|tel|mobile)\b', re.I)
WEIGHTS = {'third_party_context': -4, 'same_domain_email': 2, 'free_mail': 0, 'foreign_domain_email': -1, 'owner_cue': 1}
MIN_SCORE = 1


def _contacts(text):
    found = []
    for line in text.splitlines():
        matches = []
        for match in EMAIL.finditer(line):
            if len(match.group()) <= 254:
                matches.append((match.start(), match.end(), 'email', match.group()))
        for match in PHONE.finditer(line):
            value = match.group().strip()
            digits = re.sub(r'\D', '', value)
            if 7 <= len(digits) <= 15 and not re.fullmatch(r'\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4}', value):
                matches.append((match.start(), match.end(), 'phone', value))
        previous = 0
        for start, end, kind, value in sorted(matches):
            # Labels normally precede values; only the text since the previous value counts.
            found.append((kind, value, line[previous:start]))
            previous = end
    return found


def score(kind, value, context, host_group):
    total, reasons = 0, []
    if THIRD_PARTY.search(context):
        reasons.append('third_party_context')
    if kind == 'email':
        group = domain_group('https://' + value.rsplit('@', 1)[1])
        reasons.append('same_domain_email' if group == host_group else 'free_mail' if group in FREE_MAIL else 'foreign_domain_email')
    if OWNER_CUE.search(context):
        reasons.append('owner_cue')
    for reason in reasons:
        total += WEIGHTS[reason]
    return total, reasons


def predict(example):
    """Return (output or None, decision code). Input: id, task, input_text, domain_group."""
    if example['task'] != TASK:
        return None, 'not_applicable_task'
    ranked = {}
    for kind, value, context in _contacts(example['input_text']):
        total, _ = score(kind, value, context, example['domain_group'])
        ranked[value] = max(total, ranked.get(value, total))
    if not ranked:
        return None, 'abstained_no_contact'
    best = max(ranked.values())
    if best < MIN_SCORE:
        return None, 'abstained_low_score'
    top = [value for value, total in ranked.items() if total == best]
    if len(top) > 1:
        return None, 'abstained_tie'
    return top[0], 'selected'


def configuration():
    return {'candidate': NAME, 'task': TASK, 'weights': WEIGHTS, 'min_score': MIN_SCORE, 'free_mail': sorted(FREE_MAIL),
            'inputs': ['input_text', 'domain_group'], 'excluded_inputs': ['observed_output', 'expected_output', 'reviewer', 'reason']}
