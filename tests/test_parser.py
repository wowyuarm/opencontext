"""Tests for opencontext.ingest.parser — JSONL parsing and turn extraction."""

import json
import hashlib
from pathlib import Path

import pytest

from opencontext.ingest.parser import (
    ParsedTurn,
    detect_format,
    extract_project_path,
    parse_session,
    _extract_text_from_content,
    _clean_user_message,
    _merge_retries,
)


def _write_jsonl(path: Path, records: list) -> Path:
    """Write a list of dicts as JSONL."""
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


def _make_user_msg(text, uuid="u1", parent_uuid=None, ts="2025-01-01T10:00:00Z"):
    msg = {
        "type": "user",
        "uuid": uuid,
        "timestamp": ts,
        "message": {"content": [{"type": "text", "text": text}]},
    }
    if parent_uuid:
        msg["parentUuid"] = parent_uuid
    return msg


def _make_assistant_msg(text, uuid="a1", parent_uuid="u1", ts="2025-01-01T10:00:05Z"):
    return {
        "type": "assistant",
        "uuid": uuid,
        "parentUuid": parent_uuid,
        "timestamp": ts,
        "message": {"content": [{"type": "text", "text": text}]},
    }


# ── Format Detection ─────────────────────────────────────────────────────────


class TestDetectFormat:
    def test_claude_format(self, tmp_path):
        p = _write_jsonl(tmp_path / "session.jsonl", [
            _make_user_msg("hello"),
            _make_assistant_msg("hi"),
        ])
        assert detect_format(p) == "claude"

    def test_unknown_format(self, tmp_path):
        p = _write_jsonl(tmp_path / "other.jsonl", [
            {"role": "user", "content": "hello"},
        ])
        assert detect_format(p) is None

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        assert detect_format(p) is None

    def test_nonexistent_file(self, tmp_path):
        assert detect_format(tmp_path / "nope.jsonl") is None


# ── Project Path Extraction ──────────────────────────────────────────────────


class TestExtractProjectPath:
    def test_claude_style_path(self, tmp_path):
        # Simulate: ~/.claude/projects/-home-yu-projects-foo/session.jsonl
        proj_dir = tmp_path / ".claude" / "projects" / "-home-yu-projects-foo"
        proj_dir.mkdir(parents=True)
        session = proj_dir / "session.jsonl"
        session.write_text("")

        result = extract_project_path(session)
        # decoded path won't exist, so it tries _read_cwd_from_jsonl
        assert result is not None

    def test_non_claude_path(self, tmp_path):
        p = tmp_path / "random" / "session.jsonl"
        p.parent.mkdir(parents=True)
        p.write_text("")
        assert extract_project_path(p) is None


# ── Text Extraction ──────────────────────────────────────────────────────────


class TestExtractText:
    def test_string_content(self):
        assert _extract_text_from_content("hello") == "hello"

    def test_list_content(self):
        content = [
            {"type": "text", "text": "line 1"},
            {"type": "text", "text": "line 2"},
        ]
        assert _extract_text_from_content(content) == "line 1\nline 2"

    def test_mixed_content_skips_non_text(self):
        content = [
            {"type": "text", "text": "keep"},
            {"type": "tool_use", "name": "Read"},
        ]
        assert _extract_text_from_content(content) == "keep"

    def test_empty(self):
        assert _extract_text_from_content([]) == ""
        assert _extract_text_from_content(None) == ""


# ── Message Cleaning ─────────────────────────────────────────────────────────


class TestCleanUserMessage:
    def test_strips_system_reminders(self):
        text = "Hello <system-reminder>secret stuff</system-reminder> world"
        assert _clean_user_message(text) == "Hello world"

    def test_strips_xml_tags(self):
        assert _clean_user_message("<foo>bar</foo>") == "bar"

    def test_normalizes_whitespace(self):
        assert _clean_user_message("hello   \n\n  world") == "hello world"


# ── Retry Merging ─────────────────────────────────────────────────────────────


