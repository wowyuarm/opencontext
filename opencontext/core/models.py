"""Data models for OpenContext."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Session:
    id: str
    file_path: str
    session_type: str  # "claude" | "codex" | "gemini"
    workspace: Optional[str]
    started_at: str
    last_activity_at: str
    title: Optional[str] = None
    summary: Optional[str] = None
    summary_updated_at: Optional[str] = None
    total_turns: int = 0
    agent_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Turn:
    id: str
    session_id: str
    turn_number: int
    user_message: Optional[str]
    assistant_summary: Optional[str]
    title: str
    description: Optional[str]
    model_name: Optional[str]
    content_hash: str
    timestamp: str
    is_continuation: bool = False  # if_last_task
    satisfaction: str = "fine"     # good | fine | bad
    created_at: Optional[str] = None


@dataclass
class Event:
    id: str
    title: str
    description: Optional[str]
    event_type: str  # "task" | "temporal"
    status: str      # "active" | "frozen" | "archived"
    start_timestamp: Optional[str] = None
    end_timestamp: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Optional[str] = None  # JSON string


@dataclass
class AgentInfo:
    id: str
    name: str
    title: str = ""
    description: str = ""
    visibility: str = "visible"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Job:
    id: str
    kind: str         # "turn_summary" | "session_summary" | "event_summary" | "agent_description"
    dedupe_key: str
    payload: Optional[str] = None  # JSON string
    status: str = "queued"         # queued | processing | retry | done | failed
    priority: int = 0
    attempts: int = 0
    next_run_at: Optional[str] = None
    locked_until: Optional[str] = None
    locked_by: Optional[str] = None
    last_error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
