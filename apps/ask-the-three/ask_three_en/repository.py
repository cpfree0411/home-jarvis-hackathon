"""SQLite story store. One file, WAL, owned by this app only."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .domain import PANEL, public_panel

SCHEMA_VERSION = 1


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StoryRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.migrate()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @contextmanager
    def conn(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def migrate(self):
        with self.conn() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError("database schema is newer than this application")
            if version == 0:
                db.executescript("""
                CREATE TABLE stories (
                  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                  deleted_at TEXT, status TEXT NOT NULL, source TEXT NOT NULL,
                  sample_id TEXT, raw_transcript TEXT, organizer_output TEXT,
                  organizer TEXT, approved_input TEXT, title TEXT, error TEXT
                );
                CREATE TABLE panel_runs (
                  story_id TEXT NOT NULL REFERENCES stories(id), member TEXT NOT NULL,
                  status TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
                  live INTEGER NOT NULL, reversed_order INTEGER NOT NULL,
                  choice TEXT, strength TEXT, reasoning TEXT, other_side_credit TEXT,
                  suggestion TEXT, error TEXT, started_at TEXT, completed_at TEXT,
                  PRIMARY KEY(story_id, member)
                );
                CREATE INDEX stories_archive ON stories(deleted_at, created_at DESC);
                PRAGMA user_version=1;
                """)

    def create(self, source: str = "voice", sample_id: str | None = None) -> str:
        sid = str(uuid.uuid4())
        with self.conn() as db:
            db.execute("INSERT INTO stories(id,created_at,updated_at,status,source,sample_id) VALUES(?,?,?,?,?,?)",
                       (sid, now(), now(), "DRAFT", source, sample_id))
        return sid

    def row(self, sid: str) -> dict:
        with self.conn() as db:
            row = db.execute("SELECT * FROM stories WHERE id=? AND deleted_at IS NULL", (sid,)).fetchone()
        if not row:
            raise KeyError(sid)
        return dict(row)

    def _changed(self, db, what: str):
        if not db.execute("SELECT changes()").fetchone()[0]:
            raise ValueError(what)

    def set_transcript(self, sid: str, text: str):
        with self.conn() as db:
            db.execute("UPDATE stories SET raw_transcript=?,status='ORGANIZING',updated_at=? "
                       "WHERE id=? AND status='DRAFT' AND deleted_at IS NULL", (text, now(), sid))
            self._changed(db, "transcript state")

    def set_organized(self, sid: str, value: dict, organizer: str):
        with self.conn() as db:
            db.execute("UPDATE stories SET organizer_output=?,organizer=?,title=?,status='REVIEW',updated_at=? "
                       "WHERE id=? AND status='ORGANIZING'",
                       (json.dumps(value, ensure_ascii=False), organizer, value["title"], now(), sid))
            self._changed(db, "organizer state")

    def approve(self, sid: str, approved: dict, seats: dict[str, dict], order: dict[str, bool]):
        """seats: member -> {provider, model, live}. Stored per row so the archive never relabels."""
        with self.conn() as db:
            db.execute("UPDATE stories SET approved_input=?,status='WAITING',updated_at=? "
                       "WHERE id=? AND status='REVIEW' AND deleted_at IS NULL",
                       (json.dumps(approved, ensure_ascii=False), now(), sid))
            self._changed(db, "approve state")
            for member in PANEL:
                seat = seats[member]
                db.execute("INSERT INTO panel_runs(story_id,member,status,provider,model,live,reversed_order) "
                           "VALUES(?,?,?,?,?,?,?)",
                           (sid, member, "PENDING", seat["provider"], seat["model"], int(seat["live"]),
                            int(order[member])))

    def panel_status(self, sid: str, member: str, status: str, result: dict | None = None, error: str | None = None):
        with self.conn() as db:
            if status == "RUNNING":
                db.execute("UPDATE panel_runs SET status=?,started_at=? WHERE story_id=? AND member=? AND status='PENDING'",
                           (status, now(), sid, member))
            else:
                result = result or {}
                db.execute("""UPDATE panel_runs SET status=?,choice=?,strength=?,reasoning=?,other_side_credit=?,
                       suggestion=?,error=?,completed_at=? WHERE story_id=? AND member=? AND status='RUNNING'""",
                           (status, result.get("choice"), result.get("strength"), result.get("reasoning"),
                            result.get("other_side_credit"), result.get("suggestion"), error, now(), sid, member))
            self._changed(db, "panel state")
            terminal = db.execute("SELECT COUNT(*) FROM panel_runs WHERE story_id=? AND status IN ('COMPLETED','FAILED')",
                                  (sid,)).fetchone()[0]
            if terminal == len(PANEL):
                db.execute("UPDATE stories SET status='REVEALED',updated_at=? WHERE id=?", (now(), sid))

    def panel(self, sid: str) -> dict:
        with self.conn() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM panel_runs WHERE story_id=?", (sid,))]
        return public_panel(rows)

    def archive(self) -> list[dict]:
        with self.conn() as db:
            rows = [dict(r) for r in db.execute(
                "SELECT id,title,created_at,status,source FROM stories WHERE deleted_at IS NULL "
                "AND status='REVEALED' ORDER BY created_at DESC,id DESC LIMIT 200")]
        for row in rows:
            panel = self.panel(row["id"])
            row["aggregate"] = panel["aggregate"]
            row["members"] = panel["order"]
            row["live"] = {m: panel["members"][m]["live"] for m in panel["order"]}
        return rows

    def soft_delete(self, sid: str):
        with self.conn() as db:
            db.execute("UPDATE stories SET deleted_at=?,updated_at=? WHERE id=? AND status='REVEALED' AND deleted_at IS NULL",
                       (now(), now(), sid))
            if not db.execute("SELECT changes()").fetchone()[0]:
                raise KeyError(sid)

    def fail_story(self, sid: str, error: str):
        with self.conn() as db:
            db.execute("UPDATE stories SET status='FAILED',error=?,updated_at=? WHERE id=? AND status='ORGANIZING'",
                       (error[:60], now(), sid))

    def live_runs_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        with self.conn() as db:
            return db.execute("SELECT COUNT(DISTINCT story_id) FROM panel_runs WHERE live=1 AND started_at>=?",
                              (today,)).fetchone()[0]

    def inflight(self) -> int:
        with self.conn() as db:
            return db.execute("SELECT COUNT(*) FROM stories WHERE status IN ('ORGANIZING','WAITING') "
                              "AND deleted_at IS NULL").fetchone()[0]

    def recover_inflight(self):
        """A process restart must make an interrupted panel terminal and visible."""
        with self.conn() as db:
            db.execute("UPDATE panel_runs SET status='FAILED',error='service_restarted',completed_at=? "
                       "WHERE status IN ('PENDING','RUNNING')", (now(),))
            db.execute("UPDATE stories SET status='REVEALED',updated_at=? WHERE status='WAITING'", (now(),))
            db.execute("UPDATE stories SET status='FAILED',error='service_restarted',updated_at=? "
                       "WHERE status='ORGANIZING'", (now(),))
