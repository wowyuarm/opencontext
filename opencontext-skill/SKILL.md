---
name: opencontext
description: Project knowledge and context for any workspace the user has worked on. Use when: (1) user mentions a project or wants to work on one — load its brief, (2) starting a coding collaboration — understand the project before delegating, (3) user asks "what projects do I have" or "what's the status of X", (4) after completing work — update the brief with what was done, (5) first-time setup — guide user through OpenContext configuration. Requires the `oc` CLI.
requires_bins: ["oc"]
---

# OpenContext

Project knowledge middleware. Maintains **Project Briefs** — auto-generated knowledge documents per workspace that capture purpose, architecture, decisions, progress, and open threads.

> **Currently supports Claude Code sessions only.** Other AI coding tools are not yet supported.

## Setup (First-Time)

When OpenContext is not yet configured, guide the user through setup:

```bash
oc setup --check                          # Check state: initialized? has_api_key? project_count?
oc setup --init                           # Create config + DB
oc setup --discover                       # Scan disk, list discoverable projects
oc setup --config api_key "sk-..."        # Set API key
oc setup --config llm_model "deepseek/deepseek-chat"  # Set model (litellm format)
oc sync                                   # Import sessions + generate summaries
```

User only needs to provide: API key and confirm which model to use.
Everything else is automatic.

## Core Workflow

### 1. Know What Projects Exist

```bash
oc projects
```

Returns all projects with session counts and brief status (`+` = has brief, `-` = no brief).

### 2. Understand a Project (Read Brief)

```bash
oc brief <workspace>
```

The brief tells you: what the project is, how it's built, key decisions made, current state, recent progress, and open threads. Read it before any project work.

To get structured metadata (generation time, session count):

```bash
oc brief <workspace> --json
```

### 3. Delegate to Claude Code

After reading the brief, you already understand the project. Give Claude Code direction:
- What to do (goal, not detailed spec)
- Where (project path)
- 1-2 key anchors from the brief (architecture points, relevant modules)

Claude Code is smart — it will explore the codebase, plan, and execute autonomously.

### 4. Update the Brief

After work is completed, update the brief directly:

```bash
# Brief files live at:
~/.opencontext/briefs/<workspace-slug>.md
```

Read the brief file, then edit the relevant sections:
- **Recent Progress** — append what was just done
- **Current State** — update if maturity changed
- **Open Threads** — close resolved items, add new ones
- **Key Decisions** — add any significant decisions made

This is faster and more accurate than regenerating — you know exactly what changed.

### 5. Full Regeneration (Occasional)

Only when the brief is severely outdated or doesn't exist:

```bash
oc brief <workspace> --generate           # Regenerate from top 15 sessions
oc brief <workspace> --top 30             # Use more sessions for richer brief
```

This uses LLM (Map-Reduce over sessions) and costs tokens.

### 6. Search (When Brief Isn't Enough)

```bash
oc search <query>                         # Search across all data
oc search <query> -t content              # Deep search raw dialogue
```

## Keeping Knowledge Fresh

After significant work sessions:
1. Run `oc sync` to import new session data into the DB
2. Edit the brief directly with the latest progress

Sync imports raw sessions; brief editing captures the narrative.

## Fallbacks

- **Brief is empty** — project has no sessions yet. Suggest the user works on it first, then `oc sync`.
- **`oc` command fails** — run `oc setup --check` to diagnose (missing API key, no DB, etc).
- **Brief feels stale** — check the footer timestamp. Edit directly or `--generate` to rebuild.

## Full CLI Reference

For all commands and options, see [commands.md](references/commands.md).
Use when you need drill-down commands (`oc sessions`, `oc show`) or diagnostics (`oc status`).
