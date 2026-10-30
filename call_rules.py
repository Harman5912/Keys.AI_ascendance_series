"""call_rules.py — REMOVED.

Calling features have been removed from Keys.ai. This module now provides
only stub functions so any legacy imports do not break.
"""

from __future__ import annotations

from typing import Optional


def is_enabled() -> bool:
    return False


def is_auto_answer() -> bool:
    return False


def ring_delay() -> float:
    return 0.0


def watch_web() -> bool:
    return False


def watch_desktop() -> bool:
    return False


def set_toggle(key: str, value: bool) -> str:
    return "Calling features are disabled."


def set_ring_delay(seconds: float) -> str:
    return "Calling features are disabled."


def set_greeting(text: str) -> str:
    return "Calling features are disabled."


def add_rule(keywords, reply: str) -> str:
    return "Calling features are disabled."


def remove_rule(rule_id) -> str:
    return "Calling features are disabled."


def list_rules() -> str:
    return "Calling features are disabled. Keys.ai can only send messages, not make calls."


def match_rule(text: str) -> Optional[str]:
    return None


def greeting_text() -> str:
    return ""


def unknown_reply_text() -> str:
    return ""


def load_rules() -> dict:
    return {"enabled": False, "auto_answer": False, "rules": []}
