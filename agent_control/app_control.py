"""AppControlEngine — the universal Keys.ai Agent Control abstraction.

This is the single facade the AI tools use to take control of any
application. It wraps the existing automation stack (automation.get_engine →
UI Automation → native APIs → vision → smooth mouse/keyboard) and adds the
control-system behaviours:

    • control sessions   — take_control() / release_control() on a window,
                            visible animated gold border + watermark
    • SEE→UNDERSTAND→ACT→VERIFY loop with configurable intelligent recovery
    • state-based waits  — wait until a state appears (never fixed sleeps),
                            timeout from settings, adapts to slow machines
    • user takeover      — genuine user input pauses the agent, it never
                            fights the user
    • emergency stop     — global ESC / STOP cancel everything with priority
    • high-impact confirmation — send/delete/submit/... pause for the user
    • control history    — every action logged with status (privacy-scrubbed)

Nothing here is allowed to fake success: every method returns an honest
ActionResult and unsupported environments fail gracefully with a message
the AI repeats to the user.

The bridge (ControlOverlayBridge) is Qt-backed but optional — a NullBridge
keeps the whole engine runnable headless (tests, no GUI).
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from agent_control.settings import get_settings, settings_summary
from agent_control.action_log import get_history, SUCCESS, RUNNING, WAITING, FAILED, PAUSED, STOPPED
from agent_control.humour import get_humour
from agent_control.confirmation import get_gate
from agent_control.states import (
    get_machine, ui_status,
    IDLE, UNDERSTANDING, INSPECTING, PLANNING, CONTROL_ACTIVE, EXECUTING,
    VERIFYING, CONTINUE, RECOVER, COMPLETED, CONTROL_RELEASED, PAUSED as ST_PAUSED,
    USER_TAKEOVER, FAILED as ST_FAILED, STOPPED as ST_STOPPED,
)

# browsers we can hand tab-switching to (browser_control tool)
_BROWSER_PROCS = ("chrome", "msedge", "edge", "firefox", "opera", "brave", "vivaldi", "safari")


def _AR():
    """Lazy ActionResult import — keeps `import agent_control` free of the
    heavy automation stack (pywinauto etc.) so `import ui` stays light and
    non-Windows hosts don't break at startup."""
    from automation.base import ActionResult
    return ActionResult


def _is_ar(x) -> bool:
    from automation.base import ActionResult
    return isinstance(x, ActionResult)


def _ok(message, **kw):
    return _AR()(ok=True, message=message, **kw)


def _fail(message, **kw):
    return _AR()(ok=False, message=message, **kw)


class ControlStopped(Exception):
    """Raised internally when an emergency stop cancels the current action."""


class NullBridge:
    """No-UI bridge: everything is a silent no-op, confirmations fail honestly."""

    def set_status(self, text: str) -> None:
        pass

    def show(self, app_name: str, rect: tuple) -> None:
        pass

    def hide(self) -> None:
        pass

    def request_confirm(self, prompt: str, timeout: float, callback=None) -> str:
        if callback is not None:
            try:
                callback("cancel")
            except Exception:
                pass
        return "cancel"

    def highlight(self, x1: int, y1: int, x2: int, y2: int,
                  seconds: float = 1.2) -> None:
        pass   # headless — nothing to draw

    def target(self, from_rect, to_rect, seconds: float = 0.6) -> None:
        pass   # headless — nothing to animate

    def grid_target(self, from_rect, to_rect, seconds: float = 0.6) -> None:
        pass   # headless — no grid overlay to draw

    def grid_point(self, x: int, y: int) -> None:
        pass   # headless — no cursor crosshair

    def grid_hide(self) -> None:
        pass   # headless — nothing to hide

    def history_line(self, html: str) -> None:
        pass

    def log(self, msg: str) -> None:
        pass


def _quiet(*args, **kwargs):
    pass


