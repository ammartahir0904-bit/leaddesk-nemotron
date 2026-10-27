"""Bounded dashboard and export reads from one SQLite snapshot, without fetching."""
import json
from collections import Counter

from backend.domain.leads import LeadFilters, LeadPage, matches, summarize
from backend.domain.errors import ResearchError
from backend.storage.assessment_views import raw_record
from backend.storage.repository import Repository, now

SCAN_LIMIT = 200
MAX_EXPORT_BYTES = 16 * 1024 * 1024


class LeadRepository:
    def __init__(self, repository: Repository):
        self.repository = repository

    def _selection(self, db, filters: LeadFilters):
        total = db.execute("SELECT COUNT(*) FROM campaign WHERE synthetic=?", (filters.mode == "synthetic",)).fetchone()[0]
        rows = db.execute("SELECT id FROM campaign WHERE synthetic=? ORDER BY created_at DESC,id DESC LIMIT ?",
                          (filters.mode == "synthetic", SCAN_LIMIT)).fetchall()
        records, leads = [], []
        for row in rows:
            record = self.repository.get_in_transaction(db, row["id"])
            lead = summarize(record)
            if matches(lead, filters):
                records.append(record)
                leads.append(lead)
        return records, leads, {
            "total_in_mode": total, "scanned": len(rows), "scan_limit": SCAN_LIMIT,
            "scan_limited": total > len(rows), "matched": len(leads),
            "description": "Filters and exports cover the newest 200 saved records in the selected mode. Each record covers its saved page only; duplicates are not merged. No coverage of the wider market is claimed.",
        }

    def page(self, filters: LeadPage) -> dict:
        with self.repository.connect() as db:
            db.execute("BEGIN")
            _, leads, coverage = self._selection(db, filters)
            timestamp = now()
        end = filters.offset + filters.limit
        return {
            "items": leads[filters.offset:end], "coverage": coverage, "generated_at": timestamp,
            "offset": filters.offset, "limit": filters.limit,
            "next_offset": end if end < len(leads) else None,
            "summary": dict(Counter(lead["review_state"] for lead in leads)),
            "scope": "Source-reviewed means local manual checks are current. It does not establish corroboration, reachability, buying intent, budget or outreach approval.",
        }

    def export(self, filters: LeadFilters) -> dict:
        with self.repository.connect() as db:
            db.execute("BEGIN")
            records, leads, coverage = self._selection(db, filters)
            items = []
            exported_bytes = 0
            for record, lead in zip(records, leads):
                history = db.execute("SELECT kind,revision,created_at,document_json FROM assessment_revision WHERE campaign_id=? ORDER BY created_at DESC,id DESC LIMIT 101", (record["id"],)).fetchall()
                revisions = [{"kind": row["kind"], "revision": row["revision"], "created_at": row["created_at"],
                              "review": json.loads(row["document_json"])} for row in history[:100]]
                # Include foreign evidence cited in current or exported historical comparisons.
                comparison_ids = set()
                identity = (record.get("assessment") or {}).get("identity")
                for review in ([identity] if identity else []) + [r["review"] for r in revisions if r["kind"] == "identity"]:
                    comparison_ids.update(c["research_id"] for c in review["document"]["comparisons"])
                sources = []
                for research_id in sorted(comparison_ids):
                    other = raw_record(db, research_id)
                    sources.append({"id": research_id, "source_url": other["source_url"],
                                    "synthetic": bool(other["synthetic"]), "evidence": other["evidence"]})
                item = {"lead": lead, "research": record, "assessment_history": revisions,
                        "history_limited": len(history) > 100, "history_limit": 100,
                        "comparison_sources": sources}
                exported_bytes += len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
                if exported_bytes > MAX_EXPORT_BYTES:
                    raise ResearchError("This export exceeds the 16 MiB record-data limit. Narrow the search or review filters and download again. No partial file was created.", status=413)
                items.append(item)
            return {
                "schema_version": "1", "generated_at": now(), "mode": filters.mode,
                "synthetic": filters.mode == "synthetic", "filters": filters.model_dump(),
                "coverage": coverage, "records": items,
                "scope": "Research records, source excerpts and reviewer inferences for inspection. Suppressed and excluded contacts are retained for audit with explicit labels. Nothing here approves outreach or confirms buying interest, budget, ownership or reachability. Suggested corrections are unverified feedback.",
            }
