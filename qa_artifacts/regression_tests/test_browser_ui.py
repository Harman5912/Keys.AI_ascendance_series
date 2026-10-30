"""Offscreen UI test for the Research Browser overlay.

Builds the real widget with the real browser service, types into the real
address bar, presses the real buttons and checks what appears in the lists and
status line. The engine is the same one the user sees, so the assertions are
about actual behaviour rather than widget plumbing.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: E402,F401

from core.research_browser import library, paths  # noqa: E402
from core.research_browser.workspace_ui import BrowserWorkspace  # noqa: E402
from qa_artifacts.regression_tests.browser_fixtures import site, stop_site  # noqa: E402


class TestBrowserWorkspace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.site = site()

    @classmethod
    def tearDownClass(cls):
        stop_site()

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="rb_ui_"))
        self._patches = [
            mock.patch.object(paths, "library_path",
                              lambda: self.temp / "library.json"),
            mock.patch.object(paths, "workspace_root",
                              lambda: self.temp / "workspace"),
            mock.patch.object(paths, "capture_dir",
                              lambda: self._capture_dir()),
        ]
        for patch in self._patches:
            patch.start()
        from core.research_browser.service import BrowserService
        self.svc = BrowserService()
        self.overlay = BrowserWorkspace(service=self.svc)
        self.overlay.resize(1280, 800)
        self.overlay.show()
        self.overlay.task_edit.setText("ui_task")
        self.overlay._set_task()
        self._pump(0.2)

    def _capture_dir(self) -> Path:
        folder = self.temp / "captures"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def tearDown(self):
        try:
            self.overlay.shutdown()
            self.overlay.close()
            self.svc.shutdown()
        except Exception:
            pass
        self.app.processEvents()
        for patch in reversed(self._patches):
            patch.stop()
        shutil.rmtree(self.temp, ignore_errors=True)

    def _pump(self, seconds: float = 0.2) -> None:
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()
            time.sleep(0.02)

    def _pump_until(self, predicate, timeout: float = 20.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def _open(self, path: str = "/") -> None:
        self.overlay.address.setText(self.site.url(path))
        self.overlay._navigate_from_bar()
        self.assertTrue(self._pump_until(
            lambda: path in self.svc.state(self.svc.active_tab())["url"]), path)

    def test_overlay_builds_the_workspace(self):
        self.assertTrue(self.overlay.address.placeholderText())
        self.assertGreaterEqual(self.overlay.tab_combo.count(), 1)
        self.assertEqual(self.overlay.tabs.count(), 4)
        self.assertIsNotNone(self.overlay.view.page())

    def test_address_bar_navigates_the_real_page(self):
        self._open("/second")
        self.assertIn("/second", self.overlay.view.url().toString())
        self.assertIn("Second Page", self.svc.page_title(self.svc.active_tab())["title"])

    def test_save_source_button_records_the_page(self):
        self._open("/")
        self.overlay._save_source()
        self.assertTrue(self._pump_until(
            lambda: self.overlay.source_list.count() == 1))
        record = library.list_sources("ui_task")[0]
        self.assertEqual(record["url"], self.site.url("/"))
        self.assertIn("saved source", self.overlay.status.text())

    def test_page_images_button_lists_real_images(self):
        self._open("/")
        self.overlay._show_page_images()
        self.assertTrue(self._pump_until(
            lambda: self.overlay.image_list.count() >= 3))
        self.assertEqual(self.overlay.tabs.currentIndex(), 2)

    def test_collect_image_adds_it_to_the_asset_list(self):
        self._open("/")
        self.overlay._show_page_images()
        self.assertTrue(self._pump_until(
            lambda: self.overlay.image_list.count() >= 3))
        target = None
        for index in range(self.overlay.image_list.count()):
            item = self.overlay.image_list.item(index)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data.get("src", "").endswith("big.png"):
                target = item
                break
        self.assertIsNotNone(target)
        self.overlay._collect_image(target)
        self.assertTrue(self._pump_until(
            lambda: self.overlay.asset_list.count() == 1))
        asset = library.list_assets("ui_task")[0]
        self.assertEqual((asset["width"], asset["height"]), (800, 600))

    def test_screenshot_button_saves_and_reports(self):
        self._open("/second")
        self.overlay._screenshot()
        self.assertTrue(self._pump_until(
            lambda: "×" in self.overlay.status.text()))
        detail = self.overlay.detail.toPlainText()
        self.assertTrue(Path(detail).is_file(), detail)

    def test_add_to_project_writes_the_reference(self):
        # Collect an image, then send it into a tiny static site.
        self._open("/")
        self.overlay._show_page_images()
        self.assertTrue(self._pump_until(
            lambda: self.overlay.image_list.count() >= 3))
        item = self.overlay.image_list.item(0)
        self.overlay._collect_image(item)
        self.assertTrue(self._pump_until(
            lambda: self.overlay.asset_list.count() == 1))
        project = self.temp / "site"
        (project / "assets").mkdir(parents=True)
        (project / "index.html").write_text("<html><body></body></html>",
                                            encoding="utf-8")
        self.overlay.project_edit.setText(str(project))
        self.overlay.asset_list.setCurrentRow(0)
        self.overlay._add_asset_to_project()
        self.assertIn("added", self.overlay.status.text())
        self.assertTrue(list((project / "assets").glob("*.png")))

    def test_closing_the_workspace_detaches_the_view(self):
        self.overlay.shutdown()
        self.assertIsNone(self.svc._view)


class TestHudEntryPoint(unittest.TestCase):
    """The RESEARCH BROWSER button's handler, not just the overlay class."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_button_handler_opens_the_workspace_in_the_centre_view(self):
        import ui
        from types import SimpleNamespace

        from PyQt6.QtWidgets import QStackedWidget, QWidget

        from core.research_browser.service import BrowserService

        # The workspace resolves its engine through core.research_browser
        # .get_service(), the same call the agent's tools make. Point that at a
        # service owned by this test so the process-wide engine is untouched.
        local = BrowserService()
        stack = QStackedWidget()
        hud = QWidget()
        stack.addWidget(hud)
        stack.resize(1400, 760)
        stack.show()             # a widget's isVisible() follows its parent
        logs: list[str] = []
        # The launcher method is driven the way test_ua_integration does it: a
        # real MainWindow with only the attributes that method touches.
        window = ui.MainWindow.__new__(ui.MainWindow)
        window._center_stack = stack
        window.hud = hud
        window._research_browser = None
        window._log = SimpleNamespace(append_log=logs.append)
        try:
            with mock.patch("core.research_browser.get_service", lambda: local):
                ui.MainWindow._open_research_browser(window)
            view = window._research_browser
            self.assertIsNotNone(view)
            # It opens in the centre view — where the live camera opens —
            # rather than floating over the window.
            self.assertIs(stack.currentWidget(), view)
            self.assertTrue(view.isVisible())
            self.assertIs(view.svc, local)
            self.assertEqual(logs, [])

            # Opening again shows the same workspace, never a second one.
            ui.MainWindow._open_research_browser(window)
            self.assertIs(window._research_browser, view)
            self.assertEqual(len(stack.findChildren(BrowserWorkspace)), 1)

            # CLOSE hands the centre view back to the HUD.
            view.closed.emit()
            self.assertIs(stack.currentWidget(), hud)
        finally:
            view = window._research_browser
            if view is not None:
                view.shutdown()
                view.close()
            local.shutdown()
            stack.close()

    def test_agent_tools_drive_the_same_service_the_overlay_shows(self):
        """No second hidden browser: tools and the workspace share one engine."""
        from core.research_browser import get_service, tools

        self.assertIs(tools._service(), get_service())


if __name__ == "__main__":
    unittest.main(verbosity=2)
