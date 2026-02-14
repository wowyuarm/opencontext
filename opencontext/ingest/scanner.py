"""
Project doc scanner — extract stable context from workspace files.

Scans README.md, CLAUDE.md, AGENTS.md, docs/*.md to build
a foundation for the Project Brief.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Files to scan (in priority order)
_DOC_FILES = [
    "README.md",
    "CLAUDE.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "ARCHITECTURE.md",
]

_MAX_FILE_CHARS = 4000
_MAX_DOCS_DIR_FILES = 5
_MAX_DOCS_DIR_CHARS = 2000


def scan_project_docs(workspace: str) -> Dict[str, str]:
    """Scan a project workspace for documentation files.

    Returns dict of {filename: content} with truncated content.
    Only includes files that exist and have meaningful content.
    """
    root = Path(workspace)
    if not root.is_dir():
        return {}

    docs: Dict[str, str] = {}

    # Root-level doc files
    for name in _DOC_FILES:
        path = root / name
        if path.is_file():
            content = _read_truncated(path, _MAX_FILE_CHARS)
            if content:
                docs[name] = content

    # docs/ directory
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        md_files = sorted(docs_dir.glob("*.md"))[:_MAX_DOCS_DIR_FILES]
        for f in md_files:
            content = _read_truncated(f, _MAX_DOCS_DIR_CHARS)
            if content:
                docs[f"docs/{f.name}"] = content

    return docs


def scan_project_tech(workspace: str) -> Dict[str, str]:
    """Detect tech stack from project config files.

    Returns dict of {indicator: value} for quick tech identification.
    """
    root = Path(workspace)
    if not root.is_dir():
        return {}

    tech: Dict[str, str] = {}

    # Python
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        tech["python"] = _read_truncated(pyproject, 1000)

    setup_py = root / "setup.py"
    if setup_py.is_file() and "python" not in tech:
        tech["python"] = _read_truncated(setup_py, 1000)

    # Node
    pkg = root / "package.json"
    if pkg.is_file():
        tech["node"] = _read_truncated(pkg, 1000)

    # Rust
    cargo = root / "Cargo.toml"
    if cargo.is_file():
        tech["rust"] = _read_truncated(cargo, 1000)

    # Go
    gomod = root / "go.mod"
    if gomod.is_file():
        tech["go"] = _read_truncated(gomod, 500)

    return tech


def _read_truncated(path: Path, max_chars: int) -> str:
    """Read file content, truncated to max_chars."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        text = text.strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... (truncated)"
        return text
    except Exception as e:
        logger.debug(f"Cannot read {path}: {e}")
        return ""
