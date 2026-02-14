# OpenContext

Project Knowledge Generator for AI Assistants (e.g., Your OpenClaw Bot, Digital Assistant, etc.)

OpenContext discovers and parses your Claude Code sessions, then synthesizes them into **Project Briefs** — auto-generated knowledge documents that capture what each project is, key decisions, current state, and recent progress.

## Why

Every time an AI assistant starts working with you, it knows nothing about your projects. OpenContext fixes this — it generates per-project knowledge documents so any assistant can instantly understand your project history, decisions, and current state.

## Quick Start

```bash
# Install
cd ~/projects/opencontext
pip install -e .

# Initialize
oc init

# Edit config: set your LLM provider and API key
vim ~/.opencontext/config.yaml

# Import all sessions + generate summaries
oc sync

# See all your projects
oc projects

# Generate a Project Brief
oc brief /home/yu/projects/my-project
```

## Configuration

```yaml
# ~/.opencontext/config.yaml
llm_model: "deepseek/deepseek-chat"    # or anthropic/claude-*, openai/gpt-*, etc.
api_key: "sk-..."                       # or export DEEPSEEK_API_KEY, etc.
```

Uses [litellm](https://github.com/BerriAI/litellm) — any provider works.

## Commands

| Command | Purpose |
|---------|---------|
| `oc init` | Initialize config and database |
| `oc sync` | Discover + import + summarize sessions |
| `oc status` | Config and database diagnostics |
| `oc projects` | List all projects with brief status |
| `oc brief <workspace>` | Get or generate Project Brief |
| `oc brief <ws> --generate` | Force regenerate brief |
| `oc brief <ws> --top N` | Generate from top N sessions |
| `oc sessions` | List imported sessions |
| `oc show <id>` | Show session with all turns |
| `oc search <query>` | Search across all context |
| `oc process` | Run pending LLM summarization jobs |

## How It Works

```
Session JSONL files           ← Source (Claude Code)
    ↓ oc sync
SQLite database               ← Structured store
    ↓ oc brief (Map-Reduce)
Project Briefs                ← The product (~/.opencontext/briefs/)
    ↓ Skill
AI Assistant                  ← Reads briefs, understands projects
```

### Brief Generation (Map-Reduce)

1. **Scan** project docs (README.md, CLAUDE.md, etc.) for stable foundation
2. **Map** (parallel): extract structured facts from each session via LLM
3. **Reduce** (single call): synthesize docs + facts into a Project Brief
4. **Cache**: brief stored as markdown, regenerated on demand

### Progressive Disclosure

```
oc projects          → all projects at a glance
oc brief <workspace> → full project knowledge
oc sessions ...      → drill into session list
oc show <id>         → specific session turns
oc search <query>    → cross-project search
```

## Agent Skill

Install the skill for Claude Code:

```bash
ln -s ~/projects/opencontext/opencontext-skill ~/.claude/skills/opencontext
```

The skill teaches an AI assistant to use OpenContext's progressive disclosure workflow — brief first, drill down as needed.

## Project Structure

```
opencontext/
├── core/           Config, SQLite database, data models
├── ingest/         Session discovery, JSONL parsing (Claude Code), project doc scanning
├── summarize/      LLM client, summarization pipeline, Brief generation
├── api.py          Public API (JSON-serializable)
├── cli.py          CLI router
└── worker.py       Background job processor
```

## License

MIT
