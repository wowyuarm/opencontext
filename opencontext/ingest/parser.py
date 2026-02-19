"""
Session parser — extract turns from Claude Code JSONL session files.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ParsedTurn:
    """A single turn extracted from a session file."""

    __slots__ = (
        "turn_number", "user_message", "assistant_summary",
        "content_hash", "timestamp", "raw_content",
        "start_line", "end_line",
        "tool_uses", "files_modified", "assistant_text",
    )

    def __init__(
        self,
        turn_number: int,
        user_message: str,
        timestamp: str,
        content_hash: str,
        assistant_summary: str = "",
        raw_content: str = "",
        start_line: int = 0,
        end_line: int = 0,
        tool_uses: Optional[List[Dict[str, str]]] = None,
        files_modified: Optional[List[str]] = None,
        assistant_text: str = "",
    ):
        self.turn_number = turn_number
        self.user_message = user_message
        self.assistant_summary = assistant_summary
        self.content_hash = content_hash
        self.timestamp = timestamp
        self.raw_content = raw_content
        self.start_line = start_line
        self.end_line = end_line
        self.tool_uses = tool_uses or []
        self.files_modified = files_modified or []
        self.assistant_text = assistant_text


def parse_session(session_file: Path, *, since_turn: int = 0) -> List[ParsedTurn]:
    """
    Parse a Claude Code session file and return extracted turns.

    Args:
        session_file: Path to JSONL file
        since_turn: Only return turns after this number (for incremental import)

    Returns:
        List of ParsedTurn objects
    """
    session_type = detect_format(session_file)
    if session_type == "claude":
        return _parse_claude(session_file, since_turn=since_turn)
    else:
        logger.warning(f"Unknown session format: {session_file}")
        return []


def detect_format(session_file: Path) -> Optional[str]:
    """Auto-detect session file format by inspecting first few lines."""
    saw_claude_marker = False
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 30:  # Increased from 10 to handle file-history-snapshot etc.
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Claude Code: {type: "user"/"assistant", message: {...}}
                if data.get("type") in ("user", "assistant") and "message" in data:
                    return "claude"

                # Claude Code metadata-only/incomplete sessions are still Claude files.
                if data.get("type") in ("file-history-snapshot", "queue-operation", "progress", "system"):
                    saw_claude_marker = True
                    continue
    except Exception:
        pass

    return "claude" if saw_claude_marker else None


def extract_project_path(session_file: Path) -> Optional[str]:
    """Extract project path from a session file location or content."""
    parts = session_file.parts

    # Claude: ~/.claude/projects/-home-yu-projects-foo/session.jsonl
    if ".claude" in parts and "projects" in parts:
        parent = session_file.parent.name
        if parent.startswith("-"):
            decoded = "/" + parent[1:].replace("-", "/")
            if Path(decoded).exists():
                return decoded
            # Try reading cwd from file
            cwd = _read_cwd_from_jsonl(session_file)
            return cwd or decoded
        return None

    return None


def _read_cwd_from_jsonl(session_file: Path) -> Optional[str]:
    """Read cwd field from first few lines of a JSONL file."""
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 20:
                    break
                try:
                    obj = json.loads(line.strip())
                    cwd = obj.get("cwd")
                    if isinstance(cwd, str) and cwd.strip():
                        return cwd.strip()
                except Exception:
                    continue
    except Exception:
        pass
    return None


# ── Claude Code Parser ────────────────────────────────────────────────────────

def _parse_claude(session_file: Path, *, since_turn: int = 0) -> List[ParsedTurn]:
    """
    Parse Claude Code JSONL into turns.

    Strategy:
    1. Extract user messages (skip tool_result, commands, interrupts)
    2. Trace parentUUID chains to find root messages
    3. Group by root timestamp = one logical turn
    4. Merge API retries (same content within 2min window)
    5. Extract assistant content (text, tool usage, file changes)
    """
    lines = _read_jsonl(session_file)
    if not lines:
        return []

    # Step 1: Extract user messages
    user_messages = _extract_claude_user_messages(lines)
    if not user_messages:
        return []

    # Step 2+3: Group by root timestamp via parent chain
    groups = _group_by_root_timestamp(user_messages)

    # Step 4: Merge retries
    sorted_groups = sorted(groups.values(), key=lambda g: g["timestamp"] or "")
    merged = _merge_retries(sorted_groups)

    # Step 5: Build turns with content extraction
    total_lines = len(lines)
    turns = []

    for idx, group in enumerate(merged):
        turn_num = idx + 1
        if turn_num <= since_turn:
            continue

        # Determine line range for this turn
        start_line = group["lines"][0] if group["lines"] else 0
        if idx + 1 < len(merged) and merged[idx + 1]["lines"]:
            end_line = merged[idx + 1]["lines"][0] - 1
        else:
            end_line = total_lines

        # Extract user message text
        user_text = _extract_text_from_content(group["messages"][0].get("content", []))
        user_text = _clean_user_message(user_text)

        # Extract rich assistant content (text, tools, files)
        assistant_text, tool_uses, files_modified = _extract_assistant_content(
            lines, start_line, end_line
        )

        # Backward-compatible summary from full text
        assistant_summary = assistant_text

        # Compute content hash from the JSONL lines in range
        raw_content = "\n".join(
            lines[i]["_raw"] for i in range(start_line - 1, min(end_line, total_lines))
            if i < len(lines) and "_raw" in lines[i]
        )
        content_hash = hashlib.md5(raw_content.encode()).hexdigest()

        turns.append(ParsedTurn(
            turn_number=turn_num,
            user_message=user_text[:2000],
            assistant_summary=assistant_summary,
            content_hash=content_hash,
            timestamp=group["timestamp"] or "",
            raw_content=raw_content,
            start_line=start_line,
            end_line=end_line,
            tool_uses=tool_uses,
            files_modified=files_modified,
            assistant_text=assistant_text,
        ))

    return turns


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Read JSONL file into list of dicts with line numbers."""
    results = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line_no, raw_line in enumerate(f, 1):
                stripped = raw_line.strip()
                if not stripped:
                    results.append({"_raw": raw_line, "_line": line_no})
                    continue
                try:
                    data = json.loads(stripped)
                    data["_raw"] = stripped
                    data["_line"] = line_no
                    results.append(data)
                except json.JSONDecodeError:
                    results.append({"_raw": stripped, "_line": line_no})
    except Exception as e:
        logger.error(f"Failed to read {path}: {e}")
    return results


