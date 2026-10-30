"""Games must be games, and previews must use the research browser.

Two claims are tested:

1. "Build me a game" routes to the game builder and the generated scaffold
   really runs — its own ``--selftest`` proves the rules and the pygame scene
   work, headless, before the build reports success.
2. Built sites are previewed in the Research Browser. The creation workspace no
   longer owns a second browser, so the preview widget is not in the layout and
   ``_on_cr_preview`` navigates the research browser instead.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.app_builder import app_kind_for  # noqa: E402
from core.build_recipes import detect_stacks  # noqa: E402


class TestGameRouting(unittest.TestCase):
    def test_game_requests_route_to_the_game_builder(self):
        for brief in ("build me a space shooter game in python",
                      "make a pong game", "build a snake game",
                      "a pygame arcade game"):
            with self.subTest(brief=brief):
                self.assertIn("game", detect_stacks(brief))
                self.assertEqual(app_kind_for(brief), "game")

    def test_a_dashboard_is_not_hijacked_by_the_word_game(self):
        self.assertEqual(app_kind_for("a sales dashboard"), "dashboard")

    def test_a_python_desktop_app_still_routes_to_desktop(self):
        self.assertEqual(app_kind_for("build a PyQt stock app"), "python-desktop")

    def test_the_game_recipe_states_the_acceptance_check(self):
        from core.build_recipes import RECIPES
        recipe = RECIPES["game"]
        verify = " ".join(recipe["verify"])
        self.assertIn("--selftest", verify)
        self.assertIn("game/state.py", " ".join(recipe["files"]))


class TestGameScaffold(unittest.TestCase):
    """Build a real game in a temp folder and make it prove itself."""

    @classmethod
    def setUpClass(cls):
        from core.game_builder import build_game
        cls.dir = Path(tempfile.mkdtemp(prefix="game_test_"))
        cls.result = build_game("build me a space shooter game", cls.dir)

    def test_build_reports_verified(self):
        self.assertTrue(self.result["ok"], msg=self.result.get("checks"))

    def test_expected_files_exist_and_are_not_empty(self):
        # Per-file minimums: requirements.txt is legitimately one line, while a
        # game rule or scene module that small would be a stub.
        minimum = {"requirements.txt": 5, "README.md": 200}
        for name in ("main.py", "game/state.py", "game/scene.py",
                     "game/theme.py", "requirements.txt", "README.md"):
            with self.subTest(file=name):
                path = self.dir / name
                self.assertTrue(path.exists(), f"{name} missing")
                body = path.read_text(encoding="utf-8").strip()
                self.assertGreater(len(body), minimum.get(name, 400),
                                   f"{name} looks like a stub ({len(body)} chars)")

    def test_rules_import_without_pygame(self):
        """game/state.py must be testable headlessly — no pygame import."""
        source = (self.dir / "game" / "state.py").read_text(encoding="utf-8")
        self.assertNotIn("import pygame", source)
        self.assertIn("def selftest", source)

    def test_the_game_passes_its_own_selftest(self):
        import subprocess
        env = dict(os.environ, SDL_VIDEODRIVER="dummy",
                   SDL_AUDIODRIVER="dummy")
        proc = subprocess.run([sys.executable, "main.py", "--selftest"],
                              cwd=str(self.dir), capture_output=True,
                              text=True, timeout=180, env=env)
        self.assertEqual(proc.returncode, 0,
                         msg=(proc.stdout or "") + (proc.stderr or ""))
        self.assertIn("OK", proc.stdout)

    def test_theme_colours_come_from_the_design_tokens(self):
        from core.design_system import build_tokens
        tokens = build_tokens("build me a space shooter game", kind="game")
        source = (self.dir / "game" / "theme.py").read_text(encoding="utf-8")
        hexes = [v.lstrip("#") for v in tokens.palette.values()]
        # At least the background must be one of the generated colours.
        bg = tokens.palette["bg"].lstrip("#")
        rgb = f"({int(bg[0:2], 16)}, {int(bg[2:4], 16)}, {int(bg[4:6], 16)})"
        self.assertIn(rgb, source)
        self.assertTrue(any(h for h in hexes))


class TestPreviewUsesResearchBrowser(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "ui.py").read_text(encoding="utf-8",
                                                  errors="replace")

    def test_preview_widget_is_not_in_the_layout(self):
        self.assertNotIn("addWidget(self._preview_widget)", self.source,
                         "the second browser is back in the splitter")

    def test_preview_routes_to_the_research_browser(self):
        start = self.source.index("def _on_cr_preview")
        body = self.source[start:start + 1200]
        self.assertIn("_open_research_browser", body)
        self.assertIn("navigate_to_url", body)
        self.assertNotIn("show_preview(url)", body)

    def test_creation_preview_reaches_a_research_browser_tab(self):
        import functools
        import threading
        from http.server import HTTPServer, SimpleHTTPRequestHandler

        from PyQt6.QtCore import QEventLoop, QTimer
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication(sys.argv)
        root = Path(tempfile.mkdtemp(prefix="preview_site_"))
        (root / "index.html").write_text(
            "<html><body><h1>Built site</h1></body></html>", encoding="utf-8")
        handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root))
        srv = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}/"

        try:
            import ui
            ui._ensure_gui_imports()
            window = ui.MainWindow("icon.png")
            window._on_cr_preview(url)
            loop = QEventLoop()
            QTimer.singleShot(3000, loop.quit)
            loop.exec()

            from core.research_browser import get_service
            tabs = get_service().tabs()
            self.assertTrue(any(url in str(t.get("url")) for t in tabs),
                            f"preview did not reach the research browser: {tabs}")
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
