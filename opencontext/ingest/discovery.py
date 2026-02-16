"""
Session discovery — find Claude Code session files on disk.
"""

from __future__ import annotations

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

    Claude encodes project paths by replacing '/' with '-' and
    stripping leading dots from directory components:
        -home-yu-projects-foo  ->  /home/yu/projects/foo
        -home-yu--hal          ->  /home/yu/.hal

    Since the encoding is lossy (hyphens in real names become
    indistinguishable from path separators), we validate decoded
    paths against the filesystem to resolve ambiguity.
    """
    if not dirname.startswith("-"):
        return None

    # Split on '-', first element is empty (leading '-')
    # Consecutive '--' means the next component had a leading dot.
    parts = dirname[1:].split("-")
    segments: list[str] = []
    i = 0
    while i < len(parts):
        if parts[i] == "" and i + 1 < len(parts):
            segments.append("." + parts[i + 1])
            i += 2
        else:
            segments.append(parts[i])
            i += 1

    return _resolve_segments(segments)


def _resolve_segments(segments: list[str]) -> str:
    """Find the real filesystem path by greedily matching existing dirs."""
    full_naive = "/" + "/".join(segments)
    if Path(full_naive).exists():
        return full_naive

    # Greedily match: at each position, find the longest tail that
    # forms an existing entry when joined with '-'.
    result_parts: list[str] = []
    i = 0
    while i < len(segments):
        best_end = i + 1
        for j in range(len(segments), i, -1):
            candidate = "-".join(segments[i:j])
            parent = "/" + "/".join(result_parts) if result_parts else ""
            if Path(parent + "/" + candidate).exists():
                best_end = j
                break
        result_parts.append("-".join(segments[i:best_end]))
        i = best_end

    return "/" + "/".join(result_parts)


def _safe_iterdir(path: Path):
    """Iterate directory entries, ignoring permission errors."""
    try:
        yield from path.iterdir()
    except PermissionError:
        pass
