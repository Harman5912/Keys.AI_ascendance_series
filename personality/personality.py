"""
PERSONALITY — communication style layer.

Controls HOW Keys.ai sounds: tone, verbosity, filler avoidance, emoji usage,
and the address rule. This is injected into the system prompt so the LLM's
own phrasing matches the personality, complementing the humour post-processor
which adds situational remarks on top of final responses.
"""

from __future__ import annotations

from personality.config import load_personality_config

# Phrases the personality forbids the model from leaning on (assistant filler).
_FILLER_PHRASES = [
    "Sure!", "Absolutely!", "Great question!", "That's a great question!",
    "I'd be happy to help!", "As an AI,", "As an AI language model,",
    "I'm sorry, but I", "I cannot assist", "Let me know if you need anything "
    "else!", "Is there anything else I can help you with?",
]


class Personality:
    def __init__(self, config=None):
        self._config = config or load_personality_config()

    def style_block(self) -> str:
        style = self._config.style()
        tone = style.get("tone", "")
        verbosity = style.get("verbosity", "")
        avoid = bool(style.get("avoid_filler", True))
        address = style.get("address", "")

        lines = ["COMMUNICATION STYLE"]
        if tone:
            lines.append(f"- Tone: {tone}")
        if verbosity:
            lines.append(f"- Length: {verbosity}")
        if address:
            lines.append(f"- Address: {address}")
        if avoid:
            banned = ", ".join(_FILLER_PHRASES[:6])
            lines.append(f"- Never open with assistant filler like: {banned}")
            lines.append("- Skip canned pleasantries; just be useful and human.")
        return "\n".join(lines)

    def emoji_allowed(self) -> bool:
        return bool(self._config.style().get("emoji", True))

    def block(self) -> str:
        return self.style_block()
