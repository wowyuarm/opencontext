# Claude Code Session Format — JSONL Specification

> Research document for OpenContext parser development.
> Based on analysis of real session files from Claude Code v2.1.42+.

## Overview

Claude Code persists conversations as **append-only JSONL files** — one JSON object per line. Each line represents a discrete event in the conversation lifecycle. Files are stored at:

```
~/.claude/projects/{encoded-project-path}/{session-uuid}.jsonl
```

Project paths are URL-path-encoded: `/home/yu/projects/foo` → `-home-yu-projects-foo`.

---

## Message Types

| Type | Purpose | Frequency |
|------|---------|-----------|
| `user` | Human input or tool result delivery | High |
| `assistant` | Claude's response (text, tool calls, thinking) | High |
| `progress` | Real-time tool execution updates | High |
| `system` | System events (compaction, hooks, errors) | Low |
| `file-history-snapshot` | File version tracking checkpoints | Low |
| `queue-operation` | Task queue notifications | Low |

---

## Common Fields (all message types)

```
uuid            string    Unique message ID
parentUuid      string?   Links to parent message (null for root)
sessionId       string    Session UUID
timestamp       string    ISO 8601 (e.g., "2026-02-14T13:18:18.053Z")
type            string    Message type discriminator
cwd             string    Working directory at message time
gitBranch       string    Git branch at message time
version         string    Claude Code version
isSidechain     bool      true if message belongs to a subagent thread
userType        string    "external" (always)
slug            string    URL-safe session name (e.g., "inherited-popping-pike")
```

---

## 1. User Message (`type: "user"`)

### Fields

```
message.role        "user"
message.content     string | array    The user's input
parentUuid          string?           Links to previous assistant message (null for first)
permissionMode      string?           "default" when permissions change
thinkingMetadata    object?           {maxThinkingTokens: int}
toolUseResult       object?           Present when delivering file operation results
sourceToolAssistantUUID  string?      Links to assistant message that triggered tool call
```

### Content Formats

**Simple text input** (human typed):
```json
{
  "message": {
    "role": "user",
    "content": "Fix the login bug"
  }
}
```

**Tool result delivery** (automated after tool execution):
```json
{
  "message": {
    "role": "user",
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_01XYZ...",
        "content": "     1→#!/usr/bin/env python3\n     2→..."
      }
    ]
  }
}
```

### Filtering Rules for Turn Extraction

A user message represents a **human turn** only when:
1. `content` is a plain string (not array with tool_result)
2. Content doesn't start with `<command-name>` or `<local-command-`
3. Content doesn't contain "request interrupted by user"
4. `isMeta` is not true

---

## 2. Assistant Message (`type: "assistant"`)

### Fields

```
message.id          string    Anthropic API message ID (msg_*)
message.model       string    Model used (e.g., "claude-opus-4-6")
message.role        "assistant"
message.content     array     Content blocks (see below)
message.stop_reason string?   null (streaming), "tool_use", "end_turn"
message.usage       object    Token usage statistics
```

### Content Block Types

**Text block:**
```json
{"type": "text", "text": "Here's my analysis..."}
```

**Tool use block:**
```json
{
  "type": "tool_use",
  "id": "toolu_01ABC...",
  "name": "Edit",
  "input": {
    "file_path": "/home/yu/projects/foo/main.py",
    "old_string": "def old():",
    "new_string": "def new():"
  }
}
```

**Thinking block** (extended reasoning):
```json
{
  "type": "thinking",
  "thinking": "Let me analyze this step by step...",
  "signature": "..."
}
```

### Streaming Pattern

Assistant responses are written as **multiple JSONL lines**, each containing one or more content blocks. The `stop_reason` is `null` for intermediate lines. A complete turn's assistant output is the concatenation of all assistant lines between two user messages.

### Tool Input Schemas by Tool Name

| Tool | Key Input Fields |
|------|-----------------|
| `Bash` | `command`, `description`, `timeout` |
| `Read` | `file_path`, `offset`, `limit` |
| `Write` | `file_path`, `content` |
| `Edit` | `file_path`, `old_string`, `new_string`, `replace_all` |
| `Glob` | `pattern`, `path` |
| `Grep` | `pattern`, `path`, `glob`, `output_mode` |
| `Task` | `description`, `prompt`, `subagent_type`, `model` |
| `TaskCreate` | `subject`, `description` |
| `TaskUpdate` | `taskId`, `status` |
| `WebFetch` | `url`, `prompt` |
| `WebSearch` | `query` |
| `Skill` | `skill`, `args` |
| `EnterPlanMode` | (empty) |
| `ExitPlanMode` | (empty) |
| `AskUserQuestion` | `questions` |

### Usage Statistics

```json
"usage": {
  "input_tokens": 3,
  "output_tokens": 9,
  "cache_creation_input_tokens": 12591,
  "cache_read_input_tokens": 10306,
  "cache_creation": {
    "ephemeral_5m_input_tokens": 0,
    "ephemeral_1h_input_tokens": 12591
  },
  "service_tier": "standard"
}
```

---

## 3. Progress Message (`type: "progress"`)

Real-time updates during tool execution. Links to tool via `toolUseID`.

### Subtypes

**bash_progress** — Shell command output:
```json
{
  "data": {
    "type": "bash_progress",
    "output": "latest partial...",
    "fullOutput": "complete accumulated output",
    "elapsedTimeSeconds": 3,
    "totalLines": 42
  }
}
```

