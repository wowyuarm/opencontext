"""
Session importer — parse session files and store in database.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.db import Database, get_db
from ..core.models import Session, Turn
from .parser import ParsedTurn, detect_format, extract_project_path, parse_session

logger = logging.getLogger(__name__)


def import_session(
    session_file: str,
    *,
    force: bool = False,
    db: Optional[Database] = None,
) -> Dict[str, Any]:
    """
    Import a session file into the database.

    Parses the file, creates session + turn records, and enqueues
    summarization jobs.

    Args:
        session_file: Path to session JSONL file
        force: Re-import even if session exists
        db: Optional database instance (defaults to get_db(rw))

    Returns:
        {session_id, turns_imported, turns_skipped, status}
    """
    path = Path(session_file)
    if not path.exists():
        return {"error": f"File not found: {session_file}"}

    session_type = detect_format(path)
    if not session_type:
        return {"error": f"Unknown session format: {session_file}"}

    db = db or get_db(read_only=False)
    session_id = path.stem
    project = extract_project_path(path)

    # Check if session already exists
    existing = db.get_session(session_id)
    if existing and not force:
        # Incremental: only parse new turns
        max_turn = db.get_max_turn_number(session_id)
        new_turns = parse_session(path, since_turn=max_turn)
        if not new_turns:
            return {
                "session_id": session_id,
                "turns_imported": 0,
                "turns_skipped": 0,
                "status": "up_to_date",
            }
    else:
        new_turns = parse_session(path)
        if not new_turns:
            # Incomplete/aborted session with no dialogue — skip silently
            return {
                "session_id": session_id,
                "turns_imported": 0,
                "turns_skipped": 0,
                "status": "skipped_empty",
            }

        # Get timestamp from first turn
        started_at = new_turns[0].timestamp if new_turns else ""
        last_activity = new_turns[-1].timestamp if new_turns else started_at

        session = Session(
            id=session_id,
            file_path=str(path),
            session_type=session_type,
            workspace=project,
            started_at=started_at,
            last_activity_at=last_activity,
        )
        db.upsert_session(session)

    # Import turns
    imported = 0
    skipped = 0

    for pt in new_turns:
        # Check for duplicate by content hash
        if db.get_turn_by_hash(session_id, pt.content_hash):
            skipped += 1
            continue

        turn = Turn(
            id=str(uuid.uuid4()),
            session_id=session_id,
            turn_number=pt.turn_number,
            user_message=pt.user_message,
            assistant_summary=pt.assistant_summary,
            title=f"Turn {pt.turn_number}",  # Placeholder, LLM will update
            description="",
            model_name=None,
            content_hash=pt.content_hash,
            timestamp=pt.timestamp,
            tool_summary=json.dumps(pt.tool_uses, ensure_ascii=False) if pt.tool_uses else None,
            files_modified=json.dumps(pt.files_modified, ensure_ascii=False) if pt.files_modified else None,
        )
        db.insert_turn(turn, content=pt.raw_content or None)
        imported += 1

        # Enqueue turn summary job
        db.enqueue_job(
            kind="turn_summary",
            dedupe_key=f"turn:{session_id}:{pt.turn_number}",
            payload={
                "session_id": session_id,
                "turn_id": turn.id,
                "turn_number": pt.turn_number,
                "user_message": pt.user_message,
                "assistant_summary": pt.assistant_summary,
                "tool_uses": pt.tool_uses,
                "files_modified": pt.files_modified,
            },
        )

    # Enqueue session summary job if we imported turns
    if imported > 0:
        db.enqueue_job(
            kind="session_summary",
            dedupe_key=f"session:{session_id}",
            payload={"session_id": session_id},
            priority=1,
        )

    return {
        "session_id": session_id,
        "turns_imported": imported,
        "turns_skipped": skipped,
        "status": "imported",
    }
