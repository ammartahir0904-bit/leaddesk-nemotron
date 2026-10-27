"""Paired descriptive exact-text metrics, without semantic/production claims."""
from collections import defaultdict


def counts(rows):
    n = len(rows)
    baseline = sum(row['baseline_correct'] for row in rows)
    candidate = sum(row['candidate_correct'] for row in rows)
    return {'sample_count': n, 'baseline_correct': baseline, 'candidate_correct': candidate,
            'baseline_exact_match': baseline / n if n else None,
            'candidate_exact_match': candidate / n if n else None,
            'abstentions': sum(row['abstained'] for row in rows),
            'gains': sum(row['candidate_correct'] and not row['baseline_correct'] for row in rows),
            'regressions': sum(row['baseline_correct'] and not row['candidate_correct'] for row in rows)}


def compare(examples, predictions, executed=False):
    by_id = {p.example_id: p.output for p in predictions}
    rows, tasks, domains = [], defaultdict(list), defaultdict(list)
    for example in examples:
        review, provenance = example['review'], example['provenance']
        output = by_id[example['id']]
        row = {'baseline_correct': review['observed_output'] == review['expected_output'],
               'candidate_correct': output is not None and output == review['expected_output'],
               'abstained': output is None}
        rows.append(row)
        tasks[provenance['task']].append(row)
        domains[provenance['domain_group']].append(row)
    total = counts(rows)
    if total['regressions']:
        outcome = 'regressions_observed'
    elif total['gains']:
        outcome = 'sample_improvement_observed'
    else:
        outcome = 'no_improvement_observed'
    return {'metric': 'exact_text_v1', 'overall': total, 'outcome': outcome,
            'by_task': {key: counts(value) for key, value in sorted(tasks.items())},
            'by_domain': {key: counts(value) for key, value in sorted(domains.items())},
            'promotion_allowed': False, 'independent_holdout_verified': False,
            'limitations': [
                'Descriptive agreement with human-authored text, not factual correctness or ranking quality.',
                ('The bundled candidate ran locally on this host; its artifact hash covers source and configuration only.' if executed else
                 'Imported outputs and artifact identity are user assertions; no candidate execution is verified.'),
                'Labels may have been inspected; repeated holdout comparisons are not independent evaluation.',
                'Sample improvements do not establish statistical significance or production release gates.',
                'Null abstentions count as incorrect; expected abstention text must match exactly.',
            ]}
