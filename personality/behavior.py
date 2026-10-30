"""
BEHAVIOR — operational behavioral rules layer.

Distills the assistant's standing rules (verify before claiming, no filler,
ask when uncertain, humor hygiene) into a compact system-prompt block, and
also exposes the rules as data so other brain components can query them
(e.g. the humour engine checks whether humor is allowed in a given situation).
"""

from __future__ import annotations

from pathlib import Path

from personality.config import load_personality_config


def _base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _read_workspace_file(name: str) -> str:
    try:
        p = _base_dir() / "workspace" / name
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


class Behavior:
    def __init__(self, config=None):
        self._config = config or load_personality_config()

    def rules_block(self) -> str:
        behavior = self._config.behavior()
        lines = ["STANDING BEHAVIORAL RULES (follow always):"]
        if behavior.get("verify_before_claiming"):
            lines.append("- VERIFY before claiming: never say 'done', 'sent', "
                         "'opened' or 'fixed' unless the tool confirmed it.")
        if behavior.get("never_pretend_success"):
            lines.append("- If an action failed or is unverified, say so "
                         "honestly and offer the next step.")
        if behavior.get("ask_when_uncertain"):
            lines.append("- When an action is ambiguous (a name, a file, a "
                         "target), ask a short clarifying question instead of "
                         "guessing.")
        extra = _read_workspace_file("AGENTS.md")
        if extra:
            lines.append("\nEXTENDED OPERATING RULES (from workspace/AGENTS.md):\n"
                         + extra)
        return "\n".join(lines)

    def block(self) -> str:
        return self.rules_block()
