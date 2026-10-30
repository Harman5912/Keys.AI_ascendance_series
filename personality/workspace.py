"""
WORKSPACE LOADER — reads the optional user-editable workspace/*.md docs
(SOUL.md, AGENTS.md, USER.md, TOOLS.md, MEMORY.md) and exposes them as a
system-prompt block, OpenClaw-style.

The workspace docs are persistent behavioral/contextual files the user can
edit in a plain editor. They are appended to the personality block that is
injected into LLM system prompts, so editing them changes how Keys.ai
behaves — without touching code. Missing files are simply skipped and any
read failure is swallowed, so this can never break the app.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Order matters: identity first, then rules, then the user, then tools/memory.
_WORKSPACE_FILES = ("SOUL.md", "AGENTS.md", "USER.md", "TOOLS.md", "MEMORY.md")

# Hard cap so a huge workspace file can't bloat every LLM call.
_MAX_CHARS_PER_FILE = 4000


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def workspace_dir() -> Path:
    return _base_dir() / "workspace"


# mtime cache: build_system_block() runs on every chat turn / Live call, so
# avoid re-reading the workspace docs from disk each time. The cache is keyed
# on (name, mtime, size) and invalidated when a file changes or appears.
_cache: dict = {"signature": None, "block": ""}


def _signature(base: Path) -> tuple | None:
    try:
        if not base.exists():
            return None
        sig = []
        for name in _WORKSPACE_FILES:
            p = base / name
            if p.exists():
                st = p.stat()
                sig.append((name, st.st_mtime_ns, st.st_size))
        return tuple(sorted(sig))
    except Exception:
        return None


def load_workspace_block() -> str:
    """Concatenate the existing workspace docs into one prompt block.
    Returns "" when none exist or everything fails to read. Cached by
    file mtime so edits to workspace/*.md are picked up on the next call."""
    base = workspace_dir()
    sig = _signature(base)
    if sig is not None and sig == _cache["signature"]:
        return _cache["block"]
    parts: list[str] = []
    for name in _WORKSPACE_FILES:
        try:
            path = base / name
            if not path.exists():
                continue
            content = (path.read_text(encoding="utf-8") or "").strip()
            if not content:
                continue
            if len(content) > _MAX_CHARS_PER_FILE:
                content = content[:_MAX_CHARS_PER_FILE] + "\n…"
            parts.append(f"# {name}\n{content}")
        except Exception:
            continue
    block = "\n\n".join(parts)
    _cache["signature"] = sig
    _cache["block"] = block
    return block
