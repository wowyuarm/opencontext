"""
SQLite database for OpenContext.

Single-file implementation: schema, CRUD, search.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import AgentInfo, Event, Job, Session, Turn

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now')),
    description TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    session_type TEXT NOT NULL,
    workspace TEXT,
    started_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    title TEXT,
    summary TEXT,
    summary_updated_at TEXT,
    total_turns INTEGER DEFAULT 0,
    agent_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_number INTEGER NOT NULL,
    user_message TEXT,
    assistant_summary TEXT,
    title TEXT NOT NULL,
    description TEXT,
    model_name TEXT,
    content_hash TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    is_continuation INTEGER DEFAULT 0,
    satisfaction TEXT DEFAULT 'fine',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(session_id, turn_number)
);

CREATE TABLE IF NOT EXISTS turn_content (
    turn_id TEXT PRIMARY KEY REFERENCES turns(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    content_size INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    start_timestamp TEXT,
    end_timestamp TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS event_sessions (
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    added_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (event_id, session_id)
);

CREATE TABLE IF NOT EXISTS agent_info (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    title TEXT DEFAULT '',
    description TEXT DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'visible',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    payload TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER DEFAULT 0,
    attempts INTEGER DEFAULT 0,
    next_run_at TEXT DEFAULT (datetime('now')),
    locked_until TEXT,
    locked_by TEXT,
    last_error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- FTS for events
CREATE VIRTUAL TABLE IF NOT EXISTS fts_events USING fts5(
    title, description, content='events', content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO fts_events(rowid, title, description)
    VALUES (new.rowid, new.title, new.description);
END;
CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
    INSERT INTO fts_events(fts_events, rowid, title, description)
    VALUES ('delete', old.rowid, old.title, old.description);
END;
CREATE TRIGGER IF NOT EXISTS events_au AFTER UPDATE ON events BEGIN
    INSERT INTO fts_events(fts_events, rowid, title, description)
    VALUES ('delete', old.rowid, old.title, old.description);
    INSERT INTO fts_events(rowid, title, description)
    VALUES (new.rowid, new.title, new.description);
END;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(workspace);
CREATE INDEX IF NOT EXISTS idx_sessions_activity ON sessions(last_activity_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_agent_id ON sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_timestamp ON turns(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_turns_hash ON turns(content_hash);
CREATE INDEX IF NOT EXISTS idx_event_sessions_event ON event_sessions(event_id);
CREATE INDEX IF NOT EXISTS idx_event_sessions_session ON event_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, next_run_at);
"""


def _utcnow() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _regexp(pattern: str, value: str) -> bool:
    if value is None:
        return False
    try:
        return re.search(pattern, value) is not None
    except re.error:
        return False


# ── Database ──────────────────────────────────────────────────────────────────


