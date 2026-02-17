"""
LLM client — call language models via litellm.

litellm handles provider routing based on model string:
    "anthropic/claude-haiku-4-5"  -> Anthropic API
    "openai/gpt-4o-mini"         -> OpenAI API
    "deepseek/deepseek-chat"     -> DeepSeek API
    etc.

Environment variables (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.)
are picked up automatically by litellm.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Task Prompts ──────────────────────────────────────────────────────────────

TASK_PROMPTS: Dict[str, str] = {
    "turn_summary": (
        "You are summarizing a single turn in an AI-assisted coding session "
        "(human developer + AI coding assistant working together).\n\n"
        "You will receive a JSON object with:\n"
        "- user_message: what the developer asked or instructed\n"
        "- assistant_summary: the AI assistant's textual response\n"
        "- tools_used (optional): tool calls made — Read/Edit/Write for file ops, "
        "Bash for commands, Grep/Glob for search, Task for subagent delegation\n"
        "- files_modified (optional): file paths that were edited or created\n\n"
        "Produce a JSON object with these fields:\n"
        "- title: concise action phrase (max 80 chars), e.g. \"Fix auth middleware token validation\"\n"
        "- description: 1-3 sentences capturing what was done and why. "
        "Mention specific files or commands if they clarify the work.\n"
        "- is_continuation: true if this turn continues/debugs/fixes the PREVIOUS turn's task, "
        "false if it starts a new topic\n"
        "- satisfaction: \"good\" if user is clearly satisfied or moving forward, "
        "\"fine\" if neutral or mixed, \"bad\" if user reports failure or frustration\n\n"
        "Example output:\n"
        "{\n"
        '  "title": "Add user authentication middleware",\n'
        '  "description": "Implemented JWT-based auth middleware in src/middleware/auth.py '
        'and integrated it into the Express router. Added token validation and 401 responses.",\n'
        '  "is_continuation": false,\n'
        '  "satisfaction": "good"\n'
        "}\n\n"
        "Rules:\n"
        "- Title should be an action phrase (imperative or past tense), not a question\n"
        "- Description should focus on OUTCOMES, not process\n"
        "- Infer satisfaction from the user's tone and follow-up, not from the task itself\n"
        "- Output STRICT JSON only, no markdown fences"
    ),
    "session_summary": (
        "You are summarizing a complete coding session — a sequence of conversation turns "
        "between a developer and an AI coding assistant.\n\n"
        "You will receive a JSON object with a turns array. Each turn has:\n"
        "- turn_number, title, description: what happened in this turn\n"
        "- user_message: the developer's original request\n"
        "- tools_used (optional): tool calls made in this turn\n"
        "- files_modified (optional): files changed in this turn\n\n"
        "Produce a JSON object with:\n"
        "- title: session-level goal in max 80 chars, e.g. \"Implement parser enhancements and test suite\"\n"
        "- summary: 2-5 sentences covering the arc of work — what was the goal, what was accomplished, "
        "what remains open\n\n"
        "Example output:\n"
        "{\n"
        '  "title": "Refactor database layer and add migration support",\n'
        '  "summary": "Refactored the SQLite database module to support schema migrations. '
        "Added a version tracking table and migration runner. Fixed a thread-safety issue "
        'in the connection pool. Migration tests pass but rollback support is still pending."\n'
        "}\n\n"
        "Rules:\n"
        "- Focus on the overall narrative, not turn-by-turn recap\n"
        "- Mention concrete outcomes (files, features, fixes) over process\n"
        "- Note unresolved issues if any turns ended with problems\n"
        "- Output STRICT JSON only, no markdown fences"
    ),
    "session_extract": (
        "You are extracting structured knowledge from a coding session for a project knowledge base.\n\n"
        "You will receive session metadata and an array of turns, each with:\n"
        "- User requests, assistant responses, tool usage, and file changes\n\n"
        "Extract ONLY facts clearly supported by the data. Focus on OUTCOMES (what was actually done), "
        "not intentions that weren't followed through.\n\n"
        "Use tools_used and files_modified to identify concrete actions:\n"
        "- Edit/Write calls = code was changed\n"
        "- Bash calls = commands were run (tests, builds, deployments)\n"
        "- Task calls = work was delegated to subagents\n\n"
        "Output a JSON object with ALL of these fields (use empty arrays if nothing applies):\n"
        "{\n"
        '  "decisions": [{"what": "string", "why": "string"}],\n'
        '  "solved": ["string"],\n'
        '  "features": ["string"],\n'
        '  "tech_changes": ["string"],\n'
        '  "open_threads": ["string"]\n'
        "}\n\n"
        "Field definitions:\n"
        "- decisions: architectural or design choices with reasoning. "
        "Include WHAT was decided and WHY.\n"
        "- solved: bugs fixed, issues resolved — only if ACTUALLY resolved (not just discussed)\n"
        "- features: new functionality added or significantly modified\n"
        "- tech_changes: libraries, tools, config, or patterns introduced/removed/changed\n"
        "- open_threads: things explicitly left unfinished at session END. "
        "Do NOT include problems that were raised AND solved in the same session.\n\n"
        "Rules:\n"
        "- Each item should be a single concise sentence\n"
        "- Include all fields even if empty (use [])\n"
        "- Output STRICT JSON only, no markdown fences"
    ),
    "brief_synthesize": (
        "You are generating a Project Brief — a living knowledge document that captures "
        "everything a technical leader needs to know about a software project.\n\n"
        "You will receive:\n"
        "1. Project documentation (README, CLAUDE.md, etc.) — stable foundation\n"
        "2. Extracted knowledge from coding sessions — dynamic progress\n"
        "3. Tech stack indicators (package manifests, etc.)\n\n"
        "Generate a markdown document with EXACTLY these sections:\n\n"
        "# Project: <name>\n\n"
        "## Purpose & Value\n"
        "What this project is and why it exists. 2-3 sentences max.\n\n"
        "## Architecture & Tech Stack\n"
        "Key components, module boundaries, patterns, and dependencies. Be specific about "
        "directory structure if the data supports it.\n\n"
        "## Key Decisions\n"
        "Important decisions with reasoning. Use bullet points prefixed with date:\n"
        "- [YYYY-MM-DD] Decision description — reasoning\n"
        "Group decisions from the same date together.\n\n"
        "## Current State\n"
        "What works, what's stable, overall maturity. 2-3 sentences.\n\n"
        "## Recent Progress\n"
        "Latest work done, features added, bugs fixed. Bullet points, most recent first.\n\n"
        "## Open Threads\n"
        "Genuinely unresolved issues. Cross-reference with solved[] and features[] across "
        "ALL sessions — if something was raised in session A and solved in session B, "
        "it is NOT an open thread.\n\n"
        "Rules:\n"
        "- Be factual. Only include what the data supports.\n"
        "- Synthesize across sessions — don't just list per-session facts.\n"
        "- Resolve contradictions: later sessions override earlier ones.\n"
        "- Output ONLY the markdown document, no wrapping fences."
    ),
    "brief_update": (
        "You are updating an existing Project Brief with new information "
        "from a recent coding session.\n\n"
        "You will receive:\n"
        "1. The current Project Brief (markdown)\n"
        "2. Extracted facts from a new session\n\n"
        "Return the UPDATED brief. Rules:\n"
        "- Preserve all existing content that is still accurate\n"
        "- Add new decisions to Key Decisions (chronologically)\n"
        "- Add new progress to Recent Progress (most recent first)\n"
        "- Update Current State if the new session changes project maturity\n"
        "- RESOLVE Open Threads that the new session's solved[] or features[] address\n"
        "- Add new open threads from the session\n"
        "- Do NOT remove historical decisions or progress\n"
        "- Output ONLY the updated markdown, no wrapping fences."
    ),
    "event_summary": (
        "You are summarizing a development event that spans multiple sessions.\n\n"
        "Your task:\n"
        "1. Generate an EVENT TITLE (max 100 chars).\n"
        "2. Generate an EVENT DESCRIPTION (3-6 sentences) covering what was accomplished.\n\n"
        "Output STRICT JSON only:\n"
        '{"title": "string", "description": "string"}'
    ),
    "agent_description": (
        "You are generating a profile description for an AI coding agent based on its sessions.\n\n"
        "Your task:\n"
        "1. Generate a short TITLE (max 80 chars) for the agent.\n"
        "2. Generate a DESCRIPTION (2-5 sentences) of what this agent has worked on.\n\n"
        "Output STRICT JSON only:\n"
        '{"title": "string", "description": "string"}'
    ),
    "early_title": (
        "Generate a very short title (max 60 chars) for a coding session "
        "based on the user's first prompt. Output STRICT JSON only:\n"
        '{"title": "string"}'
    ),
}


# ── JSON Extraction ───────────────────────────────────────────────────────────

def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON object from LLM response, handling markdown fences."""
    if not text:
        return None

    s = text.strip()

    # Remove markdown code fences
    if "```json" in s:
        start = s.find("```json") + 7
        end = s.find("```", start)
        if end != -1:
            s = s[start:end].strip()
    elif "```" in s:
        start = s.find("```") + 3
        end = s.find("```", start)
        if end != -1:
            s = s[start:end].strip()

    try:
        return json.loads(s, strict=False)
    except json.JSONDecodeError:
        return None


