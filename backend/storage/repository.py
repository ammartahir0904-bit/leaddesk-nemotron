import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from backend.domain.errors import ResearchError


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


def request_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class Repository:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def migrate(self):
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS schema_migration(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            for path in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
                version = int(path.name.split("_")[0])
                if not db.execute("SELECT 1 FROM schema_migration WHERE version=?", (version,)).fetchone():
                    # One transaction covers the whole migration and version marker.
                    stamp = now().replace("'", "''")
                    db.executescript(f"BEGIN IMMEDIATE;\n{path.read_text()}\nINSERT INTO schema_migration VALUES({version},'{stamp}');\nCOMMIT;")

    def cached(self, key, digest):
        with self.connect() as db:
            row = db.execute("SELECT * FROM research_request WHERE idempotency_key=?", (key,)).fetchone()
            if not row:
                return None
            if row["request_hash"] != digest:
                raise ResearchError("This request key was already used with different inputs.", status=409)
        return self.get(row["campaign_id"])

    def save(self, payload, key, page, extracted, synthetic=False, *, brief_snapshot=None, digest=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            campaign_id = self.save_in_transaction(db, payload, key, page, extracted, synthetic,
                                                   brief_snapshot=brief_snapshot, digest=digest)
        return self.get(campaign_id)

    def save_in_transaction(self, db, payload, key, page, extracted, synthetic=False, *, brief_snapshot=None, digest=None):
        """Caller owns the transaction; workflows commit result and step together."""
        digest = digest or request_hash(payload)
        cached = db.execute("SELECT * FROM research_request WHERE idempotency_key=?", (key,)).fetchone()
        if cached:
            if cached["request_hash"] != digest:
                raise ResearchError("This request key was already used with different inputs.", status=409)
            return cached["campaign_id"]
        campaign_id, business_id, timestamp = uid(), uid(), now()
        content_hash = hashlib.sha256(page.body).hexdigest()
        host = urlsplit(page.url).hostname
        db.execute("INSERT INTO campaign(id,product,geography,created_at,synthetic) VALUES(?,?,?,?,?)",
                   (campaign_id, payload["product"], payload["location"], timestamp, synthetic))
        if brief_snapshot is not None:
            db.execute("UPDATE campaign SET brief_snapshot_json=? WHERE id=?", (json.dumps(brief_snapshot), campaign_id))
        db.execute("INSERT INTO business(id,campaign_id,canonical_name,source_url) VALUES(?,?,?,?)",
                   (business_id, campaign_id, extracted.name, page.url))

        def evidence(excerpt, method="visible_html_v1"):
            eid = uid()
            db.execute("INSERT INTO evidence(id,business_id,source_url,retrieved_at,content_hash,excerpt,extraction_method) VALUES(?,?,?,?,?,?,?)",
                       (eid, business_id, page.url, timestamp, content_hash, excerpt, method))
            return eid

        if extracted.name:
            eid = evidence(extracted.name_excerpt)
            db.execute("INSERT INTO claim(id,business_id,predicate,value,evidence_id) VALUES(?,?,?,?,?)",
                       (uid(), business_id, "source_heading", extracted.name, eid))
        for contact in extracted.contacts:
            cid = uid()
            suppressed = bool(db.execute("SELECT 1 FROM suppression WHERE source_host=? AND type=? AND normalised_value=?",
                              (host, contact["type"], contact["normalised_value"])).fetchone())
            db.execute("INSERT INTO contact VALUES(?,?,?,?,?,?,?,?)", (cid, business_id, contact["type"], contact["raw_value"],
                       contact["normalised_value"], "disputed" if suppressed else "extracted", suppressed, timestamp))
            eid = evidence(contact["excerpt"])
            db.execute("INSERT INTO contact_evidence VALUES(?,?)", (cid, eid))
        for excerpt in extracted.source_excerpts:
            evidence(excerpt, "visible_text_context_v1")
        db.execute("INSERT INTO research_request VALUES(?,?,?)", (key, digest, campaign_id))
        return campaign_id

    def get(self, campaign_id):
        with self.connect() as db:
            return self.get_in_transaction(db, campaign_id)

    def get_in_transaction(self, db, campaign_id):
        """Read effective states using the caller's consistent database snapshot."""
        row = db.execute("SELECT c.*, b.id AS business_id, b.canonical_name, b.source_url, b.identity_status FROM campaign c JOIN business b ON b.campaign_id=c.id WHERE c.id=?", (campaign_id,)).fetchone()
        if not row:
            raise ResearchError("Research record not found.", status=404)
        record = dict(row)
        snapshot = record.pop("brief_snapshot_json", None)
        assessment = record.pop("assessment_json", None)
        record["assessment"] = None
        record["product_brief"] = json.loads(snapshot) if snapshot else None
        record["synthetic"] = bool(record["synthetic"])
        bid = record["business_id"]
        record["evidence"] = [dict(r) for r in db.execute("SELECT * FROM evidence WHERE business_id=?", (bid,))]
        record["claims"] = [dict(r) for r in db.execute("SELECT * FROM claim WHERE business_id=?", (bid,))]
        record["contacts"] = []
        for contact in db.execute("SELECT * FROM contact WHERE business_id=?", (bid,)):
            value = dict(contact)
            value["suppressed"] = bool(value["suppressed"])
            value["evidence_ids"] = [r[0] for r in db.execute("SELECT evidence_id FROM contact_evidence WHERE contact_id=?", (value["id"],))]
            record["contacts"].append(value)
        record["feedback"] = [dict(r) for r in db.execute("SELECT f.* FROM feedback f JOIN contact c ON c.id=f.contact_id WHERE c.business_id=? ORDER BY f.created_at DESC", (bid,))]
        record["unknowns"] = {
            "official_business_identity": "The source heading is a candidate name; website ownership and branch are unconfirmed.",
            "business_location": "Your target location is saved separately; this page has not established the business location.",
            "contact_ownership": "Contacts appear on this page; ownership, role and reachability require review.",
            "contact_format": "Phone-like text is a candidate number, not a validity check. Local numbers retain source formatting because no country is assumed.",
            "buying_intent": "Not established by contact extraction.",
            "budget": "No evidence of budget has been collected.",
            "product_fit": "No grounded need analysis has been reviewed for this record."
        }
        record["coverage"] = "One supplied page; linked pages and JavaScript-rendered content are not inspected."
        if assessment:
            from backend.storage.assessment_views import decorate_record
            record = decorate_record(db, record, json.loads(assessment))
        return record

    def recent(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT c.id,c.product,c.geography,c.created_at,c.synthetic,b.canonical_name,b.source_url FROM campaign c JOIN business b ON b.campaign_id=c.id ORDER BY c.created_at DESC LIMIT 50")]

    def correct(self, contact_id, category, comment, expected_value):
        with self.connect() as db:
            row = db.execute("SELECT c.*,b.source_url,b.campaign_id FROM contact c JOIN business b ON b.id=c.business_id WHERE c.id=?", (contact_id,)).fetchone()
            if not row:
                raise ResearchError("Contact not found.", status=404)
            host = urlsplit(row["source_url"]).hostname
            db.execute("INSERT INTO feedback VALUES(?,?,?,?,?,?,0)", (uid(), contact_id, category, comment, expected_value, now()))
            db.execute("INSERT INTO suppression VALUES(?,?,?,?,?,?) ON CONFLICT(source_host,type,normalised_value) DO NOTHING",
                       (uid(), host, row["type"], row["normalised_value"], category, now()))
            # Same value on this source host stays suppressed across runs/campaigns.
            candidates = db.execute("SELECT c.id,b.source_url FROM contact c JOIN business b ON b.id=c.business_id WHERE c.type=? AND c.normalised_value=?",
                                    (row["type"], row["normalised_value"])).fetchall()
            db.executemany("UPDATE contact SET suppressed=1, attribution_state='disputed' WHERE id=?",
                           [(c["id"],) for c in candidates if urlsplit(c["source_url"]).hostname == host])
        return self.get(row["campaign_id"])
