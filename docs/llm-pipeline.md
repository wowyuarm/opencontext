# OpenContext LLM Pipeline — Prompt Design & Orchestration

> How OpenContext uses LLM calls to transform raw session data into Project Briefs.

## Pipeline Overview

```
Claude Code Session (.jsonl)
    │
    ▼
┌──────────┐
│  Parser  │  No LLM — pure extraction
│          │  Input:  JSONL lines
│          │  Output: ParsedTurn (user_message, assistant_text, tool_uses, files_modified)
└────┬─────┘
     │
     ▼
┌──────────┐
│ Importer │  No LLM — DB writes + job enqueue
│          │  Creates: Turn records, enqueues turn_summary + session_summary jobs
└────┬─────┘
     │
     ▼
┌──────────────────────────────────────┐
│         Worker (Job Processor)       │
│                                      │
│  Per turn:    1 LLM call             │
│    turn_summary → title, description,│
│                   is_continuation,   │
│                   satisfaction       │
│                                      │
│  Per session: 1 LLM call             │
│    session_summary → title, summary  │
│                                      │
│  Total: N + 1 calls per session      │
│  (N = number of turns)               │
└────┬─────────────────────────────────┘
     │
     ▼  (on demand: `oc brief <workspace>`)
┌──────────────────────────────────────┐
│        Brief Generation              │
│                                      │
│  Map:    M LLM calls (parallel)      │
│    session_extract per session →     │
│    {decisions, solved, features,     │
│     tech_changes, open_threads}      │
│                                      │
│  Reduce: 1 LLM call                 │
│    brief_synthesize →                │
│    Markdown Project Brief            │
│                                      │
│  Total: M + 1 calls                  │
│  (M = selected sessions, default 15) │
└──────────────────────────────────────┘
```

## Data Flow Per Stage

### Stage 1: Parser → ParsedTurn

**No LLM.** Pure mechanical extraction from JSONL.

```
Input:  ~/.claude/projects/{project}/{session}.jsonl
Output: List[ParsedTurn]
```

Each ParsedTurn contains:
| Field | Source | Example |
|-------|--------|---------|
| `user_message` | User message with string content | "Fix the login bug" |
| `assistant_text` | All assistant text blocks merged | "I'll fix the JWT validation..." |
| `tool_uses` | From tool_use content blocks | `[{name: "Edit", file_path: "/src/auth.py"}]` |
| `files_modified` | From Edit/Write tool inputs | `["/src/auth.py", "/tests/test_auth.py"]` |
| `content_hash` | MD5 of raw JSONL in turn range | Deduplication key |

### Stage 2: Importer → DB + Jobs

**No LLM.** Stores turns and enqueues jobs.

- Creates `Turn` record with tool_summary and files_modified as JSON strings
- Enqueues `turn_summary` job with full payload (user_message, assistant_summary, tool_uses, files_modified)
- Enqueues `session_summary` job (priority=1, runs after turn jobs)

### Stage 3: Worker — Turn Summary

**1 LLM call per turn.** Merged call replaces what was previously 2 separate calls.

```
Task:   turn_summary
Input:  {user_message, assistant_summary, tools_used?, files_modified?}
Output: {title, description, is_continuation, satisfaction}
```

**Prompt design:**
- System prompt establishes context: "AI-assisted coding session"
- Explains each input field and what to extract
- Includes a concrete JSON example for format stability
- Defines satisfaction scale (good/fine/bad) with behavioral anchors
- No truncation on input — trusts model to handle full context

**Why merged:** Previously `turn_summary` and `metadata` were separate calls with identical input. Merging halves the call count with no quality loss.

### Stage 4: Worker — Session Summary

**1 LLM call per session.**

```
Task:   session_summary
Input:  {turns: [{turn_number, title, description, user_message, tools_used?, files_modified?}]}
Output: {title, summary}
```

