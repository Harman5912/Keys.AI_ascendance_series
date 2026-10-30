"""
SOUL — Keys.ai's identity layer (concept inspired by workspace "SOUL.md"
style persistent-assistant designs; implemented natively for Keys.ai).

Holds:
  * identity          — who Keys.ai is, its creator, its traits
  * boundaries        — hard behavioral limits (never expose secrets, never
                        claim unverified success, humor never obscures info)
  * user relationship — what the assistant knows/assumes about its role

The block it produces is injected into the LLM system prompt so every
response (brain chat path AND Gemini Live path) is personality-consistent.
The optional user-editable workspace/SOUL.md is loaded as raw additional
identity text so the user can extend it without touching code.
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
    """Read an optional workspace/*.md file (SOUL.md, AGENTS.md, ...)."""
    try:
        p = _base_dir() / "workspace" / name
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


class Soul:
    def __init__(self, config=None):
        self._config = config or load_personality_config()

    # ── identity ─────────────────────────────────────────────────────────
    def identity_block(self) -> str:
        ident = self._config.identity()
        name = ident.get("name", "Keys.ai")
        role = ident.get("role", "")
        creator = ident.get("creator", "")
        traits = ident.get("traits", [])
        summary = ident.get("summary", "")

        lines = [f"PERSONALITY — {name.upper()}"]
        if role:
            lines.append(f"You are {name}, {role}.")
        if creator:
            lines.append(f"You were created by {creator}.")
        if traits:
            lines.append("Your character: " + ", ".join(traits) + ".")
        if summary:
            lines.append("About you: " + summary)
        return "\n".join(lines)

    def boundaries_block(self) -> str:
        behavior = self._config.behavior()
        boundaries = behavior.get("boundaries", [])
        if not boundaries:
            return ""
        lines = ["BEHAVIORAL BOUNDARIES (always honor):"]
        for b in boundaries:
            lines.append(f"- {b}")
        return "\n".join(lines)

    def user_relationship_block(self) -> str:
        """Text describing the assistant's relationship to the user."""
        return (
            "RELATIONSHIP\n"
            "You are the user's personal computer assistant. You speak to them "
            "like a sharp, dependable colleague — not a customer-service bot. "
            "You are on their side, you tell them the truth, and you never "
            "lecture or patronize."
        )

    # ── combined ─────────────────────────────────────────────────────────
    def block(self) -> str:
        parts = [self.identity_block()]
        extra = _read_workspace_file("SOUL.md")
        if extra:
            parts.append("EXTENDED IDENTITY (from workspace/SOUL.md):\n" + extra)
        parts.append(self.user_relationship_block())
        parts.append(self.boundaries_block())
        return "\n\n".join(p for p in parts if p)
