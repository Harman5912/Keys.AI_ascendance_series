"""Keys.ai custom native window chrome.

Replaces the standard OS window frame (title bar, borders, buttons) with a
self-drawn futuristic HUD frame, while the window underneath stays a normal
native top-level window: Alt+Tab, taskbar, snapping, minimize/restore, focus,
multi-monitor and DPI scaling all keep working through the OS.

Design notes
------------
- ONE native top-level window only — no fake second window.
- Native move/resize via QWindow.startSystemMove() / startSystemResize(),
  which give free Windows snap + Aero behaviour. No polling loops anywhere.
- The window is frameless with a TRANSLUCENT GLASS body: WA_TranslucentBackground
  gives per-pixel alpha, and on Windows the DWM acrylic effect blurs what is
  behind it (best-effort; plain translucency is the silent fallback). All
  fills keep alpha comfortably above zero, so nothing is fully transparent
  or click-through.- Rounded corners come from the OS (Windows 11 DWM corner preference), which
  rounds the window natively without any transparent pixels.
- The outer band paints a static visible gold border + futuristic corner
  brackets in paintEvent (expose/resize only) — no per-frame cost.
- Window geometry (size/position/maximized) is persisted to a tiny JSON file,
  written once on close, restored on startup.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QFont, QLinearGradient,
                          QPainter, QPainterPath, QPen)
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

# frame geometry ------------------------------------------------------------
_BAND      = 10      # outer band around the chrome: visible border + resize zone
_EDGE      = 8       # resize hit margin (inside the band) — spec wants ~6-10 px

# palette — restrained gold on deep charcoal (minimal futuristic console) ----
_GOLD     = (217, 182, 80)
_AMBER    = (201, 162, 68)


def _c(r: int, g: int, b: int, a: int = 255) -> QColor:
    c = QColor(r, g, b)
    c.setAlpha(a)
    return c


class _TitleButton(QPushButton):
    """Small window-control button: thin outline -> slight glow on hover."""

    def __init__(self, glyph: str, tip: str, danger: bool = False, parent=None):
        super().__init__(glyph, parent)
        self._danger = danger
        self.setFixedSize(34, 22)
        self.setFont(QFont("Segoe UI Symbol", 11))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(tip)
        self.setStyleSheet(self._css())

    def _css(self) -> str:
        if self._danger:
            hov_bg, hov_fg = "rgba(255, 60, 60, 80)", "#ff5050"
            pre_bg = "rgba(255, 60, 60, 130)"
        else:
            hov_bg, hov_fg = "rgba(217, 182, 80, 34)", "#E5C368"
            pre_bg = "rgba(217, 182, 80, 70)"
        return (
            "QPushButton { background: transparent; color: #C9C9C9;"
            " border: 1px solid transparent; border-radius: 3px;"
            " padding: 0; margin: 0; }"
            " QPushButton:hover { background: " + hov_bg + "; color: " + hov_fg + ";"
            " border: 1px solid rgba(217, 182, 80, 80); }"
            " QPushButton:pressed { background: " + pre_bg + "; }"
        )


class CustomTitleBar(QWidget):
    """Keys.ai title bar: identity, live status dot, and window controls.

    The whole bar is draggable (native move -> snap works); the buttons are
    excluded from dragging and double-click toggles normal <-> maximized.
    """

    minimizeRequested = pyqtSignal()
    maximizeRequested = pyqtSignal()
    closeRequested    = pyqtSignal()

    _H = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self._H)
        self.setObjectName("keysaiTitleBar")
        self.setStyleSheet("QWidget#keysaiTitleBar { background: transparent; }")
        self._dragging = False
        self._drag_off = QPoint(0, 0)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 6, 0)
        lay.setSpacing(8)

        ident = QLabel("◉  KEYS.AI")
        ident.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        ident.setStyleSheet("color: #E5C368; background: transparent;")
        lay.addWidget(ident)

        sub = QLabel("ACENDENCE VII [GEN I]")
        sub.setFont(QFont("Courier New", 7))
        sub.setStyleSheet("color: #8A6D2F; background: transparent;")
        lay.addWidget(sub)

        lay.addStretch(1)

        self._dot = QLabel("●")
        self._dot.setFont(QFont("Segoe UI Symbol", 8))
        self._dot.setStyleSheet("color: #00FF88; background: transparent;")
        lay.addWidget(self._dot)
        self._status = QLabel("ONLINE")
        self._status.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._status.setStyleSheet("color: #8899AA; background: transparent;")
        lay.addWidget(self._status)

        # Administrator-mode badge (legitimate elevation indicator).
        self._priv = QLabel("")
        self._priv.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._priv.setStyleSheet("color: #FFD700; background: transparent;")
        self._priv.setVisible(False)
        lay.addWidget(self._priv)

        self._min_btn   = _TitleButton("—", "Minimize")
        self._max_btn   = _TitleButton("□", "Maximize")
        self._close_btn = _TitleButton("×", "Close", danger=True)
        lay.addWidget(self._min_btn)
        lay.addWidget(self._max_btn)
        lay.addWidget(self._close_btn)

        self._min_btn.clicked.connect(self.minimizeRequested)
        self._max_btn.clicked.connect(self.maximizeRequested)
        self._close_btn.clicked.connect(self.closeRequested)

        # subtle 1 Hz pulse on the status dot — negligible cost
        self._pulse = QTimer(self)
        self._pulse.timeout.connect(self._pulse_dot)
        self._pulse.start(1000)

    # status -----------------------------------------------------------------
    def set_status(self, text: str, speaking: bool = False) -> None:
        self._status.setText((text or "ONLINE").upper()[:14])
        self._dot.setStyleSheet(
            "color: #FFD700; background: transparent;" if speaking
            else "color: #00FF88; background: transparent;")

    def set_privilege(self, elevated: bool) -> None:
        """Show/hide the ADMIN badge when running elevated."""
        self._priv.setText("◉ ADMIN" if elevated else "")
        self._priv.setVisible(bool(elevated))

    def _pulse_dot(self) -> None:
        self._dot.setVisible(not self._dot.isVisible())

    def refresh_state(self) -> None:
        """Sync the maximize/restore glyph with the window state."""
        win = self.window()
        if win is None or win is self:
            return
        try:
            maxed = bool(win.isMaximized() or win.isFullScreen())
        except Exception:
            maxed = False
        self._max_btn.setText("❐" if maxed else "□")
        self._max_btn.setToolTip("Restore" if maxed else "Maximize")

    # dragging (native move -> Windows snap works) --------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if isinstance(self.childAt(e.position().toPoint()), _TitleButton):
                e.ignore()
                return
            self._begin_native_move(e)
            e.accept()
            return
        super().mousePressEvent(e)

    def _begin_native_move(self, e) -> None:
        win = self.window()
        from_max = False
        if win.isMaximized() or win.isFullScreen():
            win.showNormal()
            from_max = True
        if from_max:
            # Reposition under the cursor after restoring, otherwise the
            # system move would start from the old maximized top-left and
            # the window would "teleport" away from the grab point.
            try:
                g = e.globalPosition().toPoint()
                win.move(g.x() - win.width() // 2, max(0, g.y() - 20))
            except Exception:
                pass
        wh = win.windowHandle()
        if wh is not None and hasattr(wh, "startSystemMove"):
            try:
                wh.startSystemMove()
                return
            except Exception:
                pass
        # Manual fallback for platforms without native system move.
        self._dragging = True
        self._drag_off = e.globalPosition().toPoint() - win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._dragging:
            win = self.window()
            win.move(e.globalPosition().toPoint() - self._drag_off)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._dragging = False
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if not isinstance(self.childAt(e.position().toPoint()), _TitleButton):
                self.maximizeRequested.emit()
                e.accept()
                return
        super().mouseDoubleClickEvent(e)


class WindowChromeFrame(QWidget):
    """Central shell: paints the custom frame, hosts the title bar + HUD, and
    provides native edge resizing with correct cursors.

    Layout:  [custom title bar]  (top)
             [existing HUD]      (stretch — the caller's own widget, reused)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("keysaiChrome")
        self.setMouseTracking(True)
        self._band      = _BAND
        self._maximized = False
        self._active    = True
        self._content: Optional[QWidget] = None

        self.title_bar = CustomTitleBar(self)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(self._band, self._band, self._band, self._band)
        self._lay.setSpacing(0)
        self._lay.addWidget(self.title_bar)

    # content ----------------------------------------------------------------
    def set_content_widget(self, w: QWidget) -> None:
        """Attach the existing HUD surface below the title bar (reused, not duplicated)."""
        if self._content is not None:
            self._lay.removeWidget(self._content)
        self._content = w
        self._lay.addWidget(w, stretch=1)

    # state ------------------------------------------------------------------
    def set_maximized(self, maxed: bool) -> None:
        """Max/fullscreen drops the chrome band so the HUD fills the work area;
        restore re-adds it. Square corners while maximized, rounded otherwise."""
        self._maximized = bool(maxed)
        self._band = 0 if self._maximized else _BAND
        m = self._band
        self._lay.setContentsMargins(m, m, m, m)
        self._apply_native_corners()
        self.update()

    def set_active(self, active: bool) -> None:
        """Dim the frame slightly while the window is inactive."""
        self._active = bool(active)
        self.update()

    # rounded corners via the OS (Windows 11) — no transparency, no click-through
    def _apply_native_corners(self) -> None:
        try:
            if sys.platform != "win32":
                return
            import ctypes
            win = self.window()
            if win is None or not win.isVisible():
                return   # showEvent applies it once the window is up
            hwnd = int(win.winId())
            dwm = ctypes.windll.dwmapi
            # Declare the signature so the 64-bit HWND isn't truncated to c_int.
            dwm.DwmSetWindowAttribute.argtypes = [
                ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
            # DWMWA_WINDOW_CORNER_PREFERENCE = 33
            # DWMWCP_DONOTROUND = 1, DWMWCP_ROUND = 2
            pref = 1 if self._maximized else 2
            dwm.DwmSetWindowAttribute(
                hwnd, 33,
                ctypes.byref(ctypes.c_int(pref)),
                ctypes.sizeof(ctypes.c_int))
        except Exception:
            pass

    def showEvent(self, e):
        super().showEvent(e)
        self._apply_native_corners()
        apply_acrylic(self.window())

    # frame painting (translucent glass body + gold frame)
    def paintEvent(self, _):
        p = QPainter(self)
        W, H = self.width(), self.height()
        if W < 4 or H < 4:
            return
        # 0) invisible input-capturing base: even the rounded corner notches
        #    keep alpha 1, so nothing is ever click-through (any compositing path).
        p.fillRect(self.rect(), _c(0, 0, 0, 1))
        # 1) glass body - translucent gradient; the desktop shows through
        #    clearly (frosted glass, not a solid slab). The black alpha-1 base
        #    above still captures input everywhere, so nothing is click-through.
        #    Alphas stay low so the window is almost fully see-through behind
        #    the DWM blur — just a faint charcoal wash for text contrast.
        _g = QLinearGradient(0, 0, 0, H)
        _g.setColorAt(0.0, _c(6, 7, 10, 56))
        _g.setColorAt(1.0, _c(8, 10, 16, 48))
        _path = QPainterPath()
        _r = 0 if self._maximized else 12
        _path.addRoundedRect(QRectF(0, 0, W - 1, H - 1), _r, _r)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillPath(_path, QBrush(_g))

        # 2) visible luminous border around the whole window (drawn WITHOUT
        #    antialiasing so the 1px line sits flush on pixel row 1, not
        #    half-straddling the widget edge)
        a = 255 if self._active else 120
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(QPen(_c(*_GOLD, a), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(1, 1, W - 2, H - 2))
        # 3) inner accent line (subtle depth)
        p.setPen(QPen(_c(*_AMBER, 48 if self._active else 24), 1))
        p.drawRect(QRectF(7, 7, W - 14, H - 14))
        # 4) futuristic corner brackets (AA on — small decorative detail only)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        br = 12
        p.setPen(QPen(_c(*_GOLD, 220 if self._active else 120), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(4, 4 + br), QPointF(4, 4))
        p.drawLine(QPointF(4, 4), QPointF(4 + br, 4))
        p.drawLine(QPointF(W - 5 - br, 4), QPointF(W - 5, 4))
        p.drawLine(QPointF(W - 5, 4), QPointF(W - 5, 4 + br))
        p.drawLine(QPointF(4, H - 5 - br), QPointF(4, H - 5))
        p.drawLine(QPointF(4, H - 5), QPointF(4 + br, H - 5))
        p.drawLine(QPointF(W - 5 - br, H - 5), QPointF(W - 5, H - 5))
        p.drawLine(QPointF(W - 5, H - 5), QPointF(W - 5, H - 5 - br))

    # native edge resizing ---------------------------------------------------
    def _edge_at(self, pos: QPoint) -> Qt.Edge:
        if self._band <= 0 or self._maximized:
            return Qt.Edge(0)
        win = self.window()
        if win is not None and win is not self:
            try:
                if win.isMaximized() or win.isFullScreen():
                    return Qt.Edge(0)
            except Exception:
                pass
        x, y = pos.x(), pos.y()
        W, H = self.width(), self.height()
        m = min(self._band, _EDGE)
        edges = Qt.Edge(0)
        if x <= m:
            edges |= Qt.Edge.LeftEdge
        elif x >= W - m:
            edges |= Qt.Edge.RightEdge
        if y <= m:
            edges |= Qt.Edge.TopEdge
        elif y >= H - m:
            edges |= Qt.Edge.BottomEdge
        return edges

    @staticmethod
    def _cursor_for(edges: Qt.Edge) -> Qt.CursorShape:
        if edges in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
                     Qt.Edge.RightEdge | Qt.Edge.BottomEdge):
            return Qt.CursorShape.SizeFDiagCursor
        if edges in (Qt.Edge.RightEdge | Qt.Edge.TopEdge,
                     Qt.Edge.LeftEdge | Qt.Edge.BottomEdge):
            return Qt.CursorShape.SizeBDiagCursor
        if edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            return Qt.CursorShape.SizeHorCursor
        if edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.NoButton:
            self.setCursor(self._cursor_for(self._edge_at(e.position().toPoint())))
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.unsetCursor()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            edges = self._edge_at(e.position().toPoint())
            if edges:
                wh = self.window().windowHandle()
                if wh is not None and hasattr(wh, "startSystemResize"):
                    try:
                        wh.startSystemResize(edges)
                        e.accept()
                        return
                    except Exception:
                        pass
        super().mousePressEvent(e)


# lightweight geometry persistence (JSON, debounced by write-on-close) --------

def save_window_state(win, path: Path) -> None:
    """Persist the window's normal geometry + maximized flag (once per close)."""
    try:
        geo = win.normalGeometry()
        data = {
            "x": int(geo.x()), "y": int(geo.y()),
            "w": int(geo.width()), "h": int(geo.height()),
            "maximized": bool(win.isMaximized()),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def load_window_state(win, path: Path) -> Optional[bool]:
    """Restore geometry from the JSON state file.

    Returns the stored "start maximized" flag (True/False) when state was
    applied, or None when there is no usable state file — the caller then
    falls back to its default geometry. Restored geometry is clamped to a
    currently-visible screen so a window never lands off-screen after a
    monitor was unplugged.
    """
    try:
        if not path.exists():
            return None
        d = json.loads(path.read_text(encoding="utf-8"))
        rect = QRect(int(d["x"]), int(d["y"]), int(d["w"]), int(d["h"]))
        from PyQt6.QtWidgets import QApplication
        screens = QApplication.screens() or []
        if not any(s.availableGeometry().intersects(rect) for s in screens):
            return None
        win.setGeometry(rect)
        return bool(d.get("maximized", False))
    except Exception:
        return None


def apply_acrylic(win) -> None:
    """Best-effort frosted-glass blur behind a top-level window (Windows DWM).

    Falls back silently to plain per-pixel translucency when the platform or
    DWM does not support the effect. Shared by the main window chrome and the
    mini overlay so every glass surface matches.
    """
    if sys.platform != "win32":
        return
    hwnd = ex = None
    user32 = None
    try:
        import ctypes
        if win is None or not win.isVisible():
            return
        hwnd = int(win.winId())
        user32 = ctypes.windll.user32
        # Declare signatures so the 64-bit HWND is never truncated to
        # c_int (mirrors _apply_native_corners).
        user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long
        user32.SetWindowCompositionAttribute.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.SetWindowCompositionAttribute.restype = ctypes.c_int

        class _ACCENT(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_int),
            ]

        class _WCADATA(ctypes.Structure):
            _fields_ = [
                ("Attrib", ctypes.c_int),
                ("pvData", ctypes.c_void_p),
                ("cbData", ctypes.c_size_t),
            ]

        GWL_EXSTYLE, WS_EX_LAYERED = -20, 0x00080000
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

        data = _WCADATA()
        data.Attrib = 19  # WCA_ACCENT_POLICY
        accent = _ACCENT()
        accent.AccentFlags = 0x20 | 0x40 | 0x80
        accent.GradientColor = 0x5406080A  # AABBGGRR - light charcoal tint: the
                                           # DWM acrylic blur stays softened, but
                                           # the desktop still reads through
        data.pvData = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
        data.cbData = ctypes.sizeof(accent)
        ok = False
        # Phase 1: acrylic with the layered style intact - Qt keeps its
        # UpdateLayeredWindow path, so there is zero black-window risk.
        accent.AccentState = 4
        if user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data)):
            ok = True
        # Phase 2: most builds need WS_EX_LAYERED dropped for the blur to
        # show; only do that once the accent API is confirmed reachable.
        if not ok:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex & ~WS_EX_LAYERED)
            for state in (4, 3):  # acrylic, then classic blur
                accent.AccentState = state
                if user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data)):
                    ok = True
                    break
        if not ok:
            raise RuntimeError("DWM accent unavailable")
    except Exception:
        # Restore the original extended style so Qt's per-pixel translucency
        # keeps working (never leave a broken window state).
        try:
            if hwnd is not None and ex is not None and user32 is not None:
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
        except Exception:
            pass
