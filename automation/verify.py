"""Verification engine (spec 27).

Every important action needs a verification strategy. This module provides
cheap, dependency-free strategies first (window appeared / disappeared / state
change, element present via the hybrid controller, pixels changed) and only
falls back to heavier checks when asked.

    wait_until(cond, timeout)       — poll a condition
    window_exists / window_gone     — cheap native window checks
    element_present(controller, ..) — cheap UIA/native find
    pixels_changed(region)          — local frame differencing
    verify(action, target, ...)     — dispatch table per action kind
"""

from __future__ import annotations

import time
from typing import Callable, Optional


def wait_until(condition: Callable[[], bool], timeout: float = 8.0,
               interval: float = 0.2) -> bool:
    """Poll `condition` until True or timeout. State-based waiting — no
    arbitrary sleeps."""
    deadline = time.monotonic() + max(0.1, timeout)
    while time.monotonic() < deadline:
        try:
            if condition():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


class VerificationEngine:
    """Cheap-first verification for computer-use actions."""

    def __init__(self, native=None, controller=None) -> None:
        self._native = native
        self._controller = controller

    def _nat(self):
        if self._native is None:
            from automation.win32_native import NativeController
            self._native = NativeController()
        return self._native

    # ── window strategies ─────────────────────────────────────────────────
    def window_exists(self, title_fragment: str) -> bool:
        return self._nat().window_by_title(title_fragment) is not None

    def window_gone(self, title_fragment: str) -> bool:
        return self._nat().window_by_title(title_fragment) is None

    def window_state(self, title_fragment: str, expect: str) -> bool:
        """expect: minimized | maximized | visible | foreground | normal."""
        w = self._nat().window_by_title(title_fragment)
        if w is None:
            return False
        if expect == "minimized":
            return w.minimized
        if expect == "maximized":
            return w.maximized
        if expect == "foreground":
            return w.foreground
        if expect == "visible":
            return w.visible
        return not w.minimized and not w.maximized

    def process_alive(self, process_name: str) -> bool:
        try:
            import psutil
            name = process_name.lower()
            for p in psutil.process_iter(["name"]):
                try:
                    if (p.info.get("name") or "").lower() == name:
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    # ── element strategies ────────────────────────────────────────────────
    def element_present(self, description: str, window_title: str = "") -> bool:
        ctrl = self._controller
        if ctrl is None:
            from automation import get_controller
            ctrl = get_controller()
        try:
            res = ctrl.find(description, window_title=window_title)
            return bool(res.ok)
        except Exception:
            return False

    def element_gone(self, description: str, window_title: str = "") -> bool:
        ctrl = self._controller
        if ctrl is None:
            from automation import get_controller
            ctrl = get_controller()
        try:
            res = ctrl.find(description, window_title=window_title)
            return bool(res.data.get("not_found"))
        except Exception:
            return False

    # ── pixel strategies ──────────────────────────────────────────────────
    def pixels_changed(self, region=None, samples: int = 2,
                       interval: float = 0.15) -> bool:
        from automation.temporal import TemporalVision
        tv = TemporalVision()
        tv.snapshot(region)
        time.sleep(interval)
        return tv.changed(region)

    # ── dispatch ──────────────────────────────────────────────────────────
    def verify(self, kind: str, target: str = "", timeout: float = 8.0,
               expect: str = "") -> tuple[bool, str]:
        """Run the right strategy for the action kind. Returns
        (ok, human_detail) so callers can log honest verification.
        """
        kind = (kind or "").lower()
        if kind in ("open", "launch", "focus"):
            ok = wait_until(lambda: self.window_exists(target), timeout)
            return ok, (f"window '{target}' appeared" if ok
                        else f"window '{target}' did NOT appear")
        if kind in ("close", "quit"):
            ok = wait_until(lambda: self.window_gone(target), timeout)
            return ok, (f"window '{target}' gone" if ok
                        else f"window '{target}' still present")
        if kind in ("minimize", "maximize", "restore", "foreground"):
            exp = "minimized" if kind == "minimize" else \
                  "maximized" if kind == "maximize" else \
                  "foreground" if kind == "foreground" else "normal"
            ok = wait_until(lambda: self.window_state(target, exp), timeout)
            return ok, f"window '{target}' {exp}" if ok else f"window '{target}' NOT {exp}"
        if kind in ("click", "type", "drag", "scroll"):
            # Cheap screen change is the honest baseline for gesture actions.
            ok = self.pixels_changed()
            return ok, ("screen changed after action" if ok
                        else "screen unchanged after action")
        if kind in ("appear", "element", "found"):
            ok = wait_until(lambda: self.element_present(target), timeout)
            return ok, (f"element '{target}' present" if ok
                        else f"element '{target}' not found")
        if kind in ("disappear", "gone"):
            ok = wait_until(lambda: self.element_gone(target), timeout)
            return ok, (f"element '{target}' gone" if ok
                        else f"element '{target}' still present")
        if kind in ("process"):
            ok = wait_until(lambda: self.process_alive(target), timeout)
            return ok, (f"process '{target}' running" if ok
                        else f"process '{target}' not running")
        return True, "(no verification strategy for this action)"
