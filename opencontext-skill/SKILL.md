---
name: opencontext
description: Project knowledge and context for any workspace the user has worked on. Use when: (1) user mentions a project or wants to work on one — load its brief, (2) starting a coding collaboration — understand the project before delegating, (3) user asks "what projects do I have" or "what's the status of X", (4) after completing work — update the brief with what was done, (5) first-time setup — guide user through OpenContext configuration. Requires the `oc` CLI.
requires_bins: ["oc"]
---

# OpenContext

Project knowledge middleware. Maintains **Project Briefs** — auto-generated knowledge documents per workspace that capture purpose, architecture, decisions, progress, and open threads.

> Currently supports **Claude Code sessions** only.

**First-time setup?** See [setup.md](references/setup.md).

## When This Skill Activates

Use OpenContext whenever:
- The user mentions a **project** or wants to work on one → read the brief first
- Starting **any coding collaboration** → understand context before writing code
- The user asks "what projects do I have" or "what's the status of X"
- After completing **significant work** → update the brief
- A session has gone on for a while → check if sync is needed

## The Knowledge Loop

This is the core workflow. Repeat it naturally as you collaborate with the user.

### Step 1: Check Context

Before working on a project, always check the brief status:

```bash
oc brief <workspace> --status       # JSON: freshness, new sessions/turns since brief
```

**Act on the recommendation:**
- `"missing"` → no brief exists. Run `oc sync` then `oc brief <workspace> --generate`
- `"stale"` → new sessions since brief. Run `oc sync`, then either:
  - Edit the brief directly (preferred for small updates)
  - Run `oc brief <workspace> --generate` (for major catch-up)
- `"fresh"` → proceed directly

Then read the brief:

```bash
oc brief <workspace>                # Markdown output
```

### Step 2: Collaborate

Use the brief's knowledge to guide your work:
- **Architecture** section tells you where things live
- **Key Decisions** tells you what patterns to follow
- **Open Threads** tells you what's unresolved

Work with the user normally. The brief gives you a head start, not a constraint.

### Step 3: Update Knowledge

After significant work is done:

```bash
oc sync                             # Import new session data into DB
```

Then update the brief. **Direct editing is preferred** — you know exactly what changed:

```
~/.opencontext/briefs/<workspace-slug>.md
```

Edit the relevant sections:
- **Recent Progress** — append what was just done (most recent first)
- **Current State** — update if project maturity changed
- **Open Threads** — close resolved items, add new ones
- **Key Decisions** — add any significant architectural decisions (with `[YYYY-MM-DD]` prefix)

For major rebuilds (after many untracked sessions), regenerate:

```bash
oc brief <workspace> --generate     # Full Map-Reduce from sessions
oc brief <workspace> --top 30       # Use more sessions for richer brief
```

### When to Sync

Run `oc sync` when:
- Starting a new collaboration session (catches up on other sessions)
- After delegating work to Claude Code (captures what was done)
- Before generating or checking brief freshness
- The user explicitly asks to update project data

## Integration with Claude-Collab

If the **claude-collab** skill is available, OpenContext and claude-collab form a powerful loop:

```
OpenContext (understand) → Claude-Collab (delegate) → OpenContext (capture)
```

**Before delegating**: Read the brief, then write a self-contained prompt for `claude_exec.py` that includes relevant context from the brief (architecture, file locations, conventions).

**After delegation completes**: Run `oc sync` to import the Claude Code session that was just created, then update the brief with what was accomplished.

This turns every delegated task into accumulated project knowledge.

## Brief Sections Reference

Each brief has these fixed sections. Know them so you can edit precisely:

| Section | Content | When to Update |
|---------|---------|---------------|
| **Purpose & Value** | What the project is and why | Rarely — only if mission changes |
| **Architecture & Tech Stack** | Components, patterns, deps | When structure changes significantly |
| **Key Decisions** | Decisions with `[date]` prefix and reasoning | After any architectural choice |
| **Current State** | What works, maturity level | After major milestones |
| **Recent Progress** | Latest work, bullet points | After every significant session |
| **Open Threads** | Unresolved issues only | Close resolved, add new |

## Quick Commands

```bash
oc projects                         # List all projects with brief status
oc brief <workspace>                # Read cached brief
oc brief <workspace> --status       # Check freshness (JSON)
oc brief <workspace> --generate     # Force regenerate
oc sync                             # Import + summarize new sessions
oc search <query>                   # Search across all data
```

## Fallbacks

- **Brief is empty** → project has no sessions yet. User needs to work on it first, then `oc sync`.
- **`oc` command fails** → run `oc setup --check` to diagnose. See [setup.md](references/setup.md).
- **Brief feels stale** → run `oc brief <workspace> --status` to check, then sync + update.
- **Need deeper context** → `oc search <query>` or `oc show <session_id>` for raw session data.

## Full CLI Reference

See [commands.md](references/commands.md) for all commands and options.
