---
name: opencontext
description: Project knowledge and context for any workspace the user has worked on. Use when: (1) user mentions a project or wants to work on one — load its brief first, (2) starting a coding collaboration — understand the project before delegating to Claude Code, (3) user asks "what projects do I have" or "what's the status of X", (4) after completing work on a project — sync to update knowledge, (5) first-time setup — guide user through configuration. Requires the `oc` CLI (pip install opencontext).
requires_bins: ["oc"]
---

# OpenContext

Project knowledge middleware. Generates and maintains **Project Briefs** —
auto-generated knowledge documents per workspace.

## Setup (First-Time)

Check if OpenContext is ready:

```bash
oc setup --check
```

If not initialized:

```bash
oc setup --init
oc setup --config api_key <USER_API_KEY>
oc setup --config llm_model deepseek/deepseek-chat   # or any litellm model
oc setup --discover    # see what projects are available
oc sync                # import sessions and generate summaries
```

Minimum user input needed: API key + confirm project list.

## Core Workflow

### 1. Understand the Project (Read Brief)

```bash
oc brief <workspace>
```

The brief tells you: what the project is, its architecture, key decisions,
current state, and open threads. Read this before doing any work on a project.

### 2. Delegate Tasks (with claude-collab)

After reading the brief, you understand the project. Give Claude Code
directional instructions:

- What to do and in which project
- 1-2 key anchors (architecture points, relevant modules)
- Claude Code explores the code and plans on its own

### 3. Update Knowledge (Sync)

After work is completed:

```bash
oc sync --project <path>
oc brief <workspace> --generate    # refresh the brief
```

## Quick Reference

```bash
oc projects                        # list all projects
oc brief <workspace>               # read Project Brief
oc brief <workspace> --generate    # regenerate brief
oc brief <workspace> --json        # structured JSON output
oc sync                            # import new sessions + summarize
oc search <query>                  # cross-project search
oc setup --check                   # environment status
```

## Fallbacks

- **Brief is empty** → project may have no sessions yet; suggest user works in that project first
- **`oc` command fails** → run `oc setup --check` to diagnose; verify API key and DB state
- **Brief is stale** → check the footer timestamp; use `--generate` to refresh
- **No projects found** → run `oc setup --discover` then `oc sync`

## Details

For full CLI reference, see [commands.md](references/commands.md).
