"""
Summarization pipeline — turn → session → event → agent.

Each level builds on the previous one, creating a hierarchical
knowledge structure that makes project context searchable.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from ..core.db import Database, get_db
from ..core.models import Event
from .llm import call_llm

logger = logging.getLogger(__name__)


def summarize_turn(
    turn_id: str,
    user_message: str,
    assistant_summary: str,
    *,
    db: Optional[Database] = None,
) -> Optional[Dict[str, str]]:
    """
    Generate LLM title + description for a single turn.

    Updates the turn record in the database.
    Returns {"title": ..., "description": ...} or None.
    """
    db = db or get_db(read_only=False)

    payload = {
        "user_message": user_message[:3000],
        "assistant_summary": assistant_summary[:3000],
    }

    model, result = call_llm("turn_summary", payload)
    if not result:
        return None

    title = result.get("title", "")[:200]
    description = result.get("description", "")[:1000]

    if title:
        conn = db._conn()
        conn.execute(
            "UPDATE turns SET title=?, description=?, model_name=? WHERE id=?",
            (title, description, model, turn_id),
        )
        conn.commit()

    # Also classify metadata
    _classify_turn_metadata(turn_id, user_message, db=db)

    return {"title": title, "description": description}


def _classify_turn_metadata(
    turn_id: str,
    user_message: str,
    *,
    db: Optional[Database] = None,
) -> None:
    """Classify turn as continuation/new and satisfaction level."""
    db = db or get_db(read_only=False)

    _, result = call_llm("metadata", {"user_message": user_message[:2000]})
    if not result:
        return

    is_cont = 1 if result.get("is_continuation") else 0
    satisfaction = result.get("satisfaction", "fine")
    if satisfaction not in ("good", "fine", "bad"):
        satisfaction = "fine"

    conn = db._conn()
    conn.execute(
        "UPDATE turns SET is_continuation=?, satisfaction=? WHERE id=?",
        (is_cont, satisfaction, turn_id),
    )
    conn.commit()


def summarize_session(
    session_id: str,
    *,
    db: Optional[Database] = None,
) -> Optional[Dict[str, str]]:
    """
    Generate session-level summary from all turns.

    Updates session title + summary in the database.
    Returns {"title": ..., "summary": ...} or None.
    """
    db = db or get_db(read_only=False)

    turns = db.get_turns(session_id)
    if not turns:
        return None

    # Build payload with turn summaries
    turn_data = []
    for t in turns:
        turn_data.append({
            "turn_number": t.turn_number,
            "title": t.title,
            "description": t.description or "",
            "user_message": (t.user_message or "")[:500],
        })

    _, result = call_llm("session_summary", {"turns": turn_data})
    if not result:
        return None

    title = result.get("title", "")[:200]
    summary = result.get("summary", "")[:2000]

    if title:
        db.update_session_summary(session_id, title, summary)

    return {"title": title, "summary": summary}


def summarize_event(
    session_ids: List[str],
    *,
    event_id: Optional[str] = None,
    db: Optional[Database] = None,
) -> Optional[Dict[str, str]]:
    """
    Generate event-level summary from multiple sessions.

    Creates or updates an Event record linking the sessions.
    Returns {"title": ..., "description": ..., "event_id": ...} or None.
    """
    db = db or get_db(read_only=False)

    if not session_ids:
        return None

    # Collect session summaries
    session_data = []
    for sid in session_ids:
        s = db.get_session(sid) or db.get_session_by_prefix(sid)
        if s:
            session_data.append({
                "session_id": s.id[:8],
                "title": s.title or "Untitled",
                "summary": s.summary or "",
                "workspace": s.workspace or "",
            })

    if not session_data:
        return None

    _, result = call_llm("event_summary", {"sessions": session_data})
    if not result:
        return None

    title = result.get("title", "")[:200]
    description = result.get("description", "")[:3000]

    eid = event_id or str(uuid.uuid4())
    event = Event(
        id=eid,
        title=title,
        description=description,
        event_type="task",
        status="active",
    )
    db.upsert_event(event, session_ids=session_ids)

    return {"title": title, "description": description, "event_id": eid}


def describe_agent(
    agent_id: str,
    *,
    db: Optional[Database] = None,
) -> Optional[Dict[str, str]]:
    """
    Generate agent profile description from its sessions.

    Updates agent_info record.
    Returns {"title": ..., "description": ...} or None.
    """
    db = db or get_db(read_only=False)

    # Get all sessions for this agent
    conn = db._conn()
    rows = conn.execute(
        "SELECT * FROM sessions WHERE agent_id=? ORDER BY last_activity_at DESC LIMIT 50",
        (agent_id,),
    ).fetchall()

    if not rows:
        return None

    session_data = []
    for r in rows:
        keys = r.keys()
        title = r["title"] if "title" in keys else "Untitled"
        summary = r["summary"] if "summary" in keys else ""
        session_data.append({
            "title": title or "Untitled",
            "summary": summary or "",
        })

    _, result = call_llm("agent_description", {"sessions": session_data})
    if not result:
        return None

    title = result.get("title", "")[:200]
    description = result.get("description", "")[:2000]

    from ..core.models import AgentInfo
    agent = AgentInfo(id=agent_id, name=agent_id[:8], title=title, description=description)
    db.upsert_agent_info(agent)

    return {"title": title, "description": description}
