"""Offscreen unit tests for the hybrid automation layer.

Run: python test_hybrid_automation.py
Covers: backend priority order, element resolution chaining, click/type routing,
vision fallback, and the hybrid_control tool dispatch. All heavy deps mocked.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automation.base import Backend, Element, Rect, ActionResult  # noqa: E402
from automation.orchestrator import HybridController  # noqa: E402
from actions import hybrid_control as hc  # noqa: E402


class _StubBackend(Backend):
    """Scriptable backend for testing the priority chain."""

    def __init__(self, name, priority, available=True, find_result=None,
                 click_ok=False, type_ok=False):
        self.name = name
        self.priority = priority
        self._avail = available
        self._find_result = find_result
        self._click_ok = click_ok
        self._type_ok = type_ok
        self.find_calls = 0
        self.click_calls = 0

    def available(self):
        return self._avail

    def find(self, description, control_type="", window_title=""):
        self.find_calls += 1
        return self._find_result

    def click(self, element):
        self.click_calls += 1
        return self._click_ok

    def click_at(self, x, y):
        return self._click_ok

    def type_text(self, element, text):
        return self._type_ok


def _make_element(name="btn", backend="uia"):
    return Element(name=name, control_type="Button",
                   rect=Rect(10, 10, 50, 20), backend=backend)


class PriorityOrderTests(unittest.TestCase):
    def test_find_uses_priority_order(self):
        """Highest-priority available backend that can find wins."""
        vision_el = _make_element("vision", backend="vision")
        uia = _StubBackend("uia", 1, find_result=None)
        native = _StubBackend("native", 2, find_result=None)
        vision = _StubBackend("vision", 3, find_result=vision_el)
        ctrl = HybridController(backends=[native, uia, vision], attempts=1)
        el = ctrl._best_find("Save")
        self.assertEqual(el.backend, "vision")
        self.assertGreaterEqual(vision.find_calls, 1)

    def test_find_skips_unavailable(self):
        uia = _StubBackend("uia", 1, available=False, find_result=_make_element())
        ctrl = HybridController(backends=[uia], attempts=1)
        self.assertEqual(ctrl.find("Save").ok, False)   # not available → not found

    def test_click_falls_through_to_input(self):
        """If the locating backend can't click, the next backend tries."""
        el = _make_element()
        uia = _StubBackend("uia", 1, find_result=el, click_ok=False)
        input_b = _StubBackend("input", 4, find_result=el, click_ok=True)
        ctrl = HybridController(backends=[uia, input_b], attempts=1)
        res = ctrl.click("Save")
        self.assertTrue(res.ok)
        self.assertGreater(input_b.click_calls, 0)

    def test_status_reports_backends(self):
        uia = _StubBackend("uia", 1, available=True)
        ctrl = HybridController(backends=[uia])
        res = ctrl.status()
        self.assertTrue(res.ok)
        self.assertEqual(res.data.get("uia"), True)


class VisionRoutingTests(unittest.TestCase):
    def test_click_at_coordinates_uses_input(self):
        input_b = _StubBackend("input", 4, click_ok=True)
        ctrl = HybridController(backends=[input_b], attempts=1)
        with mock.patch.object(input_b, "click_at", return_value=True) as m:
            res = ctrl.click(x=100, y=200)
        self.assertTrue(res.ok)
        m.assert_called_once_with(100, 200)

    def test_describe_screen_requires_vision(self):
        """describe_screen returns a clear error when vision is missing."""
        input_b = _StubBackend("input", 4, click_ok=True)
        ctrl = HybridController(backends=[input_b], attempts=1)
        res = ctrl.describe_screen()
        self.assertFalse(res.ok)
        self.assertIn("Vision", res.message)


