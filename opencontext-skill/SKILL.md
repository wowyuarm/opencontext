---
name: opencontext
description: Access project context — briefs, history, decisions, and progress for any project the user has worked on. Use proactively when historical context would help.
---

# OpenContext Skill

OpenContext generates and maintains **Project Briefs** — auto-generated knowledge documents that capture what each project is, key decisions, current state, and recent progress. As an assistant, you use this to understand projects without manually exploring codebases.

## Core Workflow: Brief First

**Always start with the brief.** It gives you project understanding in seconds.

```bash
# What projects exist?
python3 ~/projects/opencontext/scripts/oc projects

# Read a project's brief (the core document)
python3 ~/projects/opencontext/scripts/oc brief /home/yu/projects/HaL
```

Only drill down into sessions/turns when the brief doesn't have enough detail.

## When to Use

- **Starting work on a project** — read its brief first
- **User references past work** — search for it
- **Understanding why code is written a certain way** — briefs capture decisions
- **Planning next steps** — check open threads in the brief
- **Cross-project awareness** — `oc projects` shows everything

## Commands

### Level 0: Overview
```bash
oc projects                          # List all projects with brief status
```

### Level 1: Project Brief (primary)
```bash
oc brief <workspace>                 # Read existing brief (cached)
oc brief <workspace> --generate      # Force regenerate from sessions
oc brief <workspace> --top 10        # Generate from top 10 sessions
```

### Level 2: Session List
```bash
oc sessions --workspace <path>       # List sessions for a project
```

### Level 3: Session Detail
```bash
oc show <session_id>                 # Show all turns in a session
```

### Level 4: Search (cross-project)
```bash
oc search <query>                    # Search events + sessions + turns
oc search <query> -t turn            # Search turn titles only
oc search <query> -t content         # Deep search raw dialogue
```

### Maintenance
```bash
oc sync                              # Import new sessions + summarize
oc sync --no-llm                     # Import only (no LLM calls)
oc status                            # Config and database diagnostics
```

## Understanding the Brief

A Project Brief contains:

| Section | What it tells you |
|---------|-------------------|
| Purpose & Value | What the project is and why it exists |
| Architecture & Tech Stack | How it's built |
| Key Decisions | Important choices with reasoning (chronological) |
| Current State | What works, overall maturity |
| Recent Progress | Latest work done |
| Open Threads | Unfinished work, known issues |

## Progressive Disclosure

```
oc projects          → quick scan of all projects
    ↓ pick one
oc brief <workspace> → full project understanding
    ↓ need more detail
oc sessions ...      → specific session list
    ↓ drill down
oc show <id>         → individual turns
    ↓ raw search
oc search <query>    → find specific topics
```

## Notes

- **Briefs are cached** — first call generates, subsequent calls return cached
- **Use `--generate` to refresh** a stale brief with latest sessions
- **Local only** — all data in SQLite, no cloud dependency
- **All commands output to stdout** — JSON for structured data, markdown for briefs
