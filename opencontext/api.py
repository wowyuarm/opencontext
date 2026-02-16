"""
OpenContext API — clean, importable functions for all operations.

Every function returns JSON-serializable dicts/lists.
Designed to be called from scripts, skills, or other agents.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional


def init() -> Dict[str, Any]:
    """Initialize OpenContext: create config dir, default config, and database."""
    from .core.config import _DEFAULT_CONFIG_PATH, _DEFAULT_DB_PATH
    from pathlib import Path
    import os

    config_path = Path(
        os.getenv("OPENCONTEXT_CONFIG", _DEFAULT_CONFIG_PATH)
    ).expanduser()
    results: Dict[str, Any] = {"created": [], "existing": []}

    # 1. Create parent dir
    config_dir = config_path.parent
    if config_dir.exists():
        results["existing"].append(str(config_dir))
    else:
        config_dir.mkdir(parents=True)
        results["created"].append(str(config_dir))

    # 2. Write default config.yaml (skip if exists)
    if config_path.exists():
        results["existing"].append(str(config_path))
    else:
        config_path.write_text(_DEFAULT_CONFIG_TEMPLATE)
        results["created"].append(str(config_path))

    # 3. Initialize database
    db_path = Path(
        os.getenv("OPENCONTEXT_DB_PATH", _DEFAULT_DB_PATH)
    ).expanduser()
    if db_path.exists():
        results["existing"].append(str(db_path))
    else:
        db = _db(read_only=False)
        results["created"].append(str(db_path))

    return results


# ── Setup ────────────────────────────────────────────────────────────────────

def setup_check() -> Dict[str, Any]:
    """Check environment state for setup guidance.

    Returns JSON with: initialized, has_api_key, project_count, db_exists, etc.
    """
    from .core.config import Config, _DEFAULT_CONFIG_PATH, _DEFAULT_DB_PATH
    from pathlib import Path
    import os

    config_path = Path(
        os.getenv("OPENCONTEXT_CONFIG", _DEFAULT_CONFIG_PATH)
    ).expanduser()
    db_path = Path(
        os.getenv("OPENCONTEXT_DB_PATH", _DEFAULT_DB_PATH)
    ).expanduser()

    result: Dict[str, Any] = {
        "initialized": config_path.exists(),
        "config_path": str(config_path),
        "db_exists": db_path.exists(),
        "db_path": str(db_path),
    }

    if config_path.exists():
        cfg = Config.load()
        result["llm_model"] = cfg.llm_model
        result["has_api_key"] = cfg.check_api_key() is None
        if not result["has_api_key"]:
            result["api_key_error"] = cfg.check_api_key()
    else:
        result["has_api_key"] = False

    # Count known projects
    if db_path.exists():
        try:
            db = _db()
            stats = db.stats()
            result["project_count"] = stats.get("projects", 0)
            result["session_count"] = stats.get("sessions", 0)
        except Exception:
            result["project_count"] = 0
            result["session_count"] = 0
    else:
        result["project_count"] = 0
        result["session_count"] = 0

    return result


def setup_discover() -> List[Dict[str, str]]:
    """Scan common paths and return discoverable projects.

    Groups session files by project path for a cleaner overview.
    """
    from .ingest.discovery import discover_sessions

    sessions = discover_sessions()
    # Group by project
    projects_map: Dict[str, int] = {}
    for s in sessions:
        proj = s["project"]
        projects_map[proj] = projects_map.get(proj, 0) + 1

    return [
        {"project": proj, "sessions": count}
        for proj, count in sorted(projects_map.items())
    ]


def setup_config(key: str, value: str) -> Dict[str, str]:
    """Set a config key-value pair."""
    from .core.config import Config
    Config.set_config(key, value)
    return {"key": key, "value": value, "status": "ok"}


_DEFAULT_CONFIG_TEMPLATE = """\
# OpenContext configuration

# ── LLM ──────────────────────────────────────────────────
# Model string uses litellm format: "provider/model-name"
# Examples:
#   anthropic/claude-haiku-4-5-20251001   (Anthropic)
#   openai/gpt-4o-mini                    (OpenAI)
#   deepseek/deepseek-chat                (DeepSeek)
#   gemini/gemini-3.0-flash               (Google)
#   ...qwen, moonshots, etc.
llm_model: "anthropic/claude-haiku-4-5-20251001"

