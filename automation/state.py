"""Screen & world state tracking (spec 20, 26).

Keys.ai must never reset its understanding after every action. This module
maintains a lightweight CurrentScreenState (active window, cursor, visible
windows, motion regions, last action) and a WorldState context stack
("I am in VS Code", "the terminal is focused"). Updates are cheap and only
what changed is recorded.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


def _now() -> float:
    return time.monotonic()


@dataclass
class ScreenState:
    """A cheap snapshot of what is on the user's desktop right now."""

    active_hwnd: int = 0
    active_title: str = ""
    active_process: str = ""
    cursor: tuple[int, int] = (0, 0)
    cursor_moved: bool = False
    window_rect: tuple = (0, 0, 0, 0)
    visible_windows: list[str] = field(default_factory=list)
    motion_regions: list = field(default_factory=list)
    text_changes: list[str] = field(default_factory=list)
    ts: float = 0.0

    def describe(self) -> str:
        bits = []
        if self.active_title:
            bits.append(f"active: {self.active_title}")
            if self.active_process:
                bits.append(f"({self.active_process})")
        if self.cursor != (0, 0):
            bits.append(f"cursor: {self.cursor}")
        if self.motion_regions:
            bits.append(f"motion: {len(self.motion_regions)} region(s)")
        if self.text_changes:
            bits.append("text changed")
        return " ".join(bits) or "(idle desktop)"

    def to_dict(self) -> dict:
        return {
            "active_hwnd": self.active_hwnd,
            "active_title": self.active_title,
            "active_process": self.active_process,
            "cursor": list(self.cursor),
            "cursor_moved": self.cursor_moved,
            "visible_windows": self.visible_windows[:10],
            "motion_regions": [list(r) for r in self.motion_regions[:5]],
            "text_changes": self.text_changes[:5],
        }

    def relevant_changed(self, other: "ScreenState") -> bool:
        """True when something an AI action might care about changed.

        Used as a gate BEFORE any vision/AI call: same window, same rect,
        same cursor and no motion means nothing to look at.
        """
        if self.active_hwnd != other.active_hwnd:
            return True
        if self.active_title != other.active_title:
            return True
        if self.window_rect != other.window_rect:
            return True
        if self.cursor != other.cursor:
            return True
        if self.motion_regions or other.motion_regions:
            return True
        if self.text_changes or other.text_changes:
            return True
        return False


class ScreenStateTracker:
    """Observes the desktop cheaply and only records what changed."""

    def __init__(self, native=None) -> None:
        self._native = native
        self.current: Optional[ScreenState] = None
        self.previous: Optional[ScreenState] = None
        self._last_cursor = (0, 0)

    def observe(self, motion_regions=None, text_changes=None) -> ScreenState:
        """Refresh the current state from the OS (cheap: one EnumWindows pass
        only when needed — the cursor check is free)."""
        from automation.win32_native import NativeController
        nat = self._native if self._native is not None else NativeController()
        cursor = nat.cursor_pos()
        moved = cursor != self._last_cursor
        self._last_cursor = cursor

        s = ScreenState(cursor=cursor, cursor_moved=moved, ts=_now())
        fg = nat.foreground_window()
        if fg:
            s.active_hwnd = fg.hwnd
            s.active_title = fg.title
            s.active_process = fg.process
            s.window_rect = fg.rect
        if motion_regions:
            s.motion_regions = motion_regions
        if text_changes:
            s.text_changes = text_changes
        self.previous = self.current
        self.current = s
        return s

    def changed(self) -> bool:
        """Cheap gate: did anything relevant change since the last observe?
        Same window + same cursor + no motion => False (skip AI/vision)."""
        if self.current is None or self.previous is None:
            return True
        return self.current.relevant_changed(self.previous)

    def summarize(self) -> str:
        return self.current.describe() if self.current else "(no state observed yet)"


class WorldState:
    """Persistent task context — the spec's 'maintain world state during tasks'.

    Holds facts like "I am in VS Code", "the terminal is focused", "the target
    file is open" so multi-step tasks don't rediscover the world every step.
    Facts are cheap strings set by the engine and can be listed by the AI.
    """

    def __init__(self) -> None:
        self.facts: dict[str, str] = {}
        self.last_action: Optional[dict] = None

    def set(self, key: str, value: str) -> None:
        self.facts[str(key)] = str(value)

    def get(self, key: str, default: str = "") -> str:
        return self.facts.get(str(key), default)

    def app(self, name: str) -> None:
        """Convenience: record which application we are working in."""
        self.set("app", name)
        self.set("last_window", name)

    def focused(self, target: str) -> None:
        self.set("focused", target)

    def remember_action(self, action: str, ok: bool, detail: str = "") -> None:
        self.last_action = {
            "action": action, "ok": bool(ok), "detail": detail, "ts": _now(),
        }

    def describe(self) -> str:
        lines = [f"{k}: {v}" for k, v in self.facts.items()]
        if self.last_action:
            la = self.last_action
            lines.append(f"last_action: {la['action']} -> "
                         f"{'ok' if la['ok'] else 'FAILED'} {la['detail']}")
        return "\n".join(lines) if lines else "(no context yet)"
