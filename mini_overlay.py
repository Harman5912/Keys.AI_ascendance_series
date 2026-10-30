"""
mini_overlay.py — Keys.ai background push-to-talk mini overlay.

The overlay and the main window are the SAME assistant — same engine, same
Live session, same tools (search, screen/camera vision, file & document
editing, apps, etc.). The only difference is which surface is showing:

  • When the MAIN window is the active foreground window → it handles the turn
    (live voice PTT); the overlay NEVER pops up at the same time, so nothing
    looks weird. If the main window is merely open in the background (another
    app is focused), the overlay takes over.
  • When the main window is hidden/minimized/closed → the overlay becomes the UI:
    HOLD K to talk, release to send. The popup stays up through the whole
    turn so the text output, suggestions and confirmations stay readable,
    then tucks itself away once the engine goes idle.
  • Audio input AND output go to the SAME place as the main UI: while K is
    held the main engine's own microphone stream is routed straight into the
    SAME Live session as live voice (push-to-talk), exactly like the main
    window — no second mic stream, no separate transcription. The model's
    spoken reply plays through the same speaker. The overlay is ONLY the
    text-output surface: every transcript, log, state and tool result is
    mirrored into it from the shared engine.
  • It NEVER triggers while you are typing — if a classic text-editing
    control is focused (or the main window's own command input) the K key is
    ignored, and Ctrl/Alt/Win+K are treated as shortcuts, never as PTT.
  • All engine output (logs, states, briefing content, camera frames) is
    mirrored into the popup via the KeysAIUI broadcast hooks.
  • Enable / disable from the main window: the MINI OVERLAY button or F5.

Dependencies: PyQt6, google-genai (audio comes from main.py's sounddevice stream).
"""

from __future__ import annotations

try:
    import ctypes
    from ctypes import wintypes
except Exception:
    ctypes = None
    wintypes = None
import math
import threading
import time

from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QRadialGradient,
)
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from window_chrome import apply_acrylic   # same DWM frosted glass as the main window

VK_K        = 0x4B           # virtual-key code for 'K'
_POLL_SECS  = 0.015
_HOLD_SECS  = 0.22           # hold K this long before recording (quick tap = typed 'k')

# ── Active-typing tracker (low-level keyboard hook, excludes K) ──────────────

_last_key_time = 0.0        # monotonic time of the last NON-K keydown

_LL_HOOK_PROC = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t)


def _ll_keyboard_cb(nCode, wParam, lParam):
    global _last_key_time
    try:
        if nCode >= 0 and wParam in (0x0100, 0x0104):   # WM_KEYDOWN / WM_SYSKEYDOWN
            # lParam → KBDLLHOOKSTRUCT; first field is vkCode (DWORD).
            vk = ctypes.cast(lParam, ctypes.POINTER(ctypes.c_uint)).contents.value & 0xFF
            if vk != VK_K:
                _last_key_time = time.monotonic()
    except Exception:
        pass
    try:
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)
    except Exception:
        return 0


_ll_cb_ref = _LL_HOOK_PROC(_ll_keyboard_cb)   # keep the callback alive


def _start_key_hook(stop_ev):
    """Pump messages so the WH_KEYBOARD_LL hook fires; run in its own thread."""
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowsHookExW(
            13, _ll_cb_ref,
            ctypes.windll.kernel32.GetModuleHandleW(None), 0)
        msg = wintypes.MSG()
        while not stop_ev.is_set():
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.01)
    except Exception:
        pass





# ── Typing-context detection (Windows) ──────────────────────────────────────

class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize",        ctypes.c_uint),
        ("flags",         ctypes.c_uint),
        ("hwndActive",    ctypes.c_void_p),
        ("hwndFocus",     ctypes.c_void_p),
        ("hwndCapture",   ctypes.c_void_p),
        ("hwndMenuOwner", ctypes.c_void_p),
        ("hwndMoveSize",  ctypes.c_void_p),
        ("hwndCaret",     ctypes.c_void_p),
        ("rcCaret",       ctypes.c_long * 4),
    ]


_TEXT_CLASS_MARKERS = (
    "edit", "richedit", "scintilla", "notepad", "msctls_",
    "qlineedit", "suneditor", "windowsforms", "swt_widget", "textbox",
    "consolewindowclass",
)
# NOTE: browser/Electron host classes (chrome_renderwidgethost, mozilla,
# internet explorer_server) are intentionally NOT here — they are the focused
# window even when the user is merely browsing/coding, which would block PTT.


