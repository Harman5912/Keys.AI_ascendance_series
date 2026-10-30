"""
core/avatar_bridge.py — the animated holographic avatar, wrapped for Keys.ai.

`HoloAvatar` (core/avatar.py) does the rendering; this bridge owns just the
state the HUD needs to drive it:

* a smoothed audio level (so the mouth rises and falls with speech),
* the current assistant state (SPEAKING / THINKING / LISTENING / …) so the
  face can act — look away while thinking, meet you while listening,
* a graceful failure mode: if anything here raises, the HUD falls back to the
  static icon rather than crashing a paint pass.

Ported from the Mark LV assistant.
"""

from __future__ import annotations

import time

try:
    from core.avatar import HoloAvatar
except Exception:          # numpy/Qt missing, or a bad asset — HUD stays on the icon
    HoloAvatar = None


class AvatarBridge:
    """Wraps HoloAvatar with level smoothing and a safe step()."""

    def __init__(self) -> None:
        if HoloAvatar is None:
            raise RuntimeError("HoloAvatar unavailable")
        self._av = HoloAvatar()
        self._level = 0.0
        self._t = time.monotonic()

    @property
    def span(self) -> float:
        """Vertical extent of the head in units of the face radius."""
        return self._av.SPAN

    def set_level(self, level: float) -> None:
        """A fresh 0..1 audio level from the playback path."""
        try:
            self._level = max(0.0, min(1.0, float(level)))
        except Exception:
            pass

    def step(self, speaking: bool = False, muted: bool = False,
             state: str = "") -> None:
        """Advance the animation by the wall-clock delta since the last call."""
        now = time.monotonic()
        dt = now - self._t
        self._t = now
        self._av.step(dt, self._level, speaking=speaking, muted=muted,
                      state=state or "")
        # Decay so the mouth closes in the gaps between audio chunks.
        self._level *= 0.86

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        """Look somewhere for a moment (used for 'face as status')."""
        try:
            self._av.glance(dx, dy, hold)
        except Exception:
            pass

    def paint(self, p, cx: float, cy: float, r: float, main, acc, bg) -> None:
        """Draw the head centred at (cx, cy) with face radius r."""
        self._av.paint(p, cx, cy, r, main, acc, bg)
