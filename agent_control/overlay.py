"""KEYS.AI CONTROL OVERLAY.

A slim always-on-top translucent window that wraps the application Keys.ai is
currently controlling. It shows:

    • animated gold border with glow/pulse around the controlled window
    • KEYS.AI watermark (existing logo asset) — semi-transparent, slow fade
    • status pill  — KEYS.AI • CONTROL ACTIVE / ANALYZING / EXECUTING /
                     VERIFYING / WAITING / PAUSED / USER CONTROL /
                     ACTION FAILED / STOPPED
    • PAUSE · STOP · TAKE CONTROL buttons (always available)
    • high-impact confirmation dialog (CONFIRM / CANCEL / TAKE CONTROL)

The border never blocks the app: the whole window is transparent for mouse
input except the small control buttons. It disappears the moment control is
released. It follows the controlled window when it moves or resizes.

`ControlOverlayBridge` is a QObject living on the Qt main thread; every
engine call from a worker thread goes through queued signals, so the overlay
is safe to drive from anywhere.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QPainterPath
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

# palette — Keys.ai gold/black/white sci-fi identity
_GOLD = (217, 182, 80)
_AMBER = (201, 162, 68)
_STATUS_COLORS = {
    "gold":   (229, 195, 104),
    "cyan":   (95, 200, 224),
    "green":  (61, 220, 132),
    "red":    (229, 72, 77),
    "blue":   (143, 184, 216),
    "amber":  (224, 158, 80),
    "muted":  (110, 118, 134),
}

_BORDER_M = 16          # how far the overlay window extends past the app window
_PILL_H = 24
_BTN_H = 22


def _c(r: int, g: int, b: int, a: int = 255) -> QColor:
    c = QColor(r, g, b)
    c.setAlpha(a)
    return c


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


class ControlOverlayBridge(QObject):
    """Thread-safe bridge between the engine (any thread) and the overlay (Qt)."""

    statusChanged = pyqtSignal(str)
    visibilityRequested = pyqtSignal(str, int, int, int, int)   # app, x, y, w, h
    hideRequested = pyqtSignal()
    highlightRequested = pyqtSignal(int, int, int, int, float)  # x1,y1,x2,y2,secs
    targetRequested = pyqtSignal(int, int, int, int,            # from x1,y1,x2,y2
                                 int, int, int, int, float)     # to x1,y1,x2,y2,secs
    gridRequested = pyqtSignal(int, int, int, int,              # from x1,y1,x2,y2
                               int, int, int, int, float)       # to x1,y1,x2,y2,secs
    gridPointRequested = pyqtSignal(int, int)                   # live cursor (x, y)
    gridHideRequested = pyqtSignal()
    confirmRequested = pyqtSignal(str, float)                    # prompt, timeout
    confirmResolved = pyqtSignal(str)                            # result
    historyEntry = pyqtSignal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._pending: Optional[Callable[[str], None]] = None
        self._follow: Optional[Callable[[], Optional[tuple]]] = None
        self._last_rect: Optional[tuple] = None
        self._last_app = ""
        self.confirmResolved.connect(self._on_confirm_resolved)

    # ── wiring ─────────────────────────────────────────────────────────
    def set_rect_provider(self, fn: Optional[Callable[[], Optional[tuple]]]) -> None:
        """UI wiring: callable returning the controlled window (x,y,w,h)."""
        self._follow = fn

    # ── engine-facing (any thread) ─────────────────────────────────────
    def set_status(self, text: str) -> None:
        self.statusChanged.emit(str(text))

    def show(self, app_name: str, rect: tuple) -> None:
        try:
            x, y, w, h = (int(v) for v in rect)
        except Exception:
            return
        self._last_app = str(app_name)
        self._last_rect = (x, y, w, h)
        self.visibilityRequested.emit(self._last_app, x, y, w, h)

    def hide(self) -> None:
        self.hideRequested.emit()

    def highlight(self, x1: int, y1: int, x2: int, y2: int,
                  seconds: float = 1.2) -> None:
        """Draw a visible yellow target box around a screen region for a
        moment — the user sees EXACTLY what the agent is about to click."""
        try:
            self.highlightRequested.emit(int(x1), int(y1), int(x2), int(y2),
                                         float(seconds))
        except Exception:
            pass

    def target(self, from_rect, to_rect, seconds: float = 0.6) -> None:
        """Animate a missile-style reticle gliding from `from_rect` to
        `to_rect` (both (x1,y1,x2,y2) screen coords). The flying square
        border is what the user sees right before each click — every step of
        a takeover uses it, so the whole overtake feels the same."""
        try:
            fx1, fy1, fx2, fy2 = (int(v) for v in from_rect)
            tx1, ty1, tx2, ty2 = (int(v) for v in to_rect)
        except Exception:
            return
        if tx2 <= tx1 or ty2 <= ty1:
            return
        try:
            self.targetRequested.emit(fx1, fy1, fx2, fy2,
                                      tx1, ty1, tx2, ty2,
                                      max(0.12, float(seconds)))
        except Exception:
            pass

    def grid_target(self, from_rect, to_rect, seconds: float = 0.6) -> None:
        """Show the full-screen targeting GRID: it draws the grid cells over
        the screen, pulses the cell the mouse is heading to, flies a reticle
        from `from_rect` onto `to_rect` (both (x1,y1,x2,y2) screen coords),
        and then tracks the live cursor crosshair. The user always SEES where
        the mouse is going before and during the move."""
        try:
            fx1, fy1, fx2, fy2 = (int(v) for v in from_rect)
            tx1, ty1, tx2, ty2 = (int(v) for v in to_rect)
        except Exception:
            return
        if tx2 <= tx1 or ty2 <= ty1:
            return
        try:
            self.gridRequested.emit(fx1, fy1, fx2, fy2,
                                    tx1, ty1, tx2, ty2,
                                    max(0.12, float(seconds)))
        except Exception:
            pass

    def grid_point(self, x: int, y: int) -> None:
        """Stream the real cursor position onto the grid overlay — the
        crosshair follows the actual mouse, not a guessed path."""
        try:
            self.gridPointRequested.emit(int(x), int(y))
        except Exception:
            pass

    def grid_hide(self) -> None:
        """Hide the targeting grid once the mouse move is done."""
        self.gridHideRequested.emit()

    def history_line(self, entry: dict) -> None:
        self.historyEntry.emit(dict(entry))

    def log(self, msg: str) -> None:
        print(f"[ControlOverlay] {msg}")

    # ── confirmation (blocking from the engine side) ───────────────────
    def request_confirm(self, prompt: str, timeout: float,
                        callback: Optional[Callable[[str], None]] = None) -> str:
        with self._lock:
            self._pending = callback
        self.confirmRequested.emit(str(prompt), float(timeout))
        return ""   # result arrives asynchronously through the callback

    def _on_confirm_resolved(self, result: str) -> None:
        with self._lock:
            cb = self._pending
            self._pending = None
        if cb is not None:
            try:
                cb(str(result))
            except Exception:
                pass


class _MiniBtn(QPushButton):
    """Tiny gold-outlined control button with hover glow."""

    def __init__(self, text: str, danger: bool = False, parent=None):
        super().__init__(text, parent)
        self._danger = danger
        self.setFixedHeight(_BTN_H)
        self.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet(self._css())

    def _css(self) -> str:
        accent = "#E5484D" if self._danger else "#D9B650"
        return (
            f"QPushButton {{ color: {accent}; background: rgba(6,7,10,215);"
            f" border: 1px solid {accent}; border-radius: 3px; padding: 0 8px; }}"
            f" QPushButton:hover {{ background: rgba({ '229,72,77' if self._danger else '217,182,80' }, 40);"
            f" color: #FFFFFF; }}"
            f" QPushButton:pressed {{ background: {accent}; color: #05060A; }}"
        )


class _ConfirmPanel(QWidget):
    """Centered CONFIRM / CANCEL / TAKE CONTROL dialog."""

    resolved = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("""
            _ConfirmPanel {
                background: rgba(5, 6, 10, 242);
                border: 1px solid rgba(217, 182, 80, 200);
                border-radius: 8px;
            }
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        self._title = QLabel("KEYS.AI IS READY TO PERFORM THIS ACTION")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._title.setStyleSheet("color: #E5C368; background: transparent;")
        lay.addWidget(self._title)

        self._prompt = QLabel("")
        self._prompt.setWordWrap(True)
        self._prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._prompt.setFont(QFont("Courier New", 8))
        self._prompt.setStyleSheet("color: #C3CBD6; background: transparent;")
        lay.addWidget(self._prompt)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._confirm_btn = QPushButton("CONFIRM")
        self._cancel_btn = QPushButton("CANCEL")
        self._take_btn = QPushButton("TAKE CONTROL")
        for b in (self._confirm_btn, self._cancel_btn, self._take_btn):
            b.setFixedHeight(26)
            b.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._confirm_btn.setStyleSheet(
            "QPushButton { background: #D9B650; color: #05060A; border: none;"
            " border-radius: 3px; padding: 0 12px; }"
            " QPushButton:hover { background: #E5C368; }")
        self._cancel_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #C3CBD6;"
            " border: 1px solid #6E7686; border-radius: 3px; padding: 0 12px; }"
            " QPushButton:hover { border-color: #FFFFFF; color: #FFFFFF; }")
        self._take_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #4FD0E0;"
            " border: 1px solid #4FD0E0; border-radius: 3px; padding: 0 10px; }"
            " QPushButton:hover { background: rgba(79,208,224,40); }")
        self._confirm_btn.clicked.connect(lambda: self._resolve("confirm"))
        self._cancel_btn.clicked.connect(lambda: self._resolve("cancel"))
        self._take_btn.clicked.connect(lambda: self._resolve("takeover"))
        row.addWidget(self._confirm_btn)
        row.addWidget(self._cancel_btn)
        row.addWidget(self._take_btn)
        lay.addLayout(row)
        self.hide()

    def _resolve(self, result: str) -> None:
        self.hide()
        self.resolved.emit(result)

    def show_prompt(self, prompt: str) -> None:
        self._prompt.setText(prompt)
        self.adjustSize()
        self.show()
        self.raise_()
        par = self.parentWidget()
        if par is not None:
            self.move((par.width() - self.width()) // 2,
                      (par.height() - self.height()) // 2)


class ControlOverlay(QWidget):
    """The animated gold control border + watermark + controls."""

    pauseClicked = pyqtSignal()
    stopClicked = pyqtSignal()
    takeControlClicked = pyqtSignal()

    def __init__(self, bridge: Optional[ControlOverlayBridge] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._app = ""
        self._rect: Optional[tuple] = None       # (x, y, w, h) of the app window
        self._phase = 0.0
        self._watermark_phase = 0.0
        self._status = "KEYS.AI • CONTROL ACTIVE"
        self._status_role = "gold"
        self._logo: Optional[QPixmap] = None
        self._follow_timer: Optional[QTimer] = None
        self._target_rect: Optional[tuple] = None    # (x1, y1, x2, y2) screen px
        self._target_until = 0.0                     # expiry timestamp
        self._reticle: Optional[dict] = None         # flying square border (missile)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)

        # ── interactive control buttons (bottom-left) ──────────────────
        self._controls = QWidget(self)
        self._controls.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        row = QHBoxLayout(self._controls)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self._pause_btn = _MiniBtn("⏸ PAUSE")
        self._stop_btn = _MiniBtn("■ STOP", danger=True)
        self._take_btn = _MiniBtn("✋ TAKE CONTROL")
        self._pause_btn.clicked.connect(self.pauseClicked)
        self._stop_btn.clicked.connect(self.stopClicked)
        self._take_btn.clicked.connect(self.takeControlClicked)
        row.addWidget(self._pause_btn)
        row.addWidget(self._stop_btn)
        row.addWidget(self._take_btn)
        self._controls.hide()

        # ── confirmation dialog ────────────────────────────────────────
        self._confirm_panel = _ConfirmPanel(self)
        self._confirm_panel.resolved.connect(self._on_confirm_resolved)
        self._confirm_timer: Optional[QTimer] = None   # tracked auto-cancel

        self._anim = QTimer(self)
        self._anim.timeout.connect(self._step)
        self._anim.start(33)   # ~30 fps only while visible — cheap

        self.hide()
        if self._bridge is not None:
            self._bind()

    # ── bridge wiring ──────────────────────────────────────────────────
    def _bind(self) -> None:
        b = self._bridge
        b.statusChanged.connect(self.set_status)
        b.visibilityRequested.connect(self._on_show)
        b.hideRequested.connect(self._hide_overlay)
        b.highlightRequested.connect(self._on_highlight)
        b.targetRequested.connect(self._on_target)
        b.confirmRequested.connect(self._on_confirm_requested)

    def _on_highlight(self, x1: int, y1: int, x2: int, y2: int,
                      seconds: float) -> None:
        """Show a yellow target box around (x1,y1,x2,y2) in SCREEN coords."""
        if x2 <= x1 or y2 <= y1:
            return
        # pad a little so the box visibly surrounds the target, not hugs it
        self._target_rect = (x1 - 6, y1 - 6, x2 + 6, y2 + 6)
        self._target_until = time.time() + max(0.3, seconds)
        self.update()

    def _target_expired(self) -> bool:
        return time.time() > self._target_until

    def _on_target(self, fx1: int, fy1: int, fx2: int, fy2: int,
                   tx1: int, ty1: int, tx2: int, ty2: int,
                   seconds: float) -> None:
        """Start the missile reticle glide from the previous selection to
        the new one. On arrival it locks into the static TARGET box."""
        self._reticle = {
            "from": (fx1, fy1, fx2, fy2),
            "to":   (tx1, ty1, tx2, ty2),
            "start": time.time(),
            "dur":   max(0.12, float(seconds)),
        }
        self._target_rect = None      # replace any stale static box during the glide
        self.update()

    def set_rect_provider(self, fn) -> None:
        if self._bridge is not None:
            self._bridge.set_rect_provider(fn)

    # ── public (bridge slots — Qt thread) ──────────────────────────────
    def set_status(self, text: str) -> None:
        self._status = str(text)
        role = "gold"
        t = self._status.upper()
        if "VERIFY" in t:
            role = "cyan"
        elif "USER" in t or "PAUSED" in t or "WAIT" in t:
            role = "blue"
        elif "FAILED" in t or "STOP" in t:
            role = "red"
        elif "RELEASED" in t or "COMPLETED" in t:
            role = "green"
        elif "RECOVER" in t:
            role = "amber"
        self._status_role = role
        self.update()

    def _on_show(self, app: str, x: int, y: int, w: int, h: int) -> None:
        self._app = app
        self._rect = (x, y, w, h)
        self._confirm_panel.hide()
        self._controls.show()
        self._apply_geometry(x, y, w, h)
        self.show()
        self.raise_()

    def _hide_overlay(self) -> None:
        self._confirm_panel.hide()
        self._controls.hide()
        self._target_rect = None
        self._reticle = None
        self.hide()

    def _on_confirm_requested(self, prompt: str, timeout: float) -> None:
        # cancel any stale pending auto-cancel timer before showing a new dialog
        if self._confirm_timer is not None:
            self._confirm_timer.stop()
            self._confirm_timer = None
        self._controls.hide()
        self._confirm_panel.show_prompt(prompt)
        self.raise_()
        if timeout > 0:
            self._confirm_timer = QTimer(self)
            self._confirm_timer.setSingleShot(True)
            self._confirm_timer.timeout.connect(self._confirm_timeout)
            self._confirm_timer.start(int(timeout * 1000))

    def _confirm_timeout(self) -> None:
        self._confirm_timer = None
        if self._confirm_panel.isVisible():
            self._confirm_panel.hide()
            self._controls.show()
            if self._bridge is not None:
                self._bridge.confirmResolved.emit("timeout")

    def _on_confirm_resolved(self, result: str) -> None:
        if self._confirm_timer is not None:
            self._confirm_timer.stop()
            self._confirm_timer = None
        self._confirm_panel.hide()
        self._controls.show()
        if self._bridge is not None:
            self._bridge.confirmResolved.emit(result)

    # ── geometry / follow ──────────────────────────────────────────────
    def _apply_geometry(self, x: int, y: int, w: int, h: int) -> None:
        m = _BORDER_M
        self.setGeometry(x - m, y - m, w + m * 2, h + m * 2)
        self._layout_children()

    def _layout_children(self) -> None:
        W, H = self.width(), self.height()
        self._controls.setGeometry(12, H - _BTN_H - 12,
                                   self._controls.sizeHint().width(), _BTN_H)
        # center the confirm panel
        pw, ph = 400, 150
        self._confirm_panel.setGeometry((W - pw) // 2, (H - ph) // 2, pw, ph)

    def _follow(self) -> None:
        """Re-acquire the controlled window's rect (moves/resizes)."""
        if self._bridge is None:
            return
        fn = self._bridge._follow
        if fn is None:
            return
        try:
            r = fn()
        except Exception:
            return
        if not r or self._rect is None or len(r) != 4:
            return
        if r[2] <= 0 or r[3] <= 0:
            return   # no usable window geometry yet
        if (abs(r[0] - self._rect[0]) > 2 or abs(r[1] - self._rect[1]) > 2 or
                abs(r[2] - self._rect[2]) > 2 or abs(r[3] - self._rect[3]) > 2):
            self._rect = r
            if self.isVisible():
                self._apply_geometry(*r)

    # ── animation / paint ──────────────────────────────────────────────
    def _step(self) -> None:
        if not self.isVisible():
            return
        self._phase += 0.09
        self._watermark_phase += 0.025
        if self._phase >= 1000:
            self._phase = 0.0
        self._follow()
        if self._target_rect is not None and self._target_expired():
            self._target_rect = None   # box fades away once the click happens
        if self._reticle is not None:
            r = self._reticle
            t = (time.time() - r["start"]) / r["dur"]
            if t >= 1.0:
                # glide finished — lock onto the target and hold briefly
                self._reticle = None
                self._target_rect = r["to"]
                self._target_until = time.time() + 0.9
        self.update()

    def _load_logo(self) -> Optional[QPixmap]:
        if self._logo is not None:
            return self._logo
        for cand in (_base_dir() / "icon.png", _base_dir() / "keys_eye_icon.ico"):
            if cand.exists():
                px = QPixmap(str(cand))
                if not px.isNull():
                    self._logo = px.scaled(
                        46, 46, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
                    return self._logo
        self._logo = QPixmap(1, 1)
        return None

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        if W < 20 or H < 20:
            return
        m = _BORDER_M - 2
        box = QRectF(m, m, W - m * 2, H - m * 2)

        # ── animated gold glow border ──────────────────────────────────
        pulse = (math.sin(self._phase) + 1.0) / 2.0          # 0..1
        layers = [
            (6.5, 40 + int(60 * pulse)),                     # outer soft glow
            (3.5, 120 + int(80 * pulse)),                    # mid glow
            (1.6, 200 + int(55 * pulse)),                    # bright core
        ]
        for i, (width, alpha) in enumerate(layers):
            p.setPen(QPen(_c(*_GOLD, min(255, alpha)), width))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box.adjusted(i * 1.2, i * 1.2, -i * 1.2, -i * 1.2), 10, 10)

        # corner brackets
        br = 22
        p.setPen(QPen(_c(229, 195, 104, 235), 2.2))
        for cx, cy, dx, dy in [(m, m, 1, 1), (W - m, m, -1, 1),
                               (m, H - m, 1, -1), (W - m, H - m, -1, -1)]:
            p.drawLine(int(cx), int(cy), int(cx + dx * br), int(cy))
            p.drawLine(int(cx), int(cy), int(cx), int(cy + dy * br))

        # scanner sweep along the top edge
        sweep_x = m + ((self._phase * 2.2) % max(1.0, W - m * 2))
        p.fillRect(QRectF(sweep_x, m, 3, 14), _c(229, 195, 104, 210))

        # ── MISSILE reticle (the flying square border right before a click) ──
        if self._reticle is not None:
            r = self._reticle
            t = min(1.0, max(0.0, (time.time() - r["start"]) / r["dur"]))
            e = 1.0 - (1.0 - t) ** 3.2          # missile: fast launch, decel to lock
            f, to = r["from"], r["to"]
            gx1 = f[0] + (to[0] - f[0]) * e
            gy1 = f[1] + (to[1] - f[1]) * e
            gx2 = f[2] + (to[2] - f[2]) * e
            gy2 = f[3] + (to[3] - f[3]) * e
            self._draw_target_box(p, gx1, gy1, gx2, gy2)

        # ── yellow TARGET box (the element the agent is about to click) ──
        if self._target_rect is not None and not self._target_expired() \
                and self._rect is not None:
            x1, y1, x2, y2 = self._target_rect
            self._draw_target_box(p, x1, y1, x2, y2)

        # ── status pill (top-left) ─────────────────────────────────────
        role_col = _STATUS_COLORS.get(self._status_role, _GOLD)
        pill_w = min(W - 24, 12 + 8 * len(self._status) + 24)
        pill = QRectF(12, 12, pill_w, _PILL_H)
        path = QPainterPath()
        path.addRoundedRect(pill, 6, 6)
        p.fillPath(path, _c(5, 6, 10, 230))
        p.setPen(QPen(_c(*role_col, 200), 1))
        p.drawPath(path)
        p.setPen(_c(255, 255, 255, 235))
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.drawText(pill.adjusted(10, 0, -6, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._status)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_c(*role_col, 220), 1.4))
        p.drawEllipse(QRectF(pill.right() - 22, pill.top() + 7, 10, 10))

        # ── watermark (bottom-right) — semi-transparent, slow fade ─────
        fade = 0.72 + 0.18 * math.sin(self._watermark_phase)
        logo = self._load_logo()
        wm_w, wm_h = 46, 46
        wx = W - wm_w - 14
        wy = H - wm_h - 12
        p.setOpacity(fade * 0.85)
        if logo is not None and logo.width() > 1:
            p.drawPixmap(int(wx), int(wy), logo)
        else:
            p.setPen(_c(*_GOLD, 220))
            p.setFont(QFont("Courier New", 15, QFont.Weight.Bold))
            p.drawText(QRectF(wx, wy, wm_w, wm_h), Qt.AlignmentFlag.AlignCenter, "◉")
        p.setPen(_c(229, 195, 104, 215))
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.drawText(QRectF(wx - 130, wy + 46, 190, 18),
                   Qt.AlignmentFlag.AlignRight, "KEYS.AI · CONTROL ACTIVE")
        p.setOpacity(1.0)
        p.setPen(_c(169, 178, 192, 190))
        p.setFont(QFont("Courier New", 7))
        p.drawText(QRectF(wx - 150, wy + 62, 210, 14),
                   Qt.AlignmentFlag.AlignRight, self._app[:34])

    def _draw_target_box(self, p: QPainter, x1: float, y1: float,
                         x2: float, y2: float) -> None:
        """Paint the yellow square TARGET border around a screen-coord rect
        (shared by the flying missile reticle and the static lock box)."""
        if x2 <= x1 or y2 <= y1:
            return
        ox, oy = self.geometry().x(), self.geometry().y()
        lx1, ly1 = x1 - ox, y1 - oy
        lx2, ly2 = x2 - ox, y2 - oy
        box = QRectF(lx1, ly1, max(2.0, lx2 - lx1), max(2.0, ly2 - ly1))
        pulse = (math.sin(self._phase * 2.4) + 1.0) / 2.0
        p.setPen(QPen(_c(255, 214, 60, 220), 3.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(box)
        p.setPen(QPen(_c(255, 214, 60, int(90 + 120 * pulse)), 1.6))
        p.drawRect(box.adjusted(5, 5, -5, -5))
        # corner brackets make the target unmistakable
        br = 14
        p.setPen(QPen(_c(255, 240, 140, 255), 2.4))
        for cx, cy, dx, dy in [(lx1, ly1, 1, 1), (lx2, ly1, -1, 1),
                               (lx1, ly2, 1, -1), (lx2, ly2, -1, -1)]:
            p.drawLine(int(cx), int(cy), int(cx + dx * br), int(cy))
            p.drawLine(int(cx), int(cy), int(cx), int(cy + dy * br))
        # tiny TARGET label above the box
        lab = QRectF(lx1, ly1 - 20, 74, 16)
        path = QPainterPath()
        path.addRoundedRect(lab, 3, 3)
        p.fillPath(path, _c(5, 6, 10, 230))
        p.setPen(QPen(_c(255, 214, 60, 220), 1))
        p.drawPath(path)
        p.setPen(_c(255, 235, 150, 255))
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.drawText(lab, Qt.AlignmentFlag.AlignCenter, "TARGET")


_GRID_LINE_A = 46                  # faint grid-line alpha
_GRID_HOLD_S = 1.0                 # how long the locked target stays after glide


class GridTargetOverlay(QWidget):
    """Full-screen targeting GRID shown while the agent moves the mouse.

    The user asked for "grid-like control" so every mouse move is visible
    and predictable: while a move is being prepared the overlay draws a
    faint gold grid across the screen, pulses the CELL the cursor is heading
    to (with a row-column label), flies a small reticle from the previous
    selection onto the target, and streams the REAL cursor position as a
    crosshair — so the user sees exactly which grid square the mouse will
    land in, before and during the move.

    Fully transparent for mouse input; hides itself automatically after the
    target lock expires (and immediately on `hide_grid()`).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
        self._phase = 0.0
        self._cols = 1
        self._rows = 1
        self._cell: Optional[tuple] = None      # (col, row) target cell
        self._reticle: Optional[dict] = None    # flying square border (missile)
        self._cursor: Optional[tuple] = None    # (x, y) streamed from the mouse
        self._lock_rect: Optional[tuple] = None
        self._lock_until = 0.0
        self._fade = 1.0                        # 0..1 auto fade-out when idle
        self._anim = QTimer(self)
        self._anim.timeout.connect(self._step)
        self._anim.start(33)                    # ~30 fps only while visible
        self.hide()

    # ── bridge slots (Qt thread) ──────────────────────────────────────
    def show_grid(self, fx1: int, fy1: int, fx2: int, fy2: int,
                  tx1: int, ty1: int, tx2: int, ty2: int,
                  seconds: float) -> None:
        """Show the grid over the primary screen and start the targeting
        animation from `from` onto `to` (global screen coords)."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.geometry()
        self.setGeometry(geo)
        self._layout_cells(geo.width(), geo.height())
        self._reticle = {
            "from": (int(fx1), int(fy1), int(fx2), int(fy2)),
            "to":   (int(tx1), int(ty1), int(tx2), int(ty2)),
            "start": time.time(),
            "dur":   max(0.12, float(seconds)),
        }
        self._cell = self._cell_at((int(tx1) + int(tx2)) // 2,
                                   (int(ty1) + int(ty2)) // 2)
        self._lock_rect = None
        self._cursor = None      # no stale crosshair from the previous move
        self._fade = 0.0
        self._phase = 0.0
        self.show()
        self.raise_()

    def stream_point(self, x: int, y: int) -> None:
        """Live cursor position from the real mouse (thread-safe: Qt thread)."""
        self._cursor = (int(x), int(y))
        if self.isVisible():
            self.update()

    def hide_grid(self) -> None:
        self._reticle = None
        self._lock_rect = None
        self._cursor = None
        self.hide()

    # ── grid layout ───────────────────────────────────────────────────
    def _layout_cells(self, w: int, h: int) -> None:
        """Adaptive cell size (~1/7 of the long edge), never fewer than 3×2."""
        cell = max(140, min(260, int(max(w, h) / 7)))
        self._cols = max(3, math.ceil(w / cell))
        self._rows = max(2, math.ceil(h / cell))

    def _cell_at(self, gx: int, gy: int) -> Optional[tuple]:
        if self._cols < 1 or self._rows < 1:
            return None
        ox, oy = self.geometry().x(), self.geometry().y()
        col = min(self._cols - 1, max(0, (gx - ox) * self._cols // max(1, self.width())))
        row = min(self._rows - 1, max(0, (gy - oy) * self._rows // max(1, self.height())))
        return (col, row)

    def _cell_rect(self, col: int, row: int) -> QRectF:
        W, H = self.width(), self.height()
        x1 = W * col / self._cols
        y1 = H * row / self._rows
        return QRectF(x1, y1, W * (col + 1) / self._cols - x1,
                      H * (row + 1) / self._rows - y1)

    # ── animation / paint ─────────────────────────────────────────────
    def _step(self) -> None:
        if not self.isVisible():
            return
        self._phase += 0.11
        now = time.time()
        if self._reticle is not None:
            r = self._reticle
            t = (now - r["start"]) / r["dur"]
            if t >= 1.0:
                self._reticle = None
                self._lock_rect = r["to"]
                self._lock_until = now + _GRID_HOLD_S
        elif self._lock_rect is not None and now > self._lock_until:
            self._lock_rect = None
            self._cursor = None
        if self._reticle is None and self._lock_rect is None:
            # nothing active — fade out, then hide (safety net for callers
            # that forget an explicit grid_hide)
            self._fade = min(1.0, self._fade + 0.18)
            if self._fade >= 1.0:
                self.hide()
                return
        else:
            self._fade = max(0.0, self._fade - 0.25)
        self.update()

    def _to_local(self, gx: float, gy: float) -> tuple:
        return (gx - self.geometry().x(), gy - self.geometry().y())

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        if W < 20 or H < 20:
            return
        op = max(0.0, 1.0 - self._fade)
        if op <= 0.02:
            return
        p.setOpacity(op)

        # ── the grid ─────────────────────────────────────────────────
        p.setPen(QPen(_c(229, 195, 104, _GRID_LINE_A), 1))
        for c in range(1, self._cols):
            x = W * c / self._cols
            p.drawLine(QPointF(x, 0), QPointF(x, H))
        for r in range(1, self._rows):
            y = H * r / self._rows
            p.drawLine(QPointF(0, y), QPointF(W, y))

        # ── the selected cell (where the mouse is going) ─────────────
        if self._cell is not None:
            pulse = (math.sin(self._phase * 2.6) + 1.0) / 2.0
            cell = self._cell_rect(*self._cell)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(255, 214, 60, int(24 + 34 * pulse)))
            p.fillRect(cell, p.brush())
            p.setPen(QPen(_c(255, 214, 60, int(110 + 130 * pulse)), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(cell.adjusted(1, 1, -1, -1))
            # row-column label inside the cell, e.g. "3-2"
            p.setPen(_c(255, 235, 150, int(85 + 125 * pulse)))
            p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            p.drawText(cell.adjusted(6, 4, -6, -4),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                       f"{self._cell[0] + 1}-{self._cell[1] + 1}")

        # ── missile reticle (the flying square border) ───────────────
        if self._reticle is not None:
            r = self._reticle
            t = min(1.0, max(0.0, (time.time() - r["start"]) / r["dur"]))
            e = 1.0 - (1.0 - t) ** 3.2          # missile: fast launch, decel
            f, to = r["from"], r["to"]
            lx1, ly1 = self._to_local(f[0] + (to[0] - f[0]) * e,
                                      f[1] + (to[1] - f[1]) * e)
            lx2, ly2 = self._to_local(f[2] + (to[2] - f[2]) * e,
                                      f[3] + (to[3] - f[3]) * e)
            self._draw_target_box(p, lx1, ly1, lx2, ly2)

        # ── static lock box once the reticle has landed ──────────────
        if self._lock_rect is not None and time.time() <= self._lock_until:
            x1, y1 = self._to_local(self._lock_rect[0], self._lock_rect[1])
            x2, y2 = self._to_local(self._lock_rect[2], self._lock_rect[3])
            self._draw_target_box(p, x1, y1, x2, y2)

        # ── live cursor crosshair (streamed from the real mouse) ─────
        if self._cursor is not None:
            cx, cy = self._to_local(*self._cursor)
            gap, arm = 6.0, 12.0
            p.setPen(QPen(_c(255, 214, 60, 235), 1.6))
            p.drawLine(QPointF(cx - arm, cy), QPointF(cx - gap, cy))
            p.drawLine(QPointF(cx + gap, cy), QPointF(cx + arm, cy))
            p.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy - gap))
            p.drawLine(QPointF(cx, cy + gap), QPointF(cx, cy + arm))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(255, 235, 150, 255))
            p.drawEllipse(QPointF(cx, cy), 2.2, 2.2)

        # ── tiny header: grid size ───────────────────────────────────
        p.setPen(_c(229, 195, 104, 130))
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.drawText(QRectF(8, 6, 160, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"GRID {self._cols}×{self._rows}")
        p.setOpacity(1.0)

    def _draw_target_box(self, p: QPainter, x1: float, y1: float,
                         x2: float, y2: float) -> None:
        """Yellow square TARGET border around a rect (local coords), shared
        by the flying missile reticle and the static lock box."""
        if x2 <= x1 or y2 <= y1:
            return
        box = QRectF(x1, y1, max(2.0, x2 - x1), max(2.0, y2 - y1))
        pulse = (math.sin(self._phase * 2.4) + 1.0) / 2.0
        p.setPen(QPen(_c(255, 214, 60, 220), 3.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(box)
        p.setPen(QPen(_c(255, 214, 60, int(90 + 120 * pulse)), 1.6))
        p.drawRect(box.adjusted(5, 5, -5, -5))
        br = 14
        p.setPen(QPen(_c(255, 240, 140, 255), 2.4))
        for cx0, cy0, dx, dy in [(x1, y1, 1, 1), (x2, y1, -1, 1),
                                 (x1, y2, 1, -1), (x2, y2, -1, -1)]:
            p.drawLine(int(cx0), int(cy0), int(cx0 + dx * br), int(cy0))
            p.drawLine(int(cx0), int(cy0), int(cx0), int(cy0 + dy * br))



