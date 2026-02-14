"""
Project Brief — the core output of OpenContext.

Generates per-project knowledge documents by:
  1. Scanning project docs (README, CLAUDE.md, etc.) — stable foundation
  2. Extracting facts from sessions (Map) — dynamic knowledge
  3. Synthesizing into a Project Brief (Reduce) — the final product
  4. Incremental updates — append new session facts to existing brief

Brief files stored at ~/.opencontext/briefs/<workspace-slug>.md
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import Config
from ..core.db import Database, get_db
from .llm import call_llm, call_llm_text

logger = logging.getLogger(__name__)

_BRIEFS_DIR = "~/.opencontext/briefs"


# ── Brief Storage ────────────────────────────────────────────────────────────

def _briefs_dir() -> Path:
    d = Path(_BRIEFS_DIR).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _workspace_slug(workspace: str) -> str:
    """Convert workspace path to filename-safe slug.

    /home/yu/projects/HaL → home-yu-projects-HaL
    """
    slug = workspace.strip("/").replace("/", "-")
    # Remove unsafe chars
    slug = re.sub(r"[^a-zA-Z0-9_\-.]", "-", slug)
    return slug


def brief_path(workspace: str) -> Path:
    return _briefs_dir() / f"{_workspace_slug(workspace)}.md"


def read_brief(workspace: str) -> Optional[str]:
    """Read existing brief for a workspace. Returns None if not found."""
    p = brief_path(workspace)
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return None


def save_brief(workspace: str, content: str) -> Path:
    """Save brief content to file."""
    p = brief_path(workspace)
    p.write_text(content, encoding="utf-8")
    return p


# ── Map: Extract Facts from Sessions ────────────────────────────────────────

def extract_session_facts(
    session_id: str,
    *,
    db: Optional[Database] = None,
) -> Optional[Dict[str, Any]]:
    """Extract structured facts from a single session (Map phase).

    Returns dict with decisions, solved, features, tech_changes, open_threads.
    """
    db = db or get_db(read_only=True)
    session = db.get_session(session_id)
    if not session:
        return None

    turns = db.get_turns(session_id)
    if not turns:
        return None

    # Build compact payload — include both user message and assistant work
    turn_data = []
    for t in turns:
        entry: Dict[str, str] = {}
        # Prefer LLM-generated title/description if available
        if t.title and not t.title.startswith("Turn "):
            entry["title"] = t.title
        if t.description:
            entry["description"] = t.description[:300]
        # Always include user message (what was asked)
        if t.user_message:
            entry["user"] = t.user_message[:500]
        # Include assistant summary (what was done) — critical for understanding
        if t.assistant_summary:
            entry["assistant"] = t.assistant_summary[:500]
        if entry:
            turn_data.append(entry)

    payload = {
        "session_title": session.title or "Untitled",
        "session_summary": session.summary or "",
        "workspace": session.workspace or "",
        "date": (session.started_at or "")[:10],
        "turns": turn_data,
    }

    _, result = call_llm("session_extract", payload)
    if not result:
        return None

    # Attach session metadata
    result["_session_id"] = session_id
    result["_date"] = (session.started_at or "")[:10]
    result["_title"] = session.title or "Untitled"

    return result


def extract_sessions_parallel(
    session_ids: List[str],
    *,
    max_workers: int = 4,
    db: Optional[Database] = None,
) -> List[Dict[str, Any]]:
    """Extract facts from multiple sessions in parallel (Map phase)."""
    results: List[Dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(extract_session_facts, sid, db=db): sid
            for sid in session_ids
        }
        for future in as_completed(futures):
            sid = futures[future]
            try:
                result = future.result()
                if result:
                    results.append(result)
                    logger.info(f"Extracted facts from session {sid[:8]}")
            except Exception as e:
                logger.error(f"Failed to extract session {sid[:8]}: {e}")

    # Sort by date
    results.sort(key=lambda r: r.get("_date", ""))
    return results


# ── Reduce: Synthesize Brief ────────────────────────────────────────────────

def synthesize_brief(
    workspace: str,
    *,
    session_ids: Optional[List[str]] = None,
    top_n: Optional[int] = None,
    db: Optional[Database] = None,
) -> Optional[str]:
    """Generate a Project Brief from docs + sessions (full Reduce).

    Args:
        workspace: Project workspace path
        session_ids: Specific sessions to process (default: auto-select)
        top_n: Process top N sessions by turn count (default: 15)
        db: Database instance

    Returns:
        Brief content as markdown string, or None on failure.
    """
    from ..ingest.scanner import scan_project_docs, scan_project_tech

    db = db or get_db(read_only=True)

    # 1. Scan project docs
    docs = scan_project_docs(workspace)
    tech = scan_project_tech(workspace)

    # 2. Select sessions
    if not session_ids:
        session_ids = _select_sessions(workspace, top_n=top_n or 15, db=db)

    if not session_ids and not docs:
        logger.warning(f"No sessions or docs found for {workspace}")
        return None

    # 3. Map: extract facts in parallel
    extractions: List[Dict[str, Any]] = []
    if session_ids:
        logger.info(f"Extracting facts from {len(session_ids)} sessions...")
        extractions = extract_sessions_parallel(session_ids, db=db)

    # 4. Reduce: synthesize
    project_name = Path(workspace).name
    user_content = _build_synthesis_input(project_name, docs, tech, extractions)

    logger.info("Synthesizing Project Brief...")
    brief = call_llm_text("brief_synthesize", user_content)
    if not brief:
        return None

    # Add footer
    from datetime import datetime
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    brief += (
        f"\n\n---\n"
        f"*Auto-generated by OpenContext | {len(extractions)} sessions processed "
        f"| Last updated: {timestamp}*\n"
    )

    # Save
    save_brief(workspace, brief)
    return brief


def update_brief(
    workspace: str,
    session_id: str,
    *,
    db: Optional[Database] = None,
) -> Optional[str]:
    """Incrementally update an existing brief with a new session.

    If no existing brief, falls back to full synthesis.
    """
    existing = read_brief(workspace)
    if not existing:
        return synthesize_brief(workspace, session_ids=[session_id], db=db)

    # Extract facts from the new session
    facts = extract_session_facts(session_id, db=db)
    if not facts:
        return existing  # Nothing new to add

    # Build update input
    user_content = (
        "## Current Brief\n\n"
        f"{existing}\n\n"
        "## New Session Facts\n\n"
        f"Session: {facts.get('_title', 'Untitled')} ({facts.get('_date', 'unknown')})\n"
        f"{json.dumps(facts, indent=2, ensure_ascii=False, default=str)}\n"
    )

    updated = call_llm_text("brief_update", user_content)
    if not updated:
        return existing

    # Update footer
    from datetime import datetime
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    # Remove old footer if present
    updated = re.sub(r"\n---\n\*Auto-generated.*\*\n?$", "", updated)
    updated += (
        f"\n\n---\n"
        f"*Auto-generated by OpenContext | Last updated: {timestamp}*\n"
    )

    save_brief(workspace, updated)
    return updated


# ── Helpers ──────────────────────────────────────────────────────────────────

def _select_sessions(
    workspace: str,
    *,
    top_n: int = 15,
    db: Database,
) -> List[str]:
    """Select top sessions for a workspace, ranked by turn count."""
    conn = db._conn()
    rows = conn.execute(
        """SELECT id, total_turns FROM sessions
           WHERE workspace = ?
           ORDER BY total_turns DESC, last_activity_at DESC
           LIMIT ?""",
        (workspace, top_n),
    ).fetchall()
    return [r["id"] for r in rows]


def _build_synthesis_input(
    project_name: str,
    docs: Dict[str, str],
    tech: Dict[str, str],
    extractions: List[Dict[str, Any]],
) -> str:
    """Build the user message for brief synthesis."""
    parts = [f"# Project: {project_name}\n"]

    # Project docs
    if docs:
        parts.append("## Project Documentation\n")
        for name, content in docs.items():
            parts.append(f"### {name}\n{content}\n")

    # Tech stack hints
    if tech:
        parts.append("## Detected Tech Stack\n")
        for indicator, content in tech.items():
            parts.append(f"### {indicator}\n{content}\n")

    # Session extractions
    if extractions:
        parts.append(f"## Extracted Knowledge ({len(extractions)} sessions)\n")
        for ext in extractions:
            date = ext.get("_date", "?")
            title = ext.get("_title", "Untitled")
            parts.append(f"### [{date}] {title}\n")
            # Compact JSON for each extraction
            clean = {
                k: v for k, v in ext.items()
                if not k.startswith("_") and v
            }
            if clean:
                parts.append(json.dumps(clean, indent=1, ensure_ascii=False) + "\n")
    else:
        parts.append("## Sessions\nNo session data available.\n")

    return "\n".join(parts)


def list_projects(*, db: Optional[Database] = None) -> List[Dict[str, Any]]:
    """List all known projects with brief availability status."""
    db = db or get_db(read_only=True)
    conn = db._conn()

    rows = conn.execute(
        """SELECT workspace, COUNT(*) as session_count,
                  SUM(total_turns) as total_turns,
                  MAX(last_activity_at) as last_activity
           FROM sessions
           WHERE workspace IS NOT NULL AND workspace != ''
           GROUP BY workspace
           ORDER BY last_activity DESC"""
    ).fetchall()

    projects = []
    for r in rows:
        ws = r["workspace"]
        bp = brief_path(ws)
        projects.append({
            "workspace": ws,
            "name": Path(ws).name if ws else "unknown",
            "sessions": r["session_count"],
            "turns": r["total_turns"] or 0,
            "last_activity": r["last_activity"],
            "has_brief": bp.is_file(),
        })

    return projects