class TestMergeRetries:
    def test_no_retries(self):
        groups = [
            {"timestamp": "2025-01-01T10:00:00Z", "messages": [{"content": "a"}], "lines": [1]},
            {"timestamp": "2025-01-01T10:05:00Z", "messages": [{"content": "b"}], "lines": [5]},
        ]
        merged = _merge_retries(groups)
        assert len(merged) == 2

    def test_merges_identical_within_window(self):
        groups = [
            {"timestamp": "2025-01-01T10:00:00Z", "messages": [{"content": "a"}], "lines": [1]},
            {"timestamp": "2025-01-01T10:01:00Z", "messages": [{"content": "a"}], "lines": [3]},
        ]
        merged = _merge_retries(groups)
        assert len(merged) == 1
        assert len(merged[0]["messages"]) == 2

    def test_does_not_merge_different_content(self):
        groups = [
            {"timestamp": "2025-01-01T10:00:00Z", "messages": [{"content": "a"}], "lines": [1]},
            {"timestamp": "2025-01-01T10:00:30Z", "messages": [{"content": "b"}], "lines": [3]},
        ]
        merged = _merge_retries(groups)
        assert len(merged) == 2

    def test_empty_input(self):
        assert _merge_retries([]) == []


# ── Full Parse ────────────────────────────────────────────────────────────────


class TestParseSession:
    def test_basic_parse(self, tmp_path):
        records = [
            _make_user_msg("What is Python?", uuid="u1", ts="2025-01-01T10:00:00Z"),
            _make_assistant_msg("A programming language.", uuid="a1", parent_uuid="u1"),
        ]
        p = _write_jsonl(tmp_path / "session.jsonl", records)
        turns = parse_session(p)
        assert len(turns) == 1
        assert "Python" in turns[0].user_message

    def test_multiple_turns(self, tmp_path):
        records = [
            _make_user_msg("Turn 1", uuid="u1", ts="2025-01-01T10:00:00Z"),
            _make_assistant_msg("Reply 1", uuid="a1", parent_uuid="u1", ts="2025-01-01T10:00:05Z"),
            _make_user_msg("Turn 2", uuid="u2", ts="2025-01-01T10:05:00Z"),
            _make_assistant_msg("Reply 2", uuid="a2", parent_uuid="u2", ts="2025-01-01T10:05:05Z"),
        ]
        p = _write_jsonl(tmp_path / "session.jsonl", records)
        turns = parse_session(p)
        assert len(turns) == 2
        assert turns[0].turn_number == 1
        assert turns[1].turn_number == 2

    def test_since_turn_skips(self, tmp_path):
        records = [
            _make_user_msg("Turn 1", uuid="u1", ts="2025-01-01T10:00:00Z"),
            _make_assistant_msg("R1", uuid="a1", parent_uuid="u1"),
            _make_user_msg("Turn 2", uuid="u2", ts="2025-01-01T10:05:00Z"),
            _make_assistant_msg("R2", uuid="a2", parent_uuid="u2"),
        ]
        p = _write_jsonl(tmp_path / "session.jsonl", records)
        turns = parse_session(p, since_turn=1)
        assert len(turns) == 1
        assert turns[0].turn_number == 2

    def test_skips_tool_results(self, tmp_path):
        records = [
            _make_user_msg("Hello", uuid="u1", ts="2025-01-01T10:00:00Z"),
            {
                "type": "user", "uuid": "u2", "timestamp": "2025-01-01T10:00:10Z",
                "parentUuid": "a1",
                "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
            },
            _make_assistant_msg("Done", uuid="a2", parent_uuid="u2"),
        ]
        p = _write_jsonl(tmp_path / "session.jsonl", records)
        turns = parse_session(p)
        assert len(turns) == 1

    def test_skips_interrupt_messages(self, tmp_path):
        records = [
            _make_user_msg("Real message", uuid="u1", ts="2025-01-01T10:00:00Z"),
            _make_assistant_msg("Reply", uuid="a1", parent_uuid="u1"),
            {
                "type": "user", "uuid": "u2", "timestamp": "2025-01-01T10:01:00Z",
                "message": {"content": "Request interrupted by user"},
            },
        ]
        p = _write_jsonl(tmp_path / "session.jsonl", records)
        turns = parse_session(p)
        assert len(turns) == 1

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        assert parse_session(p) == []

    def test_unknown_format(self, tmp_path):
        p = _write_jsonl(tmp_path / "other.jsonl", [{"role": "user"}])
        assert parse_session(p) == []

    def test_content_hash_is_deterministic(self, tmp_path):
        records = [
            _make_user_msg("Stable content", uuid="u1", ts="2025-01-01T10:00:00Z"),
            _make_assistant_msg("Reply", uuid="a1", parent_uuid="u1"),
        ]
        p = _write_jsonl(tmp_path / "session.jsonl", records)
        turns1 = parse_session(p)
        turns2 = parse_session(p)
        assert turns1[0].content_hash == turns2[0].content_hash
