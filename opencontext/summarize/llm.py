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
        "You summarize a single coding conversation turn.\n"
        "Given user messages and assistant replies, produce:\n"
        "1. A concise TITLE (max 80 chars) describing what happened.\n"
        "2. A short DESCRIPTION (1-3 sentences) of the work done.\n\n"
        "Output STRICT JSON only:\n"
        '{"title": "string", "description": "string"}'
    ),
    "metadata": (
        "You are a metadata classifier for AI-assisted coding sessions.\n"
        "Determine two fields for the current turn:\n"
        '1. "is_continuation": true if this turn continues, debugs, or fixes '
        "the previous task. false if it is a new task.\n"
        '2. "satisfaction": "good" when the user is clearly happy or moving on, '
        '"fine" when progress is partial/mixed, "bad" when the user reports '
        "failure or dissatisfaction.\n\n"
        "Rules:\n"
        "- Prioritize the latest user request/feedback for satisfaction.\n"
        '- If uncertain, default to false and "fine".\n'
        "- Respond with JSON ONLY:\n"
        '{"is_continuation": true|false, "satisfaction": "good|fine|bad"}'
    ),
    "session_summary": (
        "You are summarizing a coding session that contains multiple conversation turns.\n\n"
        "Your task:\n"
        "1. Generate a concise SESSION TITLE (max 80 characters).\n"
        "2. Generate a SESSION SUMMARY (2-5 sentences).\n\n"
        "Output STRICT JSON only:\n"
        '{"title": "string", "summary": "string"}\n\n'
        "Rules:\n"
        "- The title should capture the overall goal.\n"
        "- The summary should highlight key accomplishments.\n"
        '- Prefer action-oriented language ("Implement X", "Fix Y").'
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
    "session_extract": (
        "You are extracting structured knowledge from a coding session.\n"
        "Given session info, user messages, and assistant responses, extract key facts.\n\n"
        "Extract ONLY what is clearly present. Do not invent or assume.\n"
        "Focus on OUTCOMES (what was actually done), not just intentions.\n\n"
        "Output STRICT JSON:\n"
        "{\n"
        '  "decisions": [{"what": "string", "why": "string"}],\n'
        '  "solved": ["string"],\n'
        '  "features": ["string"],\n'
        '  "tech_changes": ["string"],\n'
        '  "open_threads": ["string"]\n'
        "}\n\n"
        "Rules:\n"
        "- decisions: architectural or design choices with reasoning\n"
        "- solved: bugs fixed, issues resolved (only if ACTUALLY resolved in this session)\n"
        "- features: new functionality added or significantly modified\n"
        "- tech_changes: libraries, tools, patterns introduced or removed\n"
        "- open_threads: ONLY things explicitly left unfinished at session END.\n"
        "  Do NOT include problems that were raised AND solved in the same session.\n"
        "- Omit empty arrays. Be concise (each item max 1 sentence)."
    ),
    "brief_synthesize": (
        "You are generating a Project Brief — a living document that captures "
        "everything a technical leader needs to know about this software project.\n\n"
        "You will receive:\n"
        "1. Project documentation (README, CLAUDE.md, etc.) — stable foundation\n"
        "2. Extracted knowledge from coding sessions — dynamic progress\n\n"
        "Generate a markdown document with EXACTLY these sections:\n\n"
        "# Project: <name>\n\n"
        "## Purpose & Value\n"
        "What this project is and why it exists (2-3 sentences)\n\n"
        "## Architecture & Tech Stack\n"
        "Key components, patterns, dependencies (concise)\n\n"
        "## Key Decisions\n"
        "Important decisions with reasoning. Use bullet points.\n"
        "Group decisions from the same date together.\n\n"
        "## Current State\n"
        "What works, what's stable, overall maturity (2-3 sentences)\n\n"
        "## Recent Progress\n"
        "Latest work done, features added, bugs fixed. Bullet points.\n\n"
        "## Open Threads\n"
        "ONLY genuinely unresolved issues. If a problem was raised in one session "
        "and solved in a later session, it is NOT an open thread. "
        "Cross-reference solved[] and features[] to remove resolved items.\n\n"
        "Rules:\n"
        "- Be factual. Only include what the data supports.\n"
        "- Use unordered bullet points for all lists.\n"
        "- For Key Decisions, prefix each bullet with date: `- [YYYY-MM-DD] ...`\n"
        "- Group same-date decisions under one date heading.\n"
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
        "- Update Current State if the new session changes it\n"
        "- Add/resolve Open Threads as appropriate\n"
        "- Do NOT remove historical decisions or progress\n"
        "- Output ONLY the updated markdown, no wrapping fences."
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
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Call LLM via litellm.

    Args:
        task: Task type (must be a key in TASK_PROMPTS)
        payload: Data to send as user message (will be JSON-serialized)
        custom_prompt: Override the default system prompt
        model: Override the configured model
        timeout: Request timeout in seconds

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
            max_tokens=1024,
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
