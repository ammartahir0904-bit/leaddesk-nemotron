"""Bounded UTF-8 reader. Directory descriptors and O_NOFOLLOW prevent link traversal.

No document execution, OS opener, network request or model is involved.
"""
import hashlib
import os
import stat
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

from backend.domain.errors import ResearchError

MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 500
MAX_SECONDS = 5
TEXT_SUFFIXES = {".txt", ".md", ".rst", ".csv", ".tsv", ".json", ".log", ".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".xml", ".yaml", ".yml", ".toml"}
SKIP_NAMES = {"node_modules", "venv", "__pycache__", "dist", "build", "access-token", "credentials", "secrets", "id_rsa", "id_ed25519"}
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def allowed_name(name):
    return not name.startswith(".") and name.casefold() not in SKIP_NAMES and Path(name).stem.casefold() not in {"credentials", "secrets", "access-token", "id_rsa", "id_ed25519"}


@contextmanager
def directory(path):
    """Open every absolute component without following symlinks, including root."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ResearchError("Use an absolute folder path without '..'.", status=403)
    fd = os.open("/", DIR_FLAGS)
    try:
        for part in path.parts[1:]:
            new_fd = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = new_fd
        yield fd
    finally:
        os.close(fd)


@contextmanager
def approved_directory(root):
    # Only failures opening the folder itself are folder errors; errors raised by
    # the caller's body (e.g. a deleted file) must propagate unchanged.
    with ExitStack() as stack:
        try:
            fd = stack.enter_context(directory(root["path"]))
            info = os.fstat(fd)
        except OSError:
            raise ResearchError("The approved folder is unavailable or contains a symlink. Restore it or revoke approval.", status=409) from None
        if (info.st_dev, info.st_ino) != (root["device"], root["inode"]):
            raise ResearchError("This folder was replaced. Revoke it and approve its current location again.", status=409)
        yield fd


def metadata(info):
    return {"device": info.st_dev, "inode": info.st_ino, "size": info.st_size,
            "modified_ns": info.st_mtime_ns, "changed_ns": info.st_ctime_ns}


def read_entry(parent_fd, name, remaining=MAX_FILE_BYTES):
    fd = os.open(name, FILE_FLAGS, dir_fd=parent_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("Not a regular file")
        record = metadata(info) | {"status": "unsupported", "sha256": None, "text": ""}
        if Path(name).suffix.casefold() not in TEXT_SUFFIXES:
            return record, 0
        if info.st_size > MAX_FILE_BYTES:
            return record | {"status": "too_large"}, 0
        if info.st_size > remaining:
            return record | {"status": "byte_budget"}, 0
        with os.fdopen(fd, "rb", closefd=False) as stream:
            body = stream.read(min(MAX_FILE_BYTES, remaining) + 1)
        after = os.fstat(fd)
        if metadata(info) != metadata(after) or len(body) != info.st_size:
            raise OSError("File changed during reading")
        try:
            text = body.decode("utf-8-sig")
            if "\0" in text:
                raise UnicodeError()
        except UnicodeError:
            return record | {"status": "not_utf8"}, len(body)
        return record | {"status": "indexed", "sha256": hashlib.sha256(body).hexdigest(), "text": text}, len(body)
    finally:
        os.close(fd)


def scan(root, excluded_paths):
    started = time.monotonic()
    entries, records, used, skipped, errors = 0, [], 0, 0, 0
    limited = False

    def walk(fd, relative, depth=0):
        nonlocal entries, used, skipped, errors, limited
        # scandir is streamed: a large directory cannot allocate an unbounded list.
        with os.scandir(fd) as iterator:
            for entry in iterator:
                if entries >= MAX_ENTRIES or time.monotonic() - started >= MAX_SECONDS:
                    limited = True
                    return
                entries += 1
                path = relative / entry.name
                full_path = Path(root["path"]) / path
                if not allowed_name(entry.name) or any(full_path == p or p in full_path.parents for p in excluded_paths):
                    skipped += 1
                    continue
                info = None
                try:
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        if depth >= 12:
                            limited = True
                            skipped += 1
                            continue
                        child = os.open(entry.name, DIR_FLAGS, dir_fd=fd)
                        try:
                            walk(child, path, depth + 1)
                        finally:
                            os.close(child)
                    elif stat.S_ISREG(info.st_mode):
                        record, consumed = read_entry(fd, entry.name, MAX_TOTAL_BYTES - used)
                        used += consumed
                        if record["status"] == "byte_budget":
                            limited = True
                        records.append(record | {"relative_path": str(path), "name": entry.name})
                    else:
                        skipped += 1
                except OSError:
                    errors += 1
                    if info is not None and stat.S_ISREG(info.st_mode):
                        records.append(metadata(info) | {"relative_path": str(path), "name": entry.name,
                                                        "status": "unreadable", "text": "", "sha256": None})
                if limited and (entries >= MAX_ENTRIES or time.monotonic() - started >= MAX_SECONDS):
                    return

    with approved_directory(root) as fd:
        walk(fd, Path())
    return records, {"entries_seen": entries, "records": len(records), "bytes_read": used, "skipped": skipped,
                     "errors": errors, "partial": limited or errors > 0, "seconds": round(time.monotonic() - started, 4),
                     "limits": {"entries": MAX_ENTRIES, "file_bytes": MAX_FILE_BYTES, "total_bytes": MAX_TOTAL_BYTES, "seconds": MAX_SECONDS}}


def current_file(root, record):
    """Never return stored content for a missing, changed, linked or replaced file."""
    parts = Path(record["relative_path"]).parts
    if not parts or any(not allowed_name(part) or part in {"..", "/"} for part in parts):
        raise ResearchError("This file is outside the allowed scope.", status=403)
    try:
        with approved_directory(root) as root_fd:
            fd = os.dup(root_fd)
            try:
                for part in parts[:-1]:
                    new_fd = os.open(part, DIR_FLAGS, dir_fd=fd)
                    os.close(fd)
                    fd = new_fd
                current, _ = read_entry(fd, parts[-1])
            finally:
                os.close(fd)
        # Revalidate the pathname after reading in case the root was replaced.
        with approved_directory(root):
            pass
        if any(current[key] != record[key] for key in ("device", "inode", "size", "modified_ns", "changed_ns", "sha256", "status")):
            raise ResearchError("This file changed. Reconcile the folder before using it.", status=409)
        return current
    except OSError:
        raise ResearchError("This file moved, was deleted, or is unavailable. Reconcile the folder.", status=409) from None
