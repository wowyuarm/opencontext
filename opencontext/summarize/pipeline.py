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
    tool_uses: Optional[list] = None,
    files_modified: Optional[list] = None,
    db: Optional[Database] = None,
) -> Optional[Dict[str, str]]:
    """
    Generate LLM title + description + metadata for a single turn.

    Single LLM call produces title, description, is_continuation, satisfaction.
    Updates the turn record in the database.
    """
    db = db or get_db(read_only=False)

    payload: Dict[str, Any] = {
        "user_message": user_message,
        "assistant_summary": assistant_summary,
    }
    if tool_uses:
        payload["tools_used"] = tool_uses[:50]
    if files_modified:
        payload["files_modified"] = files_modified[:50]

    model, result = call_llm("turn_summary", payload)
    if not result:
        return None

    title = result.get("title", "")[:200]
    description = result.get("description", "")[:1000]

    # Extract metadata from same response (merged call)
    is_cont = 1 if result.get("is_continuation") else 0
    satisfaction = result.get("satisfaction", "fine")
    if satisfaction not in ("good", "fine", "bad"):
        satisfaction = "fine"

    if title:
        conn = db._conn()
        conn.execute(
            """UPDATE turns SET title=?, description=?, model_name=?,
               is_continuation=?, satisfaction=? WHERE id=?""",
            (title, description, model, is_cont, satisfaction, turn_id),
        )
        conn.commit()

    return {"title": title, "description": description}


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

    # Build payload with turn summaries + tool/file data
    turn_data = []
    for t in turns:
        entry: Dict[str, Any] = {
            "turn_number": t.turn_number,
            "title": t.title,
            "description": t.description or "",
            "user_message": t.user_message or "",
        }
        # Include tool/file data for richer session understanding
        if t.tool_summary:
            try:
                tools = json.loads(t.tool_summary)
                if tools:
                    entry["tools_used"] = tools[:10]
            except (json.JSONDecodeError, TypeError):
                pass
        if t.files_modified:
            try:
                files = json.loads(t.files_modified)
                if files:
                    entry["files_modified"] = files
            except (json.JSONDecodeError, TypeError):
                pass
        turn_data.append(entry)

    _, result = call_llm("session_summary", {"turns": turn_data}, max_tokens=2048)
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
