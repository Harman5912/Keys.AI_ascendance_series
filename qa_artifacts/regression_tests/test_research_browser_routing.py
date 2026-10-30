"""Regression tests for research-browser routing and its stripped-back UI.

Two things are locked in here:

1. Research actually *finds* pages. ``core/research_step._search_for_query``
   used to be a placeholder returning ``None``, so the browser research step
   could read a page but never discover one. It now uses the app's own
   ``actions.web_search`` backend; these tests drive that with a mocked search
   so they do not depend on the network.
2. The browser has no launcher button. It is opened by text/voice through the
   ``research_browser`` tool's ``open`` action, and its toolbar no longer
   carries the research/zoom buttons.

    python -m pytest qa_artifacts/regression_tests/test_research_browser_routing.py -q
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import research_step  # noqa: E402


class TestSearchWiring(unittest.TestCase):
    """``_search_for_query`` must return a real, usable page."""

    def _search(self, hits, query="python asyncio documentation"):
        with mock.patch("actions.web_search._web_results", return_value=hits):
            return research_step._search_for_query(query)

    def test_returns_first_real_hit(self):
        hit = self._search([
            {"url": "https://docs.python.org/3/library/asyncio.html",
             "title": "asyncio", "snippet": "Asynchronous I/O"},
        ])
        self.assertIsNotNone(hit)
        self.assertEqual(hit["url"], "https://docs.python.org/3/library/asyncio.html")
        self.assertEqual(hit["title"], "asyncio")
        self.assertEqual(hit["query"], "python asyncio documentation")

    def test_skips_non_http_hits(self):
        hit = self._search([
            {"url": "mailto:someone@example.com", "title": "mail"},
            {"url": "https://example.com/real", "title": "real"},
        ])
        self.assertEqual(hit["url"], "https://example.com/real")

    def test_skips_video_and_social_silos(self):
        hit = self._search([
            {"url": "https://www.youtube.com/watch?v=abc", "title": "video"},
            {"url": "https://x.com/someone/status/1", "title": "post"},
            {"url": "https://example.com/article", "title": "article"},
        ])
        self.assertEqual(hit["url"], "https://example.com/article")

    def test_returns_none_when_search_has_no_results(self):
        self.assertIsNone(self._search([]))

    def test_returns_none_when_search_backend_fails(self):
        with mock.patch("actions.web_search._web_results",
                        side_effect=RuntimeError("rate limited")):
            self.assertIsNone(research_step._search_for_query("anything"))

    def test_noise_helper(self):
        for noisy in ("https://youtube.com/x", "https://www.tiktok.com/@a",
                      "https://twitter.com/a", "https://reddit.com/r/python"):
            with self.subTest(url=noisy):
                self.assertTrue(research_step._is_noise(noisy))
        for clean in ("https://docs.python.org/3/", "https://github.com/x/y"):
            with self.subTest(url=clean):
                self.assertFalse(research_step._is_noise(clean))


class TestOpenAction(unittest.TestCase):
    """The browser opens from a command, with no button involved."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _execute(self, params, player):
        from core.research_browser import tools as rb_tools
        with mock.patch.object(rb_tools, "_service", lambda: self._svc):
            return rb_tools.execute(params, player=player)

    def setUp(self):
        class _Svc:
            def __init__(self):
                self._tabs = []
                self._state = {}

            def tabs(self):
                return self._tabs

            def active_tab(self):
                return "t1"

            def state(self, tab_id=None):
                return self._state

        self._svc = _Svc()

    def test_open_action_shows_the_workspace(self):
        class Player:
            opened = 0

            def _open_research_browser(self):
                Player.opened += 1

        self._execute({"action": "open"}, Player())
        self.assertEqual(Player.opened, 1, "the workspace was not opened")

    def test_open_action_resolves_a_wrapped_window(self):
        inner = mock.Mock()
        wrapper = mock.Mock(spec=["_win"])
        wrapper._win = inner

        self._execute({"action": "open"}, wrapper)
        inner._open_research_browser.assert_called_once()

    def test_open_with_no_page_says_so(self):
        out = self._execute({"action": "open"}, None)
        self.assertIn("no page loaded", out.lower())

    def test_open_reports_the_page_already_showing(self):
        self._svc._tabs = [{"tab_id": "t1", "title": "Docs",
                            "url": "https://example.com/docs", "active": True}]
        self._svc._state = {"url": "https://example.com/docs"}
        out = self._execute({"action": "open"}, None)
        self.assertIn("https://example.com/docs", out)


class TestNoLauncherButton(unittest.TestCase):
    """The strip-out is the requirement: no button, no palette entry."""

    def setUp(self):
        self.source = (ROOT / "ui.py").read_text(encoding="utf-8", errors="replace")

    def test_no_research_browser_button(self):
        self.assertNotIn("RESEARCH BROWSER\")", self.source,
                         "a research browser button is back in ui.py")
        self.assertNotIn("research_btn", self.source)

    def test_no_palette_entry(self):
        self.assertNotIn("Research Browser  (live web", self.source,
                         "the palette still lists the research browser")

    def test_the_opener_still_exists(self):
        # Removing the entry points must not remove the thing they opened.
        self.assertIn("def _open_research_browser", self.source)

    def test_toolbar_dropped_the_research_buttons(self):
        from PyQt6.QtWidgets import QApplication, QPushButton
        QApplication.instance() or QApplication(sys.argv)
        from core.research_browser.workspace_ui import BrowserWorkspace

        workspace = BrowserWorkspace()
        labels = {b.text().upper() for b in workspace.findChildren(QPushButton)}
        for gone in ("SCREENSHOT", "FULL PAGE", "A-", "A+"):
            with self.subTest(button=gone):
                self.assertNotIn(gone, labels)
        # A usable browser still has its navigation and tabs.
        for kept in ("GO", "+ TAB", "CLOSE TAB"):
            with self.subTest(button=kept):
                self.assertIn(kept, labels)


if __name__ == "__main__":
    unittest.main(verbosity=2)
