"""Unit tests for the computer-use engine (spec 10-28, 44-45).

Covers: motion/trajectory engine (smooth moves, drag re-acquisition),
temporal vision (frame differencing, dhash, stability, velocity), verification
engine (window/element/pixel strategies), elevation (admin detection + UAC
guard), world-state tracking, the ComputerUseEngine facade, and the app
adapters (VS Code / Terminal / Explorer).

Run: python test_computer_use.py
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automation.base import ActionResult  # noqa: E402
from automation.win32_native import AppWindow  # noqa: E402


# ── shared fakes ────────────────────────────────────────────────────────
class _FakeNative:
    """Fake NativeController surface: discovery + window ops + queries."""

    def __init__(self, windows=None):
        self.windows = windows or []
        self._cursor = (100, 200)

    def list_windows(self, visible_only=True, limit=200, include_owner=False):
        return self.windows

    def window_by_title(self, fragment):
        f = (fragment or "").lower()
        for w in self.windows:
            if f in (w.title or "").lower():
                return w
        return None

    def foreground_window(self):
        return self.windows[0] if self.windows else None

    def process_elevated(self, pid):
        return False

    def cursor_pos(self):
        return self._cursor

    def focus(self, hwnd):
        return True

    def minimize(self, hwnd):
        return True

    def maximize(self, hwnd):
        return True

    def restore(self, hwnd):
        return True

    def close(self, hwnd):
        return True

    def move(self, hwnd, x, y):
        return True

    def resize(self, hwnd, w, h):
        return True


class _FakeController:
    """Fake HybridController: find/click/type, record calls."""

    def __init__(self, found=True):
        self.found = found
        self.calls = []

    def find(self, description, window_title=""):
        self.calls.append(("find", description, window_title))
        if not self.found:
            return ActionResult(ok=False, message="not found",
                                data={"not_found": True})
        el = {"name": description, "rect": {"x": 10, "y": 20,
                                             "width": 50, "height": 30}}
        return ActionResult(ok=True, message="found",
                            data={"element": el}, backend="uia")

    def click(self, description, window_title=""):
        self.calls.append(("click", description, window_title))
        return ActionResult(ok=True, message=f"clicked {description}",
                            backend="uia")

    def type_text(self, text, description="", window_title=""):
        self.calls.append(("type", text, description, window_title))
        return ActionResult(ok=True, message="typed", backend="uia")


class _FakeMotion:
    """Fake MouseTrajectory: never injects real input."""

    def __init__(self):
        self.calls = []
        self.drag_ok = True

    def move_to(self, x, y, **kw):
        self.calls.append(("move_to", x, y))
        return True

    def click(self, x, y, button="left", clicks=1):
        self.calls.append(("click", x, y, button))
        return True

    def drag(self, src, dst, **kw):
        self.calls.append(("drag", src, dst))
        return self.drag_ok

    def scroll(self, x, y, direction="down", amount=3):
        self.calls.append(("scroll", x, y, direction))
        return True

    def type_text(self, text, interval=0.012):
        self.calls.append(("type", text))
        return True

    def hotkey(self, keys):
        self.calls.append(("hotkey", keys))
        return True

    def position(self):
        return (500, 400)


class _FakeVerify:
    """Fake VerificationEngine: everything verifies."""

    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def verify(self, kind, target="", timeout=8.0, expect=""):
        self.calls.append((kind, target))
        return (self.ok, "verified" if self.ok else "not verified")


class _FakeTemporal:
    def __init__(self):
        self.calls = []

    def snapshot(self, region=None):
        self.calls.append(("snapshot", region))
        return None, (0, 0)

    def motion_now(self, region=None):
        return []


def _make_window(title="Notepad", hwnd=100, pid=42, process="notepad.exe"):
    return AppWindow(hwnd=hwnd, title=title, class_name="Notepad", pid=pid,
                     process=process, rect=(0, 0, 400, 300), visible=True,
                     minimized=False, maximized=False, foreground=True)


def _engine(native=None, controller=None, motion=None, verify=None):
    from automation.engine import ComputerUseEngine
    from automation.state import ScreenStateTracker, WorldState
    e = ComputerUseEngine()
    e._native = native if native is not None else _FakeNative()
    e._controller = controller if controller is not None else _FakeController()
    e._motion = motion if motion is not None else _FakeMotion()
    e._verify = verify if verify is not None else _FakeVerify()
    e._temporal = _FakeTemporal()
    e._tracker = ScreenStateTracker(native=e._native)
    e._world = WorldState()
    return e




# ── motion / trajectory engine ─────────────────────────────────────────
class MotionTests(unittest.TestCase):
    """Smooth, deterministic trajectories (spec 15-17, 41)."""

    def test_trajectory_is_deterministic_and_ends_on_target(self):
        from automation.motion import trajectory_points
        a = trajectory_points((0, 0), (100, 0), steps=10)
        b = trajectory_points((0, 0), (100, 0), steps=10)
        self.assertEqual(a, b)                       # no randomness
        self.assertEqual(a[0], (0, 0))
        self.assertEqual(a[-1], (100, 0))

    def test_trajectory_stays_on_axis(self):
        from automation.motion import trajectory_points
        pts = trajectory_points((0, 0), (120, 0), steps=12)
        self.assertTrue(all(y == 0 for _, y in pts))
        # monotonic approach — no zigzag
        xs = [x for x, _ in pts]
        self.assertEqual(xs, sorted(xs))

    def test_waypoints_bend_the_path(self):
        from automation.motion import trajectory_points
        pts = trajectory_points((0, 0), (100, 0), steps=20,
                                waypoints=[(50, 60)])
        self.assertEqual(pts[-1], (100, 0))
        self.assertTrue(any(y > 40 for _, y in pts))  # path lifted

    def test_easing_monotonic(self):
        from automation.motion import EASINGS
        for name, fn in EASINGS.items():
            vals = [fn(i / 10) for i in range(11)]
            self.assertEqual(vals, sorted(vals), name)
            self.assertAlmostEqual(fn(0.0), 0.0, places=3)
            self.assertAlmostEqual(fn(1.0), 1.0, places=3)

    def test_duration_scales_with_distance(self):
        from automation.motion import duration_for
        self.assertLess(duration_for(5), duration_for(800))
        self.assertLess(duration_for(5, "click"), duration_for(800, "click"))
        self.assertLessEqual(duration_for(5000), 0.9)   # capped
        self.assertLessEqual(duration_for(5000, "click"), 0.28)

    def test_drag_refuses_stale_target(self):
        """Spec 18: re-resolve before release; stale/moved target => refuse."""
        from automation.motion import MouseTrajectory
        mt = MouseTrajectory()
        with mock.patch.object(mt, "_press") as press, \
             mock.patch.object(mt, "_release") as release, \
             mock.patch.object(mt, "move_to") as move_to:
            press.return_value = True
            release.return_value = True
            move_to.return_value = True
            # target moved beyond recovery -> resolve returns None
            ok = mt.drag((10, 10), (50, 50), resolve_target=lambda _hint: None)
            self.assertFalse(ok)
            press.assert_not_called()                 # refused, never pressed
            # target re-acquired -> drag proceeds to the FRESH point
            ok = mt.drag((10, 10), (50, 50),
                         resolve_target=lambda _hint: (90, 90))
            self.assertTrue(ok)
            move_to.assert_any_call(90, 90, duration=mock.ANY,
                                    easing=mock.ANY, task="drag")
            release.assert_called_once()

    def test_move_returns_true_for_same_point(self):
        from automation.motion import MouseTrajectory
        mt = MouseTrajectory()
        with mock.patch.object(mt, "position", return_value=(5, 5)):
            self.assertTrue(mt.move_to(5, 5))


# ── temporal vision / motion engine ────────────────────────────────────
class TemporalTests(unittest.TestCase):
    """Cheap local vision: differencing, hashing, stability (spec 12-14, 24)."""

    def test_motion_regions_detect_change(self):
        import numpy as np
        from automation.temporal import motion_regions
        a = np.zeros((60, 60), dtype=np.uint8)
        b = a.copy()
        b[10:20, 10:20] = 255
        regions = motion_regions(a, b, min_area=10)
        self.assertTrue(regions)
        self.assertEqual(motion_regions(a, a.copy(), min_area=10), [])

    def test_motion_regions_apply_origin(self):
        import numpy as np
        from automation.temporal import motion_regions
        a = np.zeros((40, 40), dtype=np.uint8)
        b = a.copy()
        b[5:15, 5:15] = 255
        regions = motion_regions(a, b, min_area=5, origin=(1000, 800))
        self.assertTrue(all(r[0] >= 1000 and r[1] >= 800 for r in regions))

    def test_dhash_and_hamming(self):
        import numpy as np
        from automation.temporal import dhash, hamming
        a = np.zeros((40, 40), dtype=np.uint8)
        a[10:30, 10:30] = 255
        b = a.copy()
        self.assertEqual(hamming(dhash(a), dhash(a)), 0)
        b[20:25, 20:25] = 0
        self.assertGreater(hamming(dhash(a), dhash(b)), 0)
        self.assertEqual(hamming(None, a), 999)

    def test_stability_settled_region(self):
        import numpy as np
        from automation import temporal
        frame = np.zeros((20, 20), dtype=np.uint8)
        with mock.patch.object(temporal, "capture_gray",
                               return_value=frame):
            stable, drift = temporal.stability((0, 0, 20, 20),
                                               samples=3, interval=0.01)
            self.assertTrue(stable)
            self.assertEqual(drift, 0.0)

    def test_temporal_velocity(self):
        from automation.temporal import TemporalVision
        tv = TemporalVision()
        self.assertIsNone(tv.velocity([]))
        self.assertIsNone(tv.velocity([(0, 0)]))
        self.assertEqual(tv.velocity([(0, 0), (10, 0), (20, 0)]), (10.0, 0.0))
        self.assertEqual(tv.velocity([(0, 0), (0, 10)]), (0.0, 10.0))

    def test_loading_is_not_stable(self):
        from automation.temporal import TemporalVision
        tv = TemporalVision()
        with mock.patch("automation.temporal.stability",
                        return_value=(False, 0.5)):
            self.assertTrue(tv.loading((0, 0, 10, 10),
                                       samples=2, interval=0.01))


# ── verification engine ────────────────────────────────────────────────
class VerifyTests(unittest.TestCase):
    """Cheap-first verification + state-based waiting (spec 27-28)."""

    def test_wait_until_returns_true_when_condition_met(self):
        from automation.verify import wait_until
        calls = []

        def cond():
            calls.append(1)
            return len(calls) >= 2

        self.assertTrue(wait_until(cond, timeout=1.0, interval=0.01))

    def test_wait_until_times_out(self):
        from automation.verify import wait_until
        self.assertFalse(wait_until(lambda: False, timeout=0.15,
                                    interval=0.02))

    def test_window_exists_and_gone(self):
        from automation.verify import VerificationEngine
        nat = _FakeNative(windows=[_make_window("Notepad")])
        ve = VerificationEngine(native=nat)
        self.assertTrue(ve.window_exists("note"))
        self.assertFalse(ve.window_exists("chrome"))
        self.assertFalse(ve.window_gone("note"))
        self.assertTrue(ve.window_gone("chrome"))

    def test_window_state(self):
        from automation.verify import VerificationEngine
        w = _make_window("Calc")
        nat = _FakeNative(windows=[w])
        ve = VerificationEngine(native=nat)
        self.assertTrue(ve.window_state("calc", "visible"))
        self.assertTrue(ve.window_state("calc", "foreground"))
        self.assertTrue(ve.window_state("calc", "normal"))
        w.minimized = True
        self.assertTrue(ve.window_state("calc", "minimized"))
        self.assertFalse(ve.window_state("calc", "normal"))

    def test_verify_dispatch_open_and_close(self):
        from automation.verify import VerificationEngine
        nat = _FakeNative(windows=[_make_window("Snipping")])
        ve = VerificationEngine(native=nat)
        ok, detail = ve.verify("open", "snipping", timeout=0.3)
        self.assertTrue(ok)
        self.assertIn("appeared", detail)
        ok, detail = ve.verify("close", "nonexistent", timeout=0.3)
        self.assertTrue(ok)
        self.assertIn("gone", detail)

    def test_verify_element_strategies(self):
        from automation.verify import VerificationEngine
        ctrl = _FakeController(found=False)
        ve = VerificationEngine(native=_FakeNative(), controller=ctrl)
        ok, detail = ve.verify("element", "Send", timeout=0.3)
        self.assertFalse(ok)                      # fake says not found
        ok, detail = ve.verify("disappear", "Send", timeout=0.3)
        self.assertTrue(ok)                       # not_found => gone


# ── elevation / administrator mode ─────────────────────────────────────
class ElevationTests(unittest.TestCase):
    """Legitimate Windows elevation (spec 10-11): detect, request, guard."""

    def test_is_elevated_returns_bool(self):
        from automation.elevation import is_elevated
        self.assertIsInstance(is_elevated(), bool)

    def test_elevation_status_shape(self):
        from automation.elevation import elevation_status
        d = elevation_status()
        for key in ("elevated", "windows", "secure_desktop", "label"):
            self.assertIn(key, d)
        self.assertIsInstance(d["elevated"], bool)

    def test_restart_elevated_already_elevated(self):
        """Already elevated => never spawns another UAC prompt."""
        with mock.patch("automation.elevation.is_elevated",
                        return_value=True):
            from automation.elevation import restart_elevated
            self.assertFalse(restart_elevated())

    def test_secure_desktop_guard_in_engine(self):
        """Spec 11: automation pauses on the UAC secure desktop."""
        e = _engine(native=_FakeNative(windows=[_make_window()]))
        with mock.patch("automation.elevation.secure_desktop_active",
                        return_value=True):
            res = e.discover()
        self.assertFalse(res.ok)
        self.assertIn("Secure desktop", res.message)

    def test_elevate_already_running(self):
        e = _engine()
        with mock.patch("automation.elevation.is_elevated",
                        return_value=True):
            res = e.elevate()
        self.assertTrue(res.ok)
        self.assertIn("Already running elevated", res.message)

    def test_elevation_status_method(self):
        e = _engine()
        res = e.elevation()
        self.assertTrue(res.ok)
        self.assertIn("Privilege", res.message)


# ── screen / world state tracking ──────────────────────────────────────
class StateTests(unittest.TestCase):
    """Spec 20/26: maintain context; only report what changed."""

    def test_relevant_changed_gates_vision(self):
        from automation.state import ScreenState
        a = ScreenState(active_hwnd=1, active_title="Notepad",
                        cursor=(0, 0), window_rect=(0, 0, 100, 100))
        same = ScreenState(active_hwnd=1, active_title="Notepad",
                           cursor=(0, 0), window_rect=(0, 0, 100, 100))
        self.assertFalse(a.relevant_changed(same))
        b = ScreenState(active_hwnd=2, active_title="Notepad",
                        cursor=(0, 0), window_rect=(0, 0, 100, 100))
        self.assertTrue(a.relevant_changed(b))
        c = ScreenState(active_hwnd=1, active_title="Notepad",
                        cursor=(5, 5), window_rect=(0, 0, 100, 100))
        self.assertTrue(a.relevant_changed(c))

    def test_world_state_context(self):
        from automation.state import WorldState
        w = WorldState()
        w.app("Code.exe")
        self.assertEqual(w.get("app"), "Code.exe")
        w.focused("terminal")
        self.assertEqual(w.get("focused"), "terminal")
        w.remember_action("click", True, "Send")
        self.assertIn("last_action", w.describe())
        self.assertIn("app: Code.exe", w.describe())

    def test_engine_context_methods(self):
        e = _engine()
        res = e.set_context("mode", "terminal")
        self.assertTrue(res.ok)
        ctx = e.context()
        self.assertTrue(ctx.ok)
        self.assertIn("mode: terminal", ctx.message)


# ── ComputerUseEngine facade ───────────────────────────────────────────
class EngineTests(unittest.TestCase):
    """The central controller: discovery, window ops, interaction, drag,
    adapters, elevation and telemetry (spec 44-45)."""

    def test_discover_lists_applications(self):
        nat = _FakeNative(windows=[_make_window("Notepad", process="notepad.exe")])
        e = _engine(native=nat)
        res = e.discover()
        self.assertTrue(res.ok)
        self.assertIn("notepad.exe", res.message)
        self.assertEqual(len(res.data["windows"]), 1)

    def test_app_info_reports_privilege(self):
        nat = _FakeNative(windows=[_make_window("Notepad", pid=42)])
        e = _engine(native=nat)
        res = e.app_info("Notepad")
        self.assertTrue(res.ok)
        self.assertIn("HWND: 100", res.message)
        self.assertIn("PRIVILEGE", res.message)

    def test_app_info_not_found(self):
        e = _engine(native=_FakeNative())
        res = e.app_info("Ghost")
        self.assertFalse(res.ok)
        self.assertTrue(res.data.get("not_found"))

    def test_active_app(self):
        nat = _FakeNative(windows=[_make_window("Active Window")])
        e = _engine(native=nat)
        res = e.active_app()
        self.assertTrue(res.ok)
        self.assertIn("Active Window", res.message)

    def test_window_op_minimize(self):
        nat = _FakeNative(windows=[_make_window("Notepad")])
        e = _engine(native=nat)
        res = e.window_op("Notepad", "minimize")
        self.assertTrue(res.ok)
        self.assertIn("minimize", res.message.lower())

    def test_window_op_bad_op(self):
        e = _engine()
        res = e.window_op("Notepad", "explode")
        self.assertFalse(res.ok)

    def test_find_routes_to_controller(self):
        ctrl = _FakeController()
        e = _engine(controller=ctrl)
        res = e.find("Send")
        self.assertTrue(res.ok)
        self.assertEqual(ctrl.calls[0][0], "find")

    def test_click_by_element(self):
        ctrl = _FakeController()
        e = _engine(controller=ctrl)
        res = e.click("Send")
        self.assertTrue(res.ok)
        self.assertIn("click", ctrl.calls[0][0])

    def test_click_by_coordinates(self):
        motion = _FakeMotion()
        e = _engine(motion=motion)
        res = e.click(x=100, y=200)
        self.assertTrue(res.ok)
        self.assertIn(("click", 100, 200, "left"), motion.calls)

    def test_click_requires_something(self):
        e = _engine()
        res = e.click()
        self.assertFalse(res.ok)

    def test_type_by_element(self):
        ctrl = _FakeController()
        e = _engine(controller=ctrl)
        res = e.type("hello", description="input")
        self.assertTrue(res.ok)

    def test_type_by_coordinates(self):
        motion = _FakeMotion()
        e = _engine(motion=motion)
        res = e.type("hello", x=10, y=10)
        self.assertTrue(res.ok)
        self.assertIn(("move_to", 10, 10), motion.calls)
        self.assertIn(("type", "hello"), motion.calls)

    def test_drag_element_to_element(self):
        ctrl = _FakeController()
        motion = _FakeMotion()
        e = _engine(controller=ctrl, motion=motion)
        res = e.drag(src_desc="File A", dst_desc="Folder")
        self.assertTrue(res.ok)
        drag = [c for c in motion.calls if c[0] == "drag"]
        self.assertEqual(len(drag), 1)
        self.assertEqual(drag[0][1], (35, 35))   # rect center (10+25, 20+15)

    def test_drag_refused_on_stale_target(self):
        motion = _FakeMotion()
        motion.drag_ok = False
        e = _engine(motion=motion)
        res = e.drag(src_xy=(10, 10), dst_xy=(50, 50))
        self.assertFalse(res.ok)
        self.assertIn("stale", res.message.lower())

    def test_move_smooth(self):
        motion = _FakeMotion()
        e = _engine(motion=motion)
        res = e.move_smooth(300, 300)
        self.assertTrue(res.ok)
        self.assertIn(("move_to", 300, 300), motion.calls)

    def test_scroll_to(self):
        motion = _FakeMotion()
        e = _engine(motion=motion)
        res = e.scroll_to(direction="down", amount=3)
        self.assertTrue(res.ok)
        self.assertIn(("scroll", 500, 400, "down"), motion.calls)

    def test_wait_for_delegates_to_verify(self):
        ve = _FakeVerify()
        e = _engine(verify=ve)
        res = e.wait_for("open", "Notepad", timeout=1.0)
        self.assertTrue(res.ok)
        self.assertEqual(ve.calls[0][0], "open")

    def test_observe_and_changed(self):
        e = _engine()
        res = e.observe()
        self.assertTrue(res.ok)
        res = e.changed()
        self.assertTrue(res.ok)          # first observation => changed

    def test_telemetry_dump(self):
        e = _engine()
        res = e.telemetry_dump()
        self.assertTrue(res.ok)
        self.assertIn("enabled", res.data)


# ── application adapters ───────────────────────────────────────────────
class AdapterTests(unittest.TestCase):
    """Spec 7-9, 29: filesystem/CLI-first VS Code, terminal, explorer."""

    def test_vscode_new_file_writes_disk(self):
        import tempfile
        from automation.adapters import VSCodeAdapter
        ad = VSCodeAdapter()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "a.py")
            with mock.patch.object(ad, "_cli", return_value=None):
                ad.new_file(path, "print('hi')\n")
            self.assertTrue(os.path.exists(path))
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "print('hi')\n")

    def test_vscode_open_file_missing(self):
        from automation.adapters import VSCodeAdapter
        ad = VSCodeAdapter()
        self.assertFalse(ad.open_file("C:/nope/definitely/missing.py"))

    def test_terminal_detect_shell(self):
        from automation.adapters import TerminalAdapter
        ad = TerminalAdapter()
        self.assertEqual(ad.detect_shell("Windows PowerShell"), "powershell")
        self.assertEqual(ad.detect_shell("Windows Terminal"), "cmd")
        self.assertEqual(ad.detect_shell("Command Prompt"), "cmd")

    def test_explorer_open_path(self):
        from automation.adapters import ExplorerAdapter
        ad = ExplorerAdapter()
        with mock.patch("automation.adapters.subprocess.Popen") as popen:
            self.assertTrue(ad.open_path("C:/Users"))
            popen.assert_called_once()
            self.assertIn("explorer.exe", popen.call_args[0][0])

    def test_register_app_adapters(self):
        from automation.adapters import register_app_adapters
        registered = []

        class _B:
            def register(self, a):
                registered.append(type(a).__name__)

        register_app_adapters(_B())
        self.assertEqual(sorted(registered),
                         ["ExplorerAdapter", "TerminalAdapter", "VSCodeAdapter"])

    def test_engine_adapter_op_terminal(self):
        motion = _FakeMotion()
        e = _engine(motion=motion)
        res = e.adapter_op("terminal", "type_command", command="dir")
        self.assertTrue(res.ok)
        self.assertIn(("type", "dir"), motion.calls)

    def test_engine_adapter_op_unknown_app(self):
        e = _engine()
        res = e.adapter_op("photoshop", "open_file")
        self.assertFalse(res.ok)

    def test_engine_adapter_op_unknown_op(self):
        e = _engine()
        res = e.adapter_op("explorer", "teleport")
        self.assertFalse(res.ok)

# ── computer_use tool dispatcher ──────────────────────────────────────
class DispatcherTests(unittest.TestCase):
    """The Gemini-facing tool wrapper (actions/computer_use.py)."""

    def _call(self, params):
        from actions.computer_use import computer_use
        return computer_use(params)

    def test_context_action(self):
        out = self._call({"action": "context"})
        self.assertIsInstance(out, str)
        self.assertNotIn("Unknown computer_use action", out)

    def test_set_context_roundtrip(self):
        self._call({"action": "set_context", "key": "app", "value": "Code.exe"})
        out = self._call({"action": "context"})
        self.assertIn("app: Code.exe", out)

    def test_unknown_action_returns_helpful_error(self):
        out = self._call({"action": "fly_to_moon"})
        self.assertIsInstance(out, str)
        self.assertIn("Unknown computer_use action", out)

    def test_missing_action_returns_helpful_error(self):
        out = self._call({})
        self.assertIn("No action specified", out)

    def test_telemetry_action(self):
        out = self._call({"action": "telemetry"})
        self.assertIsInstance(out, str)
        self.assertNotIn("Unknown computer_use action", out)

    def test_elevation_action(self):
        out = self._call({"action": "elevation"})
        self.assertIsInstance(out, str)
        self.assertIn("Privilege", out)


class ElevationRestartTests(unittest.TestCase):
    """restart_elevated: UAC prompt success/cancel branches (never bypass)."""

    def test_restart_elevated_success_when_uac_approved(self):
        import ctypes
        from automation.elevation import restart_elevated
        with (mock.patch("automation.elevation.is_elevated", return_value=False),
              mock.patch("automation.elevation.current_executable",
                         return_value=r"C:\KeysAI\keysai.exe"),
              mock.patch.object(ctypes.windll.shell32, "ShellExecuteW",
                                return_value=42) as se):
            self.assertTrue(restart_elevated())
            se.assert_called_once()
            self.assertEqual(se.call_args[0][1], "runas")  # legitimate UAC verb

    def test_restart_elevated_false_when_uac_denied(self):
        import ctypes
        from automation.elevation import restart_elevated
        with (mock.patch("automation.elevation.is_elevated", return_value=False),
              mock.patch("automation.elevation.current_executable",
                         return_value=r"C:\KeysAI\keysai.exe"),
              mock.patch.object(ctypes.windll.shell32, "ShellExecuteW",
                                return_value=5)):  # ERROR_ACCESS_DENIED
            self.assertFalse(restart_elevated())


if __name__ == "__main__":
    unittest.main(verbosity=2)
