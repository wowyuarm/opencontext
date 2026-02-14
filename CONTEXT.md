# OpenContext — Project Consensus & Architecture

> This document captures key decisions and architecture for any agent working on this project.

## What is OpenContext

OpenContext is a **project knowledge generator** for AI assistants. It discovers, parses, and summarizes Claude Code sessions, synthesizes them into **Project Briefs** — auto-generated knowledge documents per project — and exposes them through a skill interface.

**Core value**: An AI assistant can instantly understand any project — its purpose, architecture, decisions, progress, and open threads — without manually exploring codebases. The assistant reads the Brief, then delegates actual coding to agents.

**Design philosophy**: Brief is the product. Code is the pipeline. Skill is the interface.

## Architecture

```
Session JSONL files           ← Source material (Claude Code)
    ↓ oc sync
SQLite database               ← Structured store (sessions, turns, jobs)
    ↓ oc brief (Map-Reduce)
Project Briefs                ← The core product (~/.opencontext/briefs/)
    ↓ Skill (progressive disclosure)
AI Assistant                 ← Reads briefs, delegates to coding agents
```

### Data Flow for Brief Generation

```
┌── Stable Foundation ──┐    ┌── Dynamic Knowledge ──────┐
│ README.md, CLAUDE.md  │    │ Sessions (ranked by turns) │
│ AGENTS.md, docs/      │    │ user selects budget        │
└────────┬──────────────┘    └──────────┬────────────────┘
         │                              │
         │              Map (parallel, per session)
         │              LLM extracts: decisions, solved,
         │              features, tech_changes, open_threads
         │                              │
         ▼                              ▼
    ┌──────────────────────────────────────┐
    │ Reduce (single LLM call)             │
    │ docs + all extractions → Brief       │
    └───────────────┬──────────────────────┘
                    ▼
    ~/.opencontext/briefs/<project>.md
```

### Progressive Disclosure Levels

```
Level 0: oc projects      → Project list + one-liner
Level 1: oc brief <path>  → Full Project Brief (primary)
Level 2: oc sessions      → Session list (drill down)
Level 3: oc show <id>     → Turn details (deep dive)
Level 4: oc search        → Cross-project search
```

## Module Structure

```
opencontext/
├── core/
│   ├── config.py      Configuration (YAML + env vars + api_key)
│   ├── db.py          SQLite (schema, CRUD, search, jobs)
│   └── models.py      Data models (Session, Turn, Event, Job, AgentInfo)
├── ingest/
│   ├── discovery.py   Find session files on disk
│   ├── parser.py      Parse JSONL → turns (Claude Code)
│   ├── importer.py    Import sessions + enqueue summary jobs
│   └── scanner.py     Scan project docs (README, CLAUDE.md, etc.)
├── summarize/
│   ├── llm.py         LLM calls via litellm (JSON + text modes)
│   ├── pipeline.py    Turn/session/event summarization
│   └── brief.py       Project Brief: extract → synthesize → update
├── api.py             Public API — JSON-serializable functions
├── cli.py             CLI router (`oc` entrypoint)
└── worker.py          Background job processor

scripts/oc              Standalone script
opencontext-skill/      Skill for assistants (SKILL.md)
```

## Key Decisions

### 1. Brief as core product
- Sessions are raw material. Briefs are the product.
- An assistant reads the Brief, not raw sessions.
- Progressive disclosure: Brief → sessions → turns → raw content.

### 2. Map-Reduce for synthesis
- Map: extract structured facts per session (parallel, bounded input)
- Reduce: synthesize all facts + project docs into one Brief
- Incremental: new sessions append to existing Brief

### 3. litellm for model routing
- Any provider: `deepseek/deepseek-chat`, `anthropic/claude-*`, `openai/gpt-*`, etc.
- Config supports `api_key` field — auto-injected into correct env var
- No provider-specific SDK dependency

### 4. Claude Code only (for now)
- Only Claude Code JSONL format is supported
- Codex/Gemini parsers removed — will add when formats are validated

### 5. Script-based agent interface
- All functionality via `oc` CLI (JSON/markdown to stdout)
- Any agent calls scripts — no SDK dependency
- Skill (SKILL.md) teaches assistants the workflow

### 6. User-controlled LLM budget
- `--top N` controls how many sessions to process
- Sessions ranked by turn count (more turns = more substantive)
- `--no-llm` for import-only mode

## Configuration

```yaml
# ~/.opencontext/config.yaml
llm_model: "deepseek/deepseek-chat"
api_key: "sk-..."   # or use env vars (DEEPSEEK_API_KEY, etc.)
auto_detect_claude: true
auto_detect_codex: true
auto_detect_gemini: true
```

## CLI Commands

```
oc init                  Initialize config + database
oc sync [--no-llm]       Discover + import + summarize
oc status                Config diagnostics
oc projects              List projects with brief status
oc brief <path> [--top N] Get or generate Project Brief
oc sessions              List imported sessions
oc show <id>             Show session detail
oc search <query>        Search across all data
oc process               Run pending summary jobs
```
