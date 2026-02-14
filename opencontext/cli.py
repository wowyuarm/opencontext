#!/usr/bin/env python3
"""
oc — OpenContext CLI

Usage:
    oc init                             Initialize config and database
    oc sync [--project PATH] [--no-llm] Discover + import + summarize
    oc status                           Config and database diagnostics
    oc projects                         List all projects with brief status
    oc brief <workspace> [--top N]      Get or generate Project Brief
    oc brief <workspace> --generate     Force regenerate brief
    oc discover [--project PATH]        Find sessions on disk
    oc sessions [--workspace PATH]      List imported sessions
    oc show <session_id>                Show session details
    oc import <session_file> [--force]  Import a session file
    oc search <query> [-t TYPE] [-l N]  Search context
    oc events [--limit N]               List events
    oc event <event_id>                 Show event details
    oc agents                           List agent profiles
    oc process [--max N]                Run pending summary jobs
"""

from __future__ import annotations

import json
import sys


def _json_out(data):
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def cmd_init(args):
    from opencontext.api import init
    result = init()
    for item in result["created"]:
        print(f"  created: {item}")
    for item in result["existing"]:
        print(f"  exists:  {item}")
    print("\nOpenContext initialized.")
    print("Next: edit ~/.opencontext/config.yaml to set your api_key")
    print("Then: oc sync")


def cmd_sync(args):
    from opencontext.api import sync
    project = _get_opt(args, "--project")
    summarize = "--no-llm" not in args
    print("Syncing...", file=sys.stderr)
    result = sync(project=project, summarize=summarize)
    print(
        f"  found {result['sessions_found']} sessions, "
        f"imported {result['turns_imported']} turns "
        f"({result['turns_skipped']} skipped)",
        file=sys.stderr,
    )
    if result["jobs_processed"]:
        print(f"  summarized {result['jobs_processed']} jobs", file=sys.stderr)
    for err in result.get("errors", []):
        print(f"  ! {err}", file=sys.stderr)
    _json_out(result)


def cmd_status(args):
    from opencontext.api import status
    result = status()
    print(f"  model:    {result['llm_model']}")
    if result.get("api_key_ok"):
        print("  api_key:  OK")
    else:
        print(f"  api_key:  MISSING — {result.get('api_key_error', '')}")
    if "db_error" in result:
        print(f"  db:       {result['db_error']}")
    else:
        print(f"  db:       {result.get('db_path', '?')}")
        print(
            f"  data:     {result.get('sessions', 0)} sessions, "
            f"{result.get('turns', 0)} turns, "
            f"{result.get('events', 0)} events"
        )
        if result.get("jobs_pending"):
            print(f"  pending:  {result['jobs_pending']} jobs")


def cmd_projects(args):
    from opencontext.api import projects
    items = projects()
    if not items:
        print("No projects found. Run: oc sync")
        return
    for p in items:
        brief_mark = "+" if p["has_brief"] else "-"
        print(
            f"  [{brief_mark}] {p['name']:20s}  "
            f"{p['sessions']:3d} sessions  {p['turns']:4d} turns  "
            f"{p['last_activity'][:10] if p['last_activity'] else '?':10s}  "
            f"{p['workspace']}"
        )
    print(f"\n  [{len(items)} projects, + = has brief, - = no brief]")


def cmd_brief(args):
    from opencontext.api import brief
    positional = [a for a in args if not a.startswith("-")]
    if not positional:
        _err("Usage: oc brief <workspace> [--top N] [--generate]")

    workspace = positional[0]
    top_n_str = _get_opt(args, "--top")
    top_n = int(top_n_str) if top_n_str else None
    generate = "--generate" in args

    # Force generation if --generate or --top given
    if generate and top_n is None:
        top_n = 15

    print(f"Loading brief for {workspace}...", file=sys.stderr)
    result = brief(workspace, top_n=top_n)

    if "error" in result:
        _err(result["error"])

    print(f"  [{result.get('mode', '?')}] {result.get('path', '')}", file=sys.stderr)
    # Output the brief content directly (markdown, not JSON)
    print(result["content"])


def cmd_discover(args):
    from opencontext.api import discover
    project = _get_opt(args, "--project")
    _json_out(discover(project=project))


def cmd_sessions(args):
    from opencontext.api import sessions
    workspace = _get_opt(args, "--workspace")
    _json_out(sessions(workspace=workspace))


def cmd_show(args):
    from opencontext.api import show
    if not args:
        _err("Usage: oc show <session_id>")
    _json_out(show(args[0]))


def cmd_import(args):
    from opencontext.api import import_session
    if not args:
        _err("Usage: oc import <session_file> [--force]")
    force = "--force" in args
    path = [a for a in args if not a.startswith("-")][0]
    _json_out(import_session(path, force=force))


def cmd_search(args):
    from opencontext.api import search
    if not args:
        _err("Usage: oc search <query> [-t TYPE] [-l LIMIT]")

    query = args[0]
    search_type = _get_opt(args[1:], "-t") or _get_opt(args[1:], "--type") or "all"
    limit_str = _get_opt(args[1:], "-l") or _get_opt(args[1:], "--limit") or "20"
    _json_out(search(query, search_type=search_type, limit=int(limit_str)))


def cmd_events(args):
    from opencontext.api import events
    limit_str = _get_opt(args, "--limit") or "50"
    _json_out(events(limit=int(limit_str)))


def cmd_event(args):
    from opencontext.api import event
    if not args:
        _err("Usage: oc event <event_id>")
    _json_out(event(args[0]))


def cmd_agents(args):
    from opencontext.api import agents
    _json_out(agents())


def cmd_process(args):
    from opencontext.api import process
    max_str = _get_opt(args, "--max") or "50"
    _json_out(process(max_jobs=int(max_str)))


COMMANDS = {
    "init": cmd_init,
    "sync": cmd_sync,
    "status": cmd_status,
    "projects": cmd_projects,
    "brief": cmd_brief,
    "discover": cmd_discover,
    "sessions": cmd_sessions,
    "show": cmd_show,
    "import": cmd_import,
    "search": cmd_search,
    "events": cmd_events,
    "event": cmd_event,
    "agents": cmd_agents,
    "process": cmd_process,
}


def _get_opt(args, flag):
    """Extract value after a flag from args list."""
    if flag in args:
        idx = args.index(flag)
        if idx + 1 < len(args):
            return args[idx + 1]
    return None


def _err(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__.strip())
        sys.exit(0)

    cmd = sys.argv[1]
    handler = COMMANDS.get(cmd)
    if not handler:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(f"Available: {', '.join(COMMANDS.keys())}", file=sys.stderr)
        sys.exit(1)

    handler(sys.argv[2:])


if __name__ == "__main__":
    main()