class ToolDispatchTests(unittest.TestCase):
    def test_unknown_action(self):
        out = hc.hybrid_control({"action": "nope"})
        self.assertIn("Unknown hybrid_control action", out)

    def test_missing_action(self):
        self.assertIn("No action specified", hc.hybrid_control({}))

    def test_status_dispatch(self):
        with mock.patch.object(hc, "get_controller") as gc:
            ctrl = mock.Mock()
            ctrl.status.return_value = ActionResult(ok=True, message="uia: ✓ input: ✓",
                                                    data={"uia": True, "input": True})
            gc.return_value = ctrl
            out = hc.hybrid_control({"action": "status"})
        self.assertIn("uia", out)

    def test_click_dispatch_passes_coords(self):
        with mock.patch.object(hc, "get_controller") as gc:
            ctrl = mock.Mock()
            ctrl.click.return_value = ActionResult(ok=True, message="Clicked.", backend="input")
            gc.return_value = ctrl
            out = hc.hybrid_control({"action": "click", "x": 5, "y": 9})
        self.assertEqual(out, "Clicked.")
        _, kw = ctrl.click.call_args
        self.assertEqual(kw["x"], 5)
        self.assertEqual(kw["y"], 9)

    def test_ocr_dispatch(self):
        with mock.patch.object(hc, "get_controller") as gc:
            ctrl = mock.Mock()
            ctrl.ocr.return_value = ActionResult(ok=True, message="Hello world", backend="vision")
            gc.return_value = ctrl
            out = hc.hybrid_control({"action": "ocr"})
        self.assertIn("Hello world", out)


class ScreenAccessTests(unittest.TestCase):
    """New: components/elements/read/view — full per-component access."""

    class _ElementsBackend(_StubBackend):
        def __init__(self):
            super().__init__("uia", 1)

        def list_elements(self, window_title=""):
            return [_make_element("Save"), _make_element("Cancel")]

    def test_list_elements_routing(self):
        b = self._ElementsBackend()
        ctrl = HybridController(backends=[b], attempts=1)
        res = ctrl.list_elements("Notepad")
        self.assertTrue(res.ok)
        self.assertEqual(len(res.data["elements"]), 2)
        self.assertIn("Save", res.message)
        self.assertIn("Cancel", res.message)

    def test_list_elements_empty_window(self):
        b = _StubBackend("input", 4, available=True)
        ctrl = HybridController(backends=[b], attempts=1)
        res = ctrl.list_elements()
        self.assertFalse(res.ok)
        self.assertIn("No interactive components", res.message)

    def test_read_routing(self):
        class _ReadBackend(_StubBackend):
            def find(self, description, control_type="", window_title=""):
                return _make_element(description)

            def get_text(self, element):
                return "John Doe"

        b = _ReadBackend("uia", 1)
        ctrl = HybridController(backends=[b], attempts=1)
        res = ctrl.read("Name field")
        self.assertTrue(res.ok)
        self.assertEqual(res.message, "John Doe")

    def test_read_falls_back_to_value_pattern(self):
        class _ValueBackend(_StubBackend):
            def find(self, description, control_type="", window_title=""):
                return _make_element(description)

            def get_text(self, element):
                return ""

            def get_value(self, element):
                return "42"

        b = _ValueBackend("uia", 1)
        ctrl = HybridController(backends=[b], attempts=1)
        res = ctrl.read("Volume")
        self.assertTrue(res.ok)
        self.assertEqual(res.message, "42")

    def test_elements_dispatch(self):
        with mock.patch.object(hc, "get_controller") as gc:
            ctrl = mock.Mock()
            ctrl.list_elements.return_value = ActionResult(ok=True, message="  0. Save\n  1. Cancel")
            gc.return_value = ctrl
            out = hc.hybrid_control({"action": "elements", "window": "Notepad"})
        self.assertIn("Save", out)
        ctrl.list_elements.assert_called_once_with("Notepad")

    def test_read_dispatch(self):
        with mock.patch.object(hc, "get_controller") as gc:
            ctrl = mock.Mock()
            ctrl.read.return_value = ActionResult(ok=True, message="John Doe")
            gc.return_value = ctrl
            out = hc.hybrid_control({"action": "read", "description": "Name field"})
        self.assertEqual(out, "John Doe")
        args, kw = ctrl.read.call_args
        self.assertEqual(args[0], "Name field")
        self.assertEqual(kw["control_type"], "")

    def test_view_dispatch(self):
        import pathlib
        import tempfile
        with mock.patch.object(hc, "get_controller") as gc:
            ctrl = mock.Mock()
            ctrl.capture.return_value = b"\x89PNG-fake"
            gc.return_value = ctrl
            with tempfile.TemporaryDirectory() as d:
                out = hc.hybrid_control({"action": "view",
                                         "path": str(pathlib.Path(d) / "shot")})
        self.assertIn("Screenshot saved", out)

    def test_unknown_action_message_lists_new_actions(self):
        out = hc.hybrid_control({"action": "nope"})
        self.assertIn("elements", out)
        self.assertIn("view", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
