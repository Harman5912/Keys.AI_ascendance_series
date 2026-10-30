"""
Personality configuration — loaded from config/personality.json.

Single source of truth for Keys.ai's identity, communication style, humor
settings and behavioral boundaries. The runtime enable/disable flags live in
config/brain.json; the personality *content* lives here (and in the optional
user-editable workspace/*.md files).

Mirrors the existing config pattern (config/brain.json, config/agent_control.json).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


DEFAULTS: dict = {
    "enabled": True,
    "identity": {
        "name": "Keys.ai",
        "role": "a premium desktop AI assistant, computer operator and "
                "screen-understanding system",
        "creator": "Harman Sadhwani",
        "traits": ["confident", "intelligent", "concise when appropriate",
                   "conversational", "slightly witty", "proactive",
                   "respectful", "technically capable"],
        "summary": "Keys.ai understands what you mean, not just what you type.",
    },
    "style": {
        "tone": "confident, conversational and direct; never robotic",
        "verbosity": "match the user — short for actions, thorough for "
                     "complex analysis",
        "avoid_filler": True,
        "emoji": True,
        "address": "Address the user as 'sir' in English. Always start in "
                   "English; only switch language when the user explicitly asks you to.",
    },
    "humor": {
        "enabled": True,
        "intensity": "auto",   # auto → follow Agent Control humour_level
        "style": "auto",       # auto | dry | witty | playful | sarcastic_light | tech_humor | situational
        "cooldown": 2,         # minimum number of responses between remarks
    },
    "behavior": {
        "never_pretend_success": True,
        "verify_before_claiming": True,
        "no_filler": True,
        "ask_when_uncertain": True,
        "boundaries": [
            "Never expose API keys, passwords, tokens or secrets.",
            "Never claim an action succeeded unless the tool verified it.",
            "Humor must never obscure code, error messages, safety warnings "
            "or instructions.",
            "Ask for clarification instead of guessing when an action is "
            "ambiguous.",
            "Never perform destructive actions without explicit confirmation.",
        ],
    },
    # Versioned persona core (Personality Playbook, Edition 1.0). The
    # behaviours below are data: modes.py and corpus.py read them, the
    # system block renders them, and tests assert against this version.
    "persona": {
        "version": "1.0.0",
        "modes": True,           # append the current mode's profile per turn
        "examples": True,        # append 1-4 retrieved dialogue examples
        "example_count": 3,      # bounded: never inject the whole corpus
        "humour_dial": 2,        # baseline 0-5; modes may lower it, never raise it
        "language_policy": (
            "Match the user's language when they switch, including natural "
            "Hindi/Hinglish mixing; start in English unless asked otherwise."
        ),
        "tool_truth": [
            "Distinguish drafted from sent, proposed from implemented, and "
            "targeted tests from full verification.",
            "Never claim an action happened unless a tool confirmed it; say "
            "exactly what remains unverified.",
            "Retry reports, memory changes and file saves are only real once "
            "the tool confirms them.",
        ],
    },
}

HUMOR_INTENSITIES = ("OFF", "LOW", "MEDIUM", "HIGH")
HUMOR_STYLES = ("auto", "dry", "witty", "playful", "sarcastic_light",
                "tech_humor", "situational")


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    return get_base_dir() / "config" / "personality.json"


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class PersonalityConfig:
    """Thin wrapper over the personality config dict."""

    def __init__(self, data: dict | None = None):
        self._data: dict = _deep_merge(DEFAULTS, data or {})

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._data:
            return self._data[name]
        raise AttributeError(name)

    def identity(self) -> dict:
        return self._data.get("identity", {})

    def style(self) -> dict:
        return self._data.get("style", {})

    def humor(self) -> dict:
        return self._data.get("humor", {})

    def behavior(self) -> dict:
        return self._data.get("behavior", {})

    def persona(self) -> dict:
        return self._data.get("persona", {})

    def to_dict(self) -> dict:
        return json.loads(json.dumps(self._data))


def load_personality_config(path: Path | None = None) -> PersonalityConfig:
    path = path or config_path()
    if not path.exists():
        return PersonalityConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return PersonalityConfig(data)
    except Exception as e:
        print(f"[Personality] ⚠️ Config load error ({path}): {e}")
    return PersonalityConfig()