**Prompt design:**
- Asks for narrative arc, not turn-by-turn recap
- Includes tool/file data so the model understands concrete actions
- Uses max_tokens=2048 for richer summaries
- Includes example output for format consistency

### Stage 5: Brief Generation — Map (Session Extract)

**1 LLM call per session, parallel (max 4 workers).**

```
Task:   session_extract
Input:  {session_title, session_summary, workspace, date, turns: [{title, description, user, assistant, tools_used?, files_modified?}]}
Output: {decisions, solved, features, tech_changes, open_threads}
```

**Prompt design:**
- Extracts 5 structured categories of knowledge
- Grounds tool interpretation: "Edit/Write = code changed, Bash = commands run"
- Requires ALL fields present (even if empty) for reliable JSON parsing
- "Extract ONLY what is clearly present" prevents hallucination
- "Focus on OUTCOMES, not intentions" filters out unrealized plans

**Key constraint:** `open_threads` explicitly excludes problems that were raised AND solved in the same session. This prevents the brief from accumulating resolved issues.

### Stage 6: Brief Generation — Reduce (Synthesis)

**1 LLM call, produces the final Brief.**

```
Task:   brief_synthesize
Input:  Markdown document with:
        - Project documentation (README, CLAUDE.md — stable foundation)
        - Tech stack indicators (pyproject.toml, package.json)
        - Extracted knowledge from M sessions (dynamic progress)
Output: Markdown Project Brief with fixed sections
```

**Prompt design:**
- Prescribes exact section structure (Purpose, Architecture, Decisions, State, Progress, Threads)
- Cross-session deduplication instruction: "Resolve contradictions — later sessions override earlier ones"
- Open Threads resolution: "Cross-reference solved[] and features[] across ALL sessions"
- Dynamic max_tokens: 4096 for ≤10 sessions, 8192 for more

### Stage 7: Brief Update (Incremental)

**1 LLM call, appends new session facts to existing brief.**

```
Task:   brief_update
Input:  Current brief markdown + new session extraction JSON
Output: Updated brief markdown
```

**Prompt design:**
- "Preserve all existing content that is still accurate"
- "RESOLVE Open Threads that the new session's solved[] or features[] address"
- Chronological ordering for decisions, reverse-chronological for progress

## Token Economics

For a project with 5 sessions averaging 10 turns each:

| Stage | Calls | When |
|-------|-------|------|
| Turn summary | 50 | `oc sync` |
| Session summary | 5 | `oc sync` |
| Session extract | 5 | `oc brief --generate` |
| Brief synthesize | 1 | `oc brief --generate` |
| **Total** | **61** | |

Incremental update (`oc brief --update`): 1 session_extract + 1 brief_update = **2 calls**.

## Prompt Engineering Principles

1. **Domain anchoring**: Every prompt establishes "AI-assisted coding session" context
2. **Structural examples**: JSON output format shown with realistic examples
3. **Behavioral anchors**: Satisfaction scale defined by user behavior, not task outcome
4. **Anti-hallucination**: "Extract ONLY what is clearly present"
5. **Outcome focus**: "Focus on OUTCOMES, not intentions" — filters unrealized plans
6. **Cross-reference instructions**: Open threads checked against solved/features across sessions
7. **No arbitrary truncation**: Full context sent to model, trusting model capacity
8. **All fields required**: JSON output schema includes all fields (empty arrays OK) for parsing reliability

## Key Files

| File | Role |
|------|------|
| `opencontext/summarize/llm.py` | TASK_PROMPTS dict + call_llm / call_llm_text |
| `opencontext/summarize/pipeline.py` | Turn + session summarization orchestration |
| `opencontext/summarize/brief.py` | Map-Reduce brief generation + incremental update |
| `opencontext/worker.py` | Job processor — dispatches to pipeline functions |
| `opencontext/ingest/parser.py` | JSONL parsing — feeds all downstream stages |
| `opencontext/ingest/importer.py` | DB writes + job enqueue |