def _typing_context(input_focused) -> bool:
    """
    True if the user is likely actively typing, so push-to-talk must NOT
    trigger. Heuristics: modifier held (shortcut), own command input focused,
    or (a text caret is blinking AND a NON-K key was pressed recently) — so
    idle editors/browsers never block PTT, but real typing in any app does.
    """
    try:
        user32 = ctypes.windll.user32
        for vk in (0x11, 0x12, 0x5B, 0x5C):  # Ctrl, Alt, Win-L, Win-R
            if user32.GetAsyncKeyState(vk) & 0x8000:
                return True
        if input_focused and input_focused():
            return True
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        tid = user32.GetWindowThreadProcessId(hwnd, None)
        gui = _GUITHREADINFO()
        gui.cbSize = ctypes.sizeof(_GUITHREADINFO)
        if not user32.GetGUIThreadInfo(tid, ctypes.byref(gui)):
            return False
        # Only block PTT during ACTIVE typing: a non-K key was pressed within
        # the last ~1.5s (the hook excludes K itself) AND a text input is
        # active (blinking caret or classic text control). Idle focus on
        # Notepad, a terminal, a browser, or an editor must NEVER block PTT.
        if time.monotonic() - _last_key_time < 1.5:
            if gui.flags & 0x0001:   # GUI_CARETBLINKING
                return True
            focus = gui.hwndFocus
            if not focus:
                return False
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(focus, cls, 256)
            name = (cls.value or "").lower()
            return any(m in name for m in _TEXT_CLASS_MARKERS)
        return False
    except Exception:
        return False



# ── Popup log with soft edge fade ───────────────────────────────────────────

def _c(r: int, g: int, b: int, a: int = 255):
    c = QColor(r, g, b)
    c.setAlpha(a)
    return c


