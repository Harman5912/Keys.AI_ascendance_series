"""Missile-style target acquisition for screen control.

When Keys.ai is about to click something, the user should SEE the selection
like a targeting reticle: a small square border that launches from the last
selection and homes onto the new target ("missile coordinate selection"),
while the real mouse glides along the same homing arc and clicks the center.

One module is used by every step of an app takeover, so the whole overtake
feels the same: SEARCH box -> CONTACT row -> CALL button -> message box — each
one acquired with the identical missile-retarget animation.

Everything here is pure logic + optional callbacks:

    • the overlay draws the flying square border   (agent_control/overlay)
    • the motion engine moves the real mouse       (automation/motion)
    • the takeover flow wires them together        (actions/whatsapp_takeover)

Headless-safe: without a motion object or a draw callback it simply returns
the target center, so tests and NullBridge environments never break.
"""

from __future__ import annotations

import math
from typing import Callable, Optional

# (x1, y1, x2, y2) in screen pixels — top-left, bottom-right.
Rect4 = tuple[int, int, int, int]

DEFAULT_TARGET_SECONDS = 0.6   # how long the reticle glides / the mouse homes


def missile_waypoints(start: tuple[int, int], target: tuple[int, int],
                      arc: float = 0.18,
                      bends: int = 2) -> list[tuple[int, int]]:
    """Homing-missile path: a curve that bends hard at launch and straightens
    as it closes on the target (the arc tapers to zero at the end).

    Deterministic — the bend always goes to the same perpendicular side of
    the line of flight, so consecutive acquisitions don't zigzag randomly.
    Returns [] when start and target are practically the same point.
    """
    sx, sy = int(start[0]), int(start[1])
    tx, ty = int(target[0]), int(target[1])
    dx, dy = tx - sx, ty - sy
    dist = math.hypot(dx, dy)
    if dist < 10:
        return []
    nx, ny = -dy / dist, dx / dist          # unit normal (fixed side)
    n = max(1, int(bends))
    out: list[tuple[int, int]] = []
    for i in range(1, n + 1):
        f = i / (n + 1)                     # fraction along the line
        bow = max(0.0, float(arc)) * (1.0 - f)   # biggest at launch, 0 at target
        out.append((int(sx + dx * f + nx * bow * dist),
                    int(sy + dy * f + ny * bow * dist)))
    return out


def center(rect: Rect4) -> tuple[int, int]:
    return (int((rect[0] + rect[2]) / 2), int((rect[1] + rect[3]) / 2))


class Targeter:
    """Tracks the last locked rect so every new selection glides from it.

    engage() → 1) tells the drawing callback to animate the reticle from the
    previous target to the new one, 2) moves the real mouse along a homing
    arc to the new target center, 3) remembers the new rect for the next
    selection. Never raises: every optional piece (motion object, callback)
    degrades to "just return the center".
    """

    def __init__(self,
                 on_reticle: Optional[Callable[[Rect4, Rect4, float], None]] = None) -> None:
        self._on_reticle = on_reticle
        self._last: Optional[Rect4] = None

    @property
    def last_rect(self) -> Optional[Rect4]:
        """The rect of the previous selection (None before the first one)."""
        return self._last

    def reset(self) -> None:
        """Forget the previous selection — start of a new takeover."""
        self._last = None

    def launch_rect(self, motion=None) -> Rect4:
        """Where the reticle should fly FROM for the next engage: the last
        locked selection, or a small box around the cursor for the very
        first selection (so the reticle always has somewhere to fly from)."""
        if self._last is not None:
            return self._last
        try:
            px, py = motion.position()
        except Exception:
            px, py = 0, 0
        return (int(px) - 24, int(py) - 24,
                int(px) + 24, int(py) + 24)

    def engage(self, motion, rect: Rect4,
               seconds: float = DEFAULT_TARGET_SECONDS,
               on_move: Optional[Callable[[int, int], None]] = None) -> tuple[int, int]:
        """Acquire `rect` with the missile animation and return its center.

        `motion` is any object exposing position()/move_to() (the real
        MouseTrajectory, or a test fake); missing pieces are ignored.

        `on_move(x, y)` — when given — is streamed every cursor update while
        the mouse homes in (the grid overlay uses it to draw the live
        crosshair exactly where the real cursor is).
        """
        cx, cy = center(rect)
        start_rect = self.launch_rect(motion)

        if self._on_reticle is not None:
            try:
                self._on_reticle(start_rect, rect, float(seconds))
            except Exception:
                pass

        # the real mouse follows the same homing arc as the reticle
        try:
            sx, sy = motion.position()
            wp = missile_waypoints((int(sx), int(sy)), (cx, cy))
            # on_move is only forwarded when given, so motion objects whose
            # move_to predates the streaming kwarg keep working unchanged.
            if on_move is not None:
                motion.move_to(cx, cy, waypoints=wp, easing="missile",
                               duration=float(seconds), task="click",
                               on_move=on_move)
            else:
                motion.move_to(cx, cy, waypoints=wp, easing="missile",
                               duration=float(seconds), task="click")
        except Exception:
            pass

        self._last = (int(rect[0]), int(rect[1]),
                      int(rect[2]), int(rect[3]))
        return cx, cy