# API key for the provider above.
# Alternatively, export the provider's env var directly:
#   ANTHROPIC_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY, etc.
api_key: ""

# ── Database ─────────────────────────────────────────────
# db_path: "~/.opencontext/db/opencontext.db"

# Currently supports Claude Code sessions only.
# Codex/Gemini support planned for future releases.
"""


def _serialize(obj: Any) -> Any:
    """Convert dataclass to dict."""
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    return obj


def _db(read_only: bool = True):
    from .core.db import get_db
    return get_db(read_only=read_only)


# ── Status ────────────────────────────────────────────────────────────────────

def status() -> Dict[str, Any]:
    """Database stats, config diagnostics, and API key check."""
    from .core.config import Config
    cfg = Config.load()

    result: Dict[str, Any] = {
        "llm_model": cfg.llm_model,
    }

    # Check API key
    key_err = cfg.check_api_key()
    result["api_key_ok"] = key_err is None
    if key_err:
        result["api_key_error"] = key_err

    # DB stats (may not exist yet)
    try:
        db = _db()
        stats = db.stats()
        result.update(stats)
    except Exception:
        result["db_path"] = str(cfg.resolved_db_path)
        result["db_error"] = "Database not initialized. Run: oc init"

    return result


# ── Discovery ─────────────────────────────────────────────────────────────────

def discover(project: Optional[str] = None) -> List[Dict[str, str]]:
    """Find Claude Code session files on disk (not yet imported)."""
    from .ingest.discovery import discover_sessions
    return discover_sessions(project_filter=project)


# ── Sessions ──────────────────────────────────────────────────────────────────

def sessions(*, workspace: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    """List imported sessions."""
    db = _db()
    items = db.list_sessions(workspace=workspace, limit=limit)
    return {
        "sessions": [_serialize(s) for s in items],
        "total": len(items),
    }


def show(session_id: str) -> Dict[str, Any]:
    """Show session details with all turns."""
    db = _db()
    s = db.get_session(session_id) or db.get_session_by_prefix(session_id)
    if not s:
        return {"error": f"Session not found: {session_id}"}
    turns = db.get_turns(s.id)
    return {
        "session": _serialize(s),
        "turns": [_serialize(t) for t in turns],
    }


# ── Import ────────────────────────────────────────────────────────────────────

def import_session(session_file: str, *, force: bool = False) -> Dict[str, Any]:
    """Import a session file into the database."""
    from .ingest.importer import import_session as _import
    return _import(session_file, force=force)


# ── Search ────────────────────────────────────────────────────────────────────

def search(
    query: str,
    *,
    search_type: str = "all",
    limit: int = 20,
    regex: bool = True,
    ignore_case: bool = True,
) -> Dict[str, Any]:
    """
    Search across accumulated context.

    search_type: "all" | "event" | "turn" | "session" | "content"
    "all" searches events + turns + sessions (not content, for speed).
    """
    db = _db()
    results: Dict[str, Any] = {"events": [], "turns": [], "sessions": [], "content": []}

    if search_type in ("all", "event"):
        events = db.search_events(query, limit=limit, regex=regex, ignore_case=ignore_case)
        results["events"] = [_serialize(e) for e in events]

    if search_type in ("all", "turn"):
        results["turns"] = db.search_turns(
            query, limit=limit, regex=regex, ignore_case=ignore_case,
        )

    if search_type in ("all", "session"):
        found = db.search_sessions(query, limit=limit, regex=regex, ignore_case=ignore_case)
        results["sessions"] = [_serialize(s) for s in found]

    if search_type == "content":
        results["content"] = db.search_content(
            query, limit=limit, regex=regex, ignore_case=ignore_case,
        )

    return results


# ── Events ────────────────────────────────────────────────────────────────────

def events(*, limit: int = 50) -> List[Dict[str, Any]]:
    """List all events."""
    db = _db()
    return [_serialize(e) for e in db.list_events(limit=limit)]


def event(event_id: str) -> Dict[str, Any]:
    """Show event details with linked sessions."""
    db = _db()
    e = db.get_event(event_id)
    if not e:
        return {"error": f"Event not found: {event_id}"}
    linked = db.get_sessions_for_event(event_id)
    return {
        "event": _serialize(e),
        "sessions": [_serialize(s) for s in linked],
    }


# ── Agents ────────────────────────────────────────────────────────────────────

def agents() -> List[Dict[str, Any]]:
    """List all agent profiles."""
    db = _db()
    return [_serialize(a) for a in db.list_agent_info()]


# ── Worker ────────────────────────────────────────────────────────────────────

def process(*, max_jobs: int = 50) -> Dict[str, int]:
    """Process pending summarization jobs."""
    from .worker import process_jobs
    n = process_jobs(max_jobs=max_jobs)
    return {"jobs_processed": n}


# ── Sync ─────────────────────────────────────────────────────────────────────

def sync(
    *,
    project: Optional[str] = None,
    summarize: bool = True,
    max_jobs: int = 50,
) -> Dict[str, Any]:
    """Discover, import, and optionally summarize all sessions.

    This is the main entry point for ingesting context:
      1. Discover session files on disk
      2. Import each into the database (incremental)
      3. Run pending summary jobs (if summarize=True)

    Returns aggregate stats.
    """
    # 1. Discover
    found = discover(project=project)

    # 2. Import each
    from .ingest.importer import import_session as _import
    imported_total = 0
    skipped_total = 0
    errors = []

    for item in found:
        result = _import(item["path"])
        if "error" in result:
            errors.append({"path": item["path"], "error": result["error"]})
        else:
            imported_total += result.get("turns_imported", 0)
            skipped_total += result.get("turns_skipped", 0)

    # 3. Summarize
    jobs_processed = 0
    if summarize and imported_total > 0:
        from .core.config import Config
        cfg = Config.load()
        key_err = cfg.check_api_key()
        if key_err:
            errors.append({"warning": f"Skipping summarization: {key_err}"})
        else:
            cfg.inject_api_key()
            from .worker import process_jobs
            jobs_processed = process_jobs(max_jobs=max_jobs)

    # Collect projects that had new data
    projects_updated = set()
    for item in found:
        projects_updated.add(item["project"])

    return {
        "sessions_found": len(found),
        "turns_imported": imported_total,
        "turns_skipped": skipped_total,
        "jobs_processed": jobs_processed,
        "projects_updated": sorted(projects_updated) if imported_total > 0 else [],
        "errors": errors,
    }


# ── Projects & Brief ────────────────────────────────────────────────────────

def projects() -> List[Dict[str, Any]]:
    """List all known projects with brief status."""
    from .summarize.brief import list_projects
    return list_projects()


def brief(
    workspace: str,
    *,
    top_n: Optional[int] = None,
    update_session: Optional[str] = None,
) -> Dict[str, Any]:
    """Get or generate a Project Brief.

    If brief exists and no generation requested, returns it.
    If update_session is given, incrementally updates.
    If top_n is given (or no brief exists), generates from scratch.

    Returns:
        {workspace, path, content, generated}
    """
    from .summarize.brief import read_brief, synthesize_brief, update_brief

    # Incremental update
    if update_session:
        content = update_brief(workspace, update_session)
        if content:
            from .summarize.brief import brief_path
            return {
                "workspace": workspace,
                "path": str(brief_path(workspace)),
                "content": content,
                "mode": "updated",
            }

    # Read existing
    existing = read_brief(workspace)
    if existing and top_n is None:
        from .summarize.brief import brief_path
        return {
            "workspace": workspace,
            "path": str(brief_path(workspace)),
            "content": existing,
            "mode": "cached",
        }

    # Generate from scratch
    content = synthesize_brief(workspace, top_n=top_n or 15)
    if content:
        from .summarize.brief import brief_path
        return {
            "workspace": workspace,
            "path": str(brief_path(workspace)),
            "content": content,
            "mode": "generated",
        }

    return {"workspace": workspace, "error": "No data available for this project"}
