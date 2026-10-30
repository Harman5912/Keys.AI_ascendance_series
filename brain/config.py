"""
Brain configuration — loaded from config/brain.json.

Mirrors the existing pattern of config/agent_control.json: a small JSON file
with sensible defaults, overridable values, and a lightweight wrapper class.
Nothing is hard-coded inside the brain modules; they always read through this.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


DEFAULTS: dict = {
    "enabled": True,
    "provider": "gemini",
    "model": "gemini-2.5-flash",
    "max_iterations": 10,
    "max_retries": 2,
    "autonomous_mode": True,
    "confirm_moderate": True,
    "confirm_dangerous": True,
    "polish_response": False,
    "memory": {"enabled": True, "long_term": True, "llm_extract": False},
    "intent": {"llm_refine": False},
    "context": {"max_history": 12},
    # Intelligence layer (spelling / entities / semantics / situation)
    "language": {"enabled": True, "spell": True, "entities": True,
                  "semantic": True, "situation": True},
    # Personality + conversational humour (content lives in personality.json)
    "personality": {"enabled": True},
    "humor": {"enabled": True},
    "skills": {"enabled": True},
    # Session continuity (references persist across restarts)
    "session": {"persist": True},
    "logging": {"level": "info"},
    "permissions": {
        "DANGEROUS": ["file_controller"],
        "MODERATE": [],
        "SAFE": [],
    },
    "blocked_tools": [],
}


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    return get_base_dir() / "config" / "brain.json"


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively (missing keys keep base values)."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class BrainConfig:
    """Thin wrapper over the config dict — attribute + .get() access."""

    def __init__(self, data: dict | None = None):
        self._data: dict = _deep_merge(DEFAULTS, data or {})

    def __getattr__(self, name: str):
        # __getattr__ is only called when normal lookup fails.
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._data:
            return self._data[name]
        raise AttributeError(name)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def to_dict(self) -> dict:
        return json.loads(json.dumps(self._data))

    def save(self, path: Path | None = None) -> None:
        path = path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def load_config(path: Path | None = None) -> BrainConfig:
    path = path or config_path()
    if not path.exists():
        return BrainConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return BrainConfig(data)
    except Exception as e:
        print(f"[Brain] ⚠️ Config load error ({path}): {e}")
    return BrainConfig()