def _extract_claude_user_messages(lines: List[Dict]) -> List[Dict]:
    """Extract user messages, filtering out tool_result, commands, interrupts."""
    messages = []
    for data in lines:
        if data.get("type") != "user":
            continue
        if data.get("isMeta"):
            continue

        message = data.get("message", {})
        content = message.get("content", [])

        # Skip tool results
        if isinstance(content, list):
            if any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
                continue

        # Skip command wrappers
        if isinstance(content, str):
            s = content.strip()
            if s.startswith("<command-name>") or s.startswith("<local-command-"):
                continue
            if "request interrupted by user" in s.lower():
                continue

        # Skip interrupt placeholders in list content
        if isinstance(content, list):
            texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            if texts and all("request interrupted by user" in t.lower() for t in texts):
                continue

        messages.append({
            "line_no": data["_line"],
            "uuid": data.get("uuid"),
            "parent_uuid": data.get("parentUuid"),
            "timestamp": data.get("timestamp"),
            "content": content,
        })

    return messages


def _group_by_root_timestamp(messages: List[Dict]) -> Dict[str, Dict]:
    """Group messages by tracing parentUUID chains to find roots."""
    uuid_map = {m["uuid"]: m for m in messages if m.get("uuid")}

    # Find root for each message
    for msg in messages:
        root = msg
        visited = set()
        while root.get("parent_uuid") and root["parent_uuid"] in uuid_map:
            if root["uuid"] in visited:
                break
            visited.add(root["uuid"])
            root = uuid_map[root["parent_uuid"]]
        msg["root_timestamp"] = root.get("timestamp")

    # Group by root timestamp
    groups: Dict[str, Dict] = {}
    for msg in messages:
        ts = msg.get("root_timestamp")
        if not ts:
            continue
        if ts not in groups:
            groups[ts] = {"timestamp": ts, "messages": [], "lines": []}
        groups[ts]["messages"].append(msg)
        groups[ts]["lines"].append(msg["line_no"])

    # Sort lines within each group
    for g in groups.values():
        g["lines"] = sorted(g["lines"])

    return groups


