"""Humour Engine — optional, never touches automation decisions.

The humour system ONLY generates short contextual comments for the agent's
reply text. It can never change what action is taken or whether it succeeds.

Personality: friendly, confident, slightly sarcastic, occasionally dark,
technically knowledgeable. Comments are rare, short and situational.

Dark humour is allowed only as light, fictional, situational developer/tech
humour — never targeting race, religion, disability, protected
characteristics, real victims, tragedies, sexual violence, hate groups or
private individuals. It is fully gated by the `dark_humour` setting.

Settings (see agent_control.settings):
    humour_level OFF|LOW|MEDIUM|HIGH   — controls how often a comment appears
    professional_mode ON               — disables jokes entirely
    dark_humour OFF/ON                 — gates the dark one-liner pool
"""

from __future__ import annotations

import random
from typing import Optional

# ── comment pools (short, developer/tech flavoured) ────────────────────────
_LINES: dict[str, list[str]] = {
    "open": [
        "Ah, {app}. Where bugs go to reproduce.",
        "Opening {app}. Praying it starts on the first try.",
        "{app} loading. This is the part where I hold my breath.",
        "Summoning {app}…",
    ],
    "error": [
        "Found it. It was hiding in plain sight. Classic.",
        "That error message has the confidence of someone who knows absolutely nothing.",
        "The error has been located. It was inside you the whole time. Or the code. One of the two.",
    ],
    "build_failure": [
        "The compiler has chosen violence today.",
        "Build failed. The compiler and I need to have a conversation.",
        "That's not a bug — that's the code expressing its boundaries.",
    ],
    "slow_computer": [
        "Give me a second. Your computer is negotiating with reality.",
        "Your machine is processing. Slowly. Like it's reading the manual.",
        "Waiting on the CPU. It's doing its best.",
    ],
    "slow_network": [
        "The internet appears to be travelling by bicycle.",
        "Waiting for the network. The packets are walking.",
        "The server is thinking about it. Emphasis on 'about'.",
    ],
    "success": [
        "And somehow, we didn't break production. Character development.",
        "Done. I have decided not to investigate why it worked.",
        "It worked. I'm as surprised as you are.",
        "Task complete. No computers were harmed.",
    ],
    "verify": [
        "Let me verify that… because 'trust me' has burned us before.",
        "Checking the screen again. I believe nothing.",
        "Verifying… I refuse to claim victory on a guess.",
    ],
    "fix": [
        "Fixed. I have decided not to investigate why it worked.",
        "Problem solved. The code now behaves like it was written on purpose.",
        "Repaired. We're calling it a feature.",
    ],
    "long": [
        "This is getting longer than my attention span.",
        "That's not a function, that's a saga with a return statement.",
        "This could have been five lines. We chose drama.",
    ],
    "click": [
        "Clicking the thing. The thing being clicked is the target. Obviously.",
        "One click, coming up.",
    ],
    "typing": [
        "Typing. The keyboard is safe with me.",
        "Words are being typed. Try not to blink.",
    ],
    "generic": [
        "Everything is fine. Which is exactly what people say immediately before everything stops being fine.",
        "The code works. Please don't ask what I had to sacrifice.",
        "Executed. The cursor moved with intent.",
        "Consider it handled. Suspiciously smoothly, even.",
    ],
}

# ── dark humour pool — situational dev humour only (gated) ─────────────────
_DARK_LINES: list[str] = [
    "The code works. Please don't ask what I had to sacrifice.",
    "I've seen worse code. I've also seen warning labels on hairdryers.",
    "This task had a 50% success rate. The other 50% was this message.",
    "Somewhere, a rubber duck is getting blamed for this.",
    "I'd explain what happened, but I'm legally obligated not to admit I saw it.",
]

# probability of a comment per event, by humour level
_PROB = {"LOW": 0.12, "MEDIUM": 0.26, "HIGH": 0.5}
_OFF = "OFF"


def _pick(pool: list[str], app: str = "") -> str:
    line = random.choice(pool) if pool else ""
    return line.format(app=app or "it") if line else ""


class HumourEngine:
    """Generates optional short comments; never decides or blocks actions."""

    def __init__(self, settings=None) -> None:
        self._settings = settings   # lazily resolved to avoid import cycles
        self._last_event = None
        self._last_time = 0.0

    def _settings_obj(self):
        if self._settings is not None:
            return self._settings
        from agent_control.settings import get_settings
        return get_settings()

    def enabled(self) -> bool:
        s = self._settings_obj()
        if s.get("professional_mode"):
            return False
        return s.get("humour_level", _OFF) != _OFF

    def comment(self, event: str, app: str = "", force: bool = False) -> Optional[str]:
        """Return a short comment for `event`, or None when silence is better.

        force=True bypasses probability (used by the explicit `humour` tool
        action) but still respects professional mode and the OFF level.
        """
        if not event:
            return None
        s = self._settings_obj()
        if s.get("professional_mode"):
            return None
        level = s.get("humour_level", _OFF)
        if level == _OFF:
            return None
        prob = _PROB.get(level, 0.0)
        if not force and random.random() > prob:
            return None
        # never two comments in a row about the same event type
        now = __import__("time").time()
        if event == self._last_event and now - self._last_time < 8.0:
            return None
        self._last_event = event
        self._last_time = now
        pool = list(_LINES.get(event, _LINES["generic"]))
        if s.get("dark_humour") and random.random() < 0.35:
            pool += _DARK_LINES
        return _pick(pool, app)

    def sample(self, event: str, app: str = "") -> Optional[str]:
        """Force a comment (respecting professional mode / OFF) — for the
        explicit `humour` action and tests."""
        s = self._settings_obj()
        if s.get("professional_mode") or s.get("humour_level", _OFF) == _OFF:
            return None
        pool = list(_LINES.get(event, _LINES["generic"]))
        if s.get("dark_humour"):
            pool += _DARK_LINES
        return _pick(pool, app)


_humour: Optional[HumourEngine] = None


def get_humour(settings=None) -> HumourEngine:
    """Shared singleton humour engine."""
    global _humour
    if _humour is None:
        _humour = HumourEngine(settings)
    elif settings is not None:
        _humour._settings = settings
    return _humour


def reset_humour() -> None:
    global _humour
    _humour = None