class _MiniLog(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 8))
        self.setStyleSheet("""
            QTextEdit { background: transparent; color: #C3CBD6; border: none; }
            QScrollBar:vertical { background: transparent; width: 4px; border: none; }
            QScrollBar::handle:vertical { background: rgba(217, 182, 80, 100);
                                          border-radius: 2px; min-height: 14px; }
        """)
        self._fade_h = 14

    def paintEvent(self, e):
        super().paintEvent(e)
        doc_h  = int(self.document().size().height())
        view_h = self.viewport().height()
        if doc_h <= view_h:
            return
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.viewport().width(), self.viewport().height()
        fh = min(self._fade_h, H // 3)
        g1 = QLinearGradient(0, 0, 0, fh)
        g1.setColorAt(0.0, _c(10, 13, 18, 100))
        g1.setColorAt(1.0, _c(10, 13, 18, 0))
        p.fillRect(QRectF(0, 0, W, fh), QBrush(g1))
        g2 = QLinearGradient(0, H - fh, 0, H)
        g2.setColorAt(0.0, _c(10, 13, 18, 0))
        g2.setColorAt(1.0, _c(10, 13, 18, 100))
        p.fillRect(QRectF(0, H - fh, W, fh), QBrush(g2))

# ── Transparent frosted-glass shell ──────────────────────────────────────────

class _GlassShell(QWidget):
    """Transparent frosted-glass shell for the mini popup — mirrors the main
    window's backdrop: translucent gradient, calm drifting aurora, gold edge.
    Repaints only while visible, at a slow ~7 fps."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("miniShell")
        self._amb = 0.0
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._drift)
        self._tmr.start(150)
        self._tmr.stop()          # run only while visible

    def _drift(self):
        # One full ambient cycle every ~4 minutes — imperceptibly slow.
        self._amb = (self._amb + 0.24) % 3600.0
        if self.isVisible():
            self.update()

    def showEvent(self, e):
        if not self._tmr.isActive():
            self._tmr.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._tmr.stop()
        super().hideEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        if W < 4 or H < 4:
            return
        # Invisible input-capturing base — nothing is ever click-through.
        p.fillRect(self.rect(), _c(0, 0, 0, 1))
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 10, 10)
        p.save()
        p.setClipPath(path)
        # Mid charcoal glass gradient — mirrors the main window: the blurred
        # desktop still reads through clearly, just softened a little more
        # than the original.
        g = QLinearGradient(0, 0, 0, H)
        g.setColorAt(0.0, _c(6, 7, 10, 56))
        g.setColorAt(1.0, _c(8, 10, 16, 48))
        p.fillRect(self.rect(), QBrush(g))
        # Calm drifting aurora — one slow cycle, barely-there light.
        a = self._amb / 3600.0 * 2.0 * math.pi
        gx = W * (0.5 + 0.35 * math.sin(a))
        gy = H * (0.35 + 0.25 * math.cos(a * 0.7))
        glow = QRadialGradient(gx, gy, H * 1.3)
        glow.setColorAt(0.0, _c(217, 182, 80, 15))
        glow.setColorAt(1.0, _c(217, 182, 80, 0))
        p.fillRect(self.rect(), QBrush(glow))
        # Gold sheen along the top edge.
        sheen = QRadialGradient(W / 2, -H * 0.35, H * 1.0)
        sheen.setColorAt(0.0, _c(217, 182, 80, 30))
        sheen.setColorAt(1.0, _c(217, 182, 80, 0))
        p.fillRect(self.rect(), QBrush(sheen))
        # Faint HUD dot grid.
        p.setPen(QPen(_c(42, 34, 15, 80)))
        for x in range(0, W, 32):
            for y in range(0, H, 32):
                p.drawPoint(x, y)
        p.restore()
        # Gold border.
        p.setPen(QPen(_c(217, 182, 80, 110), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 10, 10)

# ── Compact sparkline for the popup strip ───────────────────────────────────

class _MiniGraph(QWidget):
    """Compact sparkline for the mini overlay — same calm eased-line style as
    the main window's MetricGraph, squeezed into the popup strip."""

    _N = 40

    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = QColor(color)
        self._text  = "--"
        self._tick  = 0
        self._shown  = [0.0] * self._N
        self._target = [0.0] * self._N
        self.setFixedHeight(26)
        self.setMinimumWidth(70)
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._animate)
        self._tmr.start(33)
        self._tmr.stop()          # run only while visible

    def set_value(self, pct: float, text: str):
        self._target.pop(0)
        self._target.append(max(0.0, min(100.0, pct)))
        self._text = text
        self._animate()

    def _animate(self):
        moved = False
        for i in range(self._N):
            cur, tgt = self._shown[i], self._target[i]
            nxt = cur + (tgt - cur) * 0.18
            if abs(nxt - tgt) < 0.05:
                nxt = tgt
            if nxt != cur:
                moved = True
            self._shown[i] = nxt
        if moved:
            self._tick += 1
            self.update()

    def showEvent(self, e):
        if not self._tmr.isActive():
            self._tmr.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._tmr.stop()
        super().hideEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        if W < 8 or H < 8:
            return
        v = self._shown[-1]
        if v > 85:
            line = QColor("#E5484D")
        elif v > 65:
            line = QColor("#E5C368")
        else:
            line = self._color

        # Faint frosted panel.
        p.setPen(QPen(_c(201, 162, 68, 22), 1))
        p.setBrush(QBrush(_c(18, 22, 31, 32)))
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 5, 5)

        # Header: label left, live value right.
        p.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        p.setPen(QPen(_c(122, 132, 148), 1))
        p.drawText(QRectF(3, 1, W / 2, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._label)
        p.setPen(QPen(line if self._text != "--" else _c(122, 132, 148), 1))
        p.drawText(QRectF(W / 2 - 2, 1, W / 2 - 2, 12),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   self._text)

        pad_l, pad_r, pad_t, pad_b = 3, 3, 15, 3
        gw, gh = W - pad_l - pad_r, H - pad_t - pad_b

        # Faint calibration grid.
        p.setPen(QPen(_c(30, 36, 46, 150), 1))
        p.drawLine(QPointF(pad_l, pad_t + gh), QPointF(W - pad_r, pad_t + gh))
        p.drawLine(QPointF(pad_l, pad_t + gh / 2), QPointF(W - pad_r, pad_t + gh / 2))

        # Smooth polyline (Catmull-Rom -> cubic beziers).
        n = len(self._shown)
        pts = [QPointF(pad_l + gw * i / (n - 1),
                       pad_t + gh * (1.0 - self._shown[i] / 100.0))
               for i in range(n)]
        path = QPainterPath()
        path.moveTo(pts[0])
        for i in range(n - 1):
            p0 = pts[max(i - 1, 0)]
            p1 = pts[i]
            p2 = pts[i + 1]
            p3 = pts[min(i + 2, n - 1)]
            path.cubicTo(p1 + (p2 - p0) * (1.0 / 6.0),
                         p2 - (p3 - p1) * (1.0 / 6.0),
                         p2)

        # Gradient fill under the curve.
        area = QPainterPath(path)
        area.lineTo(pts[-1].x(), pad_t + gh)
        area.lineTo(pts[0].x(), pad_t + gh)
        area.closeSubpath()
        fade = QLinearGradient(0, pad_t, 0, pad_t + gh)
        _fc = QColor(line); _fc.setAlpha(70)
        fade.setColorAt(0.0, _fc)
        _f0 = QColor(line); _f0.setAlpha(0)
        fade.setColorAt(1.0, _f0)
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(area, QBrush(fade))

        p.setPen(QPen(line, 1.2))
        p.drawPath(path)

        # Trailing glow dot — breathes slowly, keeps the readout alive.
        last = pts[-1]
        pulse = 1.0 + 0.4 * math.sin(self._tick * 0.14)
        p.setPen(Qt.PenStyle.NoPen)
        _gc = QColor(line); _gc.setAlpha(40)
        p.setBrush(_gc)
        p.drawEllipse(last, 4.0 * pulse, 4.0 * pulse)
        p.setBrush(line)
        p.drawEllipse(last, 1.3, 1.3)

# ── The popup widget ────────────────────────────────────────────────────────

class MiniOverlay(QWidget):
    _log_sig     = pyqtSignal(str)
    _state_sig   = pyqtSignal(str)
    _content_sig = pyqtSignal(str, str)
    _cam_sig     = pyqtSignal(bytes)
    _cam_active  = pyqtSignal(bool)
    _show_sig    = pyqtSignal()
    _hide_sig    = pyqtSignal()

    _W     = 400
    _BASE_H = 178   # header + log + compact graph strip
    _CAM_H  = 274   # + camera view

    def __init__(self, host):
        """host = the main MainWindow (provides on_text_command + broadcast signals)."""
        super().__init__(None, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool |
                         Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._H = self._BASE_H
        self.setFixedSize(self._W, self._H)
        self._host      = host          # MainWindow — on_text_command, _input, signals
        self._enabled   = True
        self._drag      = None
        self._recording = False
        self._direction = None          # 'main' or 'mini' — both push live voice into the session
        self._pressed   = False
        self._press_time = 0.0
        self._last_state = ""
        self._idle_tmr   = QTimer(self)          # tucks the popup away after quiet
        self._idle_tmr.setSingleShot(True)
        self._idle_tmr.setInterval(6000)         # generous — never hide mid-turn
        self._idle_tmr.timeout.connect(self.hide)
        self._ui_tmr     = QTimer(self)          # never float over a visible main UI
        self._ui_tmr.setInterval(500)
        self._ui_tmr.timeout.connect(self._ui_check)
        self._ui_tmr.start()
        self._metric_tmr = QTimer(self)          # live system graphs (only while showing)
        self._metric_tmr.setInterval(2000)
        self._metric_tmr.timeout.connect(self._update_mini_metrics)
        self._metric_tmr.stop()
        try:
            self._host_hwnd = int(self._host.winId())
        except Exception:
            self._host_hwnd = 0

        self._log_sig.connect(self._append_log)
        self._state_sig.connect(self._apply_state)
        self._content_sig.connect(self._show_content)
        self._cam_sig.connect(self._show_cam)
        self._cam_active.connect(self._set_cam_active)
        self._show_sig.connect(self._really_show)
        self._hide_sig.connect(self._really_hide)

        # Transparent frosted-glass shell — same look as the main window.
        self._shell = _GlassShell(self)
        self._shell.setGeometry(0, 0, self._W, self._H)

        lay = QVBoxLayout(self._shell)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        # heading row
        head = QHBoxLayout(); head.setSpacing(6)
        self._title = QLabel("◉ KEYS.AI")
        self._title.setStyleSheet("color: #E5C368; font: bold 9pt 'Courier New'; background: transparent;")
        self._status = QLabel("HOLD K TO TALK")
        self._status.setStyleSheet("color: #8FB8D8; font: 8pt 'Courier New'; background: transparent;")
        head.addWidget(self._title)
        head.addStretch(1)
        head.addWidget(self._status)
        lay.addLayout(head)

        self._log = _MiniLog()
        self._log.setPlaceholderText("[ HOLD K = record · release = send ]")
        lay.addWidget(self._log, stretch=1)

        # compact system-monitor strip — same sparkline style as the main window
        strip = QHBoxLayout(); strip.setSpacing(4)
        self._mini_graphs = [
            _MiniGraph("CPU", "#D9B650"),
            _MiniGraph("MEM", "#E5C368"),
            _MiniGraph("NET", "#3DDC84"),
            _MiniGraph("GPU", "#4FD0E0"),
        ]
        for g in self._mini_graphs:
            strip.addWidget(g)
        lay.addLayout(strip)

        # camera mini-view (grows the popup when a frame arrives)
        self._cam_lbl = QLabel()
        self._cam_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cam_lbl.setFixedHeight(0)
        self._cam_lbl.setStyleSheet(
            "background: rgba(0,0,0,160); border: 1px solid rgba(217,182,80,70);"
            " border-radius: 4px; color: #88AABB; font: 8pt 'Courier New';")
        self._cam_lbl.setText("📷 camera feed")
        self._cam_lbl.hide()
        lay.addWidget(self._cam_lbl)

        # mirror the main window's broadcast signals into the popup
        host._log_sig.connect(self._log_sig.emit)
        host._state_sig.connect(self._state_sig.emit)
        host._content_sig.connect(self._content_sig.emit)
        host._camera_sig.connect(self._cam_sig.emit)
        host._cam_stream_sig.connect(self._cam_active.emit)

        self._position_top()
        self._stop = threading.Event()
        self._key_stop = threading.Event()
        self._ptt = threading.Thread(target=self._poll_loop, daemon=True, name="mini-ptt")
        self._ptt.start()
        threading.Thread(target=_start_key_hook, args=(self._key_stop,),
                         daemon=True, name="mini-kb-hook").start()
        self.hide()   # start tucked away — pops up when K is pressed

    # ---- visibility / metrics -------------------------------------------
    def showEvent(self, e):
        super().showEvent(e)
        apply_acrylic(self)             # same frosted glass as the main window
        # Children may not receive their own show/hide events when the popup
        # is shown/hidden as a whole, so drive every animation timer here.
        if not self._metric_tmr.isActive():
            self._metric_tmr.start()
            self._update_mini_metrics()
        if not self._shell._tmr.isActive():
            self._shell._tmr.start()
        for g in self._mini_graphs:
            if not g._tmr.isActive():
                g._tmr.start()

    def hideEvent(self, e):
        self._metric_tmr.stop()
        self._shell._tmr.stop()
        for g in self._mini_graphs:
            g._tmr.stop()
        super().hideEvent(e)

    def _update_mini_metrics(self):
        """Feed the compact sparklines from the shared engine metrics snapshot."""
        try:
            snap = self._host._metrics.snapshot()
        except Exception:
            return
        try:
            cpu, mem, net, gpu = snap["cpu"], snap["mem"], snap["net"], snap["gpu"]
            self._mini_graphs[0].set_value(cpu, f"{cpu:.0f}%")
            self._mini_graphs[1].set_value(mem, f"{mem:.0f}%")
            net_pct = min(100.0, net * 25)
            net_str = f"{net * 1024:.0f}K/s" if net < 1.0 else f"{net:.1f}M/s"
            self._mini_graphs[2].set_value(net_pct, net_str)
            if gpu >= 0:
                self._mini_graphs[3].set_value(gpu, f"{gpu:.0f}%")
            else:
                self._mini_graphs[3].set_value(0, "N/A")
        except Exception:
            pass

    # ---- position / drag -------------------------------------------------
    def _position_top(self):
        try:
            scr = QApplication.primaryScreen()
            if scr is None:
                self.move(80, 40)
                return
            g = scr.availableGeometry()
            self.move(g.right() - self._W - 24, g.top() + 24)
        except Exception:
            self.move(80, 40)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag = None

    def set_enabled(self, on: bool) -> None:
        self._enabled = on
        if on:
            self.show_ready()
        else:
            self._abort_recording()
            self.hide()

    def is_enabled(self) -> bool:
        return self._enabled

    def show_ready(self, text: str = "MINI OVERLAY READY — HOLD K") -> None:
        """Brief flash so the user knows the overlay is on; it tucks away on K.
        Never shows over a visible main window — they are the same assistant."""
        self._status.setText(text)
        if self._main_window_active():
            return
        self.show()
        self.raise_()
        QTimer.singleShot(2500, lambda: self.hide() if not self._recording else None)

    def shutdown(self):
        self._stop.set()
        self._key_stop.set()
        self._idle_tmr.stop()
        self._ui_tmr.stop()
        self._metric_tmr.stop()
        self._shell._tmr.stop()
        for g in self._mini_graphs:
            g._tmr.stop()
        self._abort_recording()

    # ---- broadcast slots (main thread) ------------------------------------
    def _append_log(self, text: str):
        self._log.append(text)
        self._log.verticalScrollBar().setValue(self._log.verticalScrollBar().maximum())
        self._bump_activity()

    def _really_show(self):
        """Thread-safe: pop the overlay up (called via _show_sig from PTT thread)."""
        self._idle_tmr.stop()
        self.show()
        self.raise_()

    def _really_hide(self):
        """Thread-safe: tuck the overlay away (called via _hide_sig on K release)."""
        self._idle_tmr.stop()
        self.hide()

    def _bump_activity(self):
        """Keep the popup alive while the turn is working; hide after quiet."""
        if not self._recording:
            self._idle_tmr.start()

    def _ui_check(self):
        """The overlay is the same assistant as the main window — if the main
        window becomes the active foreground window while the popup is showing,
        tuck the popup away (the main UI takes over the turn)."""
        try:
            if self.isVisible() and not self._recording and self._main_window_active():
                self.hide()
        except Exception:
            pass

    def _apply_state(self, state: str):
        """Widget states (spec 38): idle / listening / thinking / speaking /
        executing / error — only what matters for the current state."""
        self._last_state = (state or "").upper()
        st = self._last_state
        color = "#8FB8D8"   # default muted blue
        if "SPEAK" in st:
            text, color = "◉ SPEAKING", "#E5C368"
        elif "LISTEN" in st or "HOLD K" in st:
            text, color = "◉ LISTENING", "#3DDC84"
        elif "THINK" in st or "PROCESS" in st or "WORK" in st or "TRANSCRIB" in st or "WAIT" in st:
            text, color = "◉ THINKING", "#E5C368"
        elif "EXEC" in st or "RUN" in st or "TOOL" in st:
            text, color = "◉ EXECUTING", "#E5C368"
        elif "ERR" in st or "FAIL" in st:
            text, color = "! ERROR", "#E5484D"
        elif "SLEEP" in st:
            text, color = "◉ IDLE", "#6E7686"
        else:
            text = st or "◉ IDLE"
        self._status.setText(text)
        self._status.setStyleSheet(
            f"color: {color}; font: bold 8pt 'Courier New'; background: transparent;")
        self._bump_activity()

    def _show_content(self, title: str, text: str):
        self._append_log(f"── {title} ──")
        self._append_log(text[:500])
        self._bump_activity()

    def _show_cam(self, img_bytes: bytes):
        px = QPixmap()
        if px.loadFromData(img_bytes) and not px.isNull():
            w = max(60, self._cam_lbl.width() - 2, self._W - 16)
            h = max(40, self._cam_lbl.height() - 2, 94)
            self._cam_lbl.setPixmap(px.scaled(
                w, h, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            if self._cam_lbl.isHidden():
                self._cam_lbl.setFixedHeight(96)
                self._cam_lbl.show()
                self._H = self._CAM_H
                self.setFixedSize(self._W, self._H)
                self._shell.setGeometry(0, 0, self._W, self._H)
                self._position_top()

    def _set_cam_active(self, on: bool):
        if not on:
            self._cam_lbl.clear()
            self._cam_lbl.setFixedHeight(0)
            self._cam_lbl.hide()
            self._H = self._BASE_H
            self.setFixedSize(self._W, self._H)
            self._shell.setGeometry(0, 0, self._W, self._H)
            self._position_top()

    # ---- push-to-talk poll loop (background thread) -----------------------
    def _host_input_focused(self) -> bool:
        try:
            return bool(self._host._input.hasFocus())
        except Exception:
            return False

    def _poll_loop(self):
        while not self._stop.is_set():
            time.sleep(_POLL_SECS)
            try:
                down = bool(ctypes.windll.user32.GetAsyncKeyState(VK_K) & 0x8000)
            except Exception:
                continue
            if down and not self._pressed:
                self._pressed = True
                self._press_time = time.monotonic()
            elif down and self._pressed and not self._recording:
                # Hold K for a beat before recording — a quick tap is the
                # letter 'k', not push-to-talk.
                if time.monotonic() - self._press_time >= _HOLD_SECS:
                    if not _typing_context(self._host_input_focused):
                        self._start_recording()
            elif not down and self._pressed:
                self._pressed = False
                if self._recording:
                    self._stop_recording()

    def _main_window_active(self) -> bool:
        """True when the MAIN window is the active foreground window — i.e. the
        user is actually USING the main UI right now.

        The overlay is the same assistant, so it only takes over when the main
        window is NOT the active surface: hidden, minimized, or merely sitting
        in the background while the user works in another app (Word, browser,
        etc.). This is what makes the overlay respond even when the main window
        happens to be open behind the current app."""
        try:
            if not self._host_hwnd:
                return False
            user32 = ctypes.windll.user32
            if not bool(user32.IsWindowVisible(self._host_hwnd)):
                return False
            if bool(user32.IsIconic(self._host_hwnd)):
                return False
            # 64-bit HWND — without this ctypes truncates the return value.
            user32.GetForegroundWindow.restype = ctypes.c_size_t
            fg = user32.GetForegroundWindow()
            return bool(fg) and fg == self._host_hwnd
        except Exception:
            return False

    def _barge_in(self) -> None:
        """If KEYS.AI is mid-speech, interrupt so holding K opens the mic."""
        if "SPEAK" in self._last_state:
            intr = getattr(self._host, "on_interrupt", None)
            if intr:
                try:
                    intr()
                except Exception:
                    pass

    def _start_recording(self):
        # Direction: if the MAIN window is the active foreground window, K
        # drives the main UI — live voice straight into the session (push-to-
        # talk) and the overlay does NOT pop up. Otherwise (hidden, minimized,
        # or in the background while another app is focused) the MINI overlay
        # becomes the UI and shows the same live-voice turn as text output.
        # Both directions use the SAME audio path (main_ptt_active → the shared
        # Live session) — the overlay never captures its own audio.
        if self._main_window_active():
            self._barge_in()
            self._direction = "main"
            self._recording = True
            if hasattr(self._host, "main_ptt_active"):
                self._host.main_ptt_active = True
            try:
                self._host._state_sig.emit("RECORDING — RELEASE K")
                self._host._log_sig.emit("MAIN: 🎤 talking (hold K)…")
            except Exception:
                pass
            return
        if not self._enabled:
            return
        # Barge-in only after we know a mini recording will actually start.
        self._barge_in()
        # Same audio path as the main UI: live voice straight into the shared
        # Live session while K is held (push-to-talk). No second mic stream,
        # no separate transcription — the overlay is only the text surface.
        self._direction = "mini"
        self._recording = True
        if hasattr(self._host, "main_ptt_active"):
            self._host.main_ptt_active = True
        self._show_sig.emit()              # pop the overlay up
        self._state_sig.emit("RECORDING — RELEASE K")
        self._log_sig.emit("MINI: 🎤 talking (hold K)…")

    def _stop_recording(self):
        direction = self._direction
        self._direction = None
        self._recording = False
        if hasattr(self._host, "main_ptt_active"):
            self._host.main_ptt_active = False
        if direction == "main":
            self._hide_sig.emit()
            # Reset the main HUD — releasing K ends the recording. Without
            # this the main window stays stuck on "RECORDING — RELEASE K"
            # forever after you let go of the key.
            try:
                self._host._state_sig.emit(
                    "HOLD K TO TALK" if not getattr(self._host, "_muted", False)
                    else "MUTED"
                )
            except Exception:
                pass
            return   # live voice already went straight into the session
        # Mini direction: live voice already went into the shared session.
        # Keep the popup up through the whole turn so the text output,
        # suggestions and confirmations stay readable — it tucks itself away
        # once the engine goes idle (states & logs bump the activity timer).
        self._state_sig.emit("RELEASED — WAITING FOR RESPONSE")
        self._log_sig.emit("MINI: ✓ sent — listening for reply…")

    def _abort_recording(self):
        self._direction = None
        self._recording = False
        if hasattr(self._host, "main_ptt_active"):
            self._host.main_ptt_active = False