# ── LLM Call ──────────────────────────────────────────────────────────────────

def call_llm(
    task: str,
    payload: Dict[str, Any],
    *,
    custom_prompt: Optional[str] = None,
    model: Optional[str] = None,
    timeout: float = 60.0,
    max_tokens: int = 1024,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Call LLM via litellm.

    Args:
        task: Task type (must be a key in TASK_PROMPTS)
        payload: Data to send as user message (will be JSON-serialized)
        custom_prompt: Override the default system prompt
        model: Override the configured model
        timeout: Request timeout in seconds
        max_tokens: Max response tokens

    Returns:
        (model_name, result_dict) or (None, None) on failure
    """
    try:
        from litellm import completion
    except ImportError:
        logger.error("litellm not installed. Run: pip install litellm")
        return None, None

    if model is None:
        from ..core.config import Config
        cfg = Config.load()
        model = cfg.llm_model
        cfg.inject_api_key()

    system_prompt = custom_prompt or TASK_PROMPTS.get(task, "")
    if not system_prompt:
        system_prompt = f"Complete the '{task}' task. Output STRICT JSON only."

    user_content = json.dumps(payload, ensure_ascii=False, default=str)

    logger.debug(f"LLM call: task={task} model={model}")
    start = time.time()

    try:
        response = completion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
            timeout=timeout,
        )

        content = response.choices[0].message.content or ""
        model_used = getattr(response, "model", model) or model
        elapsed = time.time() - start

        result = extract_json(content)
        if result is None:
            logger.warning(f"LLM returned non-JSON for task={task}: {content[:200]}")
            return str(model_used), None

        logger.debug(f"LLM success: task={task} model={model_used} elapsed={elapsed:.1f}s")
        return str(model_used), result

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"LLM call failed: task={task} error={e} elapsed={elapsed:.1f}s")
        return None, None


def call_llm_text(
    task: str,
    user_content: str,
    *,
    model: Optional[str] = None,
    timeout: float = 120.0,
    max_tokens: int = 4096,
) -> Optional[str]:
    """Call LLM and return raw text response (for markdown generation).

    Unlike call_llm, this does not JSON-parse the output.
    Used for Brief synthesis and updates.
    """
    try:
        from litellm import completion
    except ImportError:
        logger.error("litellm not installed. Run: pip install litellm")
        return None

    if model is None:
        from ..core.config import Config
        cfg = Config.load()
        model = cfg.llm_model
        cfg.inject_api_key()

    system_prompt = TASK_PROMPTS.get(task, "")
    if not system_prompt:
        return None

    logger.debug(f"LLM text call: task={task} model={model}")
    start = time.time()

    try:
        response = completion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
            timeout=timeout,
        )

        content = response.choices[0].message.content or ""
        elapsed = time.time() - start
        logger.debug(f"LLM text success: task={task} elapsed={elapsed:.1f}s")

        # Strip markdown fences if LLM wraps output
        content = content.strip()
        if content.startswith("```markdown"):
            content = content[len("```markdown"):].strip()
        if content.startswith("```"):
            content = content[3:].strip()
        if content.endswith("```"):
            content = content[:-3].strip()

        return content

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"LLM text call failed: task={task} error={e} elapsed={elapsed:.1f}s")
        return None
