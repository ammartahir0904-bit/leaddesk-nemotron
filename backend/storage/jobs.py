"""Transactional workflow leases, controls, evidence and crash-safe results."""
import json
import random
import time

from backend.domain.errors import ResearchError
from backend.domain.jobs import CONNECTOR, DEMO_SOURCE, TERMINAL, JobInput
from backend.storage.briefs import BriefRepository
from backend.storage.repository import Repository, now, request_hash, uid

LEASE_SECONDS = 60
MAX_ATTEMPTS = 2


class JobRepository:
    def __init__(self, repository: Repository, *, clock=time.time):
        self.repository = repository
        self.clock = clock

    @staticmethod
    def event(db, job_id: str, kind: str, message: str):
        db.execute("INSERT INTO workflow_event(job_id,created_at,kind,message) VALUES(?,?,?,?)",
                   (job_id, now(), kind, message))

    def _get(self, db, job_id: str) -> dict:
        row = db.execute("SELECT * FROM workflow_job WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ResearchError("Workflow job not found.", status=404)
        job = dict(row)
        job["input"] = json.loads(job.pop("input_json"))
        job["product_brief"] = json.loads(job.pop("brief_json"))
        discovery = job.pop("discovery_json")
        job["discovery"] = json.loads(discovery) if discovery else None
        job["connector"] = CONNECTOR
        job["pause_requested"] = bool(job["pause_requested"])
        job["cancel_requested"] = bool(job["cancel_requested"])
        job["steps"] = []
        for step in db.execute("SELECT * FROM workflow_step WHERE job_id=? ORDER BY ordinal", (job_id,)):
            value = dict(step)
            candidate = value.pop("candidate_json")
            value["candidate"] = json.loads(candidate) if candidate else None
            job["steps"].append(value)
        events = db.execute("SELECT * FROM workflow_event WHERE job_id=? ORDER BY id DESC LIMIT 100", (job_id,)).fetchall()
        job["events"] = [dict(e) for e in reversed(events)]
        job["coverage_gaps"] = [CONNECTOR["coverage"], CONNECTOR["identity"],
                                CONNECTOR["parsing_limits"],
                                "Exclusions and geography are saved planning inputs; automatic eligibility checks are not implemented."]
        if job["discovery"] and job["discovery"]["counts"]["over_limit"]:
            job["coverage_gaps"].append("Candidate limit reached; additional external links were not retained.")
        remaining = sum(s["kind"] == "candidate" and s["state"] != "completed" for s in job["steps"])
        if remaining:
            job["coverage_gaps"].append(f"{remaining} candidate page(s) have no completed inspection.")
        return job

    def get(self, job_id: str) -> dict:
        with self.repository.connect() as db:
            return self._get(db, job_id)

    def recent(self) -> list[dict]:
        with self.repository.connect() as db:
            rows = db.execute("SELECT id,status,created_at,updated_at,page_attempts,stop_reason,input_json FROM workflow_job ORDER BY created_at DESC LIMIT 50").fetchall()
        return [{**{k: row[k] for k in ("id", "status", "created_at", "updated_at", "page_attempts", "stop_reason")},
                 "input": json.loads(row["input_json"])} for row in rows]

    def create(self, inputs: JobInput, key: str) -> dict:
        payload = inputs.model_dump()
        digest = request_hash(payload)
        with self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cached = db.execute("SELECT id,request_hash FROM workflow_job WHERE idempotency_key=?", (key,)).fetchone()
            if cached:
                if cached["request_hash"] != digest:
                    raise ResearchError("This job key was already used with different inputs.", status=409)
                return self._get(db, cached["id"])
            count = db.execute("SELECT COUNT(*) FROM workflow_job WHERE status NOT IN ('completed','partial','failed','cancelled')").fetchone()[0]
            if count >= 20:
                raise ResearchError("The queue has 20 unfinished jobs. Finish or cancel one before adding more.", status=429)
            brief = BriefRepository._get(db, inputs.brief_id)
            if brief["revision"] != inputs.brief_revision:
                raise ResearchError("This brief changed. Select its latest revision before queuing research.", status=409)
            job_id, stamp = uid(), now()
            status = "paused" if inputs.start_paused else "queued"
            db.execute("INSERT INTO workflow_job(id,idempotency_key,request_hash,input_json,brief_json,status,created_at,updated_at,pause_requested) VALUES(?,?,?,?,?,?,?,?,?)",
                       (job_id, key, digest, json.dumps(payload), json.dumps(brief), status, stamp, stamp, inputs.start_paused))
            source = DEMO_SOURCE if inputs.synthetic else inputs.source_url
            db.execute("INSERT INTO workflow_step(job_id,ordinal,kind,url,state) VALUES(?,0,'source',?,'pending')", (job_id, source))
            self.event(db, job_id, "created", f"Job saved {status}; page budget {inputs.page_budget} includes retries and the source page.")
            return self._get(db, job_id)

    def control(self, job_id: str, action: str, key: str) -> dict:
        digest = request_hash({"job_id": job_id, "action": action})
        with self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cached = db.execute("SELECT * FROM workflow_control WHERE idempotency_key=?", (key,)).fetchone()
            if cached:
                if cached["request_hash"] != digest:
                    raise ResearchError("This control key was already used for a different action.", status=409)
                return self._get(db, job_id)
            job = self._get(db, job_id)
            if job["status"] in TERMINAL:
                raise ResearchError("This job has finished. Create a new job for another run.", status=409)
            if action == "cancel":
                status = "running" if job["status"] == "running" else "cancelled"
                db.execute("UPDATE workflow_job SET cancel_requested=1,status=?,stop_reason=?,updated_at=? WHERE id=?",
                           (status, "Cancellation requested" if status == "running" else "Cancelled by you", now(), job_id))
            elif action == "pause":
                status = "running" if job["status"] == "running" else "paused"
                db.execute("UPDATE workflow_job SET pause_requested=1,status=?,updated_at=? WHERE id=?", (status, now(), job_id))
            else:
                if job["cancel_requested"]:
                    raise ResearchError("Cancellation is already requested; the current page may still finish.", status=409)
                status = job["status"] if job["status"] == "running" else ("retry_wait" if job["next_attempt_at"] > self.clock() else "queued")
                db.execute("UPDATE workflow_job SET pause_requested=0,status=?,updated_at=? WHERE id=?", (status, now(), job_id))
            db.execute("INSERT INTO workflow_control VALUES(?,?,?)", (key, digest, job_id))
            self.event(db, job_id, action, f"{action.capitalize()} requested. An in-flight page may finish; budgets are retained.")
            return self._get(db, job_id)

    def _settle(self, db, job_id: str):
        """Choose the next durable state after a step or recovered lease."""
        job = self._get(db, job_id)
        steps = job["steps"]
        pending = [s for s in steps if s["state"] == "pending"]
        source = steps[0]
        state, reason = "queued", None
        if job["cancel_requested"]:
            state, reason = "cancelled", "Cancelled by you; completed evidence is retained"
        elif source["state"] == "failed":
            state, reason = "failed", "Source page failed; no directory contacts were copied"
        elif not pending:
            limited = bool(job["discovery"] and job["discovery"]["counts"]["over_limit"])
            failed = any(s["state"] == "failed" for s in steps)
            empty = source["state"] == "completed" and len(steps) == 1
            state = "partial" if limited or failed or empty else "completed"
            if empty:
                reason = "Source exhausted; no visible external website links"
            elif limited:
                reason = "Candidate limit reached"
            elif failed:
                reason = "Some candidate pages failed"
            else:
                reason = "All retained candidate pages inspected; wider source coverage remains unknown"
        elif job["page_attempts"] >= job["input"]["page_budget"]:
            state, reason = "partial", "Page attempt budget exhausted; remaining candidates were not inspected"
        elif job["active_seconds"] >= job["input"]["time_budget_seconds"]:
            state, reason = "partial", "Active time budget exhausted; remaining candidates were not inspected"
        elif job["pause_requested"]:
            state, reason = "paused", "Paused between pages"
        elif job["next_attempt_at"] > self.clock():
            state = "retry_wait"
        db.execute("UPDATE workflow_job SET status=?,stop_reason=?,lease_owner=NULL,lease_until=NULL,step_started_at=NULL,updated_at=? WHERE id=?",
                   (state, reason, now(), job_id))
        if state in TERMINAL:
            self.event(db, job_id, state, reason)

    def _recover(self, db):
        expired = db.execute("SELECT * FROM workflow_job WHERE status='running' AND lease_until<=?", (self.clock(),)).fetchall()
        for job in expired:
            # Lost work consumes its reserved attempt and at most one lease's
            # active-time allowance. Offline wall time is not charged indefinitely.
            charge = min(LEASE_SECONDS, max(0, self.clock() - job["step_started_at"]))
            db.execute("UPDATE workflow_job SET active_seconds=active_seconds+? WHERE id=?", (charge, job["id"]))
            step = db.execute("SELECT * FROM workflow_step WHERE job_id=? AND state='running'", (job["id"],)).fetchone()
            if step:
                state = "failed" if step["attempts"] >= MAX_ATTEMPTS else "pending"
                db.execute("UPDATE workflow_step SET state=?,error=? WHERE job_id=? AND ordinal=?",
                           (state, "Previous worker lease expired; fetch outcome was not committed", job["id"], step["ordinal"]))
            self.event(db, job["id"], "recovered", "Expired worker lease recovered; unfinished work may be retried within the original budgets.")
            self._settle(db, job["id"])

    def claim(self, owner: str) -> dict | None:
        with self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._recover(db)
            if db.execute("SELECT 1 FROM workflow_job WHERE status='running' AND lease_until>?", (self.clock(),)).fetchone():
                return None
            rows = db.execute("SELECT id FROM workflow_job WHERE status IN ('queued','retry_wait') AND next_attempt_at<=? ORDER BY created_at", (self.clock(),)).fetchall()
            for row in rows:
                self._settle(db, row["id"])
                job = self._get(db, row["id"])
                if job["status"] != "queued":
                    continue
                step = next(s for s in job["steps"] if s["state"] == "pending")
                db.execute("UPDATE workflow_job SET status='running',page_attempts=page_attempts+1,lease_owner=?,lease_until=?,heartbeat_at=?,step_started_at=?,updated_at=? WHERE id=?",
                           (owner, self.clock() + LEASE_SECONDS, self.clock(), self.clock(), now(), job["id"]))
                db.execute("UPDATE workflow_step SET state='running',attempts=attempts+1 WHERE job_id=? AND ordinal=?", (job["id"], step["ordinal"]))
                self.event(db, job["id"], "running", f"Inspecting {step['kind']} page; attempt {step['attempts'] + 1} of {MAX_ATTEMPTS}.")
                claimed = self._get(db, job["id"])
                claimed["active_step"] = next(s for s in claimed["steps"] if s["ordinal"] == step["ordinal"])
                return claimed
            return None

    def _owned(self, db, job_id: str, owner: str) -> dict | None:
        job = self._get(db, job_id)
        if job["status"] != "running" or job["lease_owner"] != owner or job["lease_until"] <= self.clock():
            return None
        return job

    def heartbeat(self, job_id: str, owner: str) -> bool:
        with self.repository.connect() as db:
            changed = db.execute("UPDATE workflow_job SET heartbeat_at=?,lease_until=? WHERE id=? AND status='running' AND lease_owner=? AND lease_until>?",
                                 (self.clock(), self.clock() + LEASE_SECONDS, job_id, owner, self.clock())).rowcount
            return bool(changed)

    def complete(self, job_id: str, owner: str, elapsed: float, *, discovery=None, page=None, extracted=None) -> bool:
        with self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = self._owned(db, job_id, owner)
            if job is None:
                return False
            step = next(s for s in job["steps"] if s["state"] == "running")
            research_id = None
            if step["kind"] == "source":
                discovery = discovery | {"retrieved_at": now()}
                db.execute("UPDATE workflow_job SET discovery_json=? WHERE id=?", (json.dumps(discovery | {"candidates": []}), job_id))
                for index, candidate in enumerate(discovery["candidates"], 1):
                    candidate = candidate | {"retrieved_at": discovery["retrieved_at"]}
                    db.execute("INSERT INTO workflow_step(job_id,ordinal,kind,url,state,candidate_json) VALUES(?,?,'candidate',?,'pending',?)",
                               (job_id, index, candidate["url"], json.dumps(candidate)))
                message = f"Discovered {len(discovery['candidates'])} candidate websites. Directory contacts were not copied."
            else:
                inputs = job["product_brief"]["document"]["input"]
                payload = {"url": step["url"], "product": inputs["offer"], "location": inputs["target_geography"], "synthetic": job["input"]["synthetic"]}
                research_id = self.repository.save_in_transaction(db, payload, f"workflow:{job_id}:{step['ordinal']}", page,
                    extracted, job["input"]["synthetic"], brief_snapshot=job["product_brief"])
                message = "Candidate page saved with its own contact evidence and unresolved identity."
            db.execute("UPDATE workflow_step SET state='completed',research_id=?,error=NULL WHERE job_id=? AND ordinal=?", (research_id, job_id, step["ordinal"]))
            db.execute("UPDATE workflow_job SET active_seconds=active_seconds+?,next_attempt_at=0 WHERE id=?", (max(0, elapsed), job_id))
            self.event(db, job_id, "page_completed", message)
            self._settle(db, job_id)
            return True

    def fail(self, job_id: str, owner: str, error: ResearchError, elapsed: float) -> bool:
        with self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = self._owned(db, job_id, owner)
            if job is None:
                return False
            step = next(s for s in job["steps"] if s["state"] == "running")
            retry = error.retryable and step["attempts"] < MAX_ATTEMPTS
            delay = max(2 ** step["attempts"] + random.uniform(0, .5), error.retry_after or 0) if retry else 0
            db.execute("UPDATE workflow_step SET state=?,error=? WHERE job_id=? AND ordinal=?",
                       ("pending" if retry else "failed", str(error)[:500], job_id, step["ordinal"]))
            db.execute("UPDATE workflow_job SET active_seconds=active_seconds+?,next_attempt_at=? WHERE id=?",
                       (max(0, elapsed), self.clock() + delay if retry else 0, job_id))
            self.event(db, job_id, "retry" if retry else "page_failed", str(error)[:500])
            self._settle(db, job_id)
            return True
