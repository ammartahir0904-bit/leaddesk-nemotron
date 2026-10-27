"""Descriptive source-audit statistics. No model self-scoring or release certification."""
import math
from collections import Counter, defaultdict

from backend.domain.assessments import normalized
from backend.domain.quality import ISSUE_TAGS, snapshot_evidence


def proportion(outcomes: list[str], target: float | None = None) -> dict:
    counts = Counter(outcomes)
    reviewed = counts["pass"] + counts["fail"]
    total = len(outcomes)
    rate = counts["pass"] / reviewed if reviewed else None
    interval = None
    if reviewed:
        z = 1.959963984540054
        denominator = 1 + z * z / reviewed
        center = (rate + z * z / (2 * reviewed)) / denominator
        margin = z * math.sqrt(rate * (1 - rate) / reviewed + z * z / (4 * reviewed * reviewed)) / denominator
        interval = [max(0.0, center - margin), min(1.0, center + margin)]
    status = "not_measured" if not reviewed else "incomplete" if reviewed < total else "below_target" if target is not None and rate < target else "observed_target_met" if target is not None else "descriptive_only"
    return {"eligible": total, "reviewed": reviewed, "passed": counts["pass"], "failed": counts["fail"],
            "unknown": counts["unknown"], "unreviewed": counts["unreviewed"], "rate": rate,
            "wilson_95": interval, "target": target, "gate_status": status}


def outcome(verdict: dict | None) -> str:
    return verdict["outcome"] if verdict else "unreviewed"


def group_report(cases: list[dict]) -> dict:
    identities, contacts, support, references, relevance = [], [], [], [], []
    identity_abstentions = contact_abstentions = complete = source_changed = 0
    flags = Counter()
    for case in cases:
        snapshot = case["snapshot"]
        lead = snapshot["lead"]
        document = (case.get("audit") or {}).get("document") or {}
        case_outcomes = [outcome(document.get("identity"))]
        if lead["identity_status"] == "source_attributed":
            identities.append(outcome(document.get("identity")))
        else:
            identity_abstentions += 1
        contact_reviews = {v["target_id"]: v for v in document.get("contacts", [])}
        for contact in lead["contacts"]:
            case_outcomes.append(outcome(contact_reviews.get(contact["id"])))
            if contact["effective_state"] == "attributed":
                contacts.append(outcome(contact_reviews.get(contact["id"])))
            else:
                contact_abstentions += 1
        evidence = snapshot_evidence(snapshot)
        claim_reviews = {v["target_id"]: v for v in document.get("claims", [])}
        for unit in snapshot["units"]:
            refs = unit["evidence_ids"]
            references.append("pass" if refs and set(refs) <= evidence.keys() else "fail")
            support.append(outcome(claim_reviews.get(unit["id"])))
            case_outcomes.append(support[-1])
        relevance.append(outcome(document.get("relevance")))
        case_outcomes.append(relevance[-1])
        complete += bool(case.get("audit")) and all(v in {"pass", "fail"} for v in case_outcomes)
        source_changed += bool(case.get("source_changed_since_snapshot"))
        flags.update(document.get("issue_tags", []))
    return {
        "sample_count": len(cases), "fully_reviewed_cases": complete, "changed_since_snapshot": source_changed,
        "identity_abstentions": identity_abstentions, "contact_abstentions_or_exclusions": contact_abstentions,
        "identity_accuracy": proportion(identities, .95), "contact_attribution_precision": proportion(contacts, .95),
        "factual_reference_coverage": proportion(references, 1.0), "audited_evidence_support": proportion(support, .95),
        "reviewed_relevance_rate": proportion(relevance),
        "precision_at_20": {"rate": None, "gate_status": "not_measured", "target": .8,
                            "reason": "The current dashboard has no ranked shortlist snapshot. A relevance rate over selected cases is not precision@20."},
        "reviewer_issue_tags": dict(flags),
    }


def quality_report(cases: list[dict], mode: str) -> dict:
    segments = defaultdict(list)
    for case in cases:
        lead = case["snapshot"]["lead"]
        segments[(normalized(lead["product"]), normalized(lead["target_geography"]))].append(case)
    global_results = group_report(cases)
    offers = {key[0] for key in segments}
    geographies = {key[1] for key in segments}
    missing = []
    if mode == "synthetic":
        missing.append("Synthetic examples cannot establish real-source quality or satisfy the real review sample.")
    if global_results["fully_reviewed_cases"] < 60:
        missing.append("The plan requires at least 60 fully reviewed real prospects; unknown or missing judgements do not count as complete.")
    if len(offers) < 3 or len(geographies) < 2:
        missing.append("The plan requires three unrelated offers and two geographies. Label counts alone cannot establish that offers are unrelated.")
    if global_results["changed_since_snapshot"]:
        missing.append("Live records changed after capture. Results describe frozen predictions, not the current records.")
    missing.append("Precision@20, independent identity/contact adjudication and broader live-source acceptance remain unestablished.")
    return {
        "overall": global_results,
        "segments": [{"offer": values[0]["snapshot"]["lead"]["product"],
                      "target_geography": values[0]["snapshot"]["lead"]["target_geography"], **group_report(values)}
                     for _, values in sorted(segments.items())],
        "requirements": {"minimum_real_reviewed_cases": 60, "real_fully_reviewed_cases": global_results["fully_reviewed_cases"] if mode == "live" else 0,
                         "offer_labels": len(offers), "geography_labels": len(geographies),
                         "scenario_tags_not_yet_recorded": [tag for tag in ISSUE_TAGS[:9] if not global_results["reviewer_issue_tags"].get(tag)]},
        "release_readiness": "not_established", "missing_acceptance": missing,
        "other_release_gates": [
            {"metric": "disputed_contacts_in_approved_queue", "target": 0, "status": "not_measured", "reason": "No outreach-approved queue exists; absence of approval is not a tested approval safeguard."},
            {"metric": "duplicate_outbound_actions", "target": 0, "status": "not_measured", "reason": "Outbound integrations and their retry evaluation are not implemented."},
            {"metric": "fabricated_contacts_or_file_paths_in_fixtures", "target": 0, "status": "not_measured", "reason": "This source-audit report does not run the separate parser fixture suite or a file-search evaluation."},
            {"metric": "local_file_success_at_3", "target": .9, "status": "not_measured", "reason": "Approved-folder search and its representative 30-task evaluation are future work."},
        ],
        "methodology": [
            "Pass/fail are manual reviewer judgements against saved excerpts, not independently established ground truth or proof of reachability.",
            "Unknown and unreviewed cases are shown separately and never counted as correct. Rates use known pass/fail judgements only; incomplete audit coverage cannot meet a gate.",
            "Identity/contact precision counts only source-attributed identity and effective attributed contacts captured as predictions. Abstentions and excluded contacts are reported separately.",
            "Factual reference coverage tests the presence and scope of evidence IDs. It does not prove semantic support; that requires the separate manual evidence audit.",
            "95% Wilson intervals use an independent Bernoulli approximation. Correlated pages, contacts and reviewer selection bias limit interpretation; these are descriptive intervals, not universal accuracy guarantees.",
            "Observed target met means the point estimate on fully audited eligible units reaches the proposed threshold. It does not imply statistical certification, adequate sample size or release readiness.",
            "Cases have distinct source URLs, not independently resolved business identities. Separate pages can still describe the same business. Offer/geography grouping normalizes case and whitespace only.",
            "User-selected samples are not random samples. Development and holdout declarations are user supplied; no automatic training, ranking, promotion or outreach occurs.",
        ],
    }
