"""
Background worker — process pending summarization jobs.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

from .core.db import Database, get_db

logger = logging.getLogger(__name__)


def process_jobs(
    *,
    max_jobs: int = 50,
    db: Optional[Database] = None,
) -> int:
    """
    Process pending jobs (turn summaries, session summaries, etc.).

    Returns number of jobs processed.
    """
    db = db or get_db(read_only=False)
    worker_id = f"worker-{os.getpid()}"
    processed = 0

    for _ in range(max_jobs):
        job = db.claim_job(worker_id)
        if not job:
            break

        try:
            payload = json.loads(job.payload) if job.payload else {}

            if job.kind == "turn_summary":
                _process_turn_summary(payload, db=db)
            elif job.kind == "session_summary":
                _process_session_summary(payload, db=db)
            elif job.kind == "event_summary":
                _process_event_summary(payload, db=db)
            elif job.kind == "agent_description":
                _process_agent_description(payload, db=db)
            else:
                logger.warning(f"Unknown job kind: {job.kind}")

            db.complete_job(job.id)
            processed += 1

        except Exception as e:
            logger.error(f"Job {job.id} ({job.kind}) failed: {e}")
            retry = job.attempts < 3
            db.fail_job(job.id, str(e), retry=retry)

    return processed


def _process_turn_summary(payload: dict, *, db: Database) -> None:
    from .summarize.pipeline import summarize_turn
    summarize_turn(
        turn_id=payload["turn_id"],
        user_message=payload.get("user_message", ""),
        assistant_summary=payload.get("assistant_summary", ""),
        db=db,
    )


def _process_session_summary(payload: dict, *, db: Database) -> None:
    from .summarize.pipeline import summarize_session
    summarize_session(session_id=payload["session_id"], db=db)


def _process_event_summary(payload: dict, *, db: Database) -> None:
    from .summarize.pipeline import summarize_event
    summarize_event(
        session_ids=payload.get("session_ids", []),
        event_id=payload.get("event_id"),
        db=db,
    )


def _process_agent_description(payload: dict, *, db: Database) -> None:
    from .summarize.pipeline import describe_agent
    describe_agent(agent_id=payload["agent_id"], db=db)
