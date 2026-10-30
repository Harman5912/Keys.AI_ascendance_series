"""ComputerUseEngine — the central Keys.ai computer-use controller.

Composes the layers from the spec into ONE coherent facade:

    Application Discovery  -> NativeController (win32_native)
    Window Manager         -> NativeController
    UI Automation          -> HybridController (uia -> native -> vision -> input)
    Mouse Trajectory       -> MouseTrajectory (motion)
    Temporal/Motion        -> TemporalVision (temporal)
    Screen/World State     -> ScreenStateTracker + WorldState (state)
    Verification           -> VerificationEngine (verify)
    Safety/Elevation       -> automation.elevation
    Telemetry              -> telemetry
    App Adapters           -> VSCode / Terminal / Explorer

Every public method returns ActionResult (ok / message / data / backend) and
records an ActionTrace so the debug line (spec 44) is always available.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from automation.base import ActionResult
from automation.telemetry import get_telemetry


def _quiet(*args, **kwargs):
    pass


def _ok(message, **kw) -> ActionResult:
    return ActionResult(ok=True, message=message, **kw)


def _fail(message, **kw) -> ActionResult:
    return ActionResult(ok=False, message=message, **kw)


def _resolve_target(target, native) -> Optional[object]:
    """Resolve a window by title fragment or HWND to an AppWindow."""
    if not target:
        return None
    t = str(target).strip()
    if t.isdigit():
        hwnd = int(t)
        for w in native.list_windows():
            if w.hwnd == hwnd:
                return w
        return None
    return native.window_by_title(t)


class ComputerUseEngine:
    """The computer-use engine facade. Lazily creates heavy pieces."""

    def __init__(self, log: Optional[Callable[..., None]] = None,
                 controller=None) -> None:
        self.log = log or _quiet
        self.telemetry = get_telemetry()
        self._native = None
        self._motion = None
        self._temporal = None
        self._tracker = None
        self._verify = None
        self._world = None
        self._controller = controller
        self._adapters = {}

    # ── lazy components ───────────────────────────────────────────────────
    def native(self):
        if self._native is None:
            from automation.win32_native import NativeController
            self._native = NativeController()
        return self._native

    def motion(self):
        if self._motion is None:
            from automation.motion import MouseTrajectory
            self._motion = MouseTrajectory()
        return self._motion

    def temporal(self):
        if self._temporal is None:
            from automation.temporal import TemporalVision
            self._temporal = TemporalVision()
        return self._temporal

    def tracker(self):
        if self._tracker is None:
            from automation.state import ScreenStateTracker
            self._tracker = ScreenStateTracker(native=self.native())
        return self._tracker

    def world(self):
        if self._world is None:
            from automation.state import WorldState
            self._world = WorldState()
        return self._world

    def verify(self):
        if self._verify is None:
            from automation.verify import VerificationEngine
            self._verify = VerificationEngine(native=self.native(),
                                              controller=self.controller())
        return self._verify

    def controller(self):
        if self._controller is None:
            from automation import get_controller
            self._controller = get_controller(log=self.log)
        return self._controller

    def adapter(self, name: str):
        key = (name or "").lower()
        if key in self._adapters:
            return self._adapters[key]
        from automation import adapters as A
        table = {"vscode": A.VSCodeAdapter, "code": A.VSCodeAdapter,
                 "terminal": A.TerminalAdapter, "explorer": A.ExplorerAdapter}
        cls = table.get(key)
        if cls is None:
            return None
        self._adapters[key] = cls()
        return self._adapters[key]

    # ── safety guard ──────────────────────────────────────────────────────
    def _guard(self) -> Optional[ActionResult]:
        """Stop automation on the UAC secure desktop (spec 11)."""
        try:
            from automation.elevation import secure_desktop_active
            if secure_desktop_active():
                return _fail("Secure desktop active (UAC prompt). Automation "
                             "paused — approve the prompt, then ask me to continue.")
        except Exception:
            pass
        return None

    # ── telemetry helper ──────────────────────────────────────────────────
    def _trace(self, target: str = "") -> object:
        return self.telemetry.begin(target)

    # ── application discovery ─────────────────────────────────────────────
    def discover(self, limit: int = 60) -> ActionResult:
        """Enumerate running applications with full metadata."""
        g = self._guard()
        if g:
            return g
        tr = self._trace("applications")
        wins = self.native().list_windows(limit=limit)
        tr.mark("discover")
        if not wins:
            return _fail("Could not enumerate windows.")
        lines = [w.describe() for w in wins]
        tr.method = "native"
        tr.action = "discover"
        return _ok("Applications (" + str(len(wins)) + "):\n"
                   + "\n".join(lines), data={"windows": [w.to_dict() for w in wins]},
                   backend="native")

    def app_info(self, target: str) -> ActionResult:
        """Detailed info about one app/window: HWND, PID, process, privilege."""
        g = self._guard()
        if g:
            return g
        if not target:
            return _fail("Provide an app name or HWND.")
        tr = self._trace(target)
        nat = self.native()
        w = _resolve_target(target, nat)
        if w is None:
            return _fail(f"Application '{target}' not found.", data={"not_found": True})
        if w.pid:
            w.elevated = nat.process_elevated(w.pid)
        tr.mark("discover")
        tr.method = "native"
        tr.action = "app_info"
        d = w.to_dict()
        return _ok(
            f"APP: {w.process or '?'}[{w.pid}]\nHWND: {w.hwnd}\nTITLE: {w.title}\n"
            f"RECT: {w.rect} ({w.width}x{w.height})\n"
            f"STATE: {'minimized' if w.minimized else ('maximized' if w.maximized else 'normal')}\n"
            f"FOREGROUND: {w.foreground}\n"
            f"PRIVILEGE: {('ELEVATED (admin)' if w.elevated else 'normal') if w.elevated is not None else 'unknown'}",
            data=d, backend="native")

    def active_app(self) -> ActionResult:
        """The currently focused application."""
        g = self._guard()
        if g:
            return g
        fg = self.native().foreground_window()
        if fg is None:
            return _fail("No foreground window.")
        return self.app_info(fg.title or str(fg.hwnd))

    # ── window manager ───────────────────────────────────────────────────
    def window_op(self, target: str, op: str, x: int = 0, y: int = 0,
                  width: int = 0, height: int = 0, verify: bool = True) -> ActionResult:
        """focus / minimize / maximize / restore / close / move / resize.

        Resolves the target HWND first, performs the op, and (cheaply)
        verifies the outcome when asked.
        """
        g = self._guard()
        if g:
            return g
        op = (op or "").lower()
        if op not in ("focus", "minimize", "maximize", "restore", "close",
                      "move", "resize", "info"):
            return _fail(f"Unknown window op '{op}'.")
        tr = self._trace(f"{op} {target}")
        nat = self.native()
        w = _resolve_target(target, nat)
        if w is None:
            return _fail(f"Window '{target}' not found.", data={"not_found": True})
        tr.mark("discover")
        ok = False
        if op == "focus":
            ok = nat.focus(w.hwnd)
        elif op == "minimize":
            ok = nat.minimize(w.hwnd)
        elif op == "maximize":
            ok = nat.maximize(w.hwnd)
        elif op == "restore":
            ok = nat.restore(w.hwnd)
        elif op == "close":
            ok = nat.close(w.hwnd)
        elif op == "move":
            ok = nat.move(w.hwnd, int(x), int(y))
        elif op == "resize":
            ok = nat.resize(w.hwnd, int(width), int(height))
        elif op == "info":
            return self.app_info(target)
        tr.mark("action")
        tr.method = "native"
        tr.action = op
        self.world().remember_action(op, ok, target)
        if not ok:
            return _fail(f"{op} '{target}' failed.")
        if verify and op in ("focus", "minimize", "maximize", "restore", "close"):
            kind = {"focus": "foreground", "close": "close", "restore": "restore"}.get(op, op)
            vok, detail = self.verify().verify(kind, w.title or str(w.hwnd), timeout=6.0)
            tr.verification = detail
            self.log(f"[Engine] verify {op}: {detail}")
        return _ok(f"{op} '{w.title or target}' done.", data={"hwnd": w.hwnd, "op": op},
                   backend="native")

    # ── screen state / world state ───────────────────────────────────────
    def observe(self, motion_regions=None) -> ActionResult:
        """Refresh the cheap screen state."""
        s = self.tracker().observe(motion_regions=motion_regions)
        fg = self.native().foreground_window()
        if fg:
            self.world().app(fg.process or fg.title)
        return _ok("State: " + s.describe(), data=s.to_dict(), backend="native")

    def changed(self) -> ActionResult:
        """Cheap change gate — True only when something relevant moved."""
        changed = self.tracker().changed()
        return _ok("changed" if changed else "unchanged", data={"changed": changed})

    def context(self) -> ActionResult:
        """The maintained world state ('I am in VS Code', 'terminal focused')."""
        return _ok(self.world().describe(), data={"facts": self.world().facts})

    def set_context(self, key: str, value: str) -> ActionResult:
        if not key:
            return _fail("Provide a context key.")
        self.world().set(key, value)
        return _ok(f"context {key}={value}")

    # ── interaction (hierarchy + verification + recovery) ─────────────────
    def find(self, description: str, window: str = "",
             uia_only: bool = False) -> ActionResult:
        """Locate an element via the cheapest reliable backend (spec 4).

        `uia_only=True` restricts the search to UI Automation so the caller
        can re-check the screen without triggering vision/OCR screenshots.
        """
        g = self._guard()
        if g:
            return g
        if not description:
            return _fail("Provide an element description.")
        tr = self._trace(description)
        tr.method = "uia"
        tr.action = "find"
        # uia_only is only forwarded when requested, so existing controllers
        # (and test fakes) without the kwarg keep working unchanged.
        res = self.controller().find(
            description, window_title=window,
            **({"uia_only": True} if uia_only else {}))
        tr.verification = "found" if res.ok else "not found"
        self.world().remember_action("find", res.ok, description)
        if res.ok:
            self.world().focused(description)
        return res

    def click(self, description: str = "", window: str = "",
              x: Optional[int] = None, y: Optional[int] = None,
              button: str = "left", verify_screen: bool = False) -> ActionResult:
        """Cheapest-first click: UIA Invoke -> coordinates via smooth motion.

        For coordinate clicks the mouse APPROACHES smoothly (no teleport) and
        the action is optionally verified by a cheap pixel-change check.
        """
        g = self._guard()
        if g:
            return g
        tr = self._trace(description or f"({x},{y})")
        if description:
            res = self.controller().click(description, window_title=window)
            tr.method = res.backend or "uia"
            tr.action = "invoke"
            tr.verification = "ok" if res.ok else "failed"
            self.world().remember_action("click", res.ok, description)
            return res
        if x is None or y is None:
            return _fail("Provide an element description or x/y.")
        ok = self.motion().click(int(x), int(y), button=button)
        tr.method = "input"
        tr.action = "click"
        if verify_screen:
            time.sleep(0.25)
            vok, detail = self.verify().verify("click", "")
            tr.verification = detail
        else:
            tr.verification = "ok" if ok else "failed"
        self.world().remember_action("click", ok, f"({x},{y})")
        return _ok(f"Clicked ({x}, {y})." if ok else f"Click ({x}, {y}) failed.",
                   data={"x": x, "y": y}, backend="input")

    def type(self, text: str, description: str = "", window: str = "",
             x: Optional[int] = None, y: Optional[int] = None) -> ActionResult:
        g = self._guard()
        if g:
            return g
        if not text:
            return _fail("Provide text to type.")
        tr = self._trace(description or "focused")
        if description or window:
            res = self.controller().type_text(text, description=description,
                                              window_title=window)
            tr.method = res.backend or "uia"
            tr.action = "type"
            self.world().remember_action("type", res.ok, text[:40])
            return res
        if x is not None and y is not None:
            self.motion().move_to(int(x), int(y), task="click")
            self.motion().click(int(x), int(y))
            time.sleep(0.1)
        ok = self.motion().type_text(text)
        tr.method = "input"
        tr.action = "type"
        tr.verification = "ok" if ok else "failed"
        self.world().remember_action("type", ok, text[:40])
        return _ok(f"Typed {len(text)} chars." if ok else "Typing failed.", backend="input")

    # ── mouse trajectory / drag / scroll (spec 15-19) ────────────────────
    def move_smooth(self, x: int, y: int, duration: Optional[float] = None,
                    easing: str = "ease_out_cubic") -> ActionResult:
        g = self._guard()
        if g:
            return g
        tr = self._trace(f"move ({x},{y})")
        ok = self.motion().move_to(int(x), int(y), duration=duration, easing=easing)
        tr.method = "input"
        tr.action = "move_smooth"
        tr.verification = "ok" if ok else "failed"
        return _ok(f"Moved smoothly to ({x}, {y})." if ok else "Move failed.",
                   data={"x": x, "y": y}, backend="input")

    def drag(self, src_desc: str = "", dst_desc: str = "",
             src_xy: Optional[tuple] = None, dst_xy: Optional[tuple] = None,
             window: str = "") -> ActionResult:
        """Full drag: resolve source -> resolve target (re-acquired right
        before the drop) -> press -> smooth trajectory -> release -> verify."""
        g = self._guard()
        if g:
            return g
        tr = self._trace(f"drag {src_desc or src_xy} -> {dst_desc or dst_xy}")
        src = self._point_for(src_desc, window, src_xy)
        dst = self._point_for(dst_desc, window, dst_xy)
        if src is None:
            return _fail(f"Drag source not found: '{src_desc or src_xy}'.")
        if dst is None:
            return _fail(f"Drag target not found: '{dst_desc or dst_xy}'.")

        def _resolve_dst(_hint):
            """Re-resolve the drop target immediately before release."""
            fresh = self._point_for(dst_desc, window, dst_xy, hint=_hint)
            return fresh

        ok = self.motion().drag(src, dst, resolve_target=_resolve_dst)
        tr.method = "input"
        tr.action = "drag"
        self.world().remember_action("drag", ok, f"{src} -> {dst}")
        if not ok:
            return _fail("Drag refused: target moved or disappeared (stale target).")
        time.sleep(0.2)
        vok, detail = self.verify().verify("drag", "")
        tr.verification = detail
        return _ok(f"Dragged from {src} to {dst}.", data={"src": src, "dst": dst},
                   backend="input")

    def _point_for(self, desc: str, window: str, xy: Optional[tuple],
                   hint=None) -> Optional[tuple]:
        """Resolve an element description (UIA first) or raw coords to a point."""
        if xy is not None:
            return (int(xy[0]), int(xy[1]))
        if not desc:
            return hint
        res = self.controller().find(desc, window_title=window)
        if res.ok:
            el = res.data.get("element") or {}
            rect = el.get("rect")
            if rect and rect.get("width"):
                return (int(rect["x"] + rect["width"] / 2),
                        int(rect["y"] + rect["height"] / 2))
        return hint

    def scroll_to(self, target: str = "", window: str = "",
                  direction: str = "down", amount: int = 3,
                  region: Optional[tuple] = None) -> ActionResult:
        """State-transition scrolling: wheel where the mouse should be, then a
        cheap pixel check tells us whether the view actually moved."""
        g = self._guard()
        if g:
            return g
        tr = self._trace(f"scroll {direction} x{amount}")
        x, y = None, None
        if target:
            pt = self._point_for(target, window, None)
            if pt:
                x, y = pt
        if x is None:
            cx, cy = self.motion().position()
            x, y = cx, cy
        ok = self.motion().scroll(int(x), int(y), direction=direction, amount=amount)
        tr.method = "input"
        tr.action = "scroll"
        tr.verification = "ok" if ok else "failed"
        self.world().remember_action("scroll", ok, f"{direction} x{amount}")
        return _ok(f"Scrolled {direction} at ({x}, {y})." if ok else "Scroll failed.",
                   backend="input")

    # ── temporal / motion analysis (spec 12-14, 21, 24) ──────────────────
    def motion_analysis(self, region=None) -> ActionResult:
        """Cheap local motion detection between two snapshots."""
        g = self._guard()
        if g:
            return g
        tv = self.temporal()
        tv.snapshot(region)
        time.sleep(0.15)
        regions = tv.motion_now(region)
        return _ok(
            f"Motion regions: {len(regions)}" + (f" {regions[:6]}" if regions else ""),
            data={"regions": regions[:12]}, backend="vision")

    def wait_stable(self, region: tuple, timeout: float = 6.0) -> ActionResult:
        """Wait until the region stops animating, then interact (spec 24)."""
        g = self._guard()
        if g:
            return g
        from automation.temporal import stability
        from automation.verify import wait_until
        ok = wait_until(lambda: stability(region, samples=2, interval=0.1)[0],
                        timeout=timeout, interval=0.15)
        return _ok("Target stable — safe to interact." if ok
                   else "Target still moving (timeout).",
                   data={"stable": ok}, backend="vision")

    def wait_for(self, kind: str, target: str, timeout: float = 10.0) -> ActionResult:
        """State-based wait (spec 8/27): window/element/process states."""
        g = self._guard()
        if g:
            return g
        tr = self._trace(f"wait {kind} {target}")
        ok, detail = self.verify().verify(kind, target, timeout=timeout)
        tr.verification = detail
        tr.action = f"wait_{kind}"
        self.world().remember_action(f"wait_{kind}", ok, target)
        return _ok(detail if ok else f"Timed out: {detail}",
                   data={"ok": ok, "detail": detail})

    # ── app adapters (spec 7-9, 29) ──────────────────────────────────────
    def adapter_op(self, app: str, op: str, path: str = "", text: str = "",
                   command: str = "", timeout: float = 10.0) -> ActionResult:
        """Route to VSCode / Terminal / Explorer adapters.

        ops — vscode: open_file|open_folder|new_file|toggle_terminal|run_code|
                     show_diagnostics|quick_open
              terminal: type_command|paste|interrupt|clear|read_output|
                       wait_for_prompt
              explorer: open_path|navigate_to
        """
        g = self._guard()
        if g:
            return g
        ad = self.adapter(app)
        if ad is None:
            return _fail(f"No adapter for '{app}' (vscode|terminal|explorer).")
        op = (op or "").lower()
        tr = self._trace(f"{app}.{op}")
        tr.method = "native"
        tr.action = f"adapter:{app}.{op}"
        try:
            if op in ("open_file", "open_path"):
                ok = ad.open_file(path) if hasattr(ad, "open_file") else ad.open_path(path)
            elif op == "open_folder":
                ok = ad.open_folder(path)
            elif op == "new_file":
                ok = ad.new_file(path, text)
            elif op == "toggle_terminal":
                ok = ad.toggle_terminal(self.motion())
            elif op == "run_code":
                ok = ad.run_code(self.motion())
            elif op == "show_diagnostics":
                ok = ad.show_diagnostics(self.motion())
            elif op == "quick_open":
                ok = ad.quick_open(self.motion())
            elif op == "type_command":
                ok = ad.type_command(command or text, self.motion())
            elif op == "paste":
                ok = ad.paste(text, self.motion())
            elif op == "interrupt":
                ok = ad.interrupt(self.motion())
            elif op == "clear":
                ok = ad.clear(self.motion())
            elif op == "read_output":
                out = ad.read_output()
                return _ok("Terminal output:\n" + (out or "(empty)"),
                           data={"output": out}, backend="native")
            elif op == "wait_for_prompt":
                ok = ad.wait_for_prompt(timeout=timeout)
                return _ok("Prompt returned." if ok else "Terminal did not settle (timeout).",
                           data={"settled": ok}, backend="native")
            elif op == "navigate_to":
                ok = ad.navigate_to(path, self.motion())
            else:
                return _fail(f"Unknown adapter op '{op}' for {app}.")
            tr.verification = "ok" if ok else "failed"
            self.world().remember_action(f"adapter:{app}.{op}", bool(ok), path or text or command)
            return _ok(f"{app}.{op} done." if ok else f"{app}.{op} failed.",
                       backend="native")
        except Exception as e:
            return _fail(f"adapter {app}.{op} error: {e}")

    # ── elevation / safety (spec 10-11) ──────────────────────────────────
    def elevation(self) -> ActionResult:
        """Current privilege state of Keys.ai and whether UAC secure desktop is up."""
        try:
            from automation.elevation import elevation_status
            d = elevation_status()
            msg = (
                f"Privilege: {d['label']}" + (" (elevated — admin mode active)" if d["elevated"] else "") +
                (" | UAC secure desktop active — automation paused" if d["secure_desktop"] else "")
            )
            return _ok(msg, data=d, backend="native")
        except Exception as e:
            return _fail(f"Elevation check failed: {e}")

    def elevate(self) -> ActionResult:
        """Request elevation: relaunch self via UAC (never bypasses it)."""
        try:
            from automation.elevation import is_elevated, restart_elevated
            if is_elevated():
                return _ok("Already running elevated (admin mode).")
            if restart_elevated():
                return _ok("UAC prompt raised — approve it to run Keys.ai as "
                           "administrator. This instance will close.")
            return _fail("Elevation was cancelled or could not be requested.")
        except Exception as e:
            return _fail(f"Elevation failed: {e}")

    # ── observability (spec 44-45) ───────────────────────────────────────
    def telemetry_dump(self, limit: int = 20) -> ActionResult:
        return _ok(self.telemetry.dump(limit), data={"enabled": self.telemetry.enabled})


_engine: Optional[ComputerUseEngine] = None


def get_engine(log=None) -> ComputerUseEngine:
    """Shared engine singleton (like get_controller)."""
    global _engine
    if _engine is None:
        _engine = ComputerUseEngine(log=log)
    return _engine
