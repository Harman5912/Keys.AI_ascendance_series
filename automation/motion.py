"""Mouse trajectory engine — smooth, predictable, minimal mouse movement.

The spec's core rule: the mouse is a CONTINUOUS trajectory, not a collection
of teleported clicks. This module provides:

    • deterministic easing curves (no random zigzag, no artificial slowness)
    • smooth move_to with optional waypoints
    • a dedicated drag() that RE-RESOLVES the target right before the drop and
      refuses stale/moved targets instead of injecting blindly
    • wheel scrolling at a specific position
    • click / double-click / right-click / type / hotkey via Win32 mouse_event
      with a pyautogui fallback

Duration is derived from distance and task type: short moves are fast, longer
drags are smooth but efficient.
"""

from __future__ import annotations

import math
import platform
import time
from typing import Callable, Optional

_WINDOWS = platform.system() == "Windows"


# ── easing curves ────────────────────────────────────────────────────────────
def _ease_linear(t: float) -> float:
    return t


def _ease_out_cubic(t: float) -> float:
    u = 1 - t
    return 1 - u * u * u


def _ease_in_cubic(t: float) -> float:
    return t * t * t


def _ease_in_out_quad(t: float) -> float:
    return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2


def _ease_out_quad(t: float) -> float:
    return 1 - (1 - t) * (1 - t)


def _ease_smoothstep(t: float) -> float:
    return t * t * (3 - 2 * t)


def _ease_missile(t: float) -> float:
    """Missile lock-on: fast at launch, decelerating hard as it homes in."""
    u = 1 - t
    return 1 - u * u * u * u


EASINGS: dict[str, Callable[[float], float]] = {
    "linear": _ease_linear,
    "ease_out_cubic": _ease_out_cubic,
    "ease_in_cubic": _ease_in_cubic,
    "ease_in_out_quad": _ease_in_out_quad,
    "ease_out_quad": _ease_out_quad,
    "smoothstep": _ease_smoothstep,
    "missile": _ease_missile,
}


def trajectory_points(start: tuple[int, int], end: tuple[int, int],
                      steps: int = 24, easing: str = "ease_out_cubic",
                      waypoints: Optional[list[tuple[int, int]]] = None) -> list[tuple[int, int]]:
    """Deterministic interpolated path P0 → P1 → … → target.

    waypoints (optional) bend the path; the curve always ends exactly on the
    target. No randomness anywhere.
    """
    ease = EASINGS.get(easing, _ease_out_cubic)
    points = [tuple(int(v) for v in start),
              *[tuple(int(v) for v in w) for w in (waypoints or [])],
              tuple(int(v) for v in end)]
    steps = max(2, int(steps))
    out: list[tuple[int, int]] = []
    n = len(points) - 1
    for i in range(steps + 1):
        t = ease(i / steps)
        seg = min(int(t * n), max(0, n - 1))
        lt = t * n - seg
        x0, y0 = points[seg]
        x1, y1 = points[seg + 1]
        out.append((int(round(x0 + (x1 - x0) * lt)), int(round(y0 + (y1 - y0) * lt))))
    out[-1] = (int(end[0]), int(end[1]))
    return out


def duration_for(distance: float, task: str = "move") -> float:
    """Distance-aware duration. Short moves snap; long drags glide."""
    if task == "drag":
        return min(0.25 + distance * 0.0016, 0.9)
    if task == "click":
        return min(0.03 + distance * 0.0006, 0.28)
    return min(0.05 + distance * 0.0012, 0.45)