def _merge_retries(groups: List[Dict], time_window: int = 120) -> List[Dict]:
    """Merge consecutive groups with identical content within time window."""
    if not groups:
        return []

    def _content_hash(group: Dict) -> str:
        texts = []
        for msg in group["messages"]:
            texts.append(_extract_text_from_content(msg.get("content", [])))
        return hashlib.md5("|".join(texts).encode()).hexdigest()

    def _parse_ts(ts: str) -> Optional[datetime]:
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None

    merged = []
    i = 0
    while i < len(groups):
        current = groups[i]
        current_hash = _content_hash(current)
        current_ts = _parse_ts(current["timestamp"])

        # Look ahead for retries
        j = i + 1
        while j < len(groups):
            next_ts = _parse_ts(groups[j]["timestamp"])
            if current_ts and next_ts:
                diff = abs((next_ts - current_ts).total_seconds())
                if diff <= time_window and _content_hash(groups[j]) == current_hash:
                    # Merge into current
                    current["messages"].extend(groups[j]["messages"])
                    current["lines"].extend(groups[j]["lines"])
                    current["lines"] = sorted(set(current["lines"]))
                    j += 1
                    continue
            break

        merged.append(current)
        i = j

    return merged


def _extract_text_from_content(content) -> str:
    """Extract plain text from Claude message content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return ""


def _extract_assistant_content(
    lines: List[Dict], start_line: int, end_line: int
) -> Tuple[str, List[Dict[str, str]], List[str]]:
    """Extract rich content from assistant messages within a line range.

    Returns:
        (assistant_text, tool_uses, files_modified)
        - assistant_text: all text blocks merged
        - tool_uses: [{name, ...key_params}] for each tool call
        - files_modified: deduplicated file paths from Edit/Write
    """
    text_parts: List[str] = []
    tool_uses: List[Dict[str, str]] = []
    files_modified_set: set = set()

    for data in lines:
        line_no = data.get("_line", 0)
        if line_no < start_line or line_no > end_line:
            continue
        if data.get("type") != "assistant":
            continue

        message = data.get("message", {})
        content = message.get("content", [])
        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue

            block_type = block.get("type")

            if block_type == "text":
                text = block.get("text", "").strip()
                if text:
                    text_parts.append(text)

            elif block_type == "tool_use":
                tool_info = _extract_tool_info(block)
                if tool_info:
                    tool_uses.append(tool_info)

                    # Track file modifications
                    name = tool_info.get("name", "")
                    if name in ("Edit", "Write") and "file_path" in tool_info:
                        files_modified_set.add(tool_info["file_path"])

    assistant_text = "\n\n".join(text_parts)
    files_modified = sorted(files_modified_set)

    return assistant_text, tool_uses, files_modified


def _extract_tool_info(block: Dict) -> Optional[Dict[str, str]]:
    """Extract a compact summary from a tool_use content block.

    Returns dict with 'name' and tool-specific key parameters.
    """
    name = block.get("name", "")
    if not name:
        return None

    inp = block.get("input", {})
    if not isinstance(inp, dict):
        return {"name": name}

    info: Dict[str, str] = {"name": name}

    if name == "Bash":
        if "command" in inp:
            info["command"] = str(inp["command"])[:200]
        if "description" in inp:
            info["description"] = str(inp["description"])[:100]

    elif name in ("Read", "Write", "Edit"):
        if "file_path" in inp:
            info["file_path"] = str(inp["file_path"])

    elif name == "Glob":
        if "pattern" in inp:
            info["pattern"] = str(inp["pattern"])
        if "path" in inp:
            info["path"] = str(inp["path"])

    elif name == "Grep":
        if "pattern" in inp:
            info["pattern"] = str(inp["pattern"])[:100]
        if "path" in inp:
            info["path"] = str(inp["path"])

    elif name == "Task":
        if "description" in inp:
            info["description"] = str(inp["description"])[:100]
        if "subagent_type" in inp:
            info["subagent_type"] = str(inp["subagent_type"])

    elif name == "WebSearch":
        if "query" in inp:
            info["query"] = str(inp["query"])[:100]

    elif name == "WebFetch":
        if "url" in inp:
            info["url"] = str(inp["url"])[:200]

    return info


def _clean_user_message(text: str) -> str:
    """Clean user message: strip XML tags, normalize whitespace."""
    import re
    # Remove system-reminder tags and content
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.DOTALL)
    # Remove other XML-like tags
    text = re.sub(r"<[^>]+>", "", text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text