class AppControlEngine:
    """The Agent Control Mode facade (spec §2)."""

    def __init__(self, bridge=None, settings=None, player=None,
                 log: Optional[Callable[..., None]] = None) -> None:
        self._bridge = bridge if bridge is not None else NullBridge()
        self._settings = settings if settings is not None else get_settings()
        self._player = player                  # KeysAIUI (optional) — write_log
        self._logfn = log or _quiet
        self._core = None
        self._session_app = ""
        self._session_hwnd = 0
        self._cancel = threading.Event()
        self._started = False

        self.machine = get_machine()
        self.history = get_history()
        self.humour = get_humour(self._settings)
        self.gate = get_gate(self._settings, self._bridge)
        self.emergency = self._get_emergency()
        self.detector = self.emergency.detector

        self.machine.on_transition(self._on_state_change)
        self.history.on_entry(self._on_history_entry)
        self.emergency.set_handler(self.emergency_stop)
        self._ensure_detector()

    # ── wiring / lifecycle ─────────────────────────────────────────────
    def _get_emergency(self):
        from agent_control.emergency import get_emergency
        return get_emergency()

    def _ensure_detector(self) -> None:
        """Start input hooks once (safe on non-Windows: no-op)."""
        if not self._started:
            try:
                self.emergency.start()
            except Exception:
                pass
            self._started = True

    def set_bridge(self, bridge) -> None:
        self._bridge = bridge if bridge is not None else NullBridge()
        self.gate.attach(self._bridge)
        # replay current state onto the new bridge
        try:
            text, _ = ui_status(self.machine.state)
            self._bridge.set_status("KEYS.AI • " + text)
            if self.machine.is_active() and self._session_hwnd:
                self._bridge.show(self._session_app, self._window_rect())
        except Exception:
            pass

    def set_player(self, player) -> None:
        self._player = player

    # ── low-level helpers ──────────────────────────────────────────────
    def core(self):
        """Lazily create the underlying ComputerUseEngine (automation stack)."""
        if self._core is None:
            from automation import get_engine
            self._core = get_engine(log=self._logfn)
        return self._core

    def _log(self, msg: str) -> None:
        self._logfn(msg)
        print(f"[AgentControl] {msg}")
        if self._player is not None and hasattr(self._player, "write_log"):
            try:
                self._player.write_log(f"SYS: {msg[:140]}")
            except Exception:
                pass

    def _status_text(self, state: Optional[str] = None) -> str:
        text, _ = ui_status(state or self.machine.state)
        return "KEYS.AI • " + text

    # ── state change → bridge ──────────────────────────────────────────
    def _on_state_change(self, old: str, new: str) -> None:
        try:
            if new in (CONTROL_RELEASED, COMPLETED, IDLE):
                self._bridge.hide()
                self._bridge.set_status("KEYS.AI • CONTROL RELEASED")
            elif new == ST_STOPPED:
                self._bridge.hide()
                self._bridge.set_status("KEYS.AI • STOPPED")
            elif new == ST_FAILED:
                # keep the border + FAILED pill visible so the user can see
                # where things stopped until control is released
                self._bridge.set_status("KEYS.AI • ACTION FAILED")
            else:
                self._bridge.set_status(self._status_text(new))
        except Exception:
            pass

    def _on_history_entry(self, entry: dict) -> None:
        try:
            self._bridge.history_line(entry)
        except Exception:
            pass

    # ── session / window geometry ──────────────────────────────────────
    def _window_rect(self) -> tuple:
        if not self._session_hwnd:
            return (0, 0, 0, 0)
        try:
            for w in self.core().native().list_windows():
                if w.hwnd == self._session_hwnd:
                    l, t, r, b = w.rect
                    return (int(l), int(t), max(0, int(r - l)), max(0, int(b - t)))
        except Exception:
            pass
        return (0, 0, 0, 0)

    def _active_window(self):
        try:
            return self.core().native().foreground_window()
        except Exception:
            return None

    # ── guards ─────────────────────────────────────────────────────────
    def _guard(self) -> Optional[str]:
        """Pre-action checks. Returns an honest message string to abort with,
        or None to proceed."""
        if self._cancel.is_set() or self.machine.state == ST_STOPPED:
            self._cancel.clear()   # a fresh tool call may continue after STOP
            return "Automation was stopped. Use 'release' or start a new task to continue."
        if self.detector.user_intervened():
            self.machine.transition(USER_TAKEOVER)
            self._bridge.set_status("KEYS.AI • USER CONTROL")
            self.history.add(self._session_app, "pause", "user took control", PAUSED)
            return ("You've taken control, so I paused immediately — I won't "
                    "fight your input. Say continue to let me resume.")
        if self.machine.state in (ST_PAUSED, USER_TAKEOVER):
            return ("Control is paused. Say continue (or use 'resume') to "
                    "let me carry on.")
        return None

    def _ensure_control(self) -> Optional[ActionResult]:
        """Auto-take control of the active window before an interaction.
        Never auto-resumes after an emergency STOP — the user must explicitly
        start a new task."""
        if self.machine.is_active() or self.machine.state == ST_STOPPED:
            return None
        return self.take_control(None)

    # ── SEE→UNDERSTAND→ACT→VERIFY loop ─────────────────────────────────
    # gesture kinds where re-executing after a failed visual check would be
    # dangerous (double-send / double-click) — we never re-run those on
    # verification failure, we report honestly instead.
    GESTURE_KINDS = ("click", "type", "scroll", "drag")

    def act_and_verify(self, app: str, action: str, fn: Callable[[], object],
                       verify: Optional[Callable[[], object]] = None,
                       detail: str = "", retries: Optional[int] = None,
                       verify_kind: str = "", verify_target: str = "",
                       verify_timeout: float = 8.0):
        """Run fn with retries, verifying the outcome, recovering intelligently.

        Returns the first verified-success ActionResult, or an honest failure
        with the reason after the configured retry limit. Never infinite.
        """
        guard = self._guard()
        if guard:
            return _fail(guard)
        self.machine.transition(EXECUTING)
        max_retry = self._settings.get("retry_limit", 3)
        if retries is not None:
            max_retry = max(0, min(10, int(retries)))

        def _verifier():
            if verify is not None:
                return verify()
            if verify_kind and verify_target:
                return self.core().wait_for(verify_kind, verify_target,
                                            timeout=verify_timeout)
            return _ok("ok")

        last_msg = ""
        for attempt in range(max_retry + 1):
            if self._cancel.is_set():
                raise ControlStopped()
            # each attempt (including after RECOVER) runs in EXECUTING so the
            # VERIFYING / CONTINUE transitions below are always valid
            if not self.machine.transition(EXECUTING):
                self.machine.force(EXECUTING)
            tak = self.detector.user_intervened()
            if tak:
                self.machine.transition(USER_TAKEOVER)
                self._bridge.set_status("KEYS.AI • USER CONTROL")
                self.history.add(app, action, "user took control", PAUSED)
                return _fail("You took control mid-action — paused so I never "
                             "fight you. Say continue to resume.")
            self.detector.mark_agent_action()
            note = detail if attempt == 0 else f"retry {attempt}: {detail}"
            entry = self.history.add(app, action, note, RUNNING)
            try:
                res = fn()
            except ControlStopped:
                raise
            except Exception as e:
                res = _fail(f"{type(e).__name__}: {e}")
            self.detector.mark_agent_action()

            if res.ok:
                self.machine.transition(VERIFYING)
                self._bridge.set_status("KEYS.AI • VERIFYING")
                try:
                    vres = _verifier()
                    verified = vres.ok if _is_ar(vres) else bool(vres)
                except Exception:
                    verified = False
                    vres = _fail("verification raised")
                if verified:
                    self.history.update_status(entry, SUCCESS)
                    self.machine.transition(CONTINUE)
                    self._bridge.set_status("KEYS.AI • EXECUTING")
                    c = self.humour_tick("success", app)
                    if c:
                        res.data["humour"] = c
                    return res
                last_msg = (f"action reported ok but verification failed"
                            f" ({getattr(vres, 'message', '')})")
                # For gestures we NEVER re-execute on a failed visual check
                # (that is how double-sends happen). One honest re-inspection,
                # then report "executed but unverified".
                if verify_kind in self.GESTURE_KINDS and verify is None:
                    self._recover_inspect(app)
                    self.history.update_status(entry, WAITING)
                    self.history.add(app, action,
                                     "executed but could not verify the screen change",
                                     WAITING)
                    c = self.humour_tick("verify", app)
                    extra = {}
                    if c:
                        extra["humour"] = c
                    return _ok(f"The {action} was executed, but I could not visually "
                               f"confirm the change on screen. {last_msg}", **extra)
            else:
                last_msg = res.message
            # ── RECOVER: re-inspect the app, re-find, retry intelligently ──
            self.machine.transition(RECOVER)
            self._bridge.set_status("KEYS.AI • RECOVERING")
            self.history.update_status(entry, FAILED)
            self._recover_inspect(app)
            if attempt < max_retry:
                # adaptive: short settle, then retry
                time.sleep(min(0.8 + attempt * 0.4, 2.5))

        self.machine.transition(ST_FAILED)
        self._bridge.set_status("KEYS.AI • ACTION FAILED")
        self.history.add(app, action,
                         f"failed after {max_retry + 1} attempt(s): {last_msg}",
                         FAILED)
        c = self.humour_tick("error", app)
        if c:
            return _fail(f"'{action}' could not be completed after {max_retry + 1} "
                         f"attempt(s). {last_msg}",
                         data={"humour": c})
        return _fail(f"'{action}' could not be completed after {max_retry + 1} "
                     f"attempt(s). {last_msg}")

    def _recover_inspect(self, app: str) -> None:
        """Cheap re-observation so the next attempt works on fresh state."""
        try:
            self.core().observe()
            self.history.add(app, "recover", "re-inspecting the screen", WAITING)
        except Exception:
            pass

    # ── humour helper ──────────────────────────────────────────────────
    def humour_tick(self, event: str, app: str = "") -> Optional[str]:
        """Ask the humour engine for a comment (None = stay silent)."""
        try:
            return self.humour.comment(event, app=app or self._session_app)
        except Exception:
            return None

    # ── control session (spec §1, §9, §10) ─────────────────────────────
    def take_control(self, app: Optional[str] = None,
                     human: Optional[Callable[[str], None]] = None) -> ActionResult:
        """Take visible control of an app (or the active window)."""
        if self.machine.state == ST_STOPPED:
            self.machine.transition(IDLE)
        win = None
        try:
            nat = self.core().native()
            win = nat.foreground_window() if not app else nat.window_by_title(app)
        except Exception as e:
            return _fail(f"Could not reach the window manager: {e}")
        if win is None:
            return _fail(f"Application '{app or 'the active window'}' not found "
                         f"— I can see apps but nothing to control right now.")
        self._session_app = win.process or win.title or str(win.hwnd)
        self._session_hwnd = win.hwnd
        if not self.machine.transition(CONTROL_ACTIVE):
            self.machine.force(CONTROL_ACTIVE)
        self.core().set_context("app", self._session_app)
        self.core().set_context("control", "active")
        if self._settings.get("overlay_enabled", True):
            try:
                self._bridge.show(self._session_app, self._window_rect())
            except Exception:
                pass
        self.history.add(self._session_app, "take_control", "control active", SUCCESS)
        self._log(f"Control taken: {self._session_app} (hwnd={win.hwnd})")
        return _ok(f"Control of {self._session_app} is active — the gold border "
                   f"shows it. Tell me what to do next, or I'll follow your task.",
                   data={"app": self._session_app, "hwnd": win.hwnd})

    def release_control(self) -> ActionResult:
        app = self._session_app
        self._session_app = ""
        self._session_hwnd = 0
        if not self.machine.transition(CONTROL_RELEASED):
            self.machine.force(CONTROL_RELEASED)
        self._bridge.hide()
        self.grid_hide()   # the targeting grid never lingers after control ends
        try:
            self.core().set_context("control", "released")
        except Exception:
            pass
        self.history.add(app, "release_control", "control returned to user", SUCCESS)
        self._log("Control released.")
        return _ok(f"Control released — {app or 'the application'} is all yours again.")

    # ── stop / pause / resume (spec §9, §10) ───────────────────────────
    def emergency_stop(self) -> None:
        """Global ESC / STOP handler — has priority over everything."""
        try:
            if not self.machine.is_active():
                return
            self._cancel.set()
            self.machine.force(ST_STOPPED)
            self._bridge.hide()
            self.grid_hide()   # never leave the targeting grid up after STOP
            self._bridge.set_status("KEYS.AI • STOPPED")
            app = self._session_app
            self.history.add(app, "stop", "emergency stop (ESC / STOP)", STOPPED)
            self.core().set_context("control", "stopped")
            self._log("EMERGENCY STOP — automation cancelled.")
        except Exception:
            pass

    def stop(self) -> ActionResult:
        self.emergency_stop()
        return _ok("Automation stopped. Control released — you're back in "
                   "charge. ESC / STOP are always available.")

    def pause(self, why: str = "paused by request") -> ActionResult:
        if self.machine.is_running():
            self.machine.transition(ST_PAUSED)
        self._bridge.set_status("KEYS.AI • PAUSED")
        self.history.add(self._session_app, "pause", why, PAUSED)
        return _ok("Paused. Say continue to resume, or stop to end the task.")

    def resume(self) -> ActionResult:
        if self.machine.state == ST_STOPPED:
            return _fail("The task was stopped — start a new one with "
                         "'take_control' to continue.")
        if not self.machine.transition(EXECUTING):
            self.machine.force(EXECUTING)
        self._bridge.set_status("KEYS.AI • EXECUTING")
        self.history.add(self._session_app, "resume", "resumed", SUCCESS)
        return _ok("Resumed — continuing the task.")

    def user_takeover(self) -> ActionResult:
        """TAKE CONTROL button / user request — hand the app back immediately."""
        self.machine.force(USER_TAKEOVER)
        self._bridge.set_status("KEYS.AI • USER CONTROL")
        self.history.add(self._session_app, "takeover", "user requested control", PAUSED)
        return _ok("You're in control now — I've stepped back and won't touch "
                   "anything until you say continue.")

    # ── perception (spec §3, §4) ───────────────────────────────────────
    def detect_active_window(self) -> ActionResult:
        try:
            return self.core().active_app()
        except Exception as e:
            return _fail(f"Could not detect the active window: {e}")

    def get_active_application(self) -> str:
        try:
            r = self.core().active_app()
            d = r.data or {}
            return d.get("process") or d.get("title") or (r.message or "unknown")
        except Exception:
            return "unknown"

    def inspect_screen(self, deep: bool = False) -> ActionResult:
        """Cheap window-level view; `deep=True` adds a vision/OCR description."""
        try:
            state = self.core().observe()
            active = self.core().active_app()
            lines = [f"ACTIVE: {active.message}" if active.ok else "ACTIVE: unknown",
                     f"STATE: {state.message}"]
            if deep:
                try:
                    desc = self.core().controller().describe_screen()
                    if desc.ok:
                        lines.append("SCREEN: " + desc.message[:1200])
                except Exception as e:
                    lines.append(f"SCREEN: (vision unavailable: {e})")
            return _ok("\n".join(lines),
                       data={"active": active.data if active.ok else {},
                             "state": state.data if state.ok else {}})
        except Exception as e:
            return _fail(f"Inspect failed: {e}")

    def inspect_accessibility(self, window: str = "") -> ActionResult:
        try:
            return self.core().controller().list_elements(window)
        except Exception as e:
            return _fail(f"Accessibility inspection unavailable: {e}")

    def find_element(self, description: str, window: str = "",
                     uia_only: bool = False) -> ActionResult:
        """Locate an element via the hybrid chain.

        `uia_only=True` skips the vision/OCR backends (no screenshots) so
        screen control can re-check UI Automation cheaply before spending a
        fresh screenshot on the one-shot scene analysis.
        """
        if not description:
            return _fail("Provide an element description to find.")
        guard = self._guard()
        if guard:
            return _fail(guard)
        if not self.machine.transition(INSPECTING):
            self.machine.force(INSPECTING)
        self.detector.mark_agent_action()
        return self.core().find(description, window=window, uia_only=uia_only)

    def highlight_box(self, x1: int, y1: int, x2: int, y2: int,
                      seconds: float = 1.2) -> None:
        """Draw a visible yellow target box around a screen region — the user
        sees EXACTLY what the agent found and is about to click."""
        try:
            self._bridge.highlight(int(x1), int(y1), int(x2), int(y2),
                                   float(seconds))
        except Exception:
            pass

    def target_box(self, from_rect, to_rect, seconds: float = 0.6) -> None:
        """Animate a missile-style reticle (small square border) gliding from
        `from_rect` and locking onto `to_rect` (both (x1,y1,x2,y2) screen
        coords) — the selection animation shown right before every click, so
        the whole takeover feels the same. Falls back to a static highlight
        when the bridge has no animated reticle support."""
        try:
            if hasattr(self._bridge, "target"):
                self._bridge.target(from_rect, to_rect, float(seconds))
                return
        except Exception:
            pass
        try:
            x1, y1, x2, y2 = (int(v) for v in to_rect)
            self._bridge.highlight(x1, y1, x2, y2, float(seconds))
        except Exception:
            pass

    def grid_target(self, from_rect, to_rect, seconds: float = 0.6) -> None:
        """Show the full-screen targeting GRID and highlight the cell the
        mouse is about to enter. The grid + selected cell + live crosshair
        make every mouse move visible and predictable. Best-effort: skipped
        when the overlay is disabled or no GUI bridge is attached."""
        if not self._settings.get("overlay_enabled", True):
            return
        try:
            self._bridge.grid_target(from_rect, to_rect, float(seconds))
        except Exception:
            pass

    def grid_point(self, x: int, y: int) -> None:
        """Stream the real cursor position onto the grid overlay."""
        try:
            self._bridge.grid_point(int(x), int(y))
        except Exception:
            pass

    def grid_hide(self) -> None:
        """Hide the targeting grid after the mouse move is done."""
        try:
            self._bridge.grid_hide()
        except Exception:
            pass

    # ── interaction (spec §1) ──────────────────────────────────────────
    def move_mouse(self, x: int, y: int) -> ActionResult:
        ensure = self._ensure_control()
        if ensure is not None and not ensure.ok:
            return ensure
        return self.act_and_verify(
            self._session_app, "move_mouse",
            lambda: self.core().move_smooth(int(x), int(y)),
            detail=f"({x}, {y})")

    def click(self, description: str = "", x: Optional[int] = None,
              y: Optional[int] = None, button: str = "left",
              clicks: int = 1, verify: bool = True) -> ActionResult:
        ensure = self._ensure_control()
        if ensure is not None and not ensure.ok:
            return ensure
        if button == "right":
            return self.right_click(description, x, y)
        if clicks >= 2:
            return self.double_click(description, x, y)
        kind = description or f"({x}, {y})"
        return self.act_and_verify(
            self._session_app, "click", lambda: self.core().click(
                description=description, x=x, y=y, button="left",
                verify_screen=False),
            detail=kind,
            verify_kind="click", verify_target="")

    def double_click(self, description: str = "", x: Optional[int] = None,
                     y: Optional[int] = None) -> ActionResult:
        ensure = self._ensure_control()
        if ensure is not None and not ensure.ok:
            return ensure

        def _do():
            motion = self.core().motion()
            if description:
                res = self.core().find(description)
                if not res.ok:
                    return res
                el = res.data.get("element") or {}
                rect = el.get("rect")
                if not rect or not rect.get("width"):
                    return _fail(f"Found '{description}' but no clickable point.")
                px, py = int(rect["x"] + rect["width"] / 2), \
                    int(rect["y"] + rect["height"] / 2)
                return _ok("ok") if motion.double_click(px, py) \
                    else _fail("double-click failed")
            if x is None or y is None:
                return _fail("Provide an element description or x/y.")
            return _ok("ok") if motion.double_click(int(x), int(y)) \
                else _fail("double-click failed")
        return self.act_and_verify(self._session_app, "double_click", _do,
                                   detail=description or f"({x}, {y})",
                                   verify_kind="click", verify_target="")

    def right_click(self, description: str = "", x: Optional[int] = None,
                    y: Optional[int] = None) -> ActionResult:
        ensure = self._ensure_control()
        if ensure is not None and not ensure.ok:
            return ensure

        def _do():
            motion = self.core().motion()
            if description:
                res = self.core().find(description)
                if not res.ok:
                    return res
                el = res.data.get("element") or {}
                rect = el.get("rect")
                if not rect or not rect.get("width"):
                    return _fail(f"Found '{description}' but no clickable point.")
                px, py = int(rect["x"] + rect["width"] / 2), \
                    int(rect["y"] + rect["height"] / 2)
                return _ok("ok") if motion.click(px, py, button="right") \
                    else _fail("right-click failed")
            if x is None or y is None:
                return _fail("Provide an element description or x/y.")
            return _ok("ok") if motion.click(int(x), int(y), button="right") \
                else _fail("right-click failed")
        return self.act_and_verify(self._session_app, "right_click", _do,
                                   detail=description or f"({x}, {y})",
                                   verify_kind="click", verify_target="")

    def type(self, text: str, description: str = "", x: Optional[int] = None,
             y: Optional[int] = None, private: bool = False) -> ActionResult:
        ensure = self._ensure_control()
        if ensure is not None and not ensure.ok:
            return ensure
        detail = "***" if private or _looks_secret(text) else text[:48]
        return self.act_and_verify(
            self._session_app, "type",
            lambda: self.core().type(text, description=description, x=x, y=y),
            detail=detail, verify_kind="type", verify_target="")

    def press_key(self, key: str) -> ActionResult:
        ensure = self._ensure_control()
        if ensure is not None and not ensure.ok:
            return ensure
        return self.act_and_verify(
            self._session_app, "press", lambda: self.core().motion().hotkey([key]),
            detail=f"key '{key}'")

    def hotkey(self, keys: str) -> ActionResult:
        ensure = self._ensure_control()
        if ensure is not None and not ensure.ok:
            return ensure
        return self.act_and_verify(
            self._session_app, "hotkey",
            lambda: self.core().controller().hotkey(keys),
            detail=keys)

    def select_text(self, all_text: bool = True) -> ActionResult:
        ensure = self._ensure_control()
        if ensure is not None and not ensure.ok:
            return ensure
        combo = ["ctrl", "a"] if all_text else ["ctrl", "shift", "home"]
        return self.act_and_verify(
            self._session_app, "select_text",
            lambda: self.core().motion().hotkey(combo),
            detail="select all" if all_text else "select to start")

    def copy(self) -> ActionResult:
        ensure = self._ensure_control()
        if ensure is not None and not ensure.ok:
            return ensure
        return self.act_and_verify(self._session_app, "copy",
                                   lambda: self.core().motion().hotkey(["ctrl", "c"]),
                                   detail="copied selection")

    def paste(self) -> ActionResult:
        ensure = self._ensure_control()
        if ensure is not None and not ensure.ok:
            return ensure
        return self.act_and_verify(self._session_app, "paste",
                                   lambda: self.core().motion().hotkey(["ctrl", "v"]),
                                   detail="pasted clipboard")

    def scroll(self, direction: str = "down", amount: int = 3,
               target: str = "") -> ActionResult:
        # Validate arguments BEFORE taking control — a bad direction must not
        # grab the desktop (or report "app not found") when the real problem
        # is the parameter.
        direction = (direction or "down").lower()
        if direction not in ("up", "down", "left", "right"):
            return _fail(f"Scroll direction must be up|down|left|right (got '{direction}').")
        ensure = self._ensure_control()
        if ensure is not None and not ensure.ok:
            return ensure
        return self.act_and_verify(
            self._session_app, "scroll",
            lambda: self.core().scroll_to(target=target, direction=direction,
                                          amount=int(amount)),
            detail=f"{direction} ×{amount}", verify_kind="scroll", verify_target="")

    def drag(self, source: str = "", destination: str = "",
             source_xy: Optional[tuple] = None,
             destination_xy: Optional[tuple] = None) -> ActionResult:
        ensure = self._ensure_control()
        if ensure is not None and not ensure.ok:
            return ensure
        return self.act_and_verify(
            self._session_app, "drag",
            lambda: self.core().drag(src_desc=source, dst_desc=destination,
                                     src_xy=source_xy, dst_xy=destination_xy),
            detail=f"{source or source_xy} → {destination or destination_xy}",
            verify_kind="drag", verify_target="")

    def switch_window(self, target: str) -> ActionResult:
        return self.act_and_verify(
            self._session_app or target, "switch_window",
            lambda: self.core().window_op(target, "focus"),
            detail=target, verify_kind="foreground", verify_target=target)

    def switch_tab(self, direction: str = "next", index: Optional[int] = None,
                   browser: str = "") -> ActionResult:
        """Browser-aware tab switching; generic ctrl+tab fallback."""
        proc = (browser or self.get_active_application() or "").lower()
        if index is not None or any(p in proc for p in _BROWSER_PROCS):
            try:
                from actions.browser_control import browser_control as bc
                params = {"action": "switch_tab"}
                if index is not None:
                    params["index"] = int(index)
                if any(p in proc for p in _BROWSER_PROCS):
                    params["browser"] = next((p for p in _BROWSER_PROCS if p in proc), "")
                r = bc(parameters=params, player=self._player)
                if "error" not in r.lower() and "failed" not in r.lower():
                    return _ok(r)
            except Exception as e:
                self._log(f"browser switch_tab fallback: {e}")
        combo = ["ctrl", "tab"] if direction != "prev" else ["ctrl", "shift", "tab"]
        return self.act_and_verify(
            self._session_app, "switch_tab",
            lambda: self.core().motion().hotkey(combo),
            detail=f"tab {direction}")

    def open_application(self, name: str) -> ActionResult:
        if not name:
            return _fail("Provide an app name to open.")
        try:
            from actions.open_app import open_app
            r = open_app(parameters={"app_name": name}, response=None,
                         player=self._player)
            if not r or r.lower().startswith("no "):
                return _fail(r or "Could not open the application.")
            self.history.add(name, "open_app", "launched", SUCCESS)
            return _ok(r)
        except Exception as e:
            return _fail(f"open '{name}' failed: {e}")

    # ── waiting / verification (spec §13, §14) ─────────────────────────
    def wait_for_element(self, description: str, window: str = "",
                         timeout: Optional[float] = None) -> ActionResult:
        t = timeout or float(self._settings.get("max_wait_timeout", 30.0))
        if not self.machine.transition(INSPECTING):
            self.machine.force(INSPECTING)
        self._bridge.set_status("KEYS.AI • WAITING")
        self.history.add(self._session_app, "wait", f"waiting for '{description}'", WAITING)
        res = self.core().wait_for("element", description, timeout=t)
        self.history.add(self._session_app, "wait",
                         f"'{description}' appeared" if res.ok
                         else f"'{description}' not found in {t:.0f}s",
                         SUCCESS if res.ok else FAILED)
        return res

    def verify_action(self, kind: str, target: str = "",
                      timeout: Optional[float] = None) -> ActionResult:
        if kind not in ("open", "close", "element", "process", "minimize",
                        "maximize", "foreground", "click", "type", "drag", "scroll"):
            return _fail(f"Unknown verify kind '{kind}'.")
        t = timeout or float(self._settings.get("max_wait_timeout", 30.0))
        if not self.machine.transition(VERIFYING):
            self.machine.force(VERIFYING)
        self._bridge.set_status("KEYS.AI • VERIFYING")
        self.history.add(self._session_app, "verify", f"{kind} '{target}'", WAITING)
        return self.core().wait_for(kind, target, timeout=t)

    # ── confirmation (spec §11) ────────────────────────────────────────
    def confirm_high_impact(self, action: str = "", description: str = "",
                            prompt: str = "", timeout: float = 60.0) -> str:
        """Returns gate RESULT_*: confirm | cancel | takeover | timeout."""
        if not self.gate.needs_confirmation(action, description):
            return "confirm"
        self._bridge.set_status("KEYS.AI • WAITING")
        result = self.gate.request(action, description, prompt, timeout)
        self.history.add(self._session_app, action or "confirm",
                         f"confirmation: {result}", SUCCESS if result == "confirm"
                         else PAUSED if result == "takeover" else WAITING)
        return result

    # ── status / observability ─────────────────────────────────────────
    def status(self) -> ActionResult:
        s = self._settings
        return _ok(
            f"STATE: {self.machine.state} | APP: {self._session_app or 'none'}\n"
            f"{settings_summary(s)}\nHISTORY: {self.history.count()} entries",
            data={"state": self.machine.state,
                  "app": self._session_app,
                  "settings": s.snapshot(),
                  "history_count": self.history.count()})

    def history_log(self, limit: int = 24) -> ActionResult:
        return _ok(self.history.render(limit),
                   data={"entries": self.history.recent(limit)})

    def clear_history(self) -> ActionResult:
        self.history.clear()
        return _ok("Control history cleared.")

    def humour_comment(self, event: str, app: str = "") -> Optional[str]:
        return self.humour.sample(event, app or self._session_app)


def _looks_secret(text: str) -> bool:
    if not text:
        return False
    import re
    return bool(re.search(r"(api[_-]?key|password|passwd|secret|token|bearer)"
                          r"|=.*AIza|ghp_|sk-", text, re.I))


_engine: Optional[AppControlEngine] = None
_engine_lock = threading.Lock()


def get_control_engine(bridge=None, settings=None, player=None,
                       log: Optional[Callable[..., None]] = None) -> AppControlEngine:
    """Shared AppControlEngine singleton."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = AppControlEngine(bridge=bridge, settings=settings,
                                           player=player, log=log)
    if bridge is not None:
        _engine.set_bridge(bridge)
    if player is not None:
        _engine.set_player(player)
    return _engine


def init_control_system(bridge=None, player=None) -> AppControlEngine:
    """Convenience used by the UI at startup: creates the engine with the
    Qt bridge attached (safe to call repeatedly)."""
    return get_control_engine(bridge=bridge, player=player)


def reset_control_engine() -> None:
    global _engine
    with _engine_lock:
        _engine = None
