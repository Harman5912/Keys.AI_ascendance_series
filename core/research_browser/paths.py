"""Paths and small settings for the Research Browser.

Defaults follow the app's existing conventions: metadata in ``config/`` next to
the other JSON stores, captures under the user's Pictures folder (resolved with
``Path.home()`` — no username is ever hard-coded), per-task workspaces under
``config/research_workspaces``.

Every location can be overridden with the ``research_browser`` key of the app's
own config file; no second settings system is introduced.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

CONFIG_KEY = "research_browser"

DEFAULTS: dict = {
    "capture_dir": "",
    "workspace_dir": "",
    "max_download_mb": 40,
    "search_engine": "google",
    "keep_task_sessions": True,
}


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        from core import config_store
        stored = config_store.load().get(CONFIG_KEY) or {}
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in DEFAULTS:
                    cfg[key] = value
    except Exception as exc:                       # pragma: no cover
        print(f"[research_browser] settings load failed: {exc}")
    return cfg


def save(patch: dict) -> dict:
    from core import config_store
    clean = {k: v for k, v in (patch or {}).items() if k in DEFAULTS}
    cfg = load()
    cfg.update(clean)
    config_store.update({CONFIG_KEY: cfg})
    return cfg


def _resolve(raw: str, fallback: Path) -> Path:
    text = str(raw or "").strip()
    if not text:
        return fallback
    try:
        path = Path(os.path.expandvars(os.path.expanduser(text)))
    except Exception:
        return fallback
    return path if path.is_absolute() else (base_dir() / path).resolve()


def capture_dir() -> Path:
    fallback = Path.home() / "Pictures" / "KeysAI" / "Browser"
    path = _resolve(load().get("capture_dir", ""), fallback)
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_root() -> Path:
    fallback = base_dir() / "config" / "research_workspaces"
    path = _resolve(load().get("workspace_dir", ""), fallback)
    path.mkdir(parents=True, exist_ok=True)
    return path


def task_workspace(task_id: str) -> Path:
    """Per-task folder; the id is sanitised so it can never escape the root."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(task_id or ""))[:40] or "session"
    path = workspace_root() / safe
    (path / "assets").mkdir(parents=True, exist_ok=True)
    (path / "captures").mkdir(parents=True, exist_ok=True)
    return path


def library_path() -> Path:
    return base_dir() / "config" / "research_library.json"


def max_download_bytes() -> int:
    mb = load().get("max_download_mb") or 40
    try:
        return int(float(mb) * 1024 * 1024)
    except Exception:
        return 40 * 1024 * 1024


__all__ = ["CONFIG_KEY", "DEFAULTS", "load", "save", "base_dir", "capture_dir",
           "task_workspace", "workspace_root", "library_path",
           "max_download_bytes"]
