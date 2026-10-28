from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


class Conflict(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        (root / "objects").mkdir(exist_ok=True)
        (root / "cases").mkdir(exist_ok=True)
        (root / "jobs").mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(root / "crucible.sqlite3", check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;
          CREATE TABLE IF NOT EXISTS folios(id TEXT PRIMARY KEY, doc TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, folio_id TEXT NOT NULL, run_id TEXT, type TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL, detail TEXT);
          CREATE INDEX IF NOT EXISTS events_folio ON events(folio_id,seq);
          CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, folio_id TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL, fence INTEGER NOT NULL, doc TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, folio_id TEXT NOT NULL, job_id TEXT, doc TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS artifacts(sha TEXT PRIMARY KEY, doc TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS contracts(sha TEXT PRIMARY KEY, folio_id TEXT NOT NULL, doc TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS idempotency(key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, folio_id TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS holdouts(split_sha TEXT PRIMARY KEY, signature TEXT NOT NULL, folio_id TEXT NOT NULL, registration TEXT NOT NULL);
        """)
        token_path = root / ".local-session"
        if not token_path.exists():
            fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(secrets.token_urlsafe(32))
        self.session_token = token_path.read_text().strip()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def _folio(self, id: str) -> dict:
        row = self.db.execute("SELECT doc FROM folios WHERE id=?", (id,)).fetchone()
        if not row:
            raise KeyError(id)
        return json.loads(row[0])

    def _save(self, doc: dict, advance: bool = True):
        if advance:
            doc["revision"] += 1
        doc["updated_at"] = now()
        self.db.execute("INSERT OR REPLACE INTO folios VALUES(?,?)", (doc["id"], canonical(doc).decode()))

    def _event(self, id: str, type: str, message: str, run_id: str | None = None, detail: Any = None):
        self.db.execute("INSERT INTO events(folio_id,run_id,type,message,created_at,detail) VALUES(?,?,?,?,?,?)", (id, run_id, type, message, now(), json.dumps(detail) if detail is not None else None))

    def create(self, doc: dict):
        with self.transaction():
            self.db.execute("INSERT INTO folios VALUES(?,?)", (doc["id"], canonical(doc).decode()))
            self._event(doc["id"], "created", "Authored claim created. No experiment has run.")

    def get(self, id: str) -> dict:
        with self.lock:
            doc = self._folio(id)
            doc["events"] = self.events(id)["events"]
            doc["receipts"] = [json.loads(r[0]) for r in self.db.execute("SELECT doc FROM receipts WHERE folio_id=? ORDER BY rowid", (id,))]
            doc["attempts"] = [{k: v for k, v in json.loads(r[0]).items() if k not in {"input", "pid", "fence", "folio_id"}} for r in self.db.execute("SELECT doc FROM jobs WHERE folio_id=? ORDER BY rowid", (id,))]
            return doc

    def list(self) -> list[dict]:
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute("SELECT doc FROM folios ORDER BY rowid DESC")]

    def events(self, id: str, after: int = 0) -> dict:
        with self.lock:
            rows = self.db.execute("SELECT seq,run_id,type,message,created_at FROM events WHERE folio_id=? AND seq>? ORDER BY seq LIMIT 500", (id, after)).fetchall()
        data = [dict(r) for r in rows]
        return {"events": data, "next": data[-1]["seq"] if data else after}

    def mutate(self, id: str, function: Callable[[dict], None], event: tuple[str, str] | None = None, advance: bool = True) -> dict:
        with self.transaction():
            doc = self._folio(id)
            function(doc)
            self._save(doc, advance)
            if event:
                self._event(id, *event)
        return self.get(id)

    def add_receipt(self, folio_id: str, job_id: str, receipt: dict):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO receipts VALUES(?,?,?,?)", (receipt["id"], folio_id, job_id, canonical(receipt).decode()))

    def artifact(self, content: bytes, name: str, kind: str = "evidence", media_type: str = "application/json") -> dict:
        sha = hashlib.sha256(content).hexdigest()
        path = self.root / "objects" / sha
        if not path.exists():
            temporary = path.with_name("." + sha + "." + secrets.token_hex(8) + ".tmp")
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
                with os.fdopen(fd, "wb") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    pass
            finally:
                temporary.unlink(missing_ok=True)
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise Conflict("artifact_tampered", "A content-addressed artifact failed its hash check.")
        meta = {"sha256": sha, "name": name, "kind": kind, "media_type": media_type, "bytes": len(content)}
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?)", (sha, canonical(meta).decode()))
        return meta

    def json_artifact(self, value: Any, name: str, kind: str = "evidence") -> dict:
        return self.artifact(canonical(value), name, kind)

    def get_artifact(self, sha: str) -> tuple[Path, dict]:
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise KeyError(sha)
        with self.lock:
            row = self.db.execute("SELECT doc FROM artifacts WHERE sha=?", (sha,)).fetchone()
        if not row:
            raise KeyError(sha)
        path = self.root / "objects" / sha
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise Conflict("artifact_tampered", "The stored bytes no longer match the immutable artifact digest.")
        return path, json.loads(row[0])

    def close(self):
        self.db.close()
