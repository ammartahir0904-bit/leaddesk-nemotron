"""Six authored fictional audit examples. Never used as real quality evidence."""
from backend.adapters.fetch import Page
from backend.domain.assessments import IdentityReview
from backend.domain.extract import extract
from backend.domain.quality import AuditInput, BaselineInput
from backend.storage.assessments import AssessmentRepository
from backend.storage.quality import QualityRepository


DEMO_SCENARIOS = (
    ("Appointment support", "Fictional North", "Bookings are handled manually and appointments can overlap.", "pass", "positive_fit"),
    ("Appointment support", "Fictional South", "An existing booking provider handles all appointment work.", "fail", "existing_solution"),
    ("Stock planning", "Fictional North", "This branch is permanently closed.", "fail", "closed_branch"),
    ("Stock planning", "Fictional South", "The team says its current stock process meets its needs.", "fail", "no_need"),
    ("Tender alerts", "Fictional North", "Directory contact: the published number belongs to the directory operator, not the listed prospect.", "unknown", "directory_operator"),
    ("Tender alerts", "Fictional South", "This copied listing describes a similarly named business; the contact is not the target prospect's number.", "unknown", "same_name"),
)


def build_quality_demo(repository):
    """Caller must supply disposable storage. All created records are synthetic."""
    assessments = AssessmentRepository(repository)
    records = []
    for index, (offer, geography, scenario, _, _) in enumerate(DEMO_SCENARIOS):
        name = f"Fictional audit source {index + 1}"
        html = f'<h1>{name}</h1><p>Location: {geography}.</p><p>{scenario}</p><p>Phone: +1 202-555-{110 + index:04}.</p>'
        url = f'https://quality-fixture-{index + 1}.example/'
        record = repository.save({'product': offer, 'location': geography}, f'demo-{index}', Page(url, html.encode(), html), extract(html), True)
        def quote(wording):
            item = next(e for e in record['evidence'] if wording in e['excerpt'])
            return {'value': wording, 'evidence_ids': [item['id']]}
        record = assessments.save(record['id'], 'identity', IdentityReview(expected_revision=0,
            decision='unresolved' if index == 5 else 'source_attributed', source_role='business', business_name=quote(name), address=quote(geography),
            geography='matches', exclusions='clear', exclusion_reason='Fixture-authored prediction to exercise the audit.',
            contact_reviews=[] if index == 5 else [{'contact_id': c['id'], 'decision': 'attributed', 'evidence_ids': c['evidence_ids']} for c in record['contacts']]), f'identity-{index}')
        records.append(record)
    quality = QualityRepository(repository)
    baseline = quality.create(BaselineInput(name='Six fictional source-audit examples', mode='synthetic',
        research_ids=[r['id'] for r in records]), 'demo-baseline')
    for index, case in enumerate(baseline['cases']):
        snapshot = case['snapshot']
        _, _, _, relevance, tag = DEMO_SCENARIOS[index]
        def verdict(refs, result='pass'):
            return {'outcome': result, 'evidence_ids': refs[:1],
                    'reason': 'Authored fictional example only; inspect the scenario text. This is not a real manual review.'}
        identity_refs = snapshot['research']['assessment']['identity']['document']['business_name']['evidence_ids']
        quality.save_audit(baseline['id'], case['research_id'], AuditInput(
            expected_revision=0, reviewer='Fixture author · Synthetic demonstration',
            identity=verdict(identity_refs, 'unknown' if index == 5 else 'fail' if index == 4 else 'pass'),
            relevance=verdict([snapshot['research']['evidence'][0]['id']], relevance),
            contacts=[{'target_id': c['id'], **verdict(c['evidence_ids'], 'fail' if index >= 4 else 'pass')} for c in snapshot['lead']['contacts']],
            claims=[{'target_id': unit['id'], **verdict(unit['evidence_ids'])} for unit in snapshot['units']],
            issue_tags=[tag] + (['wrong_phone'] if index >= 4 else []),
            notes='Deliberately includes erroneous fixture-authored predictions and unknown relevance. No real prospect or buying interest is represented.'
        ), f'audit-{index}')
    result = quality.get(baseline['id'])
    result['demonstration'] = {'fictional': True, 'judgement_origin': 'developer_authored_fixture',
                               'purpose': 'Illustrate pass, fail, unknown, abstention and segment reporting; not an accuracy measurement.'}
    return result