def _point_dist(a: tuple[int, int], b: tuple[int, int]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


class MouseTrajectory:
    """Smooth Win32 mouse control. Falls back to pyautogui when unavailable."""

    def __init__(self, use_pyautogui_fallback: bool = True) -> None:
        self._py = None
        self._user32 = None
        if _WINDOWS:
            try:
                import ctypes
                self._user32 = ctypes.windll.user32
            except Exception:
                self._user32 = None
        if self._user32 is None and use_pyautogui_fallback:
            try:
                import pyautogui  # noqa: F401
                self._py = "pyautogui"
            except Exception:
                self._py = None

    @property
    def available(self) -> bool:
        return self._user32 is not None or self._py is not None

    def position(self) -> tuple[int, int]:
        if self._user32 is not None:
            try:
                import ctypes
                from ctypes import wintypes
                pt = wintypes.POINT()
                if self._user32.GetCursorPos(ctypes.byref(pt)):
                    return (int(pt.x), int(pt.y))
            except Exception:
                pass
        if self._py:
            try:
                import pyautogui
                x, y = pyautogui.position()
                return (int(x), int(y))
            except Exception:
                pass
        return (0, 0)

    # ── smooth movement ───────────────────────────────────────────────────
    def move_to(self, x: int, y: int, duration: Optional[float] = None,
                easing: str = "ease_out_cubic",
                waypoints: Optional[list[tuple[int, int]]] = None,
                task: str = "move",
                on_move: Optional[Callable[[int, int], None]] = None) -> bool:
        """Move the cursor along a smooth deterministic trajectory.

        `on_move(x, y)` — if given — is invoked after every cursor update so
        callers (the grid targeting overlay, telemetry) can stream the real
        cursor position live while the mouse travels. Best-effort: a raising
        callback never stops the movement.
        """
        if not self.available:
            return False
        sx, sy = self.position()
        ex, ey = int(x), int(y)
        dist = _point_dist((sx, sy), (ex, ey))
        if dist < 1:
            return True
        dur = duration if duration is not None else duration_for(dist, task)
        steps = max(4, min(int(dist / 4), 80))
        pts = trajectory_points((sx, sy), (ex, ey), steps=steps,
                                easing=easing, waypoints=waypoints)
        delay = dur / max(1, len(pts) - 1)
        for px, py in pts:
            self._set_pos(px, py)
            if on_move is not None:
                try:
                    on_move(int(px), int(py))
                except Exception:
                    pass
            if delay > 0.002:
                time.sleep(delay)
        return True

    # ── click ─────────────────────────────────────────────────────────────
    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> bool:
        """Smoothly approach the point and click — no teleport, no wander."""
        if not self.available:
            return False
        self.move_to(x, y, task="click")
        flags = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010),
                 "middle": (0x0020, 0x0040)}
        fd, fu = flags.get(button, flags["left"])
        if self._user32 is not None:
            try:
                for _ in range(max(1, clicks)):
                    self._user32.mouse_event(fd, 0, 0, 0, 0)
                    self._user32.mouse_event(fu, 0, 0, 0, 0)
                    time.sleep(0.02)
                return True
            except Exception:
                return self._click_py(x, y, button, clicks)
        return self._click_py(x, y, button, clicks)

    def double_click(self, x: int, y: int) -> bool:
        return self.click(x, y, "left", clicks=2)

    # ── drag ──────────────────────────────────────────────────────────────
    def drag(self, src: tuple[int, int], dst: tuple[int, int],
             duration: Optional[float] = None, easing: str = "ease_in_out_quad",
             resolve_target: Optional[Callable[[tuple[int, int]], Optional[tuple[int, int]]]] = None,
             task: str = "drag") -> bool:
        """Press at source, glide to target, release.

        If resolve_target is given it is called immediately before the drop so
        a moving/stale target is re-acquired (or the drag is refused) rather
        than dropping on outdated coordinates.
        """
        if not self.available:
            return False
        final = dst
        if resolve_target is not None:
            try:
                fresh = resolve_target(dst)
            except Exception:
                fresh = None
            if fresh is None:
                return False   # target gone / moved beyond recovery — refuse
            final = fresh
        self.move_to(src[0], src[1], task="click")
        if not self._press("left"):
            return False
        try:
            self.move_to(final[0], final[1], duration=duration,
                         easing=easing, task=task)
        finally:
            self._release("left")
        return True

    # ── scroll ────────────────────────────────────────────────────────────
    def scroll(self, x: int, y: int, direction: str = "down", amount: int = 3) -> bool:
        """Move to (x, y) then inject wheel ticks there."""
        if not self.available:
            return False
        self.move_to(x, y, task="click")
        horizontal = direction in ("left", "right")
        # Positive wheel delta = forward = UP (vertical) / RIGHT (horizontal).
        sign = 1 if direction in ("up", "right") else -1
        ticks = max(1, int(amount))
        delta = sign * ticks * 120
        if self._user32 is not None:
            try:
                flag = 0x1000 if horizontal else 0x0800  # HWHEEL / WHEEL
                for _ in range(ticks):
                    self._user32.mouse_event(flag, 0, 0, delta, 0)
                return True
            except Exception:
                pass
        if self._py:
            try:
                import pyautogui
                clicks = ticks if direction in ("up", "right") else -ticks
                if horizontal:
                    pyautogui.hscroll(clicks)
                else:
                    pyautogui.scroll(clicks)
                return True
            except Exception:
                pass
        return False

    # ── typing ────────────────────────────────────────────────────────────
    def type_text(self, text: str, interval: float = 0.012) -> bool:
        """Type text; clipboard-paste long strings for speed and reliability."""
        if not self.available or not text:
            return False
        if len(text) > 20:
            try:
                import pyperclip
                pyperclip.copy(text)
                return self.hotkey(["ctrl", "v"])
            except Exception:
                pass
        try:
            import pyautogui
            pyautogui.typewrite(text, interval=interval)
            return True
        except Exception:
            pass
        if self._user32 is not None:
            try:
                for ch in text:
                    vk = ord(ch.upper()) if ch.isalpha() else ord(ch)
                    self._user32.keybd_event(vk, 0, 0, 0)
                    self._user32.keybd_event(vk, 0, 2, 0)
                    time.sleep(interval)
                return True
            except Exception:
                pass
        return False

    def hotkey(self, keys: list[str]) -> bool:
        """Press a combo like ["ctrl", "shift", "p"] (pyautogui fallback)."""
        if self._py:
            try:
                import pyautogui
                pyautogui.hotkey(*keys)
                return True
            except Exception:
                pass
        if self._user32 is not None:
            try:
                names = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
                         "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "space": 0x20,
                         "backspace": 0x08, "delete": 0x2E, "up": 0x26, "down": 0x28,
                         "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23,
                         "f5": 0x74, "f11": 0x7A, "f12": 0x7B}
                vks = []
                for k in keys:
                    k = (k or "").strip().lower()
                    if k in names:
                        vks.append(names[k])
                    elif len(k) == 1 and k.isalnum():
                        vks.append(ord(k.upper()))
                if not vks:
                    return False
                for vk in vks:
                    self._user32.keybd_event(vk, 0, 0, 0)
                for vk in reversed(vks):
                    self._user32.keybd_event(vk, 0, 2, 0)
                return True
            except Exception:
                pass
        return False

    # ── primitives ────────────────────────────────────────────────────────
    def _set_pos(self, x: int, y: int) -> bool:
        if self._user32 is not None:
            try:
                return bool(self._user32.SetCursorPos(int(x), int(y)))
            except Exception:
                pass
        if self._py:
            try:
                import pyautogui
                pyautogui.moveTo(int(x), int(y))
                return True
            except Exception:
                pass
        return False

    def _press(self, button: str = "left") -> bool:
        fd = {"left": 0x0002, "right": 0x0008, "middle": 0x0020}.get(button, 0x0002)
        if self._user32 is not None:
            try:
                self._user32.mouse_event(fd, 0, 0, 0, 0)
                return True
            except Exception:
                pass
        if self._py:
            try:
                import pyautogui
                pyautogui.mouseDown(button=button)
                return True
            except Exception:
                pass
        return False

    def _release(self, button: str = "left") -> bool:
        fu = {"left": 0x0004, "right": 0x0010, "middle": 0x0040}.get(button, 0x0004)
        if self._user32 is not None:
            try:
                self._user32.mouse_event(fu, 0, 0, 0, 0)
                return True
            except Exception:
                pass
        if self._py:
            try:
                import pyautogui
                pyautogui.mouseUp(button=button)
                return True
            except Exception:
                pass
        return False

    def _click_py(self, x: int, y: int, button: str, clicks: int) -> bool:
        if not self._py:
            return False
        try:
            import pyautogui
            pyautogui.click(x, y, button=button, clicks=clicks)
            return True
        except Exception:
            return False
