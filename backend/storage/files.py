"""Transactional file snapshots with scope-local correction rules."""
import json
import os
import re
import threading
from collections import Counter
from pathlib import Path

from backend.adapters.local_files import approved_directory, current_file, directory, scan
from backend.domain.errors import ResearchError
from backend.storage.repository import now, uid


class FileRepository:
    def __init__(self, repository, data_dir):
        self.repository = repository
        self.data_dir = Path(data_dir).resolve()
        # Approval, rescan, revocation and reads share a slot; no late scan can
        # repopulate a revoked index. This installation is one server process.
        self.lock = threading.RLock()

    def _root(self, db, root_id):
        row = db.execute("SELECT * FROM approved_folder WHERE id=?", (root_id,)).fetchone()
        if row is None:
            raise ResearchError("Approved folder not found.", status=404)
        return dict(row)

    def roots(self):
        with self.lock, self.repository.connect() as db:
            items = []
            for row in db.execute("SELECT * FROM approved_folder ORDER BY created_at,id"):
                item = dict(row)
                report = item.pop("report_json")
                item["report"] = json.loads(report) if report else None
                item["statuses"] = {r[0]: r[1] for r in db.execute("SELECT status,COUNT(*) FROM local_file WHERE root_id=? GROUP BY status", (row["id"],))}
                items.append(item)
            return {"items": items, "limit": 10}

    def approve(self, path):
        candidate = Path(path)
        # Dedicated user project folders only. Broad filesystem/home/temp roots
        # and sensitive hidden components cannot become accidental catch-alls.
        homes = (Path.home(), Path("/tmp"))
        if (not candidate.is_absolute() or ".." in candidate.parts or any(p.startswith(".") for p in candidate.parts)
                or not any(base in candidate.parents for base in homes)
                or candidate == self.data_dir or self.data_dir in candidate.parents):
            raise ResearchError("Choose a dedicated non-hidden folder inside your home or /tmp, outside LeadDesk's data folder.", status=403)
        try:
            with directory(candidate) as fd:
                info = os.fstat(fd)
        except (OSError, ValueError):
            raise ResearchError("Folder is unavailable, unreadable, or includes a symlink.", status=403) from None
        path = str(candidate)
        with self.lock, self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM approved_folder WHERE path=?", (path,)).fetchone()
            if existing:
                if (existing["device"], existing["inode"]) != (info.st_dev, info.st_ino):
                    raise ResearchError("Folder identity changed. Revoke the old approval first.", status=409)
                return dict(existing)
            roots = list(db.execute("SELECT path FROM approved_folder"))
            if len(roots) >= 10:
                raise ResearchError("At most ten approved folders are allowed. Revoke one first.", status=429)
            if any(Path(r[0]) in candidate.parents or candidate in Path(r[0]).parents for r in roots):
                raise ResearchError("Approved folders cannot overlap. Choose one scope for this tree.", status=409)
            root_id = uid()
            db.execute("INSERT INTO approved_folder(id,path,device,inode,created_at) VALUES(?,?,?,?,?)",
                       (root_id, path, info.st_dev, info.st_ino, now()))
            return self._root(db, root_id)

    def revoke(self, root_id):
        with self.lock, self.repository.connect() as db:
            db.execute("DELETE FROM approved_folder WHERE id=?", (root_id,))
        return {"deleted": True}

    def reconcile(self, root_id):
        if not self.lock.acquire(blocking=False):
            raise ResearchError("File scope is busy. Retry shortly.", status=429, retryable=True)
        try:
            with self.repository.connect() as db:
                root = self._root(db, root_id)
            records, report = scan(root, [self.data_dir])
            with approved_directory(root):
                pass
            with self.repository.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self._root(db, root_id)
                old = [dict(row) for row in db.execute("SELECT * FROM local_file WHERE root_id=?", (root_id,))]
                by_path = {row["relative_path"]: row for row in old}
                identity = lambda row: (row["device"], row["inode"], row["sha256"])
                old_counts, new_counts = Counter(map(identity, old)), Counter(map(identity, records))
                by_identity = {identity(row): row for row in old}
                assigned = set()
                for record in records:
                    previous = by_path.get(record["relative_path"])
                    if previous and identity(previous) != identity(record):
                        previous = None
                    if not previous and old_counts[identity(record)] == new_counts[identity(record)] == 1:
                        previous = by_identity.get(identity(record))
                    record["id"] = previous["id"] if previous else uid()
                    assigned.add(record["id"])
                # Remove vanished/replaced records before path updates, including
                # stale entries outside a bounded partial scan. Never imply coverage.
                for row in old:
                    if row["id"] not in assigned:
                        db.execute("DELETE FROM local_file WHERE id=?", (row["id"],))
                # Temporary names allow two existing files to swap locations.
                for record in records:
                    db.execute("UPDATE local_file SET relative_path=? WHERE id=?", (".reconcile/" + record["id"], record["id"]))
                for record in records:
                    values = (record["id"], root_id, record["relative_path"], record["name"], record["device"], record["inode"],
                              record["size"], record["modified_ns"], record["changed_ns"], record["sha256"], record["status"], record["text"])
                    db.execute("""INSERT INTO local_file VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                        relative_path=excluded.relative_path,name=excluded.name,device=excluded.device,inode=excluded.inode,
                        size=excluded.size,modified_ns=excluded.modified_ns,changed_ns=excluded.changed_ns,
                        sha256=excluded.sha256,status=excluded.status,text=excluded.text""", values)
                db.execute("UPDATE approved_folder SET scanned_at=?,report_json=? WHERE id=?", (now(), json.dumps(report), root_id))
            return report
        finally:
            self.lock.release()

    @staticmethod
    def _public(root, record, query=""):
        text = record["text"]
        words = re.findall(r"\w+", query, flags=re.UNICODE)
        position = min((text.casefold().find(word) for word in words if word in text.casefold()), default=0)
        start = max(0, position - 70)
        return {key: record[key] for key in ("id", "root_id", "relative_path", "name", "size", "modified_ns", "sha256", "status")} | {
            "path": str(Path(root["path"]) / record["relative_path"]),
            "folder": str((Path(root["path"]) / record["relative_path"]).parent), "excerpt": text[start:start + 360]}

    def search(self, payload):
        words = re.findall(r"\w+", payload.query, flags=re.UNICODE)
        if not words:
            raise ResearchError("Enter at least one word or number to search.")
        if len(words) > 20:
            raise ResearchError("Use at most twenty search words.")
        expression = " AND ".join('"' + word + '"' for word in words)
        with self.lock, self.repository.connect() as db:
            root = self._root(db, payload.root_id)
            with approved_directory(root):
                pass
            choices = [dict(row) for row in db.execute("SELECT c.*,f.name,f.relative_path FROM file_correction c JOIN local_file f ON f.id=c.file_id WHERE c.root_id=? AND c.query=? AND c.sha256=f.sha256 ORDER BY c.updated_at,c.id", (root["id"], payload.query))]
            decisions = {row["file_id"]: row["decision"] for row in choices}
            rows = [dict(row) for row in db.execute("""SELECT f.* FROM local_file_fts JOIN local_file f ON f.id=local_file_fts.file_id
                WHERE local_file_fts MATCH ? AND f.root_id=? ORDER BY bm25(local_file_fts,0,5,1),f.relative_path LIMIT 500""", (expression, root["id"]))]
            # A correct-file association may point to a file without these words.
            preferred_ids = [key for key, value in decisions.items() if value == "preferred"]
            for file_id in preferred_ids:
                if not any(row["id"] == file_id for row in rows):
                    row = db.execute("SELECT * FROM local_file WHERE id=? AND root_id=?", (file_id, root["id"])).fetchone()
                    if row:
                        rows.append(dict(row))
            rows.sort(key=lambda row: decisions.get(row["id"]) != "preferred")
            items, stale = [], 0
            for record in rows:
                if decisions.get(record["id"]) == "wrong":
                    continue
                try:
                    current_file(root, record)
                except ResearchError:
                    stale += 1
                    continue
                items.append(self._public(root, record, payload.query) | {"preferred": decisions.get(record["id"]) == "preferred"})
                if len(items) == 3:
                    break
            return {"items": items, "corrections": choices, "stale_omitted": stale, "query": payload.query,
                    "root_id": root["id"], "scanned_at": root["scanned_at"], "report": json.loads(root["report_json"]) if root["report_json"] else None,
                    "coverage": "Up to three keyword matches in this folder's last bounded snapshot. Reconcile to discover new or moved files."}

    def preview(self, file_id):
        with self.lock, self.repository.connect() as db:
            record = db.execute("SELECT * FROM local_file WHERE id=?", (file_id,)).fetchone()
            if record is None:
                raise ResearchError("Indexed file not found.", status=404)
            record = dict(record)
            root = self._root(db, record["root_id"])
            current = current_file(root, record)
            if current["status"] != "indexed":
                raise ResearchError("Preview supports bounded UTF-8 text files only. This file's status is " + current["status"] + ".")
            return self._public(root, record) | {"text": current["text"][:16000], "truncated": len(current["text"]) > 16000}

    def correct(self, payload):
        with self.lock, self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            root = self._root(db, payload.root_id)
            record = db.execute("SELECT * FROM local_file WHERE id=? AND root_id=?", (payload.file_id, root["id"])).fetchone()
            if record is None:
                raise ResearchError("Choose an indexed file from this approved folder.", status=404)
            record = dict(record)
            current_file(root, record)
            if record["status"] != "indexed" or record["sha256"] != payload.sha256:
                raise ResearchError("The selected file changed or cannot be previewed. Reconcile and choose again.", status=409)
            # One preferred file per query. Wrong-file choices remain explicit
            # until undone, the content changes or approval is revoked.
            if payload.decision == "preferred":
                db.execute("DELETE FROM file_correction WHERE root_id=? AND query=? AND decision='preferred'", (root["id"], payload.query))
            db.execute("""INSERT INTO file_correction VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(root_id,query,file_id)
                DO UPDATE SET sha256=excluded.sha256,decision=excluded.decision,comment=excluded.comment,updated_at=excluded.updated_at""",
                       (uid(), root["id"], payload.query, payload.file_id, payload.sha256, payload.decision, payload.comment, now()))
        return {"saved": True}

    def undo(self, correction_id):
        with self.lock, self.repository.connect() as db:
            db.execute("DELETE FROM file_correction WHERE id=?", (correction_id,))
        return {"deleted": True}
