"""
Session discovery — find Claude Code session files on disk.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def discover_sessions(
    *,
    project_filter: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    Find all Claude Code session files on disk.

    Returns list of dicts:
        {path, session_type, project, session_id}
    """
    return _discover_claude(project_filter)


def _discover_claude(project_filter: Optional[str] = None) -> List[Dict[str, str]]:
    """Find Claude Code sessions under ~/.claude/projects/."""
    base = Path.home() / ".claude" / "projects"
    if not base.exists():
        return []

    results = []
    for project_dir in _safe_iterdir(base):
        if not project_dir.is_dir():
            continue

        project_path = _decode_claude_project_dir(project_dir.name)

        if project_filter and project_filter not in (project_path or ""):
            continue

        for f in project_dir.glob("*.jsonl"):
            # Skip agent sub-sessions
            if f.name.startswith("agent-"):
                continue
            results.append({
                "path": str(f),
                "session_type": "claude",
                "project": project_path or project_dir.name,
                "session_id": f.stem,
            })

    return results


def _decode_claude_project_dir(dirname: str) -> Optional[str]:
    """
    Decode Claude Code project directory name to a path.

    Claude encodes project paths by replacing '/' with '-':
        -home-yu-projects-foo  ->  /home/yu/projects/foo
    """
    if not dirname.startswith("-"):
        return None

    # Replace leading '-' with '/' then remaining '-' with '/'
    decoded = "/" + dirname[1:].replace("-", "/")
    return decoded


def _safe_iterdir(path: Path):
    """Iterate directory entries, ignoring permission errors."""
    try:
        yield from path.iterdir()
    except PermissionError:
        pass
