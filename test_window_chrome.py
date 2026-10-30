"""Offscreen unit tests for the custom frameless window chrome.

Run: python test_window_chrome.py   (QT_QPA_PLATFORM=offscreen is forced here)
Covers: title-bar buttons/signals, drag exclusion, double-click toggle,
edge hit-testing + cursors, maximized band/mask behaviour, geometry persistence.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget  # noqa: E402

from window_chrome import (  # noqa: E402
    WindowChromeFrame, _TitleButton, load_window_state, save_window_state,
)

_APP = None


def _app():
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


class _Harness(QMainWindow):
    """Mirrors how MainWindow uses the chrome frame (frameless + translucent)."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.chrome = WindowChromeFrame(self)
        self.setCentralWidget(self.chrome)
        content = QWidget()
        content.setStyleSheet("background: #000000;")
        self.chrome.set_content_widget(content)
        self.min_calls = self.max_calls = self.close_calls = 0
        tb = self.chrome.title_bar
        tb.minimizeRequested.connect(lambda: setattr(self, "min_calls", self.min_calls + 1))
        tb.maximizeRequested.connect(lambda: setattr(self, "max_calls", self.max_calls + 1))
        tb.closeRequested.connect(lambda: setattr(self, "close_calls", self.close_calls + 1))


class TitleBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.win = _Harness()
        self.win.resize(600, 400)
        self.win.show()

    def tearDown(self):
        self.win.close()

    def test_three_window_buttons_exist(self):
        tb = self.win.chrome.title_bar
        self.assertIsInstance(tb._min_btn, _TitleButton)
        self.assertIsInstance(tb._max_btn, _TitleButton)
        self.assertIsInstance(tb._close_btn, _TitleButton)

    def test_buttons_emit_signals(self):
        tb = self.win.chrome.title_bar
        QTest.mouseClick(tb._min_btn, Qt.MouseButton.LeftButton)
        QTest.mouseClick(tb._max_btn, Qt.MouseButton.LeftButton)
        QTest.mouseClick(tb._close_btn, Qt.MouseButton.LeftButton)
        self.assertEqual(self.win.min_calls, 1)
        self.assertEqual(self.win.max_calls, 1)
        self.assertEqual(self.win.close_calls, 1)

    def test_button_click_does_not_start_drag(self):
        tb = self.win.chrome.title_bar
        QTest.mouseClick(tb._max_btn, Qt.MouseButton.LeftButton)
        self.assertFalse(tb._dragging)

    def test_double_click_emits_maximize(self):
        tb = self.win.chrome.title_bar
        pos = QPoint(20, tb.height() // 2)  # identity label, not a button
        QTest.mouseDClick(tb, Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.NoModifier, pos)
        self.assertGreaterEqual(self.win.max_calls, 1)

    def test_refresh_state_glyph(self):
        tb = self.win.chrome.title_bar
        tb.refresh_state()
        self.assertEqual(tb._max_btn.text(), "□")
        with mock.patch.object(self.win, "isMaximized", return_value=True):
            tb.refresh_state()
        self.assertEqual(tb._max_btn.text(), "❐")


class ChromeFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.win = _Harness()
        self.win.resize(600, 400)
        self.win.show()

    def tearDown(self):
        self.win.close()

    def test_edge_hit_testing(self):
        c = self.win.chrome
        self.assertEqual(c._edge_at(QPoint(2, 200)), Qt.Edge.LeftEdge)
        self.assertEqual(c._edge_at(QPoint(598, 200)), Qt.Edge.RightEdge)
        self.assertEqual(c._edge_at(QPoint(300, 2)), Qt.Edge.TopEdge)
        self.assertEqual(c._edge_at(QPoint(300, 398)), Qt.Edge.BottomEdge)
        self.assertEqual(c._edge_at(QPoint(2, 2)),
                         Qt.Edge.LeftEdge | Qt.Edge.TopEdge)
        self.assertEqual(c._edge_at(QPoint(300, 200)), Qt.Edge(0))

    def test_edge_cursors(self):
        c = self.win.chrome
        self.assertEqual(c._cursor_for(Qt.Edge.LeftEdge),
                         Qt.CursorShape.SizeHorCursor)
        self.assertEqual(c._cursor_for(Qt.Edge.TopEdge),
                         Qt.CursorShape.SizeVerCursor)
        self.assertEqual(c._cursor_for(Qt.Edge.LeftEdge | Qt.Edge.TopEdge),
                         Qt.CursorShape.SizeFDiagCursor)
        self.assertEqual(c._cursor_for(Qt.Edge.RightEdge | Qt.Edge.TopEdge),
                         Qt.CursorShape.SizeBDiagCursor)

    def test_maximized_drops_band_and_margin(self):
        c = self.win.chrome
        self.assertEqual(c._band, 10)
        c.set_maximized(True)
        self.assertEqual(c._band, 0)
        m = c._lay.contentsMargins()
        self.assertEqual((m.left(), m.top(), m.right(), m.bottom()), (0, 0, 0, 0))
        self.assertEqual(c._edge_at(QPoint(2, 200)), Qt.Edge(0))
        c.set_maximized(False)
        self.assertEqual(c._band, 10)

    def test_window_translucent_chrome_is_plain_child(self):
        # The top-level window is translucent (glass body); the chrome frame
        # itself stays an ordinary child widget (no extra attribute needed).
        self.assertTrue(
            self.win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertFalse(
            self.win.chrome.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))

    def test_pixels_are_glass_and_frame_is_visible(self):
        img = self.win.grab().toImage()
        W, H = img.width(), img.height()
        # Band pixel just inside the border: genuinely translucent glass —
        # the desktop shows through clearly, but alpha stays above zero
        # (never click-through).
        band = img.pixelColor(6, H // 2)
        self.assertGreater(band.alpha(), 20)
        self.assertLess(band.alpha(), 130)
        self.assertLessEqual(band.red(), 12)
        # Border pixel: the gold frame line is clearly visible.
        border = img.pixelColor(1, H // 2)
        self.assertGreater(border.red(), 180)
        self.assertGreater(border.green(), 150)
        self.assertLess(border.blue(), 90)

    def test_maximized_stays_glass(self):
        c = self.win.chrome
        c.set_maximized(True)
        img = self.win.grab().toImage()
        # Maximized = no band, square corners; still translucent glass.
        px = img.pixelColor(2, 2)
        self.assertGreater(px.alpha(), 20)
        self.assertLess(px.alpha(), 130)
        c.set_maximized(False)

    def test_active_toggle_and_paint_paths(self):
        c = self.win.chrome
        c.set_active(False)
        self.assertFalse(c._active)
        c.set_active(True)
        self.assertTrue(c._active)
        # Exercises the normal paintEvent (shadow/border/brackets).
        self.assertFalse(self.win.grab().isNull())
        # Exercises the maximized paint path too.
        c.set_maximized(True)
        self.assertFalse(self.win.grab().isNull())
        c.set_maximized(False)


class PersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_roundtrip(self):
        win = _Harness()
        win.setGeometry(120, 80, 700, 500)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            self.assertIsNone(load_window_state(win, p))
            save_window_state(win, p)
            self.assertTrue(p.exists())
            win2 = _Harness()
            flag = load_window_state(win2, p)
            self.assertIs(flag, False)
            g = win2.geometry()
            self.assertEqual((g.x(), g.y(), g.width(), g.height()), (120, 80, 700, 500))

    def test_restores_maximized_flag(self):
        win = _Harness()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            with mock.patch.object(win, "isMaximized", return_value=True):
                save_window_state(win, p)
            win2 = _Harness()
            self.assertTrue(load_window_state(win2, p))


if __name__ == "__main__":
    unittest.main(verbosity=2)
