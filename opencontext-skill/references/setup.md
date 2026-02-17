# OpenContext Setup Guide

First-time setup for the `oc` CLI.

## Quick Setup

```bash
oc init                          # Create config + database
```

Then edit `~/.opencontext/config.yaml`:

```yaml
llm_model: "deepseek/deepseek-chat"    # or anthropic/claude-haiku-4-5-20251001, etc.
api_key: "your-api-key-here"           # or set provider env var (DEEPSEEK_API_KEY, etc.)
```

Then import your first sessions:

```bash
oc sync                          # Discover + import + summarize
oc projects                      # Verify projects were found
```

## Diagnostics

```bash
oc setup --check                 # Check config, API key, DB status
oc status                        # Config + DB diagnostics
```

## Config Options

| Key | Default | Description |
|-----|---------|-------------|
| `llm_model` | `anthropic/claude-haiku-4-5-20251001` | litellm model string (`provider/model`) |
| `api_key` | (empty) | API key for the provider. Alternatively, export the provider's env var directly. |
| `db_path` | `~/.opencontext/db/opencontext.db` | SQLite database location |

## Supported Providers

Any provider supported by [litellm](https://docs.litellm.ai/docs/providers):
- `anthropic/claude-haiku-4-5-20251001`
- `deepseek/deepseek-chat`
- `openai/gpt-5-mini`
- `gemini/gemini-3.0-flash`
- And many more.

## Troubleshooting

- **`oc` command not found**: Run `pip install -e .` from the opencontext repo root.
- **API key errors**: Check `oc setup --check`. Keys from env vars may contain trailing `\r` — the config handles stripping.
- **No sessions found**: OpenContext currently supports Claude Code sessions only. Ensure you have `.claude/projects/` directories with `.jsonl` session files.
