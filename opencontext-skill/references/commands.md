# OpenContext CLI Reference

## Setup & Configuration

```bash
oc setup                         # Check environment state (JSON)
oc setup --check                 # Same as above
oc setup --init                  # Initialize config + DB (JSON)
oc setup --discover              # Scan for importable projects (JSON)
oc setup --config KEY VALUE      # Set a config value (e.g., api_key, llm_model)
```

## Overview

```bash
oc projects                      # List all projects with brief status
oc status                        # Config and database diagnostics
```

## Project Brief

```bash
oc brief <workspace>             # Read existing brief (cached, markdown)
oc brief <workspace> --generate  # Force regenerate from sessions
oc brief <workspace> --top 10    # Generate from top N sessions
oc brief <workspace> --json      # Output as structured JSON with metadata
```

## Sync & Import

```bash
oc sync                          # Discover + import + summarize all
oc sync --project PATH           # Sync only sessions for a specific project
oc sync --no-llm                 # Import only, skip LLM summarization
oc import <session_file>         # Import a single session file
oc import <session_file> --force # Re-import (overwrite existing)
```

## Session Exploration

```bash
oc sessions                      # List all imported sessions
oc sessions --workspace PATH     # Filter by workspace path
oc show <session_id>             # Show session details with all turns
```

## Search

```bash
oc search <query>                # Search events + sessions + turns
oc search <query> -t turn        # Search turn titles only
oc search <query> -t content     # Deep search raw dialogue
oc search <query> -l 50          # Limit results
```

## Discovery & Diagnostics

```bash
oc discover                      # Find session files on disk (not yet imported)
oc discover --project PATH       # Filter by project path
oc events                        # List events
oc event <event_id>              # Show event details
oc agents                        # List agent profiles
oc process                       # Run pending summary jobs
oc process --max 100             # Process up to N jobs
```

## Output Conventions

- **Briefs** output as markdown by default, JSON with `--json`
- **All other commands** output JSON to stdout
- **Progress/status messages** go to stderr
- Exit codes: 0 = success, 1 = error
