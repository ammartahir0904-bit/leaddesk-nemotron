"""Spreadsheet-safe CSV with explicit review states and complete JSON audit data."""
import csv
import io
import json


def safe_cell(value):
    text = "" if value is None else str(value)
    # Also catch formulas hidden behind leading whitespace/control characters.
    significant = text.lstrip(" \t\r\n\v\f\ufeff")
    if significant.startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def to_csv(document: dict) -> str:
    output = io.StringIO(newline="")
    fields = [
        "schema_version", "exported_at", "synthetic", "coverage_scanned", "coverage_total_in_mode", "coverage_limited",
        "research_id", "source_heading", "business_name", "branch", "address", "service_area", "source_url",
        "created_at", "product", "target_geography", "identity_status", "identity_reviewed_at",
        "review_state", "review_reasons", "exclusion_reasons", "analysis_state", "saved_fit", "effective_fit",
        "analysis_reviewed_at", "need_hypothesis", "analysis_interpretation", "intent_state", "budget", "budget_reason", "next_action", "outreach_approved",
        "contact_id", "contact_type", "contact_raw_value", "contact_normalised_value", "contact_attribution_state",
        "contact_effective_state", "contact_suppressed", "contact_excluded", "contact_last_checked_at",
        "contact_attribution_reviewed_at", "contact_reachability", "contact_exclusion_reasons", "contact_evidence_json", "research_audit_json",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\r\n")
    writer.writeheader()
    for item in document["records"]:
        lead = item["lead"]
        common = {key: lead.get(key) for key in fields if key in lead}
        common.update({
            "schema_version": document["schema_version"], "exported_at": document["generated_at"],
            "coverage_scanned": document["coverage"]["scanned"], "coverage_total_in_mode": document["coverage"]["total_in_mode"],
            "coverage_limited": document["coverage"]["scan_limited"], "research_id": lead["id"],
            "review_reasons": json.dumps(lead["review_reasons"], ensure_ascii=False),
            "exclusion_reasons": json.dumps(lead["exclusion_reasons"], ensure_ascii=False),
        })
        for index, contact in enumerate(lead["contacts"] or [None]):
            row = dict(common)
            # Carry the complete audit once per record, on its first contact row.
            if index == 0:
                row["research_audit_json"] = json.dumps({k: v for k, v in item.items() if k != "lead"}, ensure_ascii=False)
            if contact:
                row.update({"contact_id": contact["id"], "contact_type": contact["type"],
                            "contact_raw_value": contact["raw_value"], "contact_normalised_value": contact["normalised_value"],
                            "contact_attribution_state": contact["attribution_state"], "contact_effective_state": contact["effective_state"],
                            "contact_suppressed": contact["suppressed"], "contact_excluded": contact["excluded"],
                            "contact_last_checked_at": contact["last_checked_at"],
                            "contact_attribution_reviewed_at": contact.get("attribution_reviewed_at"),
                            "contact_reachability": contact["reachability"],
                            "contact_exclusion_reasons": json.dumps(contact["exclusion_reasons"], ensure_ascii=False),
                            "contact_evidence_json": json.dumps(contact["evidence"], ensure_ascii=False)})
            writer.writerow({key: safe_cell(value) for key, value in row.items()})
    return output.getvalue()