class Database:
    """Thread-safe SQLite database for OpenContext."""

    def __init__(self, db_path: Path, *, read_only: bool = False):
        self.db_path = Path(db_path).expanduser()
        self.read_only = read_only
        self._local = threading.local()

        if not read_only:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn

        if self.read_only:
            uri = f"file:{self.db_path}?mode=ro"
            try:
                conn = sqlite3.connect(
                    uri, uri=True, timeout=5.0, check_same_thread=False
                )
            except sqlite3.OperationalError:
                # WAL fallback
                conn = sqlite3.connect(
                    str(self.db_path), timeout=5.0, check_same_thread=False
                )
                conn.execute("PRAGMA query_only=ON;")
        else:
            conn = sqlite3.connect(self.db_path, timeout=5.0, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("PRAGMA busy_timeout=5000;")

        conn.row_factory = sqlite3.Row
        conn.create_function("REGEXP", 2, _regexp)
        self._local.conn = conn
        return conn

    def initialize(self) -> None:
        """Create tables if this is a fresh database."""
        if self.read_only:
            return
        conn = self._conn()
        conn.executescript(SCHEMA_SQL)
        # Record schema version
        try:
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
                (SCHEMA_VERSION, "OpenContext initial schema"),
            )
            conn.commit()
        except Exception:
            pass

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None

    # ── Sessions ──────────────────────────────────────────────────────────

    def upsert_session(self, s: Session) -> None:
        conn = self._conn()
        now = _utcnow()
        conn.execute(
            """INSERT INTO sessions
               (id, file_path, session_type, workspace, started_at, last_activity_at,
                title, summary, summary_updated_at, total_turns, agent_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 last_activity_at=excluded.last_activity_at,
                 title=COALESCE(excluded.title, title),
                 summary=COALESCE(excluded.summary, summary),
                 summary_updated_at=COALESCE(excluded.summary_updated_at, summary_updated_at),
                 total_turns=excluded.total_turns,
                 agent_id=COALESCE(excluded.agent_id, agent_id),
                 updated_at=?""",
            (
                s.id,
                s.file_path,
                s.session_type,
                s.workspace,
                s.started_at,
                s.last_activity_at,
                s.title,
                s.summary,
                s.summary_updated_at,
                s.total_turns,
                s.agent_id,
                s.created_at or now,
                now,
                now,
            ),
        )
        conn.commit()

    def update_session_summary(self, session_id: str, title: str, summary: str) -> None:
        conn = self._conn()
        now = _utcnow()
        conn.execute(
            """UPDATE sessions SET title=?, summary=?, summary_updated_at=?, updated_at=?
               WHERE id=?""",
            (title, summary, now, now, session_id),
        )
        conn.commit()

    def get_session(self, session_id: str) -> Optional[Session]:
        row = (
            self._conn()
            .execute("SELECT * FROM sessions WHERE id=?", (session_id,))
            .fetchone()
        )
        return self._row_to_session(row) if row else None

    def get_session_by_prefix(self, prefix: str) -> Optional[Session]:
        """Find session by ID prefix match."""
        row = (
            self._conn()
            .execute(
                "SELECT * FROM sessions WHERE id LIKE ? ORDER BY last_activity_at DESC LIMIT 1",
                (prefix + "%",),
            )
            .fetchone()
        )
        return self._row_to_session(row) if row else None

    def list_sessions(
        self, *, limit: int = 100, workspace: Optional[str] = None
    ) -> List[Session]:
        conn = self._conn()
        if workspace:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE workspace=? ORDER BY last_activity_at DESC LIMIT ?",
                (workspace, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY last_activity_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def _row_to_session(self, row: sqlite3.Row) -> Session:
        keys = row.keys()

        def _get(key, default=None):
            return row[key] if key in keys else default

        return Session(
            id=row["id"],
            file_path=row["file_path"],
            session_type=row["session_type"],
            workspace=row["workspace"],
            started_at=row["started_at"],
            last_activity_at=row["last_activity_at"],
            title=_get("title"),
            summary=_get("summary"),
            summary_updated_at=_get("summary_updated_at"),
            total_turns=_get("total_turns") or 0,
            agent_id=_get("agent_id"),
            created_at=_get("created_at"),
            updated_at=_get("updated_at"),
        )

    # ── Turns ─────────────────────────────────────────────────────────────

    def insert_turn(self, t: Turn, content: Optional[str] = None) -> None:
        conn = self._conn()
        conn.execute(
            """INSERT OR IGNORE INTO turns
               (id, session_id, turn_number, user_message, assistant_summary,
                title, description, model_name, content_hash, timestamp,
                is_continuation, satisfaction, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                t.id,
                t.session_id,
                t.turn_number,
                t.user_message,
                t.assistant_summary,
                t.title,
                t.description,
                t.model_name,
                t.content_hash,
                t.timestamp,
                1 if t.is_continuation else 0,
                t.satisfaction,
                t.created_at or _utcnow(),
            ),
        )
        if content:
            conn.execute(
                "INSERT OR IGNORE INTO turn_content (turn_id, content, content_size) VALUES (?, ?, ?)",
                (t.id, content, len(content)),
            )
        conn.execute(
            "UPDATE sessions SET total_turns = total_turns + 1, updated_at = ? WHERE id = ?",
            (_utcnow(), t.session_id),
        )
        conn.commit()

    def get_turns(self, session_id: str) -> List[Turn]:
        rows = (
            self._conn()
            .execute(
                "SELECT * FROM turns WHERE session_id=? ORDER BY turn_number",
                (session_id,),
            )
            .fetchall()
        )
        return [self._row_to_turn(r) for r in rows]

    def get_turn_by_hash(self, session_id: str, content_hash: str) -> Optional[Turn]:
        row = (
            self._conn()
            .execute(
                "SELECT * FROM turns WHERE session_id=? AND content_hash=?",
                (session_id, content_hash),
            )
            .fetchone()
        )
        return self._row_to_turn(row) if row else None

    def get_max_turn_number(self, session_id: str) -> int:
        row = (
            self._conn()
            .execute(
                "SELECT MAX(turn_number) as m FROM turns WHERE session_id=?",
                (session_id,),
            )
            .fetchone()
        )
        return (row["m"] or 0) if row else 0

    def get_turn_content(self, turn_id: str) -> Optional[str]:
        row = (
            self._conn()
            .execute("SELECT content FROM turn_content WHERE turn_id=?", (turn_id,))
            .fetchone()
        )
        return row["content"] if row else None

    def _row_to_turn(self, row: sqlite3.Row) -> Turn:
        keys = row.keys()

        def _get(key, default=None):
            return row[key] if key in keys else default

        is_cont = False
        if "is_continuation" in keys:
            v = row["is_continuation"]
            is_cont = v in (1, "1", True)
        return Turn(
            id=row["id"],
            session_id=row["session_id"],
            turn_number=row["turn_number"],
            user_message=_get("user_message"),
            assistant_summary=_get("assistant_summary"),
            title=_get("title", ""),
            description=_get("description"),
            model_name=_get("model_name"),
            content_hash=row["content_hash"],
            timestamp=row["timestamp"],
            is_continuation=is_cont,
            satisfaction=_get("satisfaction", "fine"),
            created_at=_get("created_at"),
        )

    # ── Events ────────────────────────────────────────────────────────────

    def upsert_event(self, e: Event, session_ids: Optional[List[str]] = None) -> None:
        conn = self._conn()
        now = _utcnow()
        conn.execute(
            """INSERT INTO events
               (id, title, description, event_type, status, start_timestamp,
                end_timestamp, created_at, updated_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, description=excluded.description,
                 status=excluded.status, end_timestamp=excluded.end_timestamp,
                 updated_at=?, metadata=excluded.metadata""",
            (
                e.id,
                e.title,
                e.description,
                e.event_type,
                e.status,
                e.start_timestamp,
                e.end_timestamp,
                e.created_at or now,
                e.updated_at or now,
                e.metadata,
                now,
            ),
        )
        if session_ids:
            for sid in session_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO event_sessions (event_id, session_id) VALUES (?, ?)",
                    (e.id, sid),
                )
        conn.commit()

    def get_event(self, event_id: str) -> Optional[Event]:
        row = (
            self._conn()
            .execute("SELECT * FROM events WHERE id=?", (event_id,))
            .fetchone()
        )
        return self._row_to_event(row) if row else None

    def list_events(self, *, limit: int = 50) -> List[Event]:
        rows = (
            self._conn()
            .execute("SELECT * FROM events ORDER BY updated_at DESC LIMIT ?", (limit,))
            .fetchall()
        )
        return [self._row_to_event(r) for r in rows]

    def get_sessions_for_event(self, event_id: str) -> List[Session]:
        rows = (
            self._conn()
            .execute(
                """SELECT s.* FROM sessions s
               JOIN event_sessions es ON s.id = es.session_id
               WHERE es.event_id = ?
               ORDER BY s.last_activity_at DESC""",
                (event_id,),
            )
            .fetchall()
        )
        return [self._row_to_session(r) for r in rows]

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        keys = row.keys()

        def _get(key, default=None):
            return row[key] if key in keys else default

        return Event(
            id=row["id"],
            title=row["title"],
            description=_get("description"),
            event_type=row["event_type"],
            status=row["status"],
            start_timestamp=_get("start_timestamp"),
            end_timestamp=_get("end_timestamp"),
            created_at=_get("created_at"),
            updated_at=_get("updated_at"),
            metadata=_get("metadata"),
        )

    # ── Agent Info ────────────────────────────────────────────────────────

    def upsert_agent_info(self, a: AgentInfo) -> None:
        conn = self._conn()
        now = _utcnow()
        conn.execute(
            """INSERT INTO agent_info (id, name, title, description, visibility, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, title=excluded.title, description=excluded.description,
                 visibility=excluded.visibility, updated_at=?""",
            (
                a.id,
                a.name,
                a.title,
                a.description,
                a.visibility,
                a.created_at or now,
                a.updated_at or now,
                now,
            ),
        )
        conn.commit()

    def list_agent_info(self, *, include_hidden: bool = False) -> List[AgentInfo]:
        conn = self._conn()
        if include_hidden:
            rows = conn.execute(
                "SELECT * FROM agent_info ORDER BY updated_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_info WHERE visibility='visible' ORDER BY updated_at DESC"
            ).fetchall()
        return [self._row_to_agent_info(r) for r in rows]

    def _row_to_agent_info(self, row: sqlite3.Row) -> AgentInfo:
        keys = row.keys()

        def _get(key, default=None):
            return row[key] if key in keys else default

        return AgentInfo(
            id=row["id"],
            name=row["name"],
            title=_get("title", ""),
            description=_get("description", ""),
            visibility=_get("visibility", "visible"),
            created_at=_get("created_at"),
            updated_at=_get("updated_at"),
        )

    # ── Jobs ──────────────────────────────────────────────────────────────

    def enqueue_job(
        self,
        kind: str,
        dedupe_key: str,
        payload: Optional[dict] = None,
        priority: int = 0,
    ) -> str:
        conn = self._conn()
        job_id = str(uuid.uuid4())
        payload_json = json.dumps(payload) if payload else None
        try:
            conn.execute(
                """INSERT INTO jobs (id, kind, dedupe_key, payload, priority)
                   VALUES (?, ?, ?, ?, ?)""",
                (job_id, kind, dedupe_key, payload_json, priority),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # Duplicate dedupe_key — just return existing
            row = conn.execute(
                "SELECT id FROM jobs WHERE dedupe_key=?", (dedupe_key,)
            ).fetchone()
            return row["id"] if row else job_id
        return job_id

    def claim_job(
        self, worker_id: str, kinds: Optional[List[str]] = None
    ) -> Optional[Job]:
        """Claim the next available job for processing."""
        conn = self._conn()
        now = _utcnow()
        kind_filter = ""
        params: list = [now, now]
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            kind_filter = f"AND kind IN ({placeholders})"
            params.extend(kinds)
        params.append(1)

        row = conn.execute(
            f"""SELECT * FROM jobs
                WHERE status IN ('queued', 'retry')
                  AND (next_run_at IS NULL OR next_run_at <= ?)
                  AND (locked_until IS NULL OR locked_until <= ?)
                  {kind_filter}
                ORDER BY priority DESC, created_at ASC
                LIMIT ?""",
            params,
        ).fetchone()

        if not row:
            return None

        # Lock it
        lock_until = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        # Give 5 minutes lease
        from datetime import timedelta

        lock_until = (datetime.utcnow() + timedelta(minutes=5)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn.execute(
            """UPDATE jobs SET status='processing', locked_by=?, locked_until=?,
               attempts=attempts+1, updated_at=? WHERE id=?""",
            (worker_id, lock_until, _utcnow(), row["id"]),
        )
        conn.commit()
        return self._row_to_job(row)

    def complete_job(self, job_id: str) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE jobs SET status='done', locked_by=NULL, locked_until=NULL, updated_at=? WHERE id=?",
            (_utcnow(), job_id),
        )
        conn.commit()

    def fail_job(self, job_id: str, error: str, *, retry: bool = True) -> None:
        conn = self._conn()
        new_status = "retry" if retry else "failed"
        conn.execute(
            """UPDATE jobs SET status=?, last_error=?, locked_by=NULL, locked_until=NULL,
               updated_at=? WHERE id=?""",
            (new_status, error[:2000], _utcnow(), job_id),
        )
        conn.commit()

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        keys = row.keys()

        def _get(key, default=None):
            return row[key] if key in keys else default

        return Job(
            id=row["id"],
            kind=row["kind"],
            dedupe_key=row["dedupe_key"],
            payload=_get("payload"),
            status=row["status"],
            priority=_get("priority", 0),
            attempts=_get("attempts", 0),
            next_run_at=_get("next_run_at"),
            locked_until=_get("locked_until"),
            locked_by=_get("locked_by"),
            last_error=_get("last_error"),
            created_at=_get("created_at"),
            updated_at=_get("updated_at"),
        )

    # ── Search ────────────────────────────────────────────────────────────

    def search_events(
        self,
        query: str,
        *,
        limit: int = 20,
        regex: bool = True,
        ignore_case: bool = True,
    ) -> List[Event]:
        conn = self._conn()
        if regex:
            pattern = f"(?i){query}" if ignore_case else query
            rows = conn.execute(
                """SELECT * FROM events
                   WHERE title REGEXP ? OR description REGEXP ?
                   ORDER BY updated_at DESC LIMIT ?""",
                (pattern, pattern, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM fts_events WHERE fts_events MATCH ? LIMIT ?",
                (query, limit),
            ).fetchall()
            # FTS returns different columns, re-query
            if rows:
                # Get actual event rows by matching title
                events = []
                for r in rows:
                    actual = conn.execute(
                        "SELECT * FROM events WHERE title=? LIMIT 1", (r["title"],)
                    ).fetchone()
                    if actual:
                        events.append(self._row_to_event(actual))
                return events[:limit]
        return [self._row_to_event(r) for r in rows]

    def search_sessions(
        self,
        query: str,
        *,
        limit: int = 20,
        regex: bool = True,
        ignore_case: bool = True,
        session_ids: Optional[List[str]] = None,
    ) -> List[Session]:
        conn = self._conn()
        pattern = f"(?i){query}" if (regex and ignore_case) else query

        id_filter = ""
        params: list = []
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            id_filter = f"AND id IN ({placeholders})"
            params.extend(session_ids)

        if regex:
            rows = conn.execute(
                f"""SELECT * FROM sessions
                    WHERE (title REGEXP ? OR summary REGEXP ?) {id_filter}
                    ORDER BY last_activity_at DESC LIMIT ?""",
                [pattern, pattern] + params + [limit],
            ).fetchall()
        else:
            like = f"%{query}%"
            rows = conn.execute(
                f"""SELECT * FROM sessions
                    WHERE (title LIKE ? OR summary LIKE ?) {id_filter}
                    ORDER BY last_activity_at DESC LIMIT ?""",
                [like, like] + params + [limit],
            ).fetchall()

        return [self._row_to_session(r) for r in rows]

    def search_turns(
        self,
        query: str,
        *,
        limit: int = 20,
        regex: bool = True,
        ignore_case: bool = True,
        session_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Search turn titles and descriptions. Returns dicts with turn + session info."""
        conn = self._conn()
        pattern = f"(?i){query}" if (regex and ignore_case) else query

        id_filter = ""
        params: list = []
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            id_filter = f"AND t.session_id IN ({placeholders})"
            params.extend(session_ids)

        if regex:
            rows = conn.execute(
                f"""SELECT t.*, s.title as _session_title, s.workspace as _workspace
                    FROM turns t JOIN sessions s ON t.session_id = s.id
                    WHERE (t.title REGEXP ? OR t.description REGEXP ?) {id_filter}
                    ORDER BY t.timestamp DESC LIMIT ?""",
                [pattern, pattern] + params + [limit],
            ).fetchall()
        else:
            like = f"%{query}%"
            rows = conn.execute(
                f"""SELECT t.*, s.title as _session_title, s.workspace as _workspace
                    FROM turns t JOIN sessions s ON t.session_id = s.id
                    WHERE (t.title LIKE ? OR t.description LIKE ?) {id_filter}
                    ORDER BY t.timestamp DESC LIMIT ?""",
                [like, like] + params + [limit],
            ).fetchall()

        results = []
        for r in rows:
            keys = r.keys()

            def _get(key, default=None):
                return r[key] if key in keys else default

            results.append(
                {
                    "turn_id": r["id"],
                    "session_id": r["session_id"],
                    "turn_number": r["turn_number"],
                    "title": _get("title", ""),
                    "description": _get("description"),
                    "timestamp": r["timestamp"],
                    "session_title": _get("_session_title"),
                    "workspace": _get("_workspace"),
                }
            )
        return results

    def search_content(
        self,
        query: str,
        *,
        limit: int = 20,
        regex: bool = True,
        ignore_case: bool = True,
        session_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Search raw turn content (slow but thorough)."""
        conn = self._conn()
        pattern = f"(?i){query}" if (regex and ignore_case) else query

        id_filter = ""
        params: list = []
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            id_filter = f"AND t.session_id IN ({placeholders})"
            params.extend(session_ids)

        if regex:
            rows = conn.execute(
                f"""SELECT t.id, t.session_id, t.turn_number, t.title, t.timestamp,
                           tc.content_size
                    FROM turns t
                    JOIN turn_content tc ON t.id = tc.turn_id
                    WHERE tc.content REGEXP ? {id_filter}
                    ORDER BY t.timestamp DESC LIMIT ?""",
                [pattern] + params + [limit],
            ).fetchall()
        else:
            like = f"%{query}%"
            rows = conn.execute(
                f"""SELECT t.id, t.session_id, t.turn_number, t.title, t.timestamp,
                           tc.content_size
                    FROM turns t
                    JOIN turn_content tc ON t.id = tc.turn_id
                    WHERE tc.content LIKE ? {id_filter}
                    ORDER BY t.timestamp DESC LIMIT ?""",
                [like] + params + [limit],
            ).fetchall()

        results = []
        for r in rows:
            keys = r.keys()
            results.append(
                {
                    "turn_id": r["id"],
                    "session_id": r["session_id"],
                    "turn_number": r["turn_number"],
                    "title": r["title"] if "title" in keys else "",
                    "timestamp": r["timestamp"],
                    "content_size": r["content_size"] if "content_size" in keys else 0,
                }
            )
        return results

    # ── Stats ─────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        conn = self._conn()
        sessions = conn.execute("SELECT COUNT(*) as c FROM sessions").fetchone()["c"]
        turns = conn.execute("SELECT COUNT(*) as c FROM turns").fetchone()["c"]
        events = conn.execute("SELECT COUNT(*) as c FROM events").fetchone()["c"]
        agents = conn.execute("SELECT COUNT(*) as c FROM agent_info").fetchone()["c"]
        jobs_pending = conn.execute(
            "SELECT COUNT(*) as c FROM jobs WHERE status IN ('queued','retry')"
        ).fetchone()["c"]

        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "db_path": str(self.db_path),
            "db_size_mb": round(db_size / (1024 * 1024), 2),
            "sessions": sessions,
            "turns": turns,
            "events": events,
            "agents": agents,
            "jobs_pending": jobs_pending,
        }


# ── Singleton accessor ────────────────────────────────────────────────────────

_db_instances: Dict[str, Database] = {}
_db_lock = threading.Lock()


def get_db(*, read_only: bool = True) -> Database:
    """Get or create database instance (process-wide singleton per path)."""
    from .config import Config

    cfg = Config.load()
    db_path = str(cfg.resolved_db_path)
    key = f"{db_path}:{'ro' if read_only else 'rw'}"

    with _db_lock:
        if key not in _db_instances:
            db = Database(cfg.resolved_db_path, read_only=read_only)
            if not read_only:
                db.initialize()
            _db_instances[key] = db
        return _db_instances[key]
