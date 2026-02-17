# OpenContext CLI Reference

All commands output JSON to stdout (except `brief` which outputs markdown by default).
Diagnostic messages go to stderr.

## Setup

```bash
oc setup --check              # Environment state (JSON): initialized, has_api_key, project/session counts
oc setup --init               # Create config + database (same as `oc init`)
oc setup --discover           # Scan disk for importable projects (JSON list)
oc setup --config KEY VALUE   # Set a config value (e.g., api_key, llm_model)
```

## Projects & Briefs

```bash
oc projects                         # List all projects with brief status
oc brief <workspace>                # Read cached brief (markdown)
oc brief <workspace> --generate     # Force regenerate from sessions
oc brief <workspace> --top N        # Generate from top N sessions
oc brief <workspace> --json         # Output as structured JSON (includes metadata)
oc brief <workspace> --status       # Check brief freshness (JSON): recommendation, sessions/turns since brief
```

## Data Import

```bash
oc sync                             # Discover + import + summarize all
oc sync --project <path>            # Sync only one project
oc sync --no-llm                    # Import only, skip LLM summarization
```

## Search

```bash
oc search <query>                   # Search events + turns + sessions
oc search <query> -t turn           # Search turn titles only
oc search <query> -t content        # Deep search raw dialogue
oc search <query> -t event          # Search events only
oc search <query> -l 50             # Limit results (default 20)
```

## Drill-Down (rarely needed)

```bash
oc sessions --workspace <path>      # List sessions for a project
oc show <session_id>                # Show all turns in a session
oc discover --project <path>        # Find session files on disk
oc import <file> [--force]          # Import a single session file
```

## Diagnostics

```bash
oc status                           # Config + DB diagnostics
oc process --max N                  # Run pending summary jobs manually
oc events --limit N                 # List events
oc agents                           # List agent profiles
```
