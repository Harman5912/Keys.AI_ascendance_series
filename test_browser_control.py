"""Offscreen unit tests for the per-tab / per-component browser_control dispatch.

Run: python test_browser_control.py
The real _BrowserSession runs Playwright in its own thread — here the registry
is swapped for a fake session so every new action's argument wiring is tested
without launching a browser.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from actions import browser_control as bc
    _HAVE_BC = True
    _IMPORT_ERR = ""
except Exception as e:  # noqa: BLE001
    _HAVE_BC = False
    _IMPORT_ERR = repr(e)


class FakeSession:
    """Records method calls; run() echoes plain strings back."""

    def __init__(self):
        self.calls = []

    def run(self, coro, timeout=60):
        return coro if isinstance(coro, str) else "ran"

    def __getattr__(self, name):
        def _rec(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return f"{name}-ok"
        return _rec


@unittest.skipUnless(_HAVE_BC, f"browser_control import failed: {_IMPORT_ERR}")
class BrowserTabDispatchTests(unittest.TestCase):

    def _dispatch(self, params):
        fake = FakeSession()
        reg = mock.Mock()
        reg.get.return_value = fake
        reg.attach.return_value = "Attached to the running chrome over CDP (port 9222)."
        reg.switch.return_value = "Active browser -> chrome"
        reg.list_sessions.return_value = "Open browsers:\n  - chrome"
        reg.close_all.return_value = "All browsers closed."
        reg.close_one.return_value = "chrome closed."
        with mock.patch.object(bc, "_registry", reg):
            out = bc.browser_control(params)
        return out, fake, reg

    def test_list_tabs(self):
        out, fake, _ = self._dispatch({"action": "list_tabs"})
        self.assertEqual(out, "list_tabs-ok")
        self.assertIn(("list_tabs", (), {}), fake.calls)

    def test_switch_tab_by_index(self):
        out, fake, _ = self._dispatch({"action": "switch_tab", "index": 2})
        self.assertEqual(out, "switch_tab-ok")
        self.assertIn(("switch_tab", (2, None, None), {}), fake.calls)

    def test_switch_tab_by_title(self):
        out, fake, _ = self._dispatch({"action": "switch_tab", "title": "gmail"})
        self.assertIn(("switch_tab", (None, "gmail", None), {}), fake.calls)

    def test_close_tab_by_index(self):
        out, fake, _ = self._dispatch({"action": "close_tab", "index": 3})
        self.assertIn(("close_tab", (3, None, None), {}), fake.calls)

    def test_close_tab_active_when_untargeted(self):
        out, fake, _ = self._dispatch({"action": "close_tab"})
        self.assertIn(("close_tab", (None, None, None), {}), fake.calls)

    def test_components(self):
        out, fake, _ = self._dispatch({"action": "components"})
        self.assertIn(("components", (), {}), fake.calls)

    def test_click_component_by_index(self):
        out, fake, _ = self._dispatch({"action": "click_component", "index": 0,
                                       "description": "Search"})
        self.assertIn(("click_component", (0, None, None, "Search"), {}), fake.calls)

    def test_type_component(self):
        out, fake, _ = self._dispatch({"action": "type_component", "index": 1,
                                       "text": "hello", "clear_first": False})
        self.assertIn(("type_component", (1, None, None, "hello", False), {}), fake.calls)

    def test_read_component_by_selector(self):
        out, fake, _ = self._dispatch({"action": "read_component", "selector": "#email"})
        self.assertIn(("read_component", (None, "#email", None), {}), fake.calls)

    def test_tab_screenshot(self):
        out, fake, _ = self._dispatch({"action": "tab_screenshot", "index": 1,
                                       "full_page": True, "path": "x.png"})
        self.assertIn(("tab_screenshot", ("x.png", 1, None, None, True), {}), fake.calls)

    def test_tab_text_by_url(self):
        out, fake, _ = self._dispatch({"action": "tab_text", "url": "youtube.com"})
        self.assertIn(("tab_text", (None, None, "youtube.com"), {}), fake.calls)

    def test_attach_dispatch(self):
        out, fake, reg = self._dispatch({"action": "attach", "browser": "chrome",
                                         "port": 9222})
        reg.attach.assert_called_once_with("chrome", 9222)
        self.assertIn("Attached", out)

    def test_attach_without_browser(self):
        out, fake, reg = self._dispatch({"action": "attach"})
        self.assertIn("Please specify a browser", out)
        reg.attach.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
