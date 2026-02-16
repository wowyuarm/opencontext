# OpenContext — Development Guide

## What This Is

Project knowledge generator for AI assistants. Parses Claude Code sessions, synthesizes **Project Briefs** via Map-Reduce, exposes them through a CLI skill.

**Philosophy**: Brief is the product. Code is the pipeline. Skill is the interface.

## Architecture

```
opencontext/
├── core/           Config (YAML), SQLite DB, dataclass models
├── ingest/         Session discovery, JSONL parsing, project doc scanning
├── summarize/      LLM calls (litellm), summarization pipeline, Brief generation
├── api.py          Public API — all output JSON-serializable
├── cli.py          CLI entrypoint (`oc`)
└── worker.py       Background job processor
```

## Key Conventions

### Code Style
- Python 3.10+, type hints on public APIs
- Dataclasses for models (no Pydantic)
- `sqlite3.Row` — use `key in row.keys()` pattern, never `.get()`
- API keys from env may contain `\r` — always `.strip()`
- litellm model format: `provider/model-name`

### Module Boundaries
- `core/` has zero imports from `ingest/` or `summarize/`
- `ingest/` may import from `core/` only
- `summarize/` may import from `core/` only
- `api.py` orchestrates across modules
- `cli.py` calls `api.py`, never imports module internals directly

### Database
- SQLite with WAL mode, schema version tracked
- All writes via `Database` methods, no raw SQL outside `db.py`
- Thread-safe via `threading.local()` connection pool
- Jobs table for async LLM work (queued → processing → done/failed)

### Testing
- Tests live in `tests/` at project root
- Use `pytest`; `tmp_path` for DB fixtures
- No mocking of SQLite — use real in-memory or temp DBs
- Mock LLM calls (litellm) when testing summarization
- Test file naming: `test_<module>.py`

### CLI
- All commands output to stdout (markdown or JSON)
- Exit codes: 0 success, 1 error
- `oc` entrypoint registered in `pyproject.toml`

## Do NOT

- Add provider-specific SDK dependencies (litellm handles routing)
- Store secrets in code or config templates
- Import across module boundaries except as specified above
- Add ORM layers — raw sqlite3 is intentional
- Over-abstract — prefer direct, readable implementations

## Session Format

Currently only Claude Code JSONL is supported. Parser extracts turns by:
1. Filter user messages (skip tool_result, commands, interrupts)
2. Trace parentUUID chains to find root messages
3. Group by root timestamp → one logical turn
4. Merge API retries (same content within 2min window)

## Quick Reference

```bash
pip install -e .          # Install in dev mode
oc init                   # Initialize config + DB
oc sync                   # Import sessions + summarize
oc brief <workspace>      # Generate/show Project Brief
pytest tests/             # Run tests
```