**agent_progress** — Subagent execution:
```json
{
  "data": {
    "type": "agent_progress",
    "prompt": "Search for...",
    "agentId": "ab5e7cc",
    "message": { ... }
  }
}
```

**hook_progress** — Hook execution:
```json
{
  "data": {
    "type": "hook_progress",
    "hookEvent": "PostToolUse",
    "hookName": "PostToolUse:Read",
    "command": "callback"
  }
}
```

---

## 4. System Message (`type: "system"`)

### Subtypes

| Subtype | Purpose |
|---------|---------|
| `compact_boundary` | Context window compaction milestone |
| `microcompact_boundary` | Fine-grained token compression |
| `turn_duration` | Turn timing stats |
| `stop_hook_summary` | Hook execution results |
| `api_error` | API communication failure |
| `local_command` | Local command execution |

### Microcompaction Metadata

```json
{
  "subtype": "microcompact_boundary",
  "microcompactMetadata": {
    "trigger": "auto",
    "preTokens": 150000,
    "tokensSaved": 45000,
    "compactedToolIds": ["toolu_01...", "toolu_02..."]
  }
}
```

---

## 5. File History Snapshot (`type: "file-history-snapshot"`)

Tracks file state at message boundaries for undo/restore.

```json
{
  "type": "file-history-snapshot",
  "messageId": "4afcb463-...",
  "isSnapshotUpdate": false,
  "snapshot": {
    "messageId": "4afcb463-...",
    "timestamp": "2026-02-14T13:18:18.138Z",
    "trackedFileBackups": {
      "/home/yu/projects/foo/main.py": {
        "backupFileName": "094de626321f00d3@v1",
        "version": 1,
        "backupTime": "2026-02-14T13:20:00.000Z"
      }
    }
  }
}
```

Backup files stored at: `~/.claude/file-history/{sessionId}/{hash}@v{N}`

---

## 6. Queue Operation (`type: "queue-operation"`)

Task queue lifecycle notifications.

```json
{
  "type": "queue-operation",
  "operation": "enqueue",
  "timestamp": "...",
  "sessionId": "...",
  "content": "<task-id>...</task-id><status>...</status>"
}
```

Operations: `enqueue`, `dequeue`, `complete`.

---

## Conversation Threading Model

Messages form a linked list via `parentUuid`:

```
USER (uuid=A, parentUuid=null)       ← first human message
  └─ ASSISTANT (uuid=B, parentUuid=A)  ← Claude's reply
       └─ USER (uuid=C, parentUuid=B)    ← tool_result delivery
            └─ ASSISTANT (uuid=D, parentUuid=C)
                 └─ USER (uuid=E, parentUuid=D)  ← tool_result
                      └─ ...
                           └─ USER (uuid=X, parentUuid=Y)  ← next human message
```

Within a single "turn" (one human request → full resolution):
- 1 human user message (string content)
- N assistant messages (text + tool calls)
- N-1 user messages (tool results, auto-generated)
- M progress messages (tool execution updates)

### Sidechains

`isSidechain: true` indicates subagent threads spawned by the `Task` tool. These have separate JSONL files at `{sessionId}/subagents/agent-{id}.jsonl`.

---

## .claude Directory Structure

```
~/.claude/
├── CLAUDE.md                      Global user instructions
├── settings.json                  User preferences (model, hooks, etc.)
├── history.jsonl                  Command history
├── projects/                      Per-project session storage
│   └── {encoded-path}/
│       ├── {session-uuid}.jsonl   Session conversation logs
│       ├── {session-uuid}/        Session artifacts
│       │   ├── subagents/         Subagent JSONL files
│       │   └── tool-results/      Cached tool outputs
│       └── memory/
│           └── MEMORY.md          Persistent project notes
├── skills/                        Installed skills (symlinks + dirs)
├── plans/                         Planning documents
├── file-history/                  File version backups
│   └── {sessionId}/{hash}@v{N}
├── debug/                         Session debug logs
├── todos/                         Task tracking per session
├── telemetry/                     Analytics events
├── shell-snapshots/               Bash profile snapshots
├── cache/                         Computed caches
├── plugins/                       Plugin marketplace data
├── paste-cache/                   Clipboard history
├── session-env/                   Session environment metadata
└── tasks/                         Task state files
```

---

## Implications for OpenContext Parser

### What to extract per turn

| Data | Source | Value for Brief |
|------|--------|----------------|
| User intent | user message (string content) | What was requested |
| Assistant text | ALL assistant text blocks in turn range | Reasoning, explanations |
| Tool calls | assistant tool_use blocks | What actions were taken |
| Files touched | Edit/Write tool inputs | What code changed |
| Commands run | Bash tool inputs | Build/test/deploy actions |
| Subagent work | Task tool inputs + agent_progress | Delegated investigations |
| File snapshots | file-history-snapshot | Files changed per turn |

### Extraction priorities

1. **Tool usage summary** — most valuable signal missing today
2. **Full assistant text** — current parser only takes last text block
3. **File modification list** — direct from Edit/Write tool inputs
4. **Bash commands** — test runs, builds, git operations

### What to skip

- `progress` content (redundant with tool_use + tool_result)
- `system` messages (infrastructure, not domain knowledge)
- `thinking` blocks (usually empty, internal reasoning)
- `queue-operation` (infrastructure)
- Tool result content (too verbose, tool_use name+params suffice)
