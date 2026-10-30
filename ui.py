from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path


# Lazy imports — avoids permission prompts at startup
MiniOverlay = None
WindowChromeFrame = None
load_window_state = None
save_window_state = None
ControlOverlay = None
ControlOverlayBridge = None
GridTargetOverlay = None
get_control_engine = None
get_agent_settings = None


def _ensure_gui_imports():
    """Lazy-load GUI modules on first use."""
    global MiniOverlay, WindowChromeFrame, load_window_state, save_window_state
    global ControlOverlay, ControlOverlayBridge, GridTargetOverlay
    global get_control_engine, get_agent_settings
    if MiniOverlay is not None:
        return
    try:
        from mini_overlay import MiniOverlay as _MO
        from window_chrome import (
            WindowChromeFrame as _WCF, load_window_state as _lws, save_window_state as _sws,
        )
        from agent_control.overlay import (
            ControlOverlay as _CO, ControlOverlayBridge as _COB, GridTargetOverlay as _GTO,
        )
        from agent_control.app_control import get_control_engine as _gce
        from agent_control.settings import get_settings as _gs
        MiniOverlay = _MO
        WindowChromeFrame = _WCF
        load_window_state = _lws
        save_window_state = _sws
        ControlOverlay = _CO
        ControlOverlayBridge = _COB
        GridTargetOverlay = _GTO
        get_control_engine = _gce
        get_agent_settings = _gs
    except Exception as e:
        print(f"[ui] GUI import warning: {e}")

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}

from PyQt6.QtCore import (
    QEasingCurve, QEvent, QMimeData, QObject, QPointF, QRect, QRectF, QSize, Qt,
    QThread, QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QFontDatabase,
    QIcon, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QShortcut, QSyntaxHighlighter, QTextCharFormat, QTextDocument,
    QTextFormat,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QSystemTrayIcon,
    QTextEdit, QVBoxLayout, QWidget, QProgressBar,
)
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
    _HAS_WEBENGINE = True
except ImportError:
    _HAS_WEBENGINE = False

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

_DEFAULT_W, _DEFAULT_H = 980, 700
_MIN_W,     _MIN_H     = 820, 580
_LEFT_W  = 148
_RIGHT_W = 340
_CMD_BAR_H = 54

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


class C:
    # Minimal futuristic AI console — deep glass surfaces, restrained gold,
    # white typography, thin borders, minimal glow.
    BG        = "#06070A"
    PANEL     = "#0B0E14"
    PANEL2    = "#12161F"
    BORDER    = "#1E242E"
    BORDER_B  = "#D9B650"
    BORDER_A  = "#C9A244"
    PRI       = "#D9B650"
    PRI_DIM   = "#8A6D2F"
    PRI_GHO   = "#2A220F"
    ACC       = "#E5C368"
    ACC2      = "#D9B650"
    GREEN     = "#3DDC84"
    GREEN_D   = "#1F8F5A"
    GLITCH_R  = "#E3406E"
    GLITCH_C  = "#4FD0E0"
    RED       = "#E5484D"
    MUTED_C   = "#6E7686"
    TEXT      = "#F2F4F8"
    TEXT_DIM  = "#7A8494"
    TEXT_MED  = "#A9B2C0"
    WHITE     = "#FFFFFF"
    DARK      = "#05060A"
    BAR_BG    = "#10141C"


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c


# ── Live theming ────────────────────────────────────────────────────────────
# The HUD and the avatar read the palette at paint time, so switching these
# values retints the head and the rings immediately, without a restart. Each
# theme keeps the same structure so the interface stays legible.
_THEMES: dict = {
    "gold":    {"PRI": "#D9B650", "PRI_DIM": "#8A6D2F", "PRI_GHO": "#2A220F",
                "ACC": "#E5C368", "ACC2": "#D9B650",
                "BORDER_B": "#D9B650", "BORDER_A": "#C9A244"},
    "azure":   {"PRI": "#5B8DEF", "PRI_DIM": "#33518F", "PRI_GHO": "#101C33",
                "ACC": "#7FB0FF", "ACC2": "#5B8DEF",
                "BORDER_B": "#5B8DEF", "BORDER_A": "#4A78C9"},
    "emerald": {"PRI": "#3DDC84", "PRI_DIM": "#1F8F5A", "PRI_GHO": "#0C2A1C",
                "ACC": "#6EF0A8", "ACC2": "#3DDC84",
                "BORDER_B": "#3DDC84", "BORDER_A": "#2FB36B"},
    "violet":  {"PRI": "#A78BFA", "PRI_DIM": "#6B4FD1", "PRI_GHO": "#1E1633",
                "ACC": "#C4B0FF", "ACC2": "#A78BFA",
                "BORDER_B": "#A78BFA", "BORDER_A": "#8A6FE0"},
    "rose":    {"PRI": "#E85D8A", "PRI_DIM": "#9E3459", "PRI_GHO": "#33101F",
                "ACC": "#FF8FB0", "ACC2": "#E85D8A",
                "BORDER_B": "#E85D8A", "BORDER_A": "#C74A72"},
}
THEME_ORDER = list(_THEMES)


def theme_names() -> list:
    return list(THEME_ORDER)


def apply_theme(name: str) -> str:
    """Retint the painted HUD/avatar palette. Returns the applied theme name."""
    name = (name or "gold").strip().lower()
    if name not in _THEMES:
        name = "gold"
    for key, value in _THEMES[name].items():
        setattr(C, key, value)
    return name


# ── Windows GPU via NVML DLL (no subprocess, no console window) ──────────────
_nvml_lib: object = None   # cached ctypes DLL
_nvml_ok:  object = None   # None=untested, True=works, False=unavailable


def _nvml_gpu_windows() -> float:
    """Return NVIDIA GPU utilisation % using nvml.dll directly — zero subprocess."""
    global _nvml_lib, _nvml_ok
    if _nvml_ok is False:
        return -1.0
    try:
        import ctypes

        class _Util(ctypes.Structure):
            _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

        if _nvml_lib is None:
            for dll_name in ("nvml", r"C:\Windows\System32\nvml.dll"):
                try:
                    lib = ctypes.WinDLL(dll_name)
                    lib.nvmlInit_v2()
                    _nvml_lib = lib
                    break
                except Exception:
                    continue

        if _nvml_lib is None:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            _nvml_ok = True
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)

        dev = ctypes.c_void_p()
        _nvml_lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
        util = _Util()
        _nvml_lib.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(util))
        _nvml_ok = True
        return float(util.gpu)
    except Exception:
        _nvml_ok = False
        return -1.0


class _SysMetrics:
    def __init__(self):
        import psutil
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0   
        self.gpu  = -1.0  
        self.tmp  = -1.0  
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.0)

    def _update(self):
        import psutil
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        gpu = self._get_gpu()

        tmp = self._get_temp()

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        # pynvml — subprocess-free, works on all platforms if installed
        try:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
        except Exception:
            pass

        # Windows: nvml.dll via ctypes (already cached in _nvml_gpu_windows)
        if _OS == "Windows":
            return _nvml_gpu_windows()

        # Linux / macOS: libnvidia-ml shared lib via ctypes
        try:
            import ctypes
            _lib = "libnvidia-ml.so.1" if _OS == "Linux" else "libnvidia-ml.dylib"

            class _Util(ctypes.Structure):
                _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

            nv = ctypes.CDLL(_lib)
            nv.nvmlInit_v2()
            dev = ctypes.c_void_p()
            nv.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
            u = _Util()
            nv.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(u))
            return float(u.gpu)
        except Exception:
            pass

        return -1.0   # N/A — zero subprocess on all platforms

    def _get_temp(self) -> float:
        # psutil — works on Linux; occasionally Windows with driver support
        try:
            import psutil
            temps = psutil.sensors_temperatures()
            for name in ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                         "cpu-thermal", "zenpower", "it8688"]:
                if name in temps and temps[name]:
                    return temps[name][0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass

        # Windows: wmi module (pure Python COM, zero subprocess)
        if _OS == "Windows":
            try:
                import wmi  # type: ignore
                w = wmi.WMI(namespace="root/wmi")
                tz = w.MSAcpi_ThermalZoneTemperature()
                if tz:
                    return (tz[0].CurrentTemperature / 10.0) - 273.15
            except Exception:
                pass

        return -1.0   # N/A — zero subprocess on all platforms

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()


class GlassBackdrop(QWidget):
    """Frosted-glass surface the whole UI floats on. Kept genuinely
    transparent (the desktop shows through), with one calm, very slow
    ambient glow that drifts like a distant aurora — subtle light, no noise."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._amb = 0.0
        self._dot_cache: QPixmap | None = None
        self._dot_cache_size: tuple[int, int] = (0, 0)
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._drift)
        self._tmr.start(250)   # ~4 fps — calm ambient glow, minimal CPU

    def _drift(self):
        # One full ambient cycle every ~4 minutes — imperceptibly slow.
        self._amb = (self._amb + 0.24) % 3600.0
        # Repaint only while actually shown AND the window is the active one;
        # otherwise the ambient freezes (calm) and idle CPU stays near zero.
        try:
            win = self.window()
            if self.isVisible() and (win is self or win.isActiveWindow()):
                self.update()
        except Exception:
            pass

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        if W < 4 or H < 4:
            return
        # Invisible input-capturing base: even the rounded corner notches keep
        # alpha 1, so nothing is ever click-through on any compositing path.
        p.fillRect(self.rect(), QColor(0, 0, 0, 1))
        # Rounded glass surface (matches the OS-rounded window corners) —
        # light enough that the desktop/acrylic blur reads through clearly.
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 12, 12)
        g = QLinearGradient(0, 0, 0, H)
        # Mid charcoal glass — the blurred desktop still reads through
        # clearly, just softened slightly more than the original.
        g.setColorAt(0.0, qcol(C.BG, 58))
        g.setColorAt(1.0, qcol("#0A0C12", 50))
        p.save()
        p.setClipPath(path)
        p.fillRect(self.rect(), QBrush(g))
        # Calm drifting aurora — two very soft glows moving on slow Lissajous
        # paths. Alphas stay low so it reads as ambient light, not animation.
        a = self._amb / 3600.0 * 2.0 * math.pi
        gx1 = W * (0.5 + 0.42 * math.sin(a * 1.0))
        gy1 = H * (0.34 + 0.20 * math.cos(a * 0.7))
        gx2 = W * (0.5 + 0.40 * math.cos(a * 0.53 + 2.0))
        gy2 = H * (0.72 + 0.18 * math.sin(a * 0.81))
        g1 = QRadialGradient(gx1, gy1, H * 0.75)
        g1.setColorAt(0.0, qcol(C.PRI, 16))
        g1.setColorAt(1.0, qcol(C.PRI, 0))
        p.fillRect(self.rect(), QBrush(g1))
        g2 = QRadialGradient(gx2, gy2, H * 0.65)
        g2.setColorAt(0.0, qcol(C.GLITCH_C, 11))
        g2.setColorAt(1.0, qcol(C.GLITCH_C, 0))
        p.fillRect(self.rect(), QBrush(g2))
        # Soft gold sheen - light catching the top of the glass.
        glow = QRadialGradient(W / 2, -H * 0.15, H * 0.9)
        glow.setColorAt(0.0, qcol(C.PRI, 34))
        glow.setColorAt(0.55, qcol(C.PRI, 7))
        glow.setColorAt(1.0, qcol(C.PRI, 0))
        p.fillRect(self.rect(), QBrush(glow))
        # Faint static HUD dot grid — cached as QPixmap (zero per-frame cost).
        if self._dot_cache_size != (W, H):
            self._dot_cache = QPixmap(W, H)
            self._dot_cache.fill(Qt.GlobalColor.transparent)
            dp = QPainter(self._dot_cache)
            dp.setPen(QPen(qcol(C.PRI_GHO, 80)))
            for x in range(0, W, 48):
                for y in range(0, H, 48):
                    dp.drawPoint(x, y)
            dp.end()
            self._dot_cache_size = (W, H)
        p.drawPixmap(0, 0, self._dot_cache)
        p.restore()


class HudCanvas(QWidget):
    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"
        self.status_line = ""   # always-on: what the assistant is doing right now

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 55.0
        self._tgt_halo   = 55.0
        self._last_t     = time.time()
        self._scan       = 0.0
        self._scan2      = 180.0
        self._rings      = [0.0, 120.0, 240.0]
        self._pulses: list[float] = [0.0, 50.0, 100.0]
        self._blink      = True
        self._blink_tick = 0
        self._particles: list[list[float]] = []
        self._face_px: QPixmap | None = None
        self._load_face(face_path)

        # ═══ Glitch ═══
        self._glitch_active = 0.0
        self._glitch_offset = 0
        self._glitch_slice_h = 0
        self._glitch_slice_y = 0
        self._glitch_rgb = False
        self._glitch_scan = 0.0

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(33)   # adaptive: 33ms idle, 16ms while speaking
        self._face_cache: tuple[int, QPixmap] | None = None   # (size, pixmap)

        # ── Dyson-sphere orbital construct around the restored icon.png logo.
        # The animated holographic avatar does not own the HUD centre anymore:
        # the restored Keys.AI logo (icon.png) is the focal point, and the orbital
        # rings are layered around it. The avatar module is still importable / used
        # elsewhere in the app; it is simply no longer built into this canvas.
        self._avatar = None
        self._avatars_enabled = False
        self._hud_level = 0.0

        # ── Simple pulsating logo (icon.png) is the HUD centre. No hologram face, no Dyson-sphere.

    def _load_face(self, path: str):
        """
        Load the face image and apply a circular mask.
        Uses Qt natively first (reliable in frozen PyInstaller apps),
        falls back to PIL if Qt fails.
        """
        try:
            # ── Approach 1: Load directly with Qt (no PIL needed) ───────────
            px = QPixmap(path)
            if px.isNull():
                raise ValueError(f"QPixmap could not load: {path}")

            # Resize to square
            sz = min(px.width(), px.height())
            if sz < 4:
                raise ValueError(f"Image too small: {sz}x{sz}")
            px = px.scaled(sz, sz,
                           Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)

            # Create circular mask with QPainter
            mask = QPixmap(sz, sz)
            mask.fill(Qt.GlobalColor.transparent)
            mp = QPainter(mask)
            mp.setRenderHint(QPainter.RenderHint.Antialiasing)
            mp.setBrush(QColor(255, 255, 255))
            mp.setPen(Qt.PenStyle.NoPen)
            mp.drawEllipse(2, 2, sz - 4, sz - 4)
            mp.end()

            px.setMask(mask.mask())
            self._face_px = px
            print(f"[HUD] Face loaded via Qt: {path} ({sz}x{sz})")
        except Exception as e1:
            print(f"[HUD] Qt face loading failed: {e1}")
            # ── Approach 2: Fall back to PIL ────────────────────────────────
            try:
                from PIL import Image, ImageDraw
                import io
                img = Image.open(path).convert("RGBA")
                sz  = min(img.size)
                img = img.resize((sz, sz), Image.LANCZOS)
                mk  = Image.new("L", (sz, sz), 0)
                ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
                img.putalpha(mk)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                px = QPixmap(); px.loadFromData(buf.getvalue())
                self._face_px = px
                print(f"[HUD] Face loaded via PIL fallback: {path}")
            except Exception as e2:
                print(f"[HUD] PIL fallback also failed: {e2}")
                self._face_px = None

    # ── Dyson-sphere painthelper (real 3D via QPainter transforms) ─────────────
    # ── Backward-compatible thin API kept for the audio path ────────────────
    # The HUD still exposes set_hud_level() because other parts of the app call it
    # via the signal; here it only nudges glow / pulse behaviour, not a face.
    def set_hud_level(self, level: float) -> None:
        """Live 0..1 activity level feeding glow / pulse energy.
        Kept for compatibility with the existing audio signal path."""
        try:
            lv = max(0.0, min(1.0, float(level)))
        except Exception:
            return
        if lv > self._hud_level:
            self._hud_level = lv

    def avatar_glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        # No holographic avatar in the HUD centre anymore.
        pass

    def _step(self):
        self._tick += 1
        # Adaptive frame rate: full 60fps only while speaking,
        # otherwise 30fps so idle CPU stays near zero.
        target = 16 if self.speaking else 50  # slow idle to 20fps
        if self._tmr.interval() != target:
            self._tmr.setInterval(target)
        now = time.time()
        # Restrained glow: calm halo while idle, slightly stronger while
        # speaking — communicates state without shouting (design spec).
        if now - self._last_t > (0.12 if self.speaking else 0.5):
            if self.speaking:
                self._tgt_scale = random.uniform(1.015, 1.04)
                self._tgt_halo  = random.uniform(90, 130)
            elif self.muted:
                self._tgt_scale = random.uniform(0.998, 1.002)
                self._tgt_halo  = random.uniform(10, 18)
            else:
                self._tgt_scale = random.uniform(1.001, 1.005)
                self._tgt_halo  = random.uniform(26, 40)
            self._last_t = now

        sp = 0.38 if self.speaking else 0.15
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo  += (self._tgt_halo  - self._halo)  * sp

        speeds = [1.3, -0.9, 2.0] if self.speaking else [0.55, -0.35, 0.9]
        for i, spd in enumerate(speeds):
            self._rings[i] = (self._rings[i] + spd) % 360

        self._scan  = (self._scan  + (3.0 if self.speaking else 1.3)) % 360
        self._scan2 = (self._scan2 + (-2.0 if self.speaking else -0.75)) % 360

        fw  = min(self.width(), self.height())
        lim = fw * 0.74
        spd = 3.4 if self.speaking else 1.2
        self._pulses = [r + spd for r in self._pulses if r + spd < lim]
        if len(self._pulses) < 3 and random.random() < (0.045 if self.speaking else 0.01):
            self._pulses.append(0.0)

        if self.speaking and random.random() < 0.28:
            cx, cy = self.width() / 2, self.height() / 2
            ang = random.uniform(0, 2 * math.pi)
            r_s = fw * 0.28
            self._particles.append([
                cx + math.cos(ang) * r_s, cy + math.sin(ang) * r_s,
                math.cos(ang) * random.uniform(0.9, 2.4),
                math.sin(ang) * random.uniform(0.9, 2.4) - 0.4, 1.0,
            ])
        self._particles = [
            [p[0]+p[2], p[1]+p[3], p[2]*0.97, p[3]*0.97, p[4]-0.028]
            for p in self._particles if p[4] > 0
        ]

        self._blink_tick += 1
        if self._blink_tick >= 38:
            self._blink = not self._blink
            self._blink_tick = 0

        # ── Glitch animation (rare — a controlled accent, not ambient noise) ──
        if self._glitch_active > 0:
            self._glitch_active *= 0.85
            if self._glitch_active < 0.05:
                self._glitch_active = 0.0
        elif random.random() < 0.0018 * (2 if self.speaking else 1):
            self._glitch_active = 0.3 + random.random() * 0.3
            self._glitch_offset = random.randint(-12, 12)
            self._glitch_slice_h = random.randint(4, 30)
            self._glitch_slice_y = random.randint(0, max(1, self.height()))
            self._glitch_rgb = random.random() > 0.5

        self._glitch_scan = (self._glitch_scan + 0.8) % max(1, self.height())

        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)

        r_face = fw * 0.31

        # ── Apply glitch offset to the entire central area ────────────────
        glitch_save = QPixmap()
        apply_glitch = self._glitch_active > 0.05 and random.random() < 0.7

        # halo glow
        for i in range(10):
            r   = r_face * (1.8 - i * 0.08)
            frc = 1.0 - i / 10
            a   = max(0, min(255, int(self._halo * 0.085 * frc)))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # pulse rings
        for pr in self._pulses:
            a   = max(0, int(230 * (1.0 - pr / (fw * 0.74))))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        # spinning arc rings
        for idx, (r_frac, w_r, arc_l, gap) in enumerate(
            [(0.48, 3, 115, 78), (0.40, 2, 78, 55), (0.32, 1, 56, 40)]
        ):
            ring_r = fw * r_frac
            base   = self._rings[idx]
            a_val  = max(0, min(255, int(self._halo * (1.0 - idx * 0.18))))
            col    = qcol(C.MUTED_C if self.muted else C.PRI, a_val)
            p.setPen(QPen(col, w_r)); p.setBrush(Qt.BrushStyle.NoBrush)
            angle = base
            rect  = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
            while angle < base + 360:
                p.drawArc(rect, int(angle * 16), int(arc_l * 16))
                angle += arc_l + gap

        # scanners
        sr = fw * 0.50
        sa = min(255, int(self._halo * 1.5))
        ex = 75 if self.speaking else 44
        p.setPen(QPen(qcol(C.MUTED_C if self.muted else C.PRI, sa), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        srect = QRectF(cx - sr, cy - sr, sr * 2, sr * 2)
        p.drawArc(srect, int(self._scan * 16), int(ex * 16))
        p.setPen(QPen(qcol(C.ACC, sa // 2), 1.5))
        p.drawArc(srect, int(self._scan2 * 16), int(ex * 16))

        # tick marks
        t_out, t_in = fw * 0.497, fw * 0.474
        p.setPen(QPen(qcol(C.PRI, 140), 1))
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 6
            p.drawLine(
                QPointF(cx + t_out * math.cos(rad), cy - t_out * math.sin(rad)),
                QPointF(cx + inn  * math.cos(rad), cy - inn  * math.sin(rad)),
            )

        # crosshair
        ch_r, gap_h = fw * 0.51, fw * 0.16
        p.setPen(QPen(qcol(C.PRI, int(self._halo * 0.5)), 1))
        p.drawLine(QPointF(cx - ch_r, cy), QPointF(cx - gap_h, cy))
        p.drawLine(QPointF(cx + gap_h, cy), QPointF(cx + ch_r, cy))
        p.drawLine(QPointF(cx, cy - ch_r), QPointF(cx, cy - gap_h))
        p.drawLine(QPointF(cx, cy + gap_h), QPointF(cx, cy + ch_r))

        # corner brackets
        bl = 24
        bc = qcol(C.PRI, 210)
        hl, hr = cx - fw // 2, cx + fw // 2
        ht, hb = cy - fw // 2, cy + fw // 2
        p.setPen(QPen(bc, 2))
        for bx, by, dx, dy in [(hl,ht,1,1),(hr,ht,-1,1),(hl,hb,1,-1),(hr,hb,-1,-1)]:
            p.drawLine(QPointF(bx, by), QPointF(bx + dx * bl, by))
            p.drawLine(QPointF(bx, by), QPointF(bx, by + dy * bl))

        # ── Restored Keys.AI logo — the hero of the HUD ─────────────────────
        # icon.png is used directly, preserving its own proportions, colours and
        # transparency. No generated face, robot, avatar or CSS-only approximation.
        # A simple pulsating glow sits behind/around the circular logo.
        if self._face_px is not None:
            fsz = int(fw * 0.55)
            if self._face_cache is None or abs(self._face_cache[0] - fsz) > 2:
                self._face_cache = (fsz, self._face_px.scaled(
                    fsz, fsz,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
            scaled = self._face_cache[1]
            logo_r = fsz / 2.0
            # simple pulsating halo behind the logo (calm pulse, not busy)
            for i in range(8, 0, -1):
                r   = logo_r + fw * 0.04 * i
                frc = i / 8.0
                a   = max(0, min(255, int(self._halo * 1.1 * frc)))
                p.setPen(QPen(qcol(C.MUTED_C if self.muted else C.PRI, a), 1.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
            # soft bloom behind the icon itself
            bloom = QRadialGradient(cx, cy, logo_r * 1.1)
            bloom.setColorAt(0.0, qcol(C.PRI, 70))
            bloom.setColorAt(0.6, qcol(C.PRI, 18))
            bloom.setColorAt(1.0, qcol(C.PRI, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bloom)
            p.drawEllipse(QRectF(cx - logo_r * 1.1, cy - logo_r * 1.1, logo_r * 2.2, logo_r * 2.2))
            p.drawPixmap(int(cx - fsz / 2), int(cy - fsz / 2), scaled)

        # ── Glitch RGB shift on center ────────────────────────────────────
        if self._glitch_active > 0.05 and self._glitch_rgb:
            shift = int(self._glitch_active * 6)
            p.save()
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            p.setOpacity(0.15 * self._glitch_active)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.GLITCH_R, int(30 * self._glitch_active))))
            p.drawRect(QRectF(cx - r_face - shift, cy - r_face, r_face * 2, r_face * 2))
            p.setBrush(QBrush(qcol(C.GLITCH_C, int(30 * self._glitch_active))))
            p.drawRect(QRectF(cx - r_face + shift, cy - r_face, r_face * 2, r_face * 2))
            p.restore()

        # ── Glitch horizontal slice displacement ───────────────────────────
        if self._glitch_active > 0.05 and self._glitch_slice_y > 0:
            p.save()
            clip = QRectF(0, self._glitch_slice_y, W, self._glitch_slice_h)
            p.setClipRect(clip)
            p.translate(self._glitch_offset * self._glitch_active, 0)
            p.setOpacity(0.3 * self._glitch_active)
            p.fillRect(QRectF(0, self._glitch_slice_y, W, self._glitch_slice_h),
                       qcol(C.WHITE, int(5 * self._glitch_active)))
            p.restore()

        # ── Glitch scan line ───────────────────────────────────────────────
        if self._glitch_active > 0.05:
            scan_y = int(self._glitch_scan)
            p.fillRect(QRectF(0, scan_y, W, 1), qcol(C.PRI, int(30 * self._glitch_active)))
            p.fillRect(QRectF(0, scan_y + 1, W, 1), qcol(C.TEXT, int(15 * self._glitch_active)))

        # particles
        for pt in self._particles:
            a = max(0, min(255, int(pt[4] * 255)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.PRI, a)))
            p.drawEllipse(QPointF(pt[0], pt[1]), 2.5, 2.5)

        # status text
        sy = cy + fw * 0.40
        if self.muted:
            txt, col = "⊘  MUTED",     qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "●  SPEAKING",  qcol(C.ACC)
        elif self.state == "THINKING":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym}  THINKING",   qcol(C.ACC2)
        elif self.state == "PROCESSING":
            sym = "▷" if self._blink else "▶"
            txt, col = f"{sym}  PROCESSING", qcol(C.ACC2)
        elif self.state == "LISTENING":
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  LISTENING",  qcol(C.GREEN)
        elif self.state == "HOLD K TO TALK":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym}  HOLD K TO TALK", qcol(C.GREEN)
        else:
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  {self.state}", qcol(C.PRI)

        p.setPen(QPen(col, 1))
        p.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)

        # waveform
        wy = sy + 30
        N, bw = 36, 8
        wx0 = (W - N * bw) / 2
        for i in range(N):
            if self.muted:
                hgt, cl = 2, qcol(C.MUTED_C)
            elif self.speaking:
                hgt = random.randint(3, 20)
                cl  = qcol(C.PRI) if hgt > 12 else qcol(C.PRI_DIM)
            else:
                hgt = int(3 + 2 * math.sin(self._tick * 0.09 + i * 0.6))
                cl  = qcol(C.BORDER_B)
            p.fillRect(QRectF(wx0 + i * bw, wy + 20 - hgt, bw - 1, hgt), cl)

        # ── Always-on status line ───────────────────────────────────────────
        # A single dim line under the waveform: the tool/agent currently
        # running, or the last thing that happened. Keeps a demo legible
        # without anyone reading the log panel.
        if self.status_line:
            p.setPen(QPen(qcol(C.TEXT_DIM), 1))
            p.setFont(QFont("Courier New", 7))
            _sl_y = min(wy + 26, H - 16)      # never clip off a short canvas
            p.drawText(QRectF(0, _sl_y, W, 16),
                       Qt.AlignmentFlag.AlignCenter, str(self.status_line)[:96])

class MetricGraph(QWidget):
    """Smooth sci-fi sparkline for one system metric. Each new sample is
    eased in rather than snapped, so the line glides instead of jumping — a
    calm, low-friction readout. Paints only while the line is actually moving."""

    _N = 48                      # history depth (samples)

    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = QColor(color)
        self._text  = "--"
        self._tick  = 0
        self._shown  = [0.0] * self._N    # displayed (smoothed) values
        self._target = [0.0] * self._N    # real incoming samples
        self.setFixedHeight(46)
        self.setMinimumWidth(90)
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._animate)
        self._tmr.start(33)

    def set_value(self, pct: float, text: str):
        self._target.pop(0)
        self._target.append(max(0.0, min(100.0, pct)))
        self._text = text
        self._animate()

    def _animate(self):
        moved = False
        for i in range(self._N):
            cur = self._shown[i]
            tgt = self._target[i]
            nxt = cur + (tgt - cur) * 0.16
            if abs(nxt - tgt) < 0.05:
                nxt = tgt
            if nxt != cur:
                moved = True
            self._shown[i] = nxt
        if moved:
            self._tick += 1
            self.update()
            if self._tmr.interval() != 33:
                self._tmr.setInterval(33)
        else:
            # Slow down when idle — saves CPU
            if self._tmr.interval() != 200:
                self._tmr.setInterval(200)

    def hideEvent(self, e):
        # Don't run 30fps tween timers for hidden widgets — zero idle cost.
        self._tmr.stop()
        super().hideEvent(e)

    def showEvent(self, e):
        if not self._tmr.isActive():
            self._tmr.start(33)
        super().showEvent(e)

    def _line_color(self) -> QColor:
        v = self._shown[-1]
        if v > 85:
            return qcol(C.RED)
        if v > 65:
            return qcol(C.ACC)
        return self._color

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        if W < 10 or H < 10:
            return

        pad_l, pad_r, pad_t, pad_b = 8, 8, 20, 6
        gw, gh = W - pad_l - pad_r, H - pad_t - pad_b

        # Rounded frosted panel — transparent glass like the window body.
        p.setPen(QPen(qcol(C.BORDER_A, 28), 1))
        p.setBrush(QBrush(qcol(C.PANEL2, 40)))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 8, 8)

        # Faint calibration grid — calm, evenly spaced, barely-there.
        p.setPen(QPen(qcol(C.BORDER, 120), 1))
        for i in range(3):
            y = pad_t + gh * i / 2
            p.drawLine(QPointF(pad_l, y), QPointF(W - pad_r, y))
        p.setPen(QPen(qcol(C.BORDER, 70), 1))
        for i in range(1, 4):
            x = pad_l + gw * i / 4
            p.drawLine(QPointF(x, pad_t), QPointF(x, pad_t + gh))

        line_col = self._line_color()

        # Header: label left, live value right.
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(8, 3, W / 2, 15),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._label)
        p.setPen(QPen(line_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(W / 2 - 6, 3, W / 2 - 2, 15),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   self._text)

        # Smooth polyline through the history (Catmull-Rom -> cubic beziers).
        n = len(self._shown)
        pts = [
            QPointF(pad_l + gw * i / (n - 1),
                    pad_t + gh * (1.0 - self._shown[i] / 100.0))
            for i in range(n)
        ]
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

        # Soft gradient fill under the curve — melts out toward the baseline.
        area = QPainterPath(path)
        area.lineTo(pts[-1].x(), pad_t + gh)
        area.lineTo(pts[0].x(), pad_t + gh)
        area.closeSubpath()
        fade = QLinearGradient(0, pad_t, 0, pad_t + gh)
        _lc = QColor(line_col); _lc.setAlpha(62)
        fade.setColorAt(0.0, _lc)
        _lc0 = QColor(line_col); _lc0.setAlpha(0)
        fade.setColorAt(1.0, _lc0)
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(area, QBrush(fade))

        p.setPen(QPen(line_col, 1.4))
        p.drawPath(path)

        # Trailing glow dot — breathes very slowly, keeps the readout alive.
        last = pts[-1]
        pulse = 1.0 + 0.45 * math.sin(self._tick * 0.14)
        p.setPen(Qt.PenStyle.NoPen)
        _gc = QColor(line_col); _gc.setAlpha(36)
        p.setBrush(_gc)
        p.drawEllipse(last, 5.0 * pulse, 5.0 * pulse)
        p.setBrush(line_col)
        p.drawEllipse(last, 1.6, 1.6)

# ── Live code viewer: syntax highlighting + line numbers ────────────────

_CODE_LANGUAGES = {
    "html": "HTML", "htm": "HTML", "css": "CSS", "js": "JavaScript",
    "mjs": "JavaScript", "jsx": "JSX", "ts": "TypeScript", "tsx": "TSX",
    "py": "Python", "json": "JSON", "md": "Markdown", "txt": "Text",
    "sql": "SQL", "sh": "Shell", "yml": "YAML", "yaml": "YAML",
}


def _language_for(path: str, text: str = "") -> str:
    """Pick a highlighter language from the filename, then from the content."""
    ext = Path(path or "").suffix.lower().lstrip(".")
    if ext in _CODE_LANGUAGES:
        return "html" if ext == "htm" else ext
    sample = (text or "")[:4000].lower()
    if "<!doctype html" in sample or "<html" in sample:
        return "html"
    if "<?php" in sample:
        return "html"
    if "def " in sample and "import " in sample:
        return "python"
    if "function " in sample or "const " in sample:
        return "js"
    if "{" in sample and ":" in sample and "<" not in sample:
        return "css"
    return "txt"


def _fmt(colour: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(colour))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    return f


def _syntax_rules(lang: str) -> list[tuple]:
    """(compiled regex, format) pairs applied per line.

    Deliberately order-sensitive: keywords before strings, comments last so a
    token inside a comment never keeps a keyword colour.
    """
    import re as _re
    comment = _fmt("#6f7b8f", italic=True)
    string = _fmt("#a8d48a")
    keyword = _fmt("#ff9e64", bold=True)
    tag = _fmt("#7dd3fc")
    attr = _fmt("#f5c76b")
    number = _fmt("#f78c6c")
    prop = _fmt("#82aaff")
    selector = _fmt("#ffcb6b")
    punctuation = _fmt("#8b97ad")
    rules: list[tuple] = []

    def add(pattern, fmt, flags=_re.M):
        rules.append((_re.compile(pattern, flags), fmt))

    if lang in ("html", "htm"):
        add(r"</?[A-Za-z][\w:-]*", tag)
        add(r"/?>", punctuation)
        add(r"\b[A-Za-z_:][\w:.-]*(?=\s*=)", attr)
        add(r"&[a-zA-Z#0-9]+;", number)
        add(r"\"[^\"]*\"|'[^']*'", string)
        add(r"<!--.*?(?:-->|$)", comment)
    elif lang == "css":
        add(r"@[\w-]+", keyword)
        add(r"#[0-9a-fA-F]{3,8}\b", number)
        add(r"\b\d+(?:\.\d+)?(?:px|rem|em|vh|vw|ms|s|%|fr)?\b", number)
        add(r"--[\w-]+|(?<=[\s;{])[a-zA-Z-]+(?=\s*:)", prop)
        add(r"^[^{}\n@/][^{}\n]*(?=\s*\{)", selector)
        add(r"\"[^\"]*\"|'[^']*'", string)
        add(r"/\*.*?(?:\*/|$)", comment)
    elif lang in ("js", "mjs", "jsx", "ts", "tsx"):
        add(r"\b(?:const|let|var|function|return|if|else|for|while|of|in|"
            r"new|class|extends|import|from|export|default|async|await|try|catch|"
            r"throw|typeof|instanceof|this|null|undefined|true|false|switch|case|"
            r"break|continue|do|delete|void|yield)\b", keyword)
        add(r"\b(?:document|window|console|Math|JSON|Object|Array|Promise|Set|Map|Number|String|Date|fetch|setTimeout|setInterval|requestAnimationFrame|addEventListener|querySelector|querySelectorAll|localStorage)\b", prop)
        add(r"\b0x[0-9a-fA-F]+\b|\b\d+(?:\.\d+)?\b", number)
        add(r"`[^`]*`|\"[^\"]*\"|'[^']*'", string)
        add(r"//.*$", comment)
        add(r"/\*.*?(?:\*/|$)", comment)
    elif lang == "python":
        add(r"\b(?:def|class|return|if|elif|else|for|while|in|not|and|or|import|from|as|try|except|finally|raise|with|yield|lambda|pass|break|continue|global|nonlocal|assert|del|is|None|True|False|async|await)\b", keyword)
        add(r"@[\w.]+", prop)
        add(r"\b\d+(?:\.\d+)?\b", number)
        add(r"\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|\"[^\"]*\"|'[^']*'", string)
        add(r"#.*$", comment)
    elif lang == "json":
        add(r"\"[^\"]*\"(?=\s*:)", prop)
        add(r"\"[^\"]*\"", string)
        add(r"\b-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b", number)
        add(r"\b(?:true|false|null)\b", keyword)
    elif lang == "md":
        add(r"^#{1,6} .*$", keyword)
        add(r"\*\*[^*]+\*\*|__[^_]+__", prop)
        add(r"`[^`]+`", string)
        add(r"\[[^\]]+\]\([^)]+\)", selector)
    elif lang in ("sql",):
        add(r"\b(?:SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|GROUP|ORDER|BY|HAVING|LIMIT|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|TABLE|AS|ON|AND|OR|NOT|NULL|SUM|COUNT|AVG|MIN|MAX|CASE|WHEN|THEN|ELSE|END)\b", keyword)
        add(r"--.*$", comment)
        add(r"'[^']*'", string)
        add(r"\b\d+(?:\.\d+)?\b", number)
    return rules


class _CodeHighlighter(QSyntaxHighlighter):
    """Line-based syntax highlighting; re-colours on language change."""

    def __init__(self, document: QTextDocument):
        super().__init__(document)
        self._rules = _syntax_rules("txt")
        self.language = "txt"

    def set_language(self, language: str) -> None:
        self.language = language or "txt"
        self._rules = _syntax_rules(self.language)
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt override
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                start, end = match.span()
                if end > start:
                    self.setFormat(start, end - start, fmt)


class _LineNumberArea(QWidget):
    def __init__(self, editor: "_CodeViewer"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._editor.paint_line_numbers(event)


class _CodeViewer(QPlainTextEdit):
    """Read-only code view with a line-number gutter and live highlighting."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setObjectName("CodeViewer")
        self.setFont(QFont("Cascadia Code", 9))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setPlaceholderText("Code appears here as Crown Code writes files…")
        self._gutter = _LineNumberArea(self)
        self._highlighter = _CodeHighlighter(self.document())
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_gutter_width()
        self._highlight_current_line()

    # gutter ---------------------------------------------------------
    def line_number_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.line_number_width(), cr.height()))

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor(8, 10, 16))
        painter.setFont(self.font())
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current = self.textCursor().blockNumber()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor(C.PRI if number == current else "#4b5568"))
                painter.drawText(0, top, self._gutter.width() - 6,
                                 self.fontMetrics().height(),
                                 Qt.AlignmentFlag.AlignRight, str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1
        painter.end()

    def _highlight_current_line(self) -> None:
        if self.isReadOnly() and not self.toPlainText():
            self.setExtraSelections([])
            return
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor(255, 255, 255, 12))
        sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        self.setExtraSelections([sel])
        self._gutter.update()

    # content ---------------------------------------------------------
    def set_language_from_path(self, path: str) -> str:
        language = _language_for(path, self.toPlainText())
        self._highlighter.set_language(language)
        return language

    def set_text(self, text: str) -> None:
        self.setPlainText(text or "")
        self.moveCursor(self.textCursor().MoveOperation.Start)
        self._update_gutter_width()


class _FadeTextEdit(QTextEdit):
    """QTextEdit whose text fades out at the top/bottom edges instead of hard-clipping.
    Fades only when the content overflows the viewport, so short logs stay bright."""

    def __init__(self, parent=None, fade_h: int = 30):
        super().__init__(parent)
        self._fade_h = fade_h

    def paintEvent(self, event):
        super().paintEvent(event)
        # Only fade when text overflows — otherwise keep every line crisp.
        doc_h  = int(self.document().size().height())
        view_h = self.viewport().height()
        if doc_h <= view_h:
            return
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.viewport().width(), self.viewport().height()
        fh = min(self._fade_h, H // 3)
        g1 = QLinearGradient(0, 0, 0, fh)
        g1.setColorAt(0.0, qcol(C.BG, 100))
        g1.setColorAt(1.0, qcol(C.BG, 0))
        p.fillRect(QRectF(0, 0, W, fh), QBrush(g1))
        g2 = QLinearGradient(0, H - fh, 0, H)
        g2.setColorAt(0.0, qcol(C.BG, 0))
        g2.setColorAt(1.0, qcol(C.BG, 100))
        p.fillRect(QRectF(0, H - fh, W, fh), QBrush(g2))


class LogWidget(_FadeTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 9))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                color: {C.TEXT};
                border: none;
                padding: 6px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(255, 215, 0, 140);
                border-radius: 3px;
                min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        if   tl.startswith("you:"):    self._tag = "you"
        elif tl.startswith("keys.ai:") or tl.startswith("keys"): self._tag = "ai"
        elif tl.startswith("file:"):   self._tag = "file"
        elif "err" in tl:              self._tag = "err"
        else:                          self._tag = "sys"
        self._tmr.start(2)

    def _step(self):
        if self._pos < len(self._text):
            # Batch up to 8 chars per tick for faster display
            batch = min(8, len(self._text) - self._pos)
            chunk = self._text[self._pos:self._pos + batch]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you":  qcol(C.WHITE),
                "ai":   qcol(C.PRI),
                "err":  qcol(C.RED),
                "file": qcol(C.GREEN),
                "sys":  qcol(C.ACC2),
            }.get(self._tag, qcol(C.TEXT))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(chunk, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += batch
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(20, self._next)


class _CameraPreview(QWidget):
    """Floating overlay that briefly shows what the camera captured."""

    _W, _H = 244, 188

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _CameraPreview {{
                background: rgba(0, 6, 10, 242);
                border: 1px solid {C.PRI};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._W)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 6)
        lay.setSpacing(4)

        hdr = QHBoxLayout()
        title = QLabel("◈  VISUAL INPUT")
        title.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(16, 16)
        close_btn.setFont(QFont("Courier New", 8))
        close_btn.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent; border: none;"
        )
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        hdr.addWidget(close_btn)
        lay.addLayout(hdr)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet("background: transparent;")
        lay.addWidget(self._img_lbl)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self.hide()

    def show_frame(self, img_bytes: bytes) -> None:
        px = QPixmap()
        px.loadFromData(img_bytes)
        if not px.isNull():
            max_w = self._W - 12
            scaled = px.scaled(
                max_w, 160,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img_lbl.setPixmap(scaled)
            self._img_lbl.setFixedSize(scaled.width(), scaled.height())
            self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(6_000)   # auto-dismiss after 6 s


class DecisionWidget(QWidget):
    """Interactive decision card — shows clickable options during creation.
    Emitted when user clicks an option or submits custom text."""
    chosen = pyqtSignal(str)   # the selected option label

    def __init__(self, question: str, options: list[str], show_why: bool = False,
                 why_text: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("DecisionWidget")
        self.setStyleSheet(f"""
            QWidget#DecisionWidget {{
                background: rgba(20, 24, 36, 220);
                border: 1px solid rgba(217, 182, 80, 60);
                border-radius: 6px;
                margin: 4px 8px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        # Header
        hdr = QHBoxLayout(); hdr.setSpacing(6)
        dot = QLabel("\u25c8")
        dot.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        dot.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(dot)
        q_lbl = QLabel(question.upper()[:60])
        q_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        q_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent; letter-spacing: 0.5px;")
        q_lbl.setWordWrap(True)
        hdr.addWidget(q_lbl, stretch=1)
        root.addLayout(hdr)

        # Options grid
        opts_layout = QHBoxLayout(); opts_layout.setSpacing(6)
        opts_layout.setContentsMargins(20, 0, 0, 0)
        for opt in options:
            btn = QPushButton(opt)
            btn.setFont(QFont("Segoe UI", 8))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(28)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(217, 182, 80, 15); color: {C.TEXT};
                    border: 1px solid rgba(217, 182, 80, 50); border-radius: 4px;
                    padding: 4px 12px;
                }}
                QPushButton:hover {{
                    background: rgba(217, 182, 80, 35); border-color: {C.PRI};
                    color: {C.WHITE};
                }}
                QPushButton:pressed {{ background: rgba(217, 182, 80, 50); }}
            """)
            btn.clicked.connect(lambda checked=False, o=opt: self._select(o))
            opts_layout.addWidget(btn)
        opts_layout.addStretch()
        root.addLayout(opts_layout)

        # Why button (optional)
        if show_why and why_text:
            why_btn = QPushButton("Why these options?")
            why_btn.setFont(QFont("Segoe UI", 7))
            why_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            why_btn.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {C.TEXT_DIM}; border: none; padding: 2px 20px; }}
                QPushButton:hover {{ color: {C.PRI}; }}
            """)
            why_lbl = QLabel(why_text)
            why_lbl.setFont(QFont("Segoe UI", 7))
            why_lbl.setWordWrap(True)
            why_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; padding: 0 20px;")
            why_lbl.hide()
            why_btn.clicked.connect(lambda: why_lbl.setVisible(not why_lbl.isVisible()))
            root.addWidget(why_btn)
            root.addWidget(why_lbl)

        # Custom direction
        custom_row = QHBoxLayout(); custom_row.setSpacing(4)
        custom_row.setContentsMargins(20, 0, 0, 0)
        self._custom_input = QLineEdit()
        self._custom_input.setPlaceholderText("Type your own direction...")
        self._custom_input.setFont(QFont("Segoe UI", 8))
        self._custom_input.setFixedHeight(26)
        self._custom_input.setStyleSheet(f"""
            QLineEdit {{ background: rgba(5,6,10,120); color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 3px; padding: 2px 8px; }}
            QLineEdit:focus {{ border-color: {C.PRI}; }}
        """)
        self._custom_input.returnPressed.connect(self._submit_custom)
        custom_row.addWidget(self._custom_input, stretch=1)

        apply_btn = QPushButton("Apply")
        apply_btn.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        apply_btn.setFixedHeight(26)
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(f"""
            QPushButton {{ background: rgba(217,182,80,30); color: {C.PRI}; border: 1px solid {C.PRI_DIM}; border-radius: 3px; padding: 2px 10px; }}
            QPushButton:hover {{ background: rgba(217,182,80,50); }}
        """)
        apply_btn.clicked.connect(self._submit_custom)
        custom_row.addWidget(apply_btn)
        root.addLayout(custom_row)

        self._answered = False

    def _select(self, option: str):
        if self._answered:
            return
        self._answered = True
        self.chosen.emit(option)
        self._fade_out()

    def _submit_custom(self):
        if self._answered:
            return
        text = self._custom_input.text().strip()
        if not text:
            return
        self._answered = True
        self.chosen.emit(f"Custom: {text}")
        self._fade_out()

    def _fade_out(self):
        self._custom_input.setEnabled(False)
        for btn in self.findChildren(QPushButton):
            btn.setEnabled(False)
            btn.setStyleSheet(btn.styleSheet().replace(C.TEXT, C.TEXT_DIM))
        self.setStyleSheet(self.styleSheet().replace(
            "border: 1px solid rgba(217, 182, 80, 60)",
            "border: 1px solid rgba(61, 220, 132, 60)"
        ).replace(
            f"color: {C.PRI}; background: transparent; letter-spacing: 0.5px",
            f"color: {C.GREEN}; background: transparent; letter-spacing: 0.5px"
        ))


class PermissionWidget(QWidget):
    """Interactive permission card — asks user to approve/deny an action."""
    decided = pyqtSignal(str)   # "allow_once" | "allow_task" | "deny"

    def __init__(self, action: str, reason: str = "", location: str = "",
                 parent=None):
        super().__init__(parent)
        self.setObjectName("PermissionWidget")
        self.setStyleSheet(f"""
            QWidget#PermissionWidget {{
                background: rgba(24, 18, 10, 220);
                border: 1px solid rgba(227, 64, 110, 50);
                border-radius: 6px;
                margin: 4px 8px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(6)

        # Header
        hdr = QHBoxLayout(); hdr.setSpacing(6)
        icon = QLabel("\u26a0")
        icon.setFont(QFont("Segoe UI", 10))
        icon.setStyleSheet(f"color: #F0A500; background: transparent;")
        hdr.addWidget(icon)
        title = QLabel("PERMISSION REQUIRED")
        title.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        title.setStyleSheet(f"color: #F0A500; background: transparent; letter-spacing: 0.5px;")
        hdr.addWidget(title)
        hdr.addStretch()
        root.addLayout(hdr)

        # Details
        if action:
            a_lbl = QLabel(f"Action:  {action}")
            a_lbl.setFont(QFont("Segoe UI", 8))
            a_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
            a_lbl.setWordWrap(True)
            root.addWidget(a_lbl)
        if reason:
            r_lbl = QLabel(f"Reason:  {reason}")
            r_lbl.setFont(QFont("Segoe UI", 8))
            r_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            r_lbl.setWordWrap(True)
            root.addWidget(r_lbl)
        if location:
            l_lbl = QLabel(f"Location:  {location}")
            l_lbl.setFont(QFont("Courier New", 7))
            l_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            root.addWidget(l_lbl)

        # Buttons
        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        btn_row.setContentsMargins(20, 4, 0, 0)
        buttons = [
            ("Allow Once", "allow_once", C.GREEN),
            ("Allow for Task", "allow_task", C.PRI),
            ("Deny", "deny", C.RED),
        ]
        for label, key, color in buttons:
            btn = QPushButton(label)
            btn.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(28)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(5,6,10,120); color: {color};
                    border: 1px solid {color}; border-radius: 4px;
                    padding: 4px 14px;
                }}
                QPushButton:hover {{ background: rgba(255,255,255,12); }}
                QPushButton:pressed {{ background: rgba(255,255,255,20); }}
            """)
            btn.clicked.connect(lambda checked=False, k=key: self._decide(k))
            btn_row.addWidget(btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._decided = False

    def _decide(self, choice: str):
        if self._decided:
            return
        self._decided = True
        self.decided.emit(choice)
        # Visual feedback
        color = {"allow_once": C.GREEN, "allow_task": C.PRI, "deny": C.RED}.get(choice, C.TEXT_DIM)
        self.setStyleSheet(self.styleSheet().replace(
            "border: 1px solid rgba(227, 64, 110, 50)",
            f"border: 1px solid {color}"
        ))
        for btn in self.findChildren(QPushButton):
            btn.setEnabled(False)


class _WebLoadingSpinner(QWidget):
    """Animated loading spinner overlay for the web preview panel.
    Shows a spinning gold arc with "Loading..." text while the page loads."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0.0
        self._dots = 0
        self._dot_timer = 0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: rgba(6,7,10,230); border: none;")

        # Spinning timer — ~60fps for smooth arc rotation
        self._spin_timer = QTimer(self)
        self._spin_timer.timeout.connect(self._rotate)
        self._spin_timer.start(16)

    def _rotate(self):
        self._angle = (self._angle + 6.0) % 360.0
        self._dot_timer += 1
        if self._dot_timer % 20 == 0:
            self._dots = (self._dots + 1) % 4
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        if W < 20 or H < 20:
            return
        cx, cy = W / 2, H / 2 - 10

        # ── Spinning arc ring ──
        ring_r = min(W, H) * 0.18
        ring_w = max(2, int(ring_r * 0.14))
        rect = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
        # Outer glow ring (subtle)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        glow_col = qcol(C.PRI, 18)
        p.setPen(QPen(glow_col, ring_w + 6))
        p.drawArc(rect, int(self._angle * 16), int(90 * 16))
        # Main spinning arc
        arc_col = qcol(C.PRI, 220)
        p.setPen(QPen(arc_col, ring_w))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(rect, int(self._angle * 16), int(90 * 16))
        # Trailing faint arc
        trail_col = qcol(C.PRI_DIM, 80)
        p.setPen(QPen(trail_col, ring_w - 1))
        p.drawArc(rect, int((self._angle - 40) * 16), int(50 * 16))

        # ── Center dot ──
        p.setPen(Qt.PenStyle.NoPen)
        dot_pulse = 1.0 + 0.3 * math.sin(self._angle * 0.05)
        p.setBrush(qcol(C.PRI, 140))
        p.drawEllipse(QPointF(cx, cy), 2.5 * dot_pulse, 2.5 * dot_pulse)

        # ── "Loading" text with animated dots ──
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        dots = "." * self._dots
        p.drawText(
            QRectF(0, cy + ring_r + 16, W, 24),
            Qt.AlignmentFlag.AlignCenter,
            f"Loading{dots}"
        )

        # ── Outer decorative ring (static, very faint) ──
        outer_r = ring_r * 1.7
        outer_rect = QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2)
        p.setPen(QPen(qcol(C.PRI, 25), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(outer_rect)
        # Tiny tick marks on the outer ring
        p.setPen(QPen(qcol(C.PRI, 50), 1))
        for deg in range(0, 360, 30):
            rad = math.radians(deg + self._angle * 0.1)
            ix = cx + outer_r * math.cos(rad)
            iy = cy + outer_r * math.sin(rad)
            ox = cx + (outer_r + 5) * math.cos(rad)
            oy = cy + (outer_r + 5) * math.sin(rad)
            p.drawLine(QPointF(ix, iy), QPointF(ox, oy))

        p.end()

    def showEvent(self, e):
        if not self._spin_timer.isActive():
            self._spin_timer.start(16)
        super().showEvent(e)

    def hideEvent(self, e):
        self._spin_timer.stop()
        super().hideEvent(e)


# ── Live Coding terminal helpers ────────────────────────────────────────────
# ANSI SGR → Qt colour. Real build tools (npm, cargo, pytest, tsc) emit colour
# escapes; rendering them instead of the literal "\x1b[32m" is most of what
# makes an embedded terminal feel like a terminal.
_ANSI_COLORS = {
    30: "#3B3B3B", 31: "#FF5C57", 32: "#5AF78E", 33: "#F3F99D",
    34: "#57C7FF", 35: "#FF6AC1", 36: "#9AEDFE", 37: "#E6E6E6",
    90: "#7F7F7F", 91: "#FF8A80", 92: "#8EF7B0", 93: "#FFE680",
    94: "#8AD8FF", 95: "#FF9AD5", 96: "#B7F5FF", 97: "#FFFFFF",
}


def _ansi_segments(text: str):
    """Split ANSI-coloured text into (chunk, colour|None, bold) segments."""
    import re
    out: list = []
    color, bold, pos = None, False, 0
    for m in re.finditer(r"\x1b\[([0-9;]*)m", text):
        if m.start() > pos:
            out.append((text[pos:m.start()], color, bold))
        codes = [c for c in m.group(1).split(";") if c != ""] or ["0"]
        for c in codes:
            try:
                n = int(c)
            except ValueError:
                continue
            if n == 0:
                color, bold = None, False
            elif n == 1:
                bold = True
            elif n == 22:
                bold = False
            elif n == 39:
                color = None
            elif n in _ANSI_COLORS:
                color = _ANSI_COLORS[n]
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], color, bold))
    return out or [(text, None, False)]


def _terminal_runs(text: str, base_color: str) -> list:
    """Turn raw terminal output into (chunk, colour, bold) runs.

    Pure so it can be tested without a GUI. A trailing `[exit N]` becomes a
    highlighted chip: green on success, red otherwise.
    """
    import re
    runs: list = []
    for txt, ansi_color, bold in _ansi_segments(text):
        for part in re.split(r"(\[exit -?\d+\])", txt):
            if not part:
                continue
            mm = re.fullmatch(r"\[exit (-?\d+)\]", part)
            if mm:
                runs.append((part, "#5AF78E" if mm.group(1) == "0" else "#FF5C57", True))
            else:
                runs.append((part, ansi_color or base_color, bold))
    return runs


class _TerminalInput(QLineEdit):
    """Command input with ↑/↓ history, like a real terminal."""

    submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: list[str] = []
        self._idx = 0
        self.returnPressed.connect(self._on_return)

    def _on_return(self):
        cmd = self.text().strip()
        if cmd and (not self._history or self._history[-1] != cmd):
            self._history.append(cmd)
        self._idx = len(self._history)
        self.submitted.emit(cmd)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Up and self._history:
            self._idx = max(0, self._idx - 1)
            self.setText(self._history[self._idx])
            self.setCursorPosition(len(self.text()))
            return
        if e.key() == Qt.Key.Key_Down and self._history:
            self._idx = min(len(self._history), self._idx + 1)
            self.setText(self._history[self._idx] if self._idx < len(self._history) else "")
            self.setCursorPosition(len(self.text()))
            return
        super().keyPressEvent(e)


class CreationWorkspace(QWidget):
    """
    Real-time creation workspace — split Activity Timeline + Live Code Viewer.
    Shown below the HUD when Keys.AI is building a project or creating a document.
    """

    # ── Signals (emitted when user interacts) ──────────────────────────────
    fileClicked = pyqtSignal(str)  # user clicked a file in the timeline
    terminalCommandSubmitted = pyqtSignal(str)  # user typed a command in the terminal
    stopRequested = pyqtSignal()                # user pressed Stop in the terminal

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CreationWorkspace")
        self.setStyleSheet(f"""
            QWidget#CreationWorkspace {{
                background: rgba(8, 10, 16, 220);
                border-top: 1px solid rgba(255, 215, 0, 55);
            }}
        """)
        self.hide()  # hidden until a creation starts

        # ── State ────────────────────────────────────────────────────────────
        self._mode = None          # "code" | "ppt" | "excel" | "doc" | "txt" | None
        self._project_name = ""
        self._project_path = ""
        self._current_file = ""
        self._files: list[dict] = []   # [{path, lines, status}]
        self._file_contents: dict[str, str] = {}   # path -> code written so far
        self._writing_path = ""        # file the agent is writing right now
        self._follow = True            # view follows the file being written
        self._reveal_queue: list[tuple[str, str]] = []
        self._reveal_left = ""
        self._reveal_path = ""
        self._reveal_ticks = 0
        self._reveal_step = 60
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setInterval(16)
        self._reveal_timer.timeout.connect(self._reveal_tick)
        self._events: list[dict] = []  # [{icon, text, file, color}]
        self._event_widgets: list[QWidget] = []
        self._progress = 0.0
        self._started = False
        self._phase = "idle"
        self._eta = 0.0
        self._began_at = 0.0
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._refresh_phase)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ───────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(32)
        hdr.setStyleSheet("background: rgba(14, 17, 24, 200); border-bottom: 1px solid rgba(255,215,0,30);")
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(10, 0, 10, 0)
        hdr_lay.setSpacing(8)

        dot = QLabel("◈")
        dot.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        dot.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr_lay.addWidget(dot)

        self._title_lbl = QLabel("LIVE CREATION")
        self._title_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent; letter-spacing: 1px;")
        hdr_lay.addWidget(self._title_lbl)

        self._project_lbl = QLabel("")
        self._project_lbl.setFont(QFont("Courier New", 7))
        self._project_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        hdr_lay.addWidget(self._project_lbl)

        hdr_lay.addStretch()

        # Every file this session has touched, newest last. Picking one shows
        # it even while the agent writes something else.
        self._file_combo = QComboBox()
        self._file_combo.setFont(QFont("Courier New", 7))
        self._file_combo.setFixedHeight(18)
        self._file_combo.setMinimumWidth(120)
        self._file_combo.setToolTip("Files written in this session — pick one to view it")
        self._file_combo.setStyleSheet(
            f"QComboBox {{ color: {C.GREEN}; background: rgba(20,24,36,220);"
            f" border: 1px solid rgba(61,220,132,60); border-radius: 3px; padding: 0 4px; }}"
            f"QComboBox QAbstractItemView {{ color: {C.TEXT}; background: #0e1118;"
            f" selection-background-color: rgba(217,182,80,60); }}")
        self._file_combo.currentIndexChanged.connect(self._on_file_combo)
        self._file_combo.hide()
        hdr_lay.addWidget(self._file_combo)

        # Pinned when the user is reading an older file; LIVE resumes following
        # whatever the agent writes next.
        self._follow_btn = QPushButton("LIVE")
        self._follow_btn.setFixedHeight(18)
        self._follow_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._follow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._follow_btn.setToolTip("Follow the file being written (click a file to pin)")
        self._follow_btn.clicked.connect(self._resume_follow)
        self._follow_btn.hide()
        hdr_lay.addWidget(self._follow_btn)

        self._file_lbl = QLabel("")
        self._file_lbl.setFont(QFont("Courier New", 7))
        self._file_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent;")
        hdr_lay.addWidget(self._file_lbl)

        # Phase + percent + ETA. One glance answers "what is it doing and how
        # long will it take?" without reading the timeline.
        self._phase_lbl = QLabel("IDLE")
        self._phase_lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._phase_lbl.setStyleSheet(
            f"color: {C.PRI}; background: rgba(217,182,80,20); border: 1px solid rgba(217,182,80,60);"
            " border-radius: 3px; padding: 1px 6px;")
        hdr_lay.addWidget(self._phase_lbl)

        dismiss = QPushButton("✕")
        dismiss.setFixedSize(18, 18)
        dismiss.setFont(QFont("Courier New", 8))
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.setStyleSheet(f"QPushButton {{ color: {C.TEXT_DIM}; background: transparent; border: none; }} QPushButton:hover {{ color: {C.PRI}; }}")
        dismiss.clicked.connect(self._dismiss)
        hdr_lay.addWidget(dismiss)

        root.addWidget(hdr)

        # ── Progress bar ─────────────────────────────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(3)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: rgba(30, 36, 46, 180);
                border: none;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {C.PRI_DIM}, stop:0.5 {C.PRI}, stop:1 {C.ACC});
                border-radius: 1px;
            }}
        """)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        root.addWidget(self._progress_bar)

        # ── Splitter: Activity | Code ────────────────────────────────────────
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setStyleSheet(f"""
            QSplitter::handle {{ background: rgba(255, 215, 0, 30); width: 1px; }}
            QSplitter::handle:hover {{ background: rgba(255, 215, 0, 90); }}
        """)

        # ── Left: Activity Timeline ──────────────────────────────────────────
        act_widget = QWidget()
        act_widget.setStyleSheet("background: transparent;")
        act_lay = QVBoxLayout(act_widget)
        act_lay.setContentsMargins(0, 0, 0, 0)
        act_lay.setSpacing(0)

        act_hdr = QLabel("  CREATION ACTIVITY")
        act_hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        act_hdr.setFixedHeight(22)
        act_hdr.setStyleSheet(f"color: {C.PRI_DIM}; background: rgba(14,17,24,120); border-bottom: 1px solid rgba(255,215,0,20); padding: 3px 0;")
        act_lay.addWidget(act_hdr)

        self._event_scroll = QScrollArea()
        self._event_scroll.setWidgetResizable(True)
        self._event_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._event_scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 5px; border: none; }}
            QScrollBar::handle:vertical {{ background: rgba(217,182,80,100); border-radius: 2px; min-height: 16px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; }}
        """)
        self._event_container = QWidget()
        self._event_container.setStyleSheet("background: transparent;")
        self._event_layout = QVBoxLayout(self._event_container)
        self._event_layout.setContentsMargins(6, 4, 6, 4)
        self._event_layout.setSpacing(1)
        self._event_layout.addStretch()
        self._event_scroll.setWidget(self._event_container)
        act_lay.addWidget(self._event_scroll)

        self._splitter.addWidget(act_widget)

        # ── Right: Live Code Viewer ──────────────────────────────────────────
        code_widget = QWidget()
        code_widget.setStyleSheet("background: transparent;")
        code_lay = QVBoxLayout(code_widget)
        code_lay.setContentsMargins(0, 0, 0, 0)
        code_lay.setSpacing(0)

        code_hdr = QWidget()
        code_hdr.setFixedHeight(24)
        code_hdr.setStyleSheet("background: rgba(14,17,24,150); border-bottom: 1px solid rgba(61,220,132,25);")
        code_hdr_lay = QHBoxLayout(code_hdr)
        code_hdr_lay.setContentsMargins(8, 0, 6, 0)
        code_hdr_lay.setSpacing(7)

        self._code_file_hdr = QLabel("  LIVE CODE")
        self._code_file_hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._code_file_hdr.setStyleSheet(f"color: {C.GREEN}; background: transparent;")
        code_hdr_lay.addWidget(self._code_file_hdr)

        self._code_lang_lbl = QLabel("TEXT")
        self._code_lang_lbl.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        self._code_lang_lbl.setStyleSheet(
            "color: #7dd3fc; background: rgba(100,140,255,18); border: 1px solid rgba(100,140,255,45);"
            " border-radius: 3px; padding: 0px 4px;")
        code_hdr_lay.addWidget(self._code_lang_lbl)

        self._code_stats_lbl = QLabel("0 lines · 0 B")
        self._code_stats_lbl.setFont(QFont("Courier New", 6))
        self._code_stats_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        code_hdr_lay.addWidget(self._code_stats_lbl)

        code_hdr_lay.addStretch()

        _code_btn_ss = (
            "QPushButton { color: #8b97ad; background: rgba(255,255,255,6); border: 1px solid rgba(255,255,255,25);"
            " border-radius: 3px; padding: 1px 6px; font-size: 9px; }"
            "QPushButton:hover { color: #fff; border-color: rgba(61,220,132,140); background: rgba(61,220,132,25); }"
            "QPushButton:pressed { background: rgba(61,220,132,45); }"
        )
        self._code_copy_btn = QPushButton("COPY")
        self._code_copy_btn.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        self._code_copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._code_copy_btn.setToolTip("Copy the visible file")
        self._code_copy_btn.setFixedHeight(17)
        self._code_copy_btn.setStyleSheet(_code_btn_ss)
        self._code_copy_btn.clicked.connect(self._copy_code)
        code_hdr_lay.addWidget(self._code_copy_btn)

        self._code_wrap_btn = QPushButton("WRAP")
        self._code_wrap_btn.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        self._code_wrap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._code_wrap_btn.setToolTip("Toggle soft wrapping")
        self._code_wrap_btn.setCheckable(True)
        self._code_wrap_btn.setFixedHeight(17)
        self._code_wrap_btn.setStyleSheet(_code_btn_ss)
        self._code_wrap_btn.clicked.connect(self._toggle_wrap)
        code_hdr_lay.addWidget(self._code_wrap_btn)
        code_lay.addWidget(code_hdr)

        self._code_viewer = _CodeViewer()
        self._code_viewer.setStyleSheet(f"""
            QPlainTextEdit#CodeViewer {{
                background: rgba(6, 7, 10, 205);
                color: {C.TEXT};
                border: none;
                padding: 4px 0px 6px 4px;
                selection-background-color: {C.PRI_GHO};
            }}
            QPlainTextEdit#CodeViewer:focus {{ border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 6px; border: none; }}
            QScrollBar::handle:vertical {{ background: rgba(217,182,80,110); border-radius: 3px; min-height: 18px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; }}
            QScrollBar:horizontal {{ background: transparent; height: 6px; border: none; }}
            QScrollBar::handle:horizontal {{ background: rgba(217,182,80,90); border-radius: 3px; min-width: 18px; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; border: none; }}
        """)
        self._code_viewer.textChanged.connect(self._update_code_stats)
        code_lay.addWidget(self._code_viewer)

        self._splitter.addWidget(code_widget)

        # ── Web Preview Panel (hidden until a URL is loaded) ────────────────
        self._preview_widget = QWidget()
        self._preview_widget.setStyleSheet("background: transparent;")
        prev_lay = QVBoxLayout(self._preview_widget)
        prev_lay.setContentsMargins(0, 0, 0, 0)
        prev_lay.setSpacing(0)

        prev_hdr = QWidget()
        prev_hdr.setFixedHeight(22)
        prev_hdr.setStyleSheet(f"background: rgba(14,17,24,120); border-bottom: 1px solid rgba(100,140,255,20);")
        prev_hdr_lay = QHBoxLayout(prev_hdr)
        prev_hdr_lay.setContentsMargins(8, 0, 8, 0)
        prev_lbl = QLabel("  WEB PREVIEW")
        prev_lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        prev_lbl.setStyleSheet(f"color: #648CFF; background: transparent; padding: 3px 0;")
        prev_hdr_lay.addWidget(prev_lbl)
        prev_hdr_lay.addStretch()
        # Open in external browser button
        self._open_browser_btn = QPushButton("  Open in Browser  ")
        self._open_browser_btn.setFont(QFont("Courier New", 6))
        self._open_browser_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_browser_btn.setStyleSheet(f"""
            QPushButton {{ color: #648CFF; background: rgba(100,140,255,15); border: 1px solid rgba(100,140,255,40); border-radius: 2px; padding: 2px 6px; }}
            QPushButton:hover {{ background: rgba(100,140,255,35); border-color: #648CFF; }}
        """)
        self._open_browser_btn.clicked.connect(self._open_in_browser)
        self._open_browser_btn.hide()
        prev_hdr_lay.addWidget(self._open_browser_btn)
        prev_lay.addWidget(prev_hdr)

        # ── URL bar + nav row ──────────────────────────────────────────────
        self._preview_nav = QWidget()
        self._preview_nav.setFixedHeight(24)
        self._preview_nav.setStyleSheet("background: rgba(10,12,18,200); border-bottom: 1px solid rgba(100,140,255,15);")
        nav_lay = QHBoxLayout(self._preview_nav)
        nav_lay.setContentsMargins(4, 0, 4, 0)
        nav_lay.setSpacing(2)

        _nav_btn_ss = """
            QPushButton {
                color: #648CFF; background: rgba(100,140,255,8); border: none;
                border-radius: 2px; padding: 1px 5px; font-size: 10px;
                min-width: 18px; max-width: 18px; min-height: 16px; max-height: 16px;
            }
            QPushButton:hover { background: rgba(100,140,255,30); color: #fff; }
            QPushButton:pressed { background: rgba(100,140,255,50); }
            QPushButton:disabled { color: rgba(100,140,255,40); background: transparent; }
        """

        self._prev_back_btn = QPushButton("\u25C0")
        self._prev_back_btn.setFont(QFont("Courier New", 7))
        self._prev_back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev_back_btn.setToolTip("Back")
        self._prev_back_btn.setStyleSheet(_nav_btn_ss)
        self._prev_back_btn.clicked.connect(self._preview_back)
        self._prev_back_btn.setEnabled(False)
        nav_lay.addWidget(self._prev_back_btn)

        self._prev_fwd_btn = QPushButton("\u25B6")
        self._prev_fwd_btn.setFont(QFont("Courier New", 7))
        self._prev_fwd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev_fwd_btn.setToolTip("Forward")
        self._prev_fwd_btn.setStyleSheet(_nav_btn_ss)
        self._prev_fwd_btn.clicked.connect(self._preview_forward)
        self._prev_fwd_btn.setEnabled(False)
        nav_lay.addWidget(self._prev_fwd_btn)

        self._prev_refresh_btn = QPushButton("\u21BB")
        self._prev_refresh_btn.setFont(QFont("Courier New", 8))
        self._prev_refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev_refresh_btn.setToolTip("Refresh")
        self._prev_refresh_btn.setStyleSheet(_nav_btn_ss)
        self._prev_refresh_btn.clicked.connect(self._preview_refresh)
        nav_lay.addWidget(self._prev_refresh_btn)

        # Readonly URL bar
        self._preview_url_bar = QLineEdit()
        self._preview_url_bar.setReadOnly(True)
        self._preview_url_bar.setFont(QFont("Courier New", 7))
        self._preview_url_bar.setFixedHeight(16)
        self._preview_url_bar.setStyleSheet(f"""
            QLineEdit {{ background: rgba(5,6,10,100); color: {C.TEXT_DIM}; border: 1px solid rgba(100,140,255,20);
                           border-radius: 2px; padding: 0 6px; selection-background-color: rgba(100,140,255,40); }}
        """)
        nav_lay.addWidget(self._preview_url_bar, stretch=1)

        self._prev_nav_btns = [self._prev_back_btn, self._prev_fwd_btn, self._prev_refresh_btn]

        prev_lay.addWidget(self._preview_nav)
        self._preview_nav.hide()  # hidden until a URL is loaded

        if _HAS_WEBENGINE:
            # Stack web view + spinner overlay
            self._preview_stack = QStackedWidget()
            self._preview_stack.setStyleSheet("background: #0a0a0a; border: none;")

            self._web_view = QWebEngineView()
            self._web_view.setStyleSheet("background: #0a0a0a; border: none;")
            self._preview_stack.addWidget(self._web_view)   # index 0

            self._loading_spinner = _WebLoadingSpinner()
            self._preview_stack.addWidget(self._loading_spinner)  # index 1

            # Connect load signals to show/hide spinner + update nav state
            self._web_view.loadStarted.connect(self._on_preview_load_started)
            self._web_view.loadFinished.connect(self._on_preview_load_finished)

            # Update URL bar on navigation
            self._web_view.urlChanged.connect(self._on_preview_url_changed)

            self._preview_stack.setCurrentIndex(1)  # start with spinner visible
            prev_lay.addWidget(self._preview_stack)
            self._current_preview_url = ""
        else:
            _no_web = QLabel("  QWebEngineView not available  |  Install: pip install PyQt6-WebEngine")
            _no_web.setFont(QFont("Courier New", 9))
            _no_web.setStyleSheet(f"color: {C.TEXT_DIM}; background: rgba(6,7,10,200); padding: 20px;")
            _no_web.setAlignment(Qt.AlignmentFlag.AlignCenter)
            prev_lay.addWidget(_no_web)

        # No preview browser here any more. The Research Browser is the preview
        # browser: a built site opens there, in the same surface the agent uses
        # to read the page. The widget is deliberately never added to the
        # splitter, so it cannot reappear and cannot take width from the app.
        self._preview_widget.hide()

        # ── Terminal pane used by the Dev Agent (Crown Code Terminal Agent) ─────
        # Kept to look exactly like the old Crown Code TERMINAL panel; the only
        # change is the label now names the Dev Agent while the workflow behind
        # it is the Mark LV-style plan→write→deps→run→fix loop.
        term_widget = QWidget()
        term_widget.setStyleSheet("background: transparent;")
        term_lay = QVBoxLayout(term_widget)
        term_lay.setContentsMargins(0, 0, 0, 0)
        term_lay.setSpacing(0)

        term_hdr = QWidget()
        term_hdr.setFixedHeight(22)
        term_hdr.setStyleSheet("background: rgba(14,17,24,120); border-bottom: 1px solid rgba(100,140,255,20);")
        term_hdr_lay = QHBoxLayout(term_hdr)
        term_hdr_lay.setContentsMargins(8, 0, 6, 0)
        term_hdr_lay.setSpacing(6)

        term_lbl = QLabel("  TERMINAL  (Crown Code Terminal Agent)")
        term_lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        term_lbl.setStyleSheet("color: #648CFF; background: transparent; padding: 3px 0;")
        term_hdr_lay.addWidget(term_lbl)

        self._term_run_lbl = QLabel("idle")
        self._term_run_lbl.setFont(QFont("Courier New", 6))
        self._term_run_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        term_hdr_lay.addWidget(self._term_run_lbl)
        term_hdr_lay.addStretch()

        # Cumulative coding-model picker — switch the local Ollama model for
        # Crown Code without editing config/crown_code.json by hand. "auto"
        # lets the bridge choose a model that fits this machine's RAM.
        self._loading_models = True
        self._model_combo = QComboBox()
        self._model_combo.setFont(QFont("Courier New", 6))
        self._model_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._model_combo.setToolTip("Coding model for Crown Code (Ollama). "
                                     "'auto' picks one for this machine's RAM.")
        self._model_combo.addItem("auto")
        self._model_combo.setStyleSheet(
            f"QComboBox {{ color: {C.TEXT_MED}; background: rgba(20,24,36,200);"
            " border: 1px solid rgba(100,140,255,40); border-radius: 2px;"
            " padding: 0px 4px; }"
            f"QComboBox QAbstractItemView {{ background: #0A0D14;"
            f" color: {C.TEXT_MED}; selection-background-color: rgba(100,140,255,60); }}")
        self._model_combo.currentTextChanged.connect(self._on_coding_model_changed)
        term_hdr_lay.addWidget(self._model_combo)
        self._loading_models = False
        self._refresh_coding_models()

        _term_btn_ss = (
            "QPushButton { color: #648CFF; background: rgba(100,140,255,12);"
            " border: 1px solid rgba(100,140,255,40); border-radius: 2px; padding: 1px 6px; }"
            " QPushButton:hover { background: rgba(100,140,255,35); border-color: #648CFF; }"
        )

        self._term_stop_btn = QPushButton("Stop")
        self._term_stop_btn.setFont(QFont("Courier New", 6))
        self._term_stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._term_stop_btn.setToolTip("Stop the running Dev Agent / Crown Code terminal task")
        self._term_stop_btn.setStyleSheet(_term_btn_ss)
        self._term_stop_btn.clicked.connect(lambda: self.stopRequested.emit())
        term_hdr_lay.addWidget(self._term_stop_btn)

        self._term_clear_btn = QPushButton("Clear")
        self._term_clear_btn.setFont(QFont("Courier New", 6))
        self._term_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._term_clear_btn.setStyleSheet(_term_btn_ss)
        self._term_clear_btn.clicked.connect(self.terminal_clear)
        term_hdr_lay.addWidget(self._term_clear_btn)

        term_lay.addWidget(term_hdr)

        self._term_view = QTextEdit()
        self._term_view.setReadOnly(True)
        self._term_view.setFont(QFont("Cascadia Code", 8))
        self._term_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._term_view.setStyleSheet(f"""
            QTextEdit {{
                background: rgba(4, 5, 8, 220);
                color: {C.TEXT_MED};
                border: none;
                padding: 6px 8px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{ background: transparent; width: 5px; border: none; }}
            QScrollBar::handle:vertical {{ background: rgba(100,140,255,110); border-radius: 2px; min-height: 16px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; }}
        """)
        term_lay.addWidget(self._term_view, stretch=1)

        term_inp_row = QWidget()
        term_inp_row.setFixedHeight(20)
        term_inp_row.setStyleSheet("background: rgba(6,7,10,200); border-top: 1px solid rgba(100,140,255,15);")
        term_inp_lay = QHBoxLayout(term_inp_row)
        term_inp_lay.setContentsMargins(6, 0, 6, 0)
        term_inp_lay.setSpacing(4)

        self._term_cwd = ""
        self._term_prompt = QLabel("$")
        self._term_prompt.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._term_prompt.setStyleSheet("color: #648CFF; background: transparent;")
        self._term_prompt.setToolTip("Terminal working directory")
        term_inp_lay.addWidget(self._term_prompt)

        self._term_input = _TerminalInput()
        self._term_input.setFont(QFont("Cascadia Code", 8))
        self._term_input.setPlaceholderText("Type a command and press Enter... (↑/↓ history)")
        self._term_input.setStyleSheet(f"QLineEdit {{ background: transparent; color: {C.TEXT}; border: none; }}")
        self._term_input.submitted.connect(self._submit_terminal_cmd)
        term_inp_lay.addWidget(self._term_input, stretch=1)

        term_lay.addWidget(term_inp_row)
        self._splitter.addWidget(term_widget)

        # Splitter ratios: activity | code | preview | terminal
        self._splitter.setStretchFactor(0, 18)
        self._splitter.setStretchFactor(1, 30)
        self._splitter.setStretchFactor(2, 22)
        self._splitter.setStretchFactor(3, 30)
        self._splitter.setSizes([170, 280, 200, 280])

        root.addWidget(self._splitter, stretch=1)

    # ── Public API (called from KeysAIUI thread-safe signals) ──────────────

    def _dismiss(self):
        """Close the console (and the now-empty panel around it)."""
        self.hide()
        parent = self.parentWidget()
        if parent is not None:
            parent.hide()

    def begin(self, mode: str, project_name: str, project_path: str):
        """Start a new creation session."""
        self._mode = mode
        self._project_name = project_name
        self._project_path = project_path
        self.set_terminal_cwd(project_path)
        self._current_file = ""
        self._files.clear()
        self._file_contents.clear()
        self._writing_path = ""
        self._follow = True
        self._reveal_timer.stop()
        self._reveal_left = ""
        self._reveal_queue.clear()
        self._refresh_file_combo()
        self._events.clear()
        self._progress = 0.0
        self._started = True

        mode_labels = {
            "code": "LIVE CREATION",
            "ppt": "DOCUMENT CREATION",
            "excel": "WORKBOOK CREATION",
            "doc": "DOCUMENT CREATION",
            "txt": "TEXT CREATION",
        }
        self._title_lbl.setText("CROWN CODE · LIVE BUILD" if mode == "code"
                                else mode_labels.get(mode, "LIVE CREATION"))
        self._project_lbl.setText(f"{project_name}  ·  {project_path}")
        self._file_lbl.setText("")
        self._code_file_hdr.setText("  LIVE CODE")
        self._progress_bar.setValue(0)
        self._progress = 0.0
        self._phase = "planning"
        self._eta = 0.0
        self._began_at = time.time()
        self._refresh_phase()
        self._tick.start()

        # Clear previous
        self._code_viewer.clear()
        self._code_viewer.set_language_from_path("")
        self._code_lang_lbl.setText("TEXT")
        self._code_stats_lbl.setText("0 lines · 0 B")
        self._clear_events()
        self.terminal_clear()
        self.set_terminal_running(True, "ready")
        self.terminal_write("Crown Code Terminal Agent - commands run in " + (project_path or "") + "\n\n", "meta")

        self.show()

    def add_event(self, icon: str, text: str, file: str = None, color: str = None):
        """Add an event to the activity timeline."""
        if not self._started:
            return
        self._events.append({"icon": icon, "text": text, "file": file})

        ev = QWidget()
        ev.setStyleSheet("background: transparent; border-radius: 2px; padding: 1px 0;")
        ev_lay = QHBoxLayout(ev)
        ev_lay.setContentsMargins(4, 1, 4, 1)
        ev_lay.setSpacing(6)

        icon_lbl = QLabel(icon)
        icon_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        if color:
            icol = color
        elif icon == "✓":
            icol = C.GREEN
        elif icon == "→":
            icol = C.PRI
        elif icon == "!":
            icol = "#F0A500"
        elif icon == "✕":
            icol = C.RED
        else:
            icol = C.TEXT_DIM
        icon_lbl.setStyleSheet(f"color: {icol}; background: transparent; min-width: 14px;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
        ev_lay.addWidget(icon_lbl)

        text_lbl = QLabel(text)
        text_lbl.setFont(QFont("Courier New", 7))
        text_lbl.setWordWrap(True)
        text_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        ev_lay.addWidget(text_lbl, stretch=1)

        if file:
            file_btn = QPushButton(file.split("/")[-1])  # show basename
            file_btn.setFont(QFont("Courier New", 6))
            file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            file_btn.setStyleSheet(f"""
                QPushButton {{ color: {C.GREEN}; background: rgba(61,220,132,15); border: 1px solid rgba(61,220,132,40); border-radius: 2px; padding: 1px 4px; }}
                QPushButton:hover {{ background: rgba(61,220,132,35); border-color: {C.GREEN}; }}
            """)
            _f = file
            file_btn.clicked.connect(lambda checked=False, f=_f: self.fileClicked.emit(f))
            ev_lay.addWidget(file_btn)
        else:
            ev_lay.addSpacing(60)  # placeholder to keep alignment

        self._event_layout.insertWidget(self._event_layout.count() - 1, ev)  # before stretch
        self._event_widgets.append(ev)

        # Auto-scroll
        sb = self._event_scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_phase(self, name: str, pct: float = -1.0, eta: float = 0.0):
        """Show the current build phase, percent and ETA in the header."""
        self._phase = (name or "working").strip() or "working"
        if pct >= 0:
            self._progress = min(1.0, pct)
            self._progress_bar.setValue(int(self._progress * 100))
        self._eta = max(0.0, eta or 0.0)
        if not self._began_at:
            self._began_at = time.time()
        self._refresh_phase()

    def _refresh_phase(self):
        """Header chip: PHASE · 62% · 1m12s · ETA 45s."""
        if not self._started:
            return
        pct = int(round(self._progress * 100))
        parts = [self._phase.upper(), f"{pct}%"]
        if self._began_at:
            elapsed = max(0, int(time.time() - self._began_at))
            parts.append(f"{elapsed}s" if elapsed < 60 else f"{elapsed // 60}m{elapsed % 60:02d}s")
        if self._eta and self._progress < 0.999:
            parts.append("ETA " + (f"{int(self._eta)}s" if self._eta < 60
                                   else f"{int(self._eta) // 60}m{int(self._eta) % 60:02d}s"))
        self._phase_lbl.setText(" · ".join(parts))
        colour = {True: C.GREEN, False: C.PRI}.get(self._phase in ("done", "complete"), C.PRI)
        if self._phase in ("failed", "error"):
            colour = C.RED
        elif self._phase in ("verifying", "repairing"):
            colour = "#648CFF"
        self._phase_lbl.setStyleSheet(
            f"color: {colour}; background: rgba(217,182,80,18);"
            f" border: 1px solid {colour}55; border-radius: 3px; padding: 1px 6px;")
        if self._progress >= 0.999:
            self._tick.stop()

    def set_current_file(self, path: str):
        """Switch to the file the agent is writing.

        Ignored while the user has pinned an older file — the point of the
        file list is to read a previous file without being dragged back to
        whatever is being written now.
        """
        if not path:
            return
        self._writing_path = path
        if not self._follow and self._current_file:
            return
        if path == self._current_file:
            return
        self._display_path(path)

    def user_show_file(self, path: str):
        """The user picked a file: pin it, even if another is being written."""
        if not path:
            return
        self._follow = False
        self._display_path(path)

    def _set_view_labels(self, path: str):
        """Point the header/language labels and the file picker at `path`."""
        self._current_file = path
        basename = path.split("/")[-1] if path else ""
        self._file_lbl.setText(basename)
        self._code_file_hdr.setText(f"  {path}")
        language = self._code_viewer.set_language_from_path(path)
        self._code_lang_lbl.setText(_CODE_LANGUAGES.get(language, language.upper()))
        self._refresh_file_combo()

    def _display_path(self, path: str, *, reveal: bool = False):
        """Show `path` (labels, language, remembered content) in the viewer."""
        self._reveal_timer.stop()
        self._reveal_left = ""
        self._reveal_queue.clear()
        self._set_view_labels(path)
        content = self._file_contents.get(path, "")
        if reveal and content:
            self._start_reveal(path, content)
        else:
            self._code_viewer.set_text(content)
            self._update_code_stats()

    def _on_file_combo(self, idx: int):
        path = self._file_combo.itemData(idx) if idx >= 0 else ""
        if path:
            self.user_show_file(path)

    def _resume_follow(self):
        """Resume following the live file (LIVE button / after a pin)."""
        self._follow = True
        latest = self._files[-1]["path"] if self._files else ""
        if latest and latest != self._current_file:
            self._display_path(latest)
        else:
            self._refresh_file_combo()

    def _refresh_file_combo(self):
        combo = getattr(self, "_file_combo", None)
        if combo is None:
            return
        paths = [f["path"] for f in self._files]
        combo.blockSignals(True)
        if [combo.itemData(i) for i in range(combo.count())] != paths:
            combo.clear()
            for p in paths:
                combo.addItem(p.split("/")[-1], p)
        combo.setCurrentIndex(paths.index(self._current_file)
                              if self._current_file in paths else -1)
        combo.blockSignals(False)
        combo.setVisible(bool(paths))
        self._follow_btn.setVisible(bool(paths))
        colour = C.GREEN if self._follow else C.PRI
        self._follow_btn.setText("LIVE" if self._follow else "PINNED")
        self._follow_btn.setStyleSheet(
            f"QPushButton {{ color: {colour}; background: rgba(20,24,36,200);"
            f" border: 1px solid {colour}66; border-radius: 3px; padding: 0 5px; }}")

    def set_code(self, content: str):
        """A whole file arrived: remember it and type it into the viewer."""
        path = self._writing_path or self._current_file
        self._file_contents[path] = content
        if not self._follow:
            return
        if path != self._current_file:
            # Labels only: the content is about to be typed in, so showing it
            # whole first would flash the finished file before the reveal.
            self._reveal_timer.stop()
            self._reveal_left = ""
            self._set_view_labels(path)
        self._start_reveal(path, content)

    def _start_reveal(self, path: str, content: str):
        """Reveal a whole file progressively, like it is being typed."""
        self._reveal_path = path
        self._reveal_queue = [(path, content)]
        self._reveal_left = content
        self._reveal_step = max(60, len(content) // 150)   # ~2.5 s at 16 ms
        self._reveal_ticks = 0
        self._code_viewer.clear()
        self._reveal_timer.start()

    def _reveal_tick(self):
        if not self._reveal_left:
            self._reveal_timer.stop()
            self._update_code_stats()
            return
        chunk, self._reveal_left = (self._reveal_left[:self._reveal_step],
                                    self._reveal_left[self._reveal_step:])
        self._append_text(chunk)
        self._reveal_ticks += 1
        if self._reveal_ticks % 5 == 0 or not self._reveal_left:
            self._update_code_stats()

    def _update_code_stats(self):
        """Show the real size of the file being streamed."""
        text = self._code_viewer.toPlainText()
        lines = text.count("\n") + 1 if text else 0
        size = len(text.encode("utf-8", errors="replace"))
        if size >= 1024 * 1024:
            human = f"{size / (1024 * 1024):.1f} MB"
        elif size >= 1024:
            human = f"{size / 1024:.1f} KB"
        else:
            human = f"{size} B"
        self._code_stats_lbl.setText(f"{lines:,} lines · {human}")

    def _copy_code(self):
        """Copy the visible file and confirm on the button."""
        try:
            QApplication.clipboard().setText(self._code_viewer.toPlainText())
            self._code_copy_btn.setText("COPIED ✓")
            QTimer.singleShot(1200, lambda: self._code_copy_btn.setText("COPY"))
        except Exception:
            self._code_copy_btn.setText("FAILED")
            QTimer.singleShot(1200, lambda: self._code_copy_btn.setText("COPY"))

    def _toggle_wrap(self):
        wrapped = (self._code_viewer.lineWrapMode()
                   == QPlainTextEdit.LineWrapMode.WidgetWidth)
        new_mode = (QPlainTextEdit.LineWrapMode.NoWrap if wrapped
                    else QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._code_viewer.setLineWrapMode(new_mode)
        self._code_wrap_btn.setChecked(not wrapped)
        self._code_wrap_btn.setText("WRAP" if wrapped else "NO WRAP")

    def _append_text(self, chunk: str):
        """Append to the viewer itself (no bookkeeping)."""
        cur = self._code_viewer.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText(chunk)
        self._code_viewer.setTextCursor(cur)
        self._code_viewer.ensureCursorVisible()

    def append_code(self, chunk: str):
        """Append a chunk of code the agent streamed (true live output)."""
        if not chunk:
            return
        path = self._writing_path or self._current_file
        self._file_contents[path] = self._file_contents.get(path, "") + chunk
        if not self._follow:
            return
        self._append_text(chunk)
        self._update_code_stats()

    def set_progress(self, pct: float):
        """Update progress 0.0–1.0 (and the phase chip's percentage)."""
        self._progress = max(0.0, min(1.0, pct))
        self._progress_bar.setValue(int(self._progress * 100))
        self._refresh_phase()

    def add_file(self, path: str, lines: int = 0, status: str = "done"):
        """Register a file in the session's file list (deduplicated)."""
        if not path:
            return
        for f in self._files:
            if f["path"] == path:
                f["lines"] = max(int(f.get("lines") or 0), int(lines or 0))
                f["status"] = status or f.get("status", "done")
                break
        else:
            self._files.append({"path": path, "lines": lines, "status": status})
        self._refresh_file_combo()

    def error(self, text: str):
        """Show an error event."""
        self.set_phase("failed", self._progress, 0.0)
        self.add_event("✕", text, color=C.RED)

    def complete(self, summary: str = ""):
        """Mark creation as complete."""
        self._progress = 1.0
        self._progress_bar.setValue(100)
        self.set_phase("done", 1.0, 0.0)
        self.add_event("✓", summary or "Creation complete", color=C.GREEN)
        self._file_lbl.setText("✓ DONE")
        self._file_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent;")
        self.set_terminal_running(False, "done")

    def reset(self):
        """Clear everything and hide."""
        self._started = False
        self._mode = None
        self._project_name = ""
        self._project_path = ""
        self._current_file = ""
        self._files.clear()
        self._file_contents.clear()
        self._writing_path = ""
        self._follow = True
        self._reveal_timer.stop()
        self._reveal_left = ""
        self._reveal_queue.clear()
        self._refresh_file_combo()
        self._events.clear()
        self._progress = 0.0
        self._phase = "idle"
        self._began_at = 0.0
        self._tick.stop()
        self._code_viewer.clear()
        self._code_viewer.set_language_from_path("")
        self._code_lang_lbl.setText("TEXT")
        self._code_stats_lbl.setText("0 lines · 0 B")
        self._clear_events()
        self._progress_bar.setValue(0)
        self._file_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent;")
        self.terminal_clear()
        self.set_terminal_running(False, "idle")
        self.hide()

    def _clear_events(self):
        """Remove all event widgets from the timeline."""
        for w in self._event_widgets:
            self._event_layout.removeWidget(w)
            w.deleteLater()
        self._event_widgets.clear()

    # ── Embedded terminal API (Crown Code) ─────────────────────────────────

    def _submit_terminal_cmd(self, cmd: str = ""):
        """User pressed Enter in the terminal input — forward the command."""
        cmd = (cmd or self._term_input.text()).strip()
        if not cmd:
            return
        self._term_input.clear()
        self.terminal_write(f"$ {cmd}\n", "stdin")
        self.terminalCommandSubmitted.emit(cmd)

    def _refresh_coding_models(self):
        """Populate the model picker from the configured + installed Ollama
        models, off the UI thread (the Ollama query is a network call)."""
        self._loading_models = True
        try:
            from core.crown_bridge import load_config
            current = (load_config().get("model") or "").strip()
        except Exception:
            current = ""
        self._model_combo.clear()
        self._model_combo.addItem("auto")
        self._loading_models = False

        def _work():
            try:
                from core.crown_bridge import list_models
                names = list_models() or []
            except Exception:
                names = []
            self._installed_coding_models = names   # used by the auto-pick sync

            def _apply():
                self._loading_models = True
                for n in names:
                    self._model_combo.addItem(n)
                if current and self._model_combo.findText(current) >= 0:
                    self._model_combo.setCurrentText(current)
                self._loading_models = False

            QTimer.singleShot(0, _apply)

        threading.Thread(target=_work, daemon=True, name="crown-model-list").start()

    def _on_coding_model_changed(self, text: str):
        """Persist the chosen coding model to config/crown_code.json AND mirror
        it into the AI Provider settings (api_keys.json task_models.dev_agent),
        so the Dev Agent row always shows exactly what Crown Code runs."""
        if getattr(self, "_loading_models", False):
            return
        try:
            from core.crown_bridge import save_config, pick_model
            model = "" if text == "auto" else text
            save_config({"model": model})
            # Mirror into the AI Provider settings — "auto" resolves to the
            # same pick the bridge would make, so the two can never disagree.
            try:
                from core.api_config import set_task_model
                installed = getattr(self, "_installed_coding_models", None) or []
                task_model = model or (pick_model(installed) if installed else "")
                if task_model:
                    set_task_model("dev_agent", "ollama", task_model)
            except Exception:
                pass
            self.terminal_write(f"[model] Crown Code will use: {text}\n", "meta")
        except Exception as e:
            self.terminal_write(f"[model] could not save choice: {e}\n", "stderr")

    def set_terminal_cwd(self, path: str):
        """Show the terminal's working directory in the prompt."""
        self._term_cwd = path or ""
        name = os.path.basename(self._term_cwd.rstrip("\\/")) if self._term_cwd else ""
        self._term_prompt.setText(f"{name} $" if name else "$")
        self._term_prompt.setToolTip(self._term_cwd or "Terminal working directory")

    def terminal_write(self, chunk: str, stream: str = "stdout"):
        """Append streamed output. stream: stdout | stderr | meta | stdin.

        Understands ANSI colour escapes and turns a trailing `[exit N]` into a
        coloured exit-code chip (green on 0, red otherwise).
        """
        if not chunk:
            return
        base_color = {
            "stdout": C.TEXT_MED,
            "stderr": "#F0A500",
            "meta": C.TEXT_DIM,
            "stdin": "#648CFF",
        }.get(stream, C.TEXT_MED)

        view = self._term_view
        cur = view.textCursor()
        cur.movePosition(cur.MoveOperation.End)

        for part, color, bold in _terminal_runs(chunk, base_color):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            fmt.setFontWeight(QFont.Weight.Bold.value if bold
                              else QFont.Weight.Normal.value)
            cur.insertText(part, fmt)

        view.setTextCursor(cur)
        view.ensureCursorVisible()
        # Cap memory for very chatty processes.
        if view.document().blockCount() > 4000:
            trim = view.textCursor()
            trim.movePosition(trim.MoveOperation.Start)
            trim.movePosition(trim.MoveOperation.Down, trim.MoveMode.KeepAnchor, 2000)
            trim.removeSelectedText()

    def terminal_clear(self):
        """Clear the terminal output."""
        self._term_view.clear()

    def set_terminal_running(self, running: bool, label: str = ""):
        """Update the running-state indicator chip."""
        self._term_run_lbl.setText(label or ("running" if running else "idle"))
        self._term_run_lbl.setStyleSheet(
            f"color: {C.GREEN if running else C.TEXT_DIM}; background: transparent;")

    # ── Web Preview API ─────────────────────────────────────────────────────

    def show_preview(self, url: str = ""):
        """Retired: previews are shown in the Research Browser, not here.

        Kept as a no-op so any older caller cannot resurrect a second browser
        inside the creation workspace. ``ui.MainWindow._on_cr_preview`` is the
        path that actually opens a built page.
        """
        return

    def hide_preview(self):
        """Hide the web preview panel."""
        self._preview_widget.hide()
        self._open_browser_btn.hide()
        self._preview_nav.hide()
        # Re-balance splitter to 2-panel
        self._splitter.setSizes([200, 360, 0, 280])

    def load_preview(self, url: str):
        """Load a URL in the web preview."""
        if not _HAS_WEBENGINE:
            return
        self._current_preview_url = url
        self._preview_url_bar.setText(url)
        self._web_view.setUrl(QUrl(url))
        self._preview_widget.show()
        self._open_browser_btn.show()
        self._preview_nav.show()
        self._splitter.setSizes([150, 260, 240, 250])
        self.add_event("🌐", f"Preview opened: {url}", color="#648CFF")

    # ── Preview nav handlers ────────────────────────────────────────────────

    def _preview_back(self):
        """Navigate back in the web preview."""
        if _HAS_WEBENGINE and self._web_view.history().canGoBack():
            self._web_view.back()

    def _preview_forward(self):
        """Navigate forward in the web preview."""
        if _HAS_WEBENGINE and self._web_view.history().canGoForward():
            self._web_view.forward()

    def _preview_refresh(self):
        """Refresh the current preview page."""
        if _HAS_WEBENGINE:
            self._web_view.reload()

    def _on_preview_url_changed(self, url: QUrl):
        """Update URL bar and nav button state when the page navigates."""
        url_str = url.toString()
        self._current_preview_url = url_str
        self._preview_url_bar.setText(url_str)
        self._update_nav_state()

    def _update_nav_state(self):
        """Enable/disable back/forward buttons based on history."""
        if not _HAS_WEBENGINE:
            return
        hist = self._web_view.history()
        self._prev_back_btn.setEnabled(hist.canGoBack())
        self._prev_fwd_btn.setEnabled(hist.canGoForward())

    def _on_preview_load_started(self):
        """Show spinner when page starts loading."""
        if _HAS_WEBENGINE:
            self._preview_stack.setCurrentIndex(1)  # spinner

    def _on_preview_load_finished(self, ok: bool):
        """Hide spinner when page finishes loading."""
        if _HAS_WEBENGINE:
            self._preview_stack.setCurrentIndex(0)  # web view
            if not ok:
                self.add_event("!", "Preview failed to load", color="#F0A500")

    def refresh_preview(self):
        """Refresh the current preview URL."""
        if not _HAS_WEBENGINE or not self._current_preview_url:
            return
        self._web_view.setUrl(QUrl(self._current_preview_url))

    def _open_in_browser(self):
        """Open the current preview URL in the default browser."""
        if self._current_preview_url:
            import webbrowser
            webbrowser.open(self._current_preview_url)


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str, str, str, str)  # provider, api_key, model, base_url, os_name

    _COMBO_SS = """
        QComboBox {{ background: #000d12; color: {C.TEXT}; border: 1px solid {C.BORDER};
                      border-radius: 3px; padding: 3px 6px; }}
        QComboBox::drop-down {{ border: none; }}
        QComboBox QAbstractItemView {{ background: #0B0E14; color: {C.TEXT};
                      selection-background-color: {C.PRI_GHO}; }}
    """

    _INPUT_SS = """
        QLineEdit {{
            background: #000d12; color: {C.TEXT};
            border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px 8px;
        }}
        QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
    """

    def __init__(self, parent=None, initial: dict | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(0, 6, 10, 248);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        initial = initial or {}
        self._initial = initial
        detected = {"darwin": "mac", "windows": "windows"}.get(_OS.lower(), "linux")
        self._sel_os = initial.get("os_system") or detected

        from core.model_catalog import PROVIDER_ORDER, provider_info

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 20, 26, 20)
        layout.setSpacing(7)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("◈  AI PROVIDER CONFIGURATION", 12, True))
        layout.addWidget(_lbl("Pick a provider, add its API key, choose a model.", 8,
                              color=C.PRI_DIM))

        # ── provider ──
        layout.addWidget(_lbl("PROVIDER", 8, color=C.TEXT_DIM,
                              align=Qt.AlignmentFlag.AlignLeft))
        self._provider_combo = QComboBox()
        self._provider_ids = list(PROVIDER_ORDER)
        for pid in self._provider_ids:
            self._provider_combo.addItem(provider_info(pid)["label"], pid)
        cur_provider = initial.get("llm_provider") or "gemini"
        idx = self._provider_combo.findData(cur_provider)
        if idx >= 0:
            self._provider_combo.setCurrentIndex(idx)
        self._provider_combo.setFont(QFont("Courier New", 9))
        self._provider_combo.setStyleSheet(self._COMBO_SS.format(C=C))
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        layout.addWidget(self._provider_combo)

        # ── API key ──
        self._key_lbl = _lbl("API KEY", 8, color=C.TEXT_DIM,
                             align=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._key_lbl)
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setFont(QFont("Courier New", 10))
        self._key_input.setFixedHeight(30)
        self._key_input.setStyleSheet(self._INPUT_SS.format(C=C))
        layout.addWidget(self._key_input)

        # ── model ──
        layout.addWidget(_lbl("MODEL", 8, color=C.TEXT_DIM,
                              align=Qt.AlignmentFlag.AlignLeft))
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._model_combo.setFont(QFont("Courier New", 9))
        self._model_combo.setStyleSheet(self._COMBO_SS.format(C=C))
        layout.addWidget(self._model_combo)

        # ── base url ──
        self._url_lbl = _lbl("BASE URL", 8, color=C.TEXT_DIM,
                             align=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._url_lbl)
        self._url_input = QLineEdit()
        self._url_input.setFont(QFont("Courier New", 9))
        self._url_input.setFixedHeight(28)
        self._url_input.setStyleSheet(self._INPUT_SS.format(C=C))
        layout.addWidget(self._url_input)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};")
        layout.addWidget(sep)

        # ── OS (kept from the original first-boot flow) ──
        os_row = QHBoxLayout(); os_row.setSpacing(6)
        os_row.addWidget(_lbl("OS", 8, color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft))
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows", "⊞  Windows"), ("mac", "  macOS"),
                           ("linux", "🐧  Linux")]:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            btn.setFixedHeight(26)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        os_row.addStretch()
        layout.addLayout(os_row)
        self._sel(self._sel_os)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};")
        layout.addWidget(sep2)

        # ── Active providers status panel ──
        self._api_status_panel = self._build_api_status()
        layout.addWidget(self._api_status_panel)
        # Kick off reachability checks in background
        QTimer.singleShot(300, self._refresh_api_status)

        # ── Task model assignments ──
        sep3 = QFrame(); sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet(f"color: {C.BORDER};")
        layout.addWidget(sep3)
        self._build_task_models(layout)

        # ── status + actions ──
        self._status = _lbl("", 8, color=C.ACC2)
        layout.addWidget(self._status)

        btns = QHBoxLayout(); btns.setSpacing(6)
        reset_btn = QPushButton("⟲  RESET API KEY")
        reset_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        reset_btn.setFixedHeight(34)
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.RED};
                border: 1px solid #7a2f36; border-radius: 3px;
            }}
            QPushButton:hover {{ background: rgba(229, 72, 77, 30); border: 1px solid {C.RED}; }}
        """)
        reset_btn.clicked.connect(self._reset_key)
        btns.addWidget(reset_btn)

        init_btn = QPushButton("▸  INITIALISE SYSTEMS")
        init_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(34)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        init_btn.clicked.connect(self._submit)
        btns.addWidget(init_btn)
        layout.addLayout(btns)

        # Prefill from the current config, then sync the UI to the provider.
        self._url_input.setText(initial.get("llm_url") or "")
        self._on_provider_changed()
        if initial.get("llm_model"):
            self._model_combo.setCurrentText(str(initial["llm_model"]))

    # ── provider-dependent UI ────────────────────────────────────────────
    def _on_provider_changed(self):
        from core.model_catalog import provider_info
        pid = self._provider_combo.currentData() or "gemini"
        info = provider_info(pid)
        self._key_lbl.setText("API KEY" if info.get("needs_key")
                              else "API KEY (NOT NEEDED)")
        self._key_input.setPlaceholderText(info.get("placeholder", ""))
        self._key_input.setEnabled(bool(info.get("needs_key")))
        models = info.get("models", [])

        # ── Ollama: auto-launch + detect installed models ─────────────────
        if pid == "ollama":
            self._status.setText("Checking Ollama...")
            threading.Thread(target=self._ollama_detect,
                             args=(info.get("base_url", ""),),
                             daemon=True).start()
            return  # _ollama_detect will populate the model combo

        current = self._model_combo.currentText()
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        self._model_combo.addItems(models)
        if current and current in models:
            self._model_combo.setCurrentText(current)
        self._model_combo.blockSignals(False)
        url = info.get("base_url", "")
        local = pid in ("ollama", "custom")
        self._url_lbl.setText("BASE URL" if local else "ENDPOINT (DEFAULT)")
        self._url_input.setEnabled(local)
        if local:
            self._url_input.setPlaceholderText(url or "http://localhost:11434")
            if not self._url_input.text().strip():
                self._url_input.setText(url)
        else:
            # hosted provider: always use its default endpoint — a stale
            # custom URL from another provider must never leak into this one.
            self._url_input.setText("")
            self._url_input.setPlaceholderText(url or "uses provider default")

    # ── Ollama auto-detect ──────────────────────────────────────────────
    def _ollama_detect(self, base_url: str):
        """Background: ensure Ollama is running, detect models, update UI."""
        from core.model_catalog import (ensure_ollama_running,
                                        detect_ollama_models, provider_info)
        info = provider_info("ollama")
        url = base_url or info.get("base_url", "")

        # Try to start Ollama if not running
        running = ensure_ollama_running(url)
        if not running:
            self._ollama_done([], "Ollama not found — install from ollama.com")
            return

        models = detect_ollama_models(url)
        if not models:
            self._ollama_done([], "Ollama running but no models installed.")
            return

        self._ollama_done(models, f"Ollama running — {len(models)} model{'s' if len(models) != 1 else ''} detected.")

    def _ollama_done(self, models: list[str], status: str):
        """Update the model combo + status on the GUI thread."""
        current = self._model_combo.currentText()
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        self._model_combo.addItems(models)
        if current and current in models:
            self._model_combo.setCurrentText(current)
        elif models:
            self._model_combo.setCurrentText(models[0])
        self._model_combo.blockSignals(False)
        self._url_lbl.setText("BASE URL")
        self._url_input.setEnabled(True)
        self._url_input.setPlaceholderText("http://localhost:11434")
        if not self._url_input.text().strip():
            self._url_input.setText("http://localhost:11434")
        self._status.setText(status[:120])
        # Refresh the API status panel
        self._refresh_api_status()

    # ── API status panel ────────────────────────────────────────────────
    def _build_api_status(self) -> QWidget:
        """Build the provider status panel (shown below OS selector)."""
        from core.model_catalog import provider_info, PROVIDER_ORDER, needs_key
        from core import api_config

        panel = QWidget()
        panel.setStyleSheet(
            "background: rgba(17, 17, 17, 55); border: 1px solid rgba(255, 215, 0, 45);"
            " border-radius: 4px;"
        )
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(2)

        hdr = QLabel("▸ ACTIVE PROVIDERS")
        hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent; padding: 2px 0;")
        lay.addWidget(hdr)

        self._api_rows: dict[str, QLabel] = {}
        cfg = api_config.load_config()
        for pid in PROVIDER_ORDER:
            info = provider_info(pid)
            key_field = info.get("key_field")
            has_key = bool(cfg.get(key_field)) if key_field else False
            label = info.get("label", pid)
            if needs_key(pid):
                badge = "● KEY SET" if has_key else "○ NO KEY"
                badge_col = C.GREEN if has_key else C.TEXT_DIM
            else:
                badge = "● KEYLESS"
                badge_col = C.GREEN

            row = QLabel(f"  {label:<24s}  {badge}")
            row.setFont(QFont("Courier New", 7))
            row.setStyleSheet(f"color: {badge_col}; background: transparent; padding: 1px 0;")
            lay.addWidget(row)
            self._api_rows[pid] = row

        return panel

    def _refresh_api_status(self):
        """Background: ping each provider and update the status rows."""
        threading.Thread(target=self._api_status_worker, daemon=True).start()

    def _api_status_worker(self):
        """Worker: check reachability of all providers, update labels."""
        from core.model_catalog import (provider_info, PROVIDER_ORDER,
                                        needs_key, provider_reachable)
        from core import api_config
        cfg = api_config.load_config()

        for pid in PROVIDER_ORDER:
            info = provider_info(pid)
            key_field = info.get("key_field")
            api_key = str(cfg.get(key_field, "")) if key_field else ""
            has_key = bool(api_key.strip())
            label = info.get("label", pid)

            reachable = False
            if has_key or not needs_key(pid):
                reachable = provider_reachable(pid, api_key)

            if needs_key(pid):
                if has_key and reachable:
                    badge = "● KEY SET  ● ONLINE"
                    col = C.GREEN
                elif has_key and not reachable:
                    badge = "● KEY SET  ○ OFFLINE"
                    col = C.ACC
                else:
                    badge = "○ NO KEY"
                    col = C.TEXT_DIM
            else:
                if reachable:
                    badge = "● RUNNING"
                    col = C.GREEN
                else:
                    badge = "○ NOT RUNNING"
                    col = C.TEXT_DIM

            row = self._api_rows.get(pid)
            if row is not None:
                row.setText(f"  {label:<24s}  {badge}")
                row.setStyleSheet(f"color: {col}; background: transparent; padding: 1px 0;")

    # ── Task model assignments ─────────────────────────────────────────
    def _build_task_models(self, layout: QVBoxLayout):
        """Add per-task model assignment dropdowns to the setup overlay."""
        from core.model_catalog import PROVIDER_ORDER, provider_info
        from core.api_config import TASK_NAMES, TASK_LABELS, get_task_model

        def _lbl2(txt, font_size=8, color=C.TEXT_DIM, bold=False,
                  align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl2("◈  TASK MODEL ASSIGNMENTS", 10, True))
        layout.addWidget(_lbl2("Assign a specific provider + model for each task.",
                              7, color=C.PRI_DIM))

        self._task_combos: dict[str, tuple[QComboBox, QComboBox]] = {}
        task_models_cfg = self._initial.get("task_models") or {}

        for task_id in TASK_NAMES:
            label = TASK_LABELS.get(task_id, task_id)
            cur = get_task_model(task_id)
            cur_provider = cur.get("provider", "gemini")
            cur_model = cur.get("model", "gemini-2.5-flash")
            overridden = task_id in (task_models_cfg or {})

            row_w = QWidget()
            row_w.setStyleSheet("background: transparent;")
            row_lay = QHBoxLayout(row_w)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(4)

            # Task label (with indicator if overridden)
            indicator = "●" if overridden else "○"
            ind_col = C.GREEN if overridden else C.TEXT_DIM
            task_lbl = QLabel(f"{indicator} {label}")
            task_lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            task_lbl.setFixedWidth(150)
            task_lbl.setStyleSheet(f"color: {ind_col}; background: transparent;")
            row_lay.addWidget(task_lbl)

            # Provider dropdown
            prov_combo = QComboBox()
            prov_combo.setFont(QFont("Courier New", 7))
            prov_combo.setStyleSheet(self._COMBO_SS.format(C=C))
            prov_combo.setFixedHeight(22)
            for pid in PROVIDER_ORDER:
                prov_combo.addItem(provider_info(pid)["label"], pid)
            idx = prov_combo.findData(cur_provider)
            if idx >= 0:
                prov_combo.setCurrentIndex(idx)
            row_lay.addWidget(prov_combo, 1)

            # Model dropdown
            model_combo = QComboBox()
            model_combo.setEditable(True)
            model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            model_combo.setFont(QFont("Courier New", 7))
            model_combo.setStyleSheet(self._COMBO_SS.format(C=C))
            model_combo.setFixedHeight(22)
            info = provider_info(cur_provider)
            model_combo.addItems(info.get("models", []))
            if cur_model:
                model_combo.setCurrentText(cur_model)
            row_lay.addWidget(model_combo, 2)

            # Clear button (revert to default)
            clear_btn = QPushButton("✕")
            clear_btn.setFixedSize(20, 20)
            clear_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            clear_btn.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {C.RED};
                    border: 1px solid {C.BORDER}; border-radius: 2px; }}
                QPushButton:hover {{ background: rgba(229, 72, 77, 40); border: 1px solid {C.RED}; }}
            """)
            clear_btn.setToolTip(f"Reset {label} to default (uses main provider)")
            row_lay.addWidget(clear_btn)

            layout.addWidget(row_w)
            self._task_combos[task_id] = (prov_combo, model_combo)

            # Wire up: when provider changes, update model list
            def _make_handler(mc, tc, tid):
                def _handler():
                    pid = tc.currentData() or "gemini"
                    inf = provider_info(pid)
                    cur_m = mc.currentText()
                    mc.blockSignals(True)
                    mc.clear()
                    mc.addItems(inf.get("models", []))
                    if cur_m and cur_m in [mc.itemText(i) for i in range(mc.count())]:
                        mc.setCurrentText(cur_m)
                    elif mc.count() > 0:
                        mc.setCurrentText(mc.itemText(0))
                    mc.blockSignals(False)
                    # For Ollama: auto-detect installed models in background
                    if pid == "ollama":
                        def _detect():
                            try:
                                from core.model_catalog import detect_ollama_models
                                base = inf.get("base_url", "http://localhost:11434")
                                models = detect_ollama_models(base)
                                if models:
                                    def _update():
                                        mc.blockSignals(True)
                                        prev = mc.currentText()
                                        mc.clear()
                                        mc.addItems(models)
                                        if prev in models:
                                            mc.setCurrentText(prev)
                                        elif models:
                                            mc.setCurrentText(models[0])
                                        mc.blockSignals(False)
                                    QTimer.singleShot(0, _update)
                            except Exception:
                                pass
                        threading.Thread(target=_detect, daemon=True).start()
                    # Update indicator
                    row = mc.parent()
                    if row:
                        task_row = row.parent()
                        if task_row:
                            lbls = task_row.findChildren(QLabel)
                            for l in lbls:
                                if tid in l.text().lower() or (TASK_LABELS.get(tid, "") in l.text()):
                                    l.setText(f"● {TASK_LABELS.get(tid, tid)}")
                                    l.setStyleSheet(f"color: {C.GREEN}; background: transparent;")
                return _handler

            prov_combo.currentIndexChanged.connect(
                _make_handler(model_combo, prov_combo, task_id))

            # Wire up clear button — reset to the MAIN provider/model above,
            # which is exactly what get_task_model() falls back to (so the row
            # never claims a default that differs from what will really run).
            def _make_clear(tc, mc, tid, provOrd=PROVIDER_ORDER, pi=provider_info):
                def _clear():
                    main_prov = self._provider_combo.currentData() or "gemini"
                    main_model = (self._model_combo.currentText().strip()
                                  or pi(main_prov).get("default_model", ""))
                    idx = tc.findData(main_prov)
                    if idx >= 0:
                        tc.setCurrentIndex(idx)
                    mc.setCurrentText(main_model)
                    # Update indicator to show "default"
                    row = mc.parent()
                    if row:
                        task_row = row.parent()
                        if task_row:
                            lbls = task_row.findChildren(QLabel)
                            for l in lbls:
                                if TASK_LABELS.get(tid, "") in l.text():
                                    l.setText(f"○ {TASK_LABELS.get(tid, tid)}")
                                    l.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
                return _clear

            clear_btn.clicked.connect(
                _make_clear(prov_combo, model_combo, task_id))

    # ── reset ──
    def _reset_key(self):
        from core import api_config
        pid = self._provider_combo.currentData() or "gemini"
        self._key_input.clear()
        try:
            msg = api_config.reset_api_key(pid)
        except Exception as e:
            msg = f"Reset failed: {e}"
        self._status.setText(msg[:110])

    # ── OS selector (original flow) ─────────────────────────────────────
    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows": (C.PRI, "#001a22"), "mac": (C.ACC2, "#1a1400"),
               "linux": (C.GREEN, "#001a0d")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #000d12; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _submit(self):
        from core import api_config
        from core.model_catalog import provider_info
        pid = self._provider_combo.currentData() or "gemini"
        info = provider_info(pid)
        key = self._key_input.text().strip()
        if info.get("needs_key") and not key and not api_config.has_api_key(pid):
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            self._status.setText("This provider needs an API key.")
            return
        model = (self._model_combo.currentText().strip()
                 or info.get("default_model", ""))
        url = self._url_input.text().strip()

        # Save per-task model assignments
        from core.api_config import set_task_model, TASK_NAMES
        for task_id in TASK_NAMES:
            if task_id in self._task_combos:
                prov_c, model_c = self._task_combos[task_id]
                t_prov = prov_c.currentData() or "gemini"
                t_model = model_c.currentText().strip() or ""
                # Check if this differs from the default provider/model
                default_prov = pid
                default_model = model
                if t_prov != default_prov or (t_model and t_model != default_model):
                    set_task_model(task_id, t_prov, t_model)
                else:
                    # Revert to default (clear the override)
                    set_task_model(task_id, "", "")

        # The Dev Agent row IS Crown Code's runtime config — write it straight
        # into config/crown_code.json too, so the setting and the behaviour
        # are the same thing (never a different model in the background).
        if "dev_agent" in self._task_combos:
            prov_c, model_c = self._task_combos["dev_agent"]
            try:
                from core.crown_bridge import save_config as _save_crown_cfg
                _save_crown_cfg({
                    "provider": (prov_c.currentData() or "ollama"),
                    "model": model_c.currentText().strip(),
                })
            except Exception:
                pass

        self.done.emit(pid, key, model, url, self._sel_os)


class AgentSettingsOverlay(QWidget):
    """Agent Control settings: humour level, dark humour, professional mode,
    retry limit, confirmations, overlay — all without touching the AI provider."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            AgentSettingsOverlay {{
                background: rgba(0, 6, 10, 246);
                border: 1px solid {C.BORDER_B};
                border-radius: 8px;
            }}
        """)
        self.setFixedWidth(380)

        s = get_agent_settings()
        snap = s.snapshot()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        def _lbl(txt, size=8, color=C.TEXT_DIM, bold=False):
            w = QLabel(txt)
            w.setFont(QFont("Courier New", size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("◈  AGENT CONTROL SETTINGS", 11, C.PRI, True))
        layout.addSpacing(4)

        # humour level
        layout.addWidget(_lbl("HUMOUR LEVEL"))
        self._humour_combo = QComboBox()
        self._humour_combo.addItems(["OFF", "LOW", "MEDIUM", "HIGH"])
        self._humour_combo.setCurrentText(str(snap.get("humour_level", "MEDIUM")))
        self._humour_combo.setFont(QFont("Courier New", 9))
        self._humour_combo.setStyleSheet(f"""
            QComboBox {{ background: #000d12; color: {C.TEXT}; border: 1px solid {C.BORDER};
                          border-radius: 3px; padding: 4px 8px; }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{ background: #0B0E14; color: {C.TEXT};
                          selection-background-color: {C.PRI_GHO}; }}
        """)
        layout.addWidget(self._humour_combo)

        def _check(text, key):
            cb = QCheckBox(text)
            cb.setChecked(bool(snap.get(key, False)))
            cb.setFont(QFont("Courier New", 8))
            cb.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            layout.addWidget(cb)
            return cb

        self._dark_cb = _check("Dark humour  (situational dev humour only)", "dark_humour")
        self._pro_cb = _check("Professional mode  (no unnecessary jokes)", "professional_mode")
        self._confirm_cb = _check("Confirm high-impact actions (send/delete/submit)", "confirm_high_impact")
        self._overlay_cb = _check("Show the animated gold control border", "overlay_enabled")

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(_lbl("RETRY LIMIT"))
        self._retry_spin = QSpinBox()
        self._retry_spin.setRange(0, 10)
        self._retry_spin.setValue(int(snap.get("retry_limit", 3)))
        self._retry_spin.setFont(QFont("Courier New", 9))
        self._retry_spin.setStyleSheet(
            f"QSpinBox {{ background: #000d12; color: {C.TEXT}; border: 1px solid {C.BORDER};"
            f" border-radius: 3px; padding: 2px 6px; }}"
            f" QSpinBox::up-button, QSpinBox::down-button {{ border: none; }}")
        row.addWidget(self._retry_spin)
        row.addStretch()
        layout.addLayout(row)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};")
        layout.addWidget(sep)

        save_btn = QPushButton("▸  SAVE SETTINGS")
        save_btn.setFixedHeight(30)
        save_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)

    def _save(self):
        s = get_agent_settings()
        s.set("humour_level", self._humour_combo.currentText())
        s.set("dark_humour", self._dark_cb.isChecked())
        s.set("professional_mode", self._pro_cb.isChecked())
        s.set("confirm_high_impact", self._confirm_cb.isChecked())
        s.set("overlay_enabled", self._overlay_cb.isChecked())
        s.set("retry_limit", self._retry_spin.value())
        self.hide()
        try:
            self.parent()._log.append_log("SYS: Agent control settings saved.")
        except Exception:
            pass


class GoogleAccountsOverlay(QWidget):
    """Proper UI for managing MULTIPLE Google accounts: add (browser
    sign-in with Google's account picker), switch the active account, remove
    accounts and sign out. Contacts & email then work across all of them."""

    _result_sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            GoogleAccountsOverlay {{
                background: rgba(0, 6, 10, 248);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.on_change = None   # callable(str) — notify the main window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        hdr = QHBoxLayout()
        hdr.addWidget(_lbl("◈  GOOGLE ACCOUNTS", 11, True,
                           align=Qt.AlignmentFlag.AlignLeft))
        # live account-count badge in the header
        self._count_lbl = _lbl("", 8, color=C.PRI_DIM,
                               align=Qt.AlignmentFlag.AlignLeft)
        self._count_lbl.setContentsMargins(6, 0, 0, 0)
        hdr.addWidget(self._count_lbl)
        hdr.addStretch()
        refresh_btn = QPushButton("⟳")
        refresh_btn.setFixedSize(20, 20)
        refresh_btn.setFont(QFont("Courier New", 10))
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setToolTip("Refresh account list")
        refresh_btn.setStyleSheet(
            f"color: {C.PRI_DIM}; background: transparent; border: none;"
        )
        refresh_btn.clicked.connect(self.refresh)
        hdr.addWidget(refresh_btn)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setFont(QFont("Courier New", 9))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        close_btn.clicked.connect(self.close)
        hdr.addWidget(close_btn)
        layout.addLayout(hdr)

        # line 1: which account is ACTIVE (drives contacts/calls/email)
        self._active_lbl = _lbl("", 8, color=C.PRI,
                                align=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._active_lbl)
        # line 2: transient operation feedback (switched / removed / signed in…)
        self._status = _lbl("", 8, color=C.ACC2, align=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            " QScrollBar:vertical { background: transparent; width: 4px; border: none; }"
            " QScrollBar::handle:vertical { background: rgba(217,182,80,110); border-radius: 2px; }"
        )
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list = QVBoxLayout(self._list_widget)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(6)
        self._list.addStretch()
        scroll.setWidget(self._list_widget)
        layout.addWidget(scroll, stretch=1)

        self._add_btn = QPushButton("＋  ADD ACCOUNT  (opens Google sign-in)")
        self._add_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._add_btn.setFixedHeight(32)
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
            QPushButton:disabled {{ color: {C.TEXT_DIM}; border-color: {C.BORDER}; }}
        """)
        self._add_btn.clicked.connect(self._add_account)
        layout.addWidget(self._add_btn)

        self._result_sig.connect(self._on_result)
        self.refresh()

    # ── account list ────────────────────────────────────────────────────
    def refresh(self):
        from core import firebase_client as fb
        load_error = ""
        try:
            accounts = fb.get_accounts()
        except Exception as e:
            accounts = []
            load_error = str(e)[:100]
            self._status.setText(f"Could not load accounts: {load_error}")
        # header badge: live count (— when the load itself failed)
        n = len(accounts)
        if load_error:
            self._count_lbl.setText("—")
        else:
            self._count_lbl.setText(
                f"{n} ACCOUNT{'S' if n != 1 else ''}" if n else "NO ACCOUNTS"
            )
        # active-account line (separate from transient op feedback)
        active = next((a for a in accounts if a.get("active")), None)
        if active:
            who = active.get("display_name") or active.get("email") or ""
            self._active_lbl.setText(
                f"ACTIVE  ▶  {who}" + (f"  ({active.get('email')})" if who != active.get("email") else "")
            )
        else:
            self._active_lbl.setText("NO ACTIVE ACCOUNT")
        while self._list.count() > 1:      # keep the trailing stretch
            item = self._list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not accounts:
            lbl = QLabel("No Google accounts signed in yet.\n"
                         "Tap ADD ACCOUNT to sign in — Google's picker lets you\n"
                         "add several. The ACTIVE account drives contacts, calls\n"
                         "and email, while contacts from ALL accounts are searched.")
            lbl.setFont(QFont("Courier New", 8))
            lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            self._list.insertWidget(0, lbl)
            return
        for a in accounts:
            self._list.insertWidget(self._list.count() - 1, self._row(a))

    def _row(self, a: dict) -> QWidget:
        row = QWidget()
        row.setStyleSheet(
            "background: rgba(17, 17, 17, 60); border: 1px solid rgba(255, 215, 0, 60);"
            " border-radius: 4px;"
        )
        lay = QVBoxLayout(row)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        top = QHBoxLayout(); top.setSpacing(6)
        name = QLabel(a.get("display_name") or a.get("email") or "Account")
        name.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        name.setStyleSheet(f"color: {C.TEXT}; background: transparent; border: none;")
        top.addWidget(name)
        top.addStretch()
        if a.get("active"):
            badge = QLabel("● ACTIVE")
            badge.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            badge.setStyleSheet(f"color: {C.GREEN}; background: rgba(0,255,136,14);"
                                f" border: 1px solid {C.GREEN_D}; border-radius: 3px;"
                                f" padding: 1px 6px;")
            top.addWidget(badge)
        lay.addLayout(top)

        email_lbl = QLabel(a.get("email") or "(no email)")
        email_lbl.setFont(QFont("Courier New", 8))
        email_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        lay.addWidget(email_lbl)

        key = a.get("email") or str((a.get("index") or 0) + 1)
        if a.get("active"):
            out = QPushButton("SIGN OUT")
            out.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            out.setFixedHeight(22)
            out.setCursor(Qt.CursorShape.PointingHandCursor)
            out.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.RED};
                    border: 1px solid #7a2f36; border-radius: 3px; padding: 0 8px;
                }}
                QPushButton:hover {{ background: rgba(229,72,77,28); }}
            """)
            out.clicked.connect(lambda: self._sign_out())
            lay.addWidget(out, 0, Qt.AlignmentFlag.AlignLeft)
        else:
            btns = QHBoxLayout(); btns.setSpacing(6)
            sw = QPushButton("MAKE ACTIVE")
            sw.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            sw.setFixedHeight(22)
            sw.setCursor(Qt.CursorShape.PointingHandCursor)
            sw.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.ACC2};
                    border: 1px solid {C.BORDER_B}; border-radius: 3px; padding: 0 8px;
                }}
                QPushButton:hover {{ background: {C.PRI_GHO}; }}
            """)
            sw.clicked.connect(lambda _=False, k=key: self._switch(k))
            btns.addWidget(sw)
            rm = QPushButton("REMOVE")
            rm.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            rm.setFixedHeight(22)
            rm.setCursor(Qt.CursorShape.PointingHandCursor)
            rm.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.RED};
                    border: 1px solid #7a2f36; border-radius: 3px; padding: 0 8px;
                }}
                QPushButton:hover {{ background: rgba(229,72,77,28); }}
            """)
            rm.clicked.connect(lambda _=False, k=key: self._remove(k))
            btns.addWidget(rm)
            btns.addStretch()
            lay.addLayout(btns)
        return row

    # ── actions ─────────────────────────────────────────────────────────
    def _switch(self, key: str):
        from core import firebase_client as fb
        try:
            msg = fb.switch_account(key)
        except Exception as e:
            msg = f"Switch failed: {e}"
        self._status.setText(msg[:110])
        self.refresh()
        if self.on_change:
            self.on_change(msg)

    def _remove(self, key: str):
        from core import firebase_client as fb
        try:
            msg = fb.remove_account(key)
        except Exception as e:
            msg = f"Remove failed: {e}"
        self._status.setText(msg[:110])
        self.refresh()
        if self.on_change:
            self.on_change(msg)

    def _sign_out(self):
        from core import firebase_client as fb
        try:
            msg = fb.sign_out()
        except Exception as e:
            msg = f"Sign out failed: {e}"
        self._status.setText(msg[:110])
        self.refresh()
        if self.on_change:
            self.on_change(msg)

    def _add_account(self):
        self._add_btn.setEnabled(False)
        self._add_btn.setText("OPENING GOOGLE…")
        self._status.setText("Waiting for you to approve in the browser…")
        threading.Thread(target=self._sign_in_worker, daemon=True).start()

    def _sign_in_worker(self):
        try:
            from core import firebase_client as fb
            result = fb.sign_in()
        except Exception as e:
            result = f"Google sign-in failed: {e}"
        self._result_sig.emit(str(result))

    def _on_result(self, msg: str):
        self._add_btn.setEnabled(True)
        self._add_btn.setText("＋  ADD ACCOUNT  (opens Google sign-in)")
        self._status.setText(msg[:110])
        self.refresh()
        if self.on_change:
            self.on_change(msg)


class ShortcutsOverlay(QWidget):
    """F1 cheat-sheet — every shortcut and headline capability, for demos.

    A centred glass panel drawn over the HUD; toggled with F1, so a live
    demonstration can put the whole feature set on screen in one keystroke.
    """

    _SHORTCUTS = [
        ("F1",         "Show / hide this guide"),
        ("F4",         "Mute / unmute the microphone"),
        ("F5",         "Mini push-to-talk overlay"),
        ("F6",         "Live Coding console (Crown Code)"),
        ("F11",        "Fullscreen"),
        ("Esc",        "Interrupt Keys.ai mid-speech"),
        ("K  (hold)",  "Push-to-talk")
    ]

    _FEATURES = [
        "Crown Code terminal agent — real shell, live stream, exit codes",
        "Holographic avatar with lip-sync, blinking and facial acting",
        "Optional local wake word + self-echo guard",
        "Model ladder — never hangs, steps around quotas and outages",
        "Agent control: UI Automation → vision/OCR → mouse/keyboard",
        "Terminal: ANSI colour, \u2191/\u2193 history, coloured exit-code chips",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "ShortcutsOverlay { background: rgba(6, 8, 13, 244);"
            " border: 1px solid rgba(100,140,255,90); border-radius: 10px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(8)

        head = QLabel("KEYS.AI  \u00b7  SHORTCUTS & FEATURES")
        head.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        head.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(head)

        sub = QLabel("Press F1 again to close")
        sub.setFont(QFont("Courier New", 8))
        sub.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addWidget(sub)
        lay.addSpacing(4)

        for key, desc in self._SHORTCUTS:
            row = QLabel(
                f"<span style='color:{C.ACC}; font-weight:bold;'>{key}</span>"
                f"<span style='color:{C.TEXT_MED};'>&nbsp;&nbsp;&mdash;&nbsp;&nbsp;{desc}</span>")
            row.setFont(QFont("Courier New", 9))
            row.setStyleSheet("background: transparent;")
            lay.addWidget(row)

        lay.addSpacing(8)
        fl = QLabel("WHAT IT CAN DO")
        fl.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        fl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(fl)
        for feat in self._FEATURES:
            row = QLabel(f"<span style='color:{C.GREEN};'>&#9656;</span>"
                         f"<span style='color:{C.TEXT_MED};'> {feat}</span>")
            row.setFont(QFont("Courier New", 8))
            row.setWordWrap(True)
            row.setStyleSheet("background: transparent;")
            lay.addWidget(row)

        lay.addStretch()
        self.hide()

    def recenter(self, parent: QWidget):
        """Size to the parent and sit in the middle of it."""
        pw, ph = parent.width(), parent.height()
        self.resize(min(640, int(pw * 0.82)), min(560, int(ph * 0.86)))
        self.move(max(0, (pw - self.width()) // 2),
                  max(0, (ph - self.height()) // 2))


class _PaletteInput(QLineEdit):
    """Command-palette input: ↑/↓ move the selection, Enter runs it."""

    move = pyqtSignal(int)
    accepted = pyqtSignal()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Down:
            self.move.emit(1)
            return
        if e.key() == Qt.Key.Key_Up:
            self.move.emit(-1)
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accepted.emit()
            return
        super().keyPressEvent(e)


class CommandPalette(QWidget):
    """Ctrl+K — fuzzy-find any action and run it. Made for demos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "CommandPalette { background: rgba(6, 8, 13, 246);"
            " border: 1px solid rgba(100,140,255,110); border-radius: 10px; }")
        self._commands: list = []
        self._matches: list = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        self._input = _PaletteInput()
        self._input.setFont(QFont("Courier New", 11))
        self._input.setPlaceholderText("Type a command\u2026  (\u2191\u2193 to pick, Enter to run)")
        self._input.setStyleSheet(
            f"QLineEdit {{ background: rgba(20,24,36,220); color: {C.TEXT};"
            " border: 1px solid rgba(100,140,255,60); border-radius: 6px;"
            " padding: 8px 10px; }")
        lay.addWidget(self._input)

        self._list = QListWidget()
        self._list.setFont(QFont("Courier New", 9))
        self._list.setStyleSheet(
            "QListWidget { background: transparent; color: %s; border: none;"
            " outline: none; }"
            "QListWidget::item { padding: 5px 6px; }"
            "QListWidget::item:selected { background: rgba(100,140,255,45);"
            " color: %s; border-radius: 4px; }" % (C.TEXT_MED, C.TEXT))
        lay.addWidget(self._list, stretch=1)

        self._input.textChanged.connect(self._filter)
        self._input.move.connect(self._nudge)
        self._input.accepted.connect(self._activate)
        self._list.itemActivated.connect(lambda _: self._activate())
        self.hide()

    # ── API ────────────────────────────────────────────────────────────────

    def set_commands(self, commands: list):
        """commands: list of (label, callable)."""
        self._commands = list(commands or [])
        self._filter("")

    def focus_input(self):
        self._input.clear()
        self._filter("")
        self._input.setFocus()

    def recenter(self, parent: QWidget):
        pw, ph = parent.width(), parent.height()
        self.resize(min(560, int(pw * 0.7)), min(420, int(ph * 0.7)))
        self.move(max(0, (pw - self.width()) // 2), max(0, int(ph * 0.22)))

    # ── internals ──────────────────────────────────────────────────────────

    def _filter(self, text: str):
        text = (text or "").lower().strip()
        self._matches = [c for c in self._commands
                         if not text or text in c[0].lower()]
        self._list.clear()
        for label, _ in self._matches:
            self._list.addItem(label)
        if self._matches:
            self._list.setCurrentRow(0)

    def _nudge(self, delta: int):
        if not self._matches:
            return
        row = self._list.currentRow()
        row = max(0, min(len(self._matches) - 1, row + delta))
        self._list.setCurrentRow(row)

    def _activate(self):
        row = self._list.currentRow()
        if 0 <= row < len(self._matches):
            label, cb = self._matches[row]
            self.hide()
            try:
                cb()
            except Exception as e:
                print(f"[Palette] '{label}' failed: {e}")


class MemoryPanel(QWidget):
    """See — and forget — everything Keys.ai has stored about you (F2)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "MemoryPanel { background: rgba(6, 8, 13, 244);"
            " border: 1px solid rgba(100,140,255,90); border-radius: 10px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        head = QLabel("KEYS.AI  \u00b7  MEMORY")
        head.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        head.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(head)

        self._status = QLabel("")
        self._status.setFont(QFont("Courier New", 8))
        self._status.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addWidget(self._status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self._rows = QVBoxLayout(inner)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(4)
        scroll.setWidget(inner)
        lay.addWidget(scroll, stretch=1)
        self.hide()

    def recenter(self, parent: QWidget):
        pw, ph = parent.width(), parent.height()
        self.resize(min(640, int(pw * 0.82)), min(560, int(ph * 0.86)))
        self.move(max(0, (pw - self.width()) // 2),
                  max(0, (ph - self.height()) // 2))

    def refresh(self):
        while self._rows.count():
            item = self._rows.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        try:
            from memory.memory_manager import all_entries_for_ui
            rows = all_entries_for_ui()
        except Exception as e:
            self._status.setText(f"Memory unavailable: {e}")
            return
        self._status.setText(f"{len(rows)} thing(s) remembered \u00b7 ✕ forgets one")
        if not rows:
            empty = QLabel("Nothing stored yet — just talk to Keys.ai.")
            empty.setFont(QFont("Courier New", 8))
            empty.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            self._rows.addWidget(empty)
        for r in rows:
            self._rows.addWidget(self._make_row(r))
        self._rows.addStretch()

    def _make_row(self, r: dict) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        lbl = QLabel(
            f"<span style='color:{C.ACC}; font-weight:bold;'>{r['key']}</span>"
            f"<span style='color:{C.TEXT_MED};'> — {r['value']}</span>"
            f"<span style='color:{C.TEXT_DIM}; font-size:7pt;'>  {r['category']}"
            f" \u00b7 {r['updated']}</span>")
        lbl.setWordWrap(True)
        lbl.setFont(QFont("Courier New", 8))
        lbl.setStyleSheet("background: transparent;")
        h.addWidget(lbl, stretch=1)
        btn = QPushButton("✕")
        btn.setFixedSize(20, 20)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(f"Forget {r['key']}")
        btn.setStyleSheet(
            f"QPushButton {{ color: {C.TEXT_DIM}; background: transparent; border: none; }}"
            f"QPushButton:hover {{ color: {C.RED}; }}")
        btn.clicked.connect(lambda _, k=r["key"], c=r["category"]: self._forget(k, c))
        h.addWidget(btn)
        return w

    def _forget(self, key: str, category: str):
        try:
            from memory.memory_manager import forget
            forget(key, category)
        except Exception as e:
            print(f"[MemoryPanel] forget failed: {e}")
        self.refresh()


class PresentationOverlay(QWidget):
    """F3 — a full-window, one-key-per-card feature showcase for demos.

    Each card names a capability and says what makes it work. ← / → (or space)
    move through them; F3 closes. Built so a live demonstration never has to
    hunt through the UI to explain what it is showing.
    """

    _CARDS = [
        ("Holographic Avatar",
         "A software-rendered head — real facial geometry, lit and drawn without a "
         "GPU. It lip-syncs to the actual audio, blinks, sways, and acts: it looks "
         "away while thinking and meets you while listening."),
        ("Crown Code Terminal Agent (Dev Agent)",
         "This panel is the TERMINAL tab and it uses the Dev Agent workflow: plan "
         "the project, write each file, install deps, open the IDE, run it, then fix "
         "errors and re-run until it works. It still looks and behaves like the old "
         "Crown Code terminal — real shell, live stream, exit codes — just driven by "
         "the Dev Agent plan->write->deps->run->fix loop."),
        ("Never-Hangs Model Ladder",
         "Every one-shot model call carries a deadline and steps down a measured "
         "ladder when one is quota-limited or unwell. Failing models rest for a "
         "time that matches the failure; backup keys rotate automatically."),
        ("Wake Word + Self-Echo Guard",
         "An optional local wake word opens the mic hands-free. The echo guard "
         "tells your voice apart from its own, so it never answers the tail of its "
         "own sentence."),
        ("Desktop Agent Control",
         "It drives real applications through UI Automation first, falling back to "
         "native APIs, then vision and OCR, then the mouse — with a visible gold "
         "border while it has control, and ESC always wins."),
        ("Memory That Remembers",
         "It stores what it learns about you and recalls it on demand. Press F2 to "
         "see every stored fact and forget any one of them."),
        ("Command Palette  ·  Ctrl+K",
         "Fuzzy-find any action by name and run it instantly — mute, fullscreen, "
         "agent settings, memory, and more."),
        ("Phone & Web Dashboard",
         "Pair your phone as a microphone and remote, and drive the assistant from "
         "the browser dashboard when a second screen is easier."),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "PresentationOverlay { background: rgba(4, 6, 11, 250);"
            " border: 1px solid rgba(100,140,255,90); border-radius: 12px; }")
        self._idx = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(46, 40, 46, 34)
        lay.setSpacing(12)

        kicker = QLabel("KEYS.AI  \u00b7  FEATURE SHOWCASE")
        kicker.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        kicker.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addWidget(kicker)
        lay.addStretch(1)

        self._title = QLabel("")
        self._title.setFont(QFont("Courier New", 22, QFont.Weight.Bold))
        self._title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._title.setWordWrap(True)
        lay.addWidget(self._title)

        rule = QFrame()
        rule.setFixedHeight(2)
        rule.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            " stop:0 rgba(100,140,255,0), stop:0.5 rgba(100,140,255,160),"
            " stop:1 rgba(100,140,255,0));")
        lay.addWidget(rule)

        self._body = QLabel("")
        self._body.setFont(QFont("Courier New", 11))
        self._body.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._body.setWordWrap(True)
        self._body.setAlignment(Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self._body, stretch=2)
        lay.addStretch(1)

        self._foot = QLabel("")
        self._foot.setFont(QFont("Courier New", 9))
        self._foot.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._foot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._foot)
        self.hide()

    # ── API ────────────────────────────────────────────────────────────────

    def recenter(self, parent: QWidget):
        m = 24
        self.setGeometry(m, m, max(320, parent.width() - 2 * m),
                         max(240, parent.height() - 2 * m))

    def start(self, parent: QWidget):
        self._idx = 0
        self._render()
        self.recenter(parent)
        self.show()
        self.raise_()
        self.setFocus()

    def next_card(self):
        self._idx = (self._idx + 1) % len(self._CARDS)
        self._render()

    def prev_card(self):
        self._idx = (self._idx - 1) % len(self._CARDS)
        self._render()

    # ── internals ──────────────────────────────────────────────────────────

    def _render(self):
        title, body = self._CARDS[self._idx]
        self._title.setText(title)
        self._body.setText(body)
        self._foot.setText(
            f"\u2190  \u2192  navigate   \u00b7   {self._idx + 1} / {len(self._CARDS)}"
            f"   \u00b7   F3 to close")

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Right, Qt.Key.Key_Space, Qt.Key.Key_Down):
            self.next_card()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.prev_card()
        elif k == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)


class MainWindow(QMainWindow):
    _log_sig         = pyqtSignal(str)
    _state_sig       = pyqtSignal(str)
    _content_sig     = pyqtSignal(str, str)   # (title, text) — thread-safe content display
    _coding_log_sig  = pyqtSignal(str)        # thread-safe coding activity line
    _coding_clear_sig = pyqtSignal()          # clear coding panel at start of new turn
    _reconfig_sig = pyqtSignal()          # trigger setup overlay from any thread
    _camera_sig     = pyqtSignal(bytes)   # show camera frame preview (small overlay)
    _cam_stream_sig = pyqtSignal(bool)   # True=start live stream, False=stop
    _cam_frame_sig  = pyqtSignal(bytes)  # live camera frame → HUD area
    _show_req_sig   = pyqtSignal()       # bring main window to front (any thread)
    _google_sig     = pyqtSignal(str)    # Google sign-in/out result (any thread)
    # ── Creation workspace signals ─────────────────────────────────────────
    _cr_begin_sig   = pyqtSignal(str, str, str)   # (mode, project_name, project_path)
    _cr_event_sig   = pyqtSignal(str, str, str)   # (icon, text, file_or_empty)
    _cr_file_sig    = pyqtSignal(str, int, str)   # (path, lines, status)
    _cr_setfile_sig = pyqtSignal(str)             # (path) — switch active file
    _cr_code_sig    = pyqtSignal(str)             # (chunk) — append code
    _cr_codeset_sig = pyqtSignal(str)             # (full_content) — replace code viewer
    _cr_progress_sig = pyqtSignal(float)          # (0.0–1.0)
    _cr_phase_sig   = pyqtSignal(str, float, float)  # (phase, pct, eta_seconds)
    _cr_error_sig   = pyqtSignal(str)             # (text)
    _cr_complete_sig = pyqtSignal(str)            # (summary)
    _cr_reset_sig   = pyqtSignal()                # clear and hide
    _cr_preview_sig = pyqtSignal(str)             # (url) — load web preview
    _term_output_sig = pyqtSignal(str, str, str)  # (chunk, stream, origin) — terminal output
    _term_clear_sig  = pyqtSignal()               # clear terminal output
    _term_cmd_sig    = pyqtSignal(str)            # user command typed in the terminal
    _term_stop_sig   = pyqtSignal()               # user pressed Stop in the terminal
    _hud_level_sig   = pyqtSignal(float)          # live audio level → avatar mouth
    _status_line_sig = pyqtSignal(str)            # always-on HUD status line
    _gui_call_sig    = pyqtSignal(object)         # (job) — job() runs on the GUI thread, any caller thread
    # ── Decision/permission signals ─────────────────────────────────────
    _dec_ask_sig    = pyqtSignal(str, list, bool, str)  # (question, options, show_why, why_text)
    _dec_perm_sig   = pyqtSignal(str, str, str)         # (action, reason, location)
    _dec_result_sig = pyqtSignal(str)                    # user's answer
    _dec_answered   = threading.Event()                  # blocks until user decides
    _dec_answer_val = ""                                  # stores the answer
    # ── Irreversible-action confirmation gate (core/confirm.py) ──────────
    # Same CONFIRM/CANCEL panel Agent Control uses — hosted over this HUD so
    # the gate works app-wide without adding any new visual element.
    _confirm_show_sig = pyqtSignal(str, str)   # (title, detail) — any thread
    _confirm_hide_sig = pyqtSignal()           # hide panel — any thread

    def __init__(self, face_path: str):
        super().__init__()
        self._face_path = face_path
        self.setWindowTitle("Keys.ai — ACENDENCE VII [GEN I]")
                # Custom Keys.ai window chrome: frameless with a translucent glass
        # body (WA_TranslucentBackground + DWM acrylic on Windows) so the
        # desktop shows through the frosted surface. Every fill below uses
        # semi-transparent alpha (comfortably above zero) so there are no
        # fully transparent, click-through regions. Alt+Tab, taskbar, snap,
        # minimize and DPI scaling all keep working through the OS.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        # Set the window icon from keys_eye_icon.ico
        # In frozen mode (one-dir build), BASE_DIR = Path(sys.executable).parent = dist/KeysAI/
        # which is where the spec's COLLECT puts keys_eye_icon.ico alongside the EXE.
        _ico = BASE_DIR / "keys_eye_icon.ico"
        if _ico.exists():
            self.setWindowIcon(QIcon(str(_ico)))
        self.setMinimumSize(_MIN_W, _MIN_H)
        # Restore the previous window geometry (position/size/maximized); fall
        # back to the default centered size when no state is saved yet.
        _restored = load_window_state(self, CONFIG_DIR / "window_state.json")
        self._start_maximized = bool(_restored)
        if _restored is None:
            self.resize(_DEFAULT_W, _DEFAULT_H)
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(
                (screen.width()  - _DEFAULT_W) // 2,
                (screen.height() - _DEFAULT_H) // 2,
            )

        # Worker threads (research + design-reference capture) need a way onto
        # the GUI thread; this window is it. Registered here, not on first
        # browser open, because the agent may capture before any view is open and
        # would otherwise have no handle to the event loop.
        try:
            from core.research_browser import tools as _rb_tools
            _rb_tools.register_ui(self)
        except Exception:
            pass

        self.on_text_command   = None
        self.on_interrupt      = None   # callable: () -> None — stop Keys.ai mid-speech
        self._muted            = False
        self.main_ptt_active   = False   # True while K is held — main UI or mini overlay (voice PTT)
        self._mini             = None    # MiniOverlay (created by KeysAIUI)

        # Keys.ai custom frame wraps the existing HUD: [custom title bar] + [HUD].
        self._chrome = WindowChromeFrame()
        self.setCentralWidget(self._chrome)
        central = GlassBackdrop()
        self._backdrop = central
        self._chrome.set_content_widget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._left_panel = self._build_left_panel()
        body.addWidget(self._left_panel, stretch=0)

        # Center column: HUD + resizable content panel via QSplitter
        self.hud = HudCanvas(face_path)
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._content_panel = self._build_content_panel()

        # Live camera container — replaces HUD when camera stream is active
        _cam_cont = QWidget()
        _cam_cont.setStyleSheet("background: rgba(0, 3, 8, 130);")
        _cam_v = QVBoxLayout(_cam_cont)
        _cam_v.setContentsMargins(0, 0, 0, 0)
        _cam_v.setSpacing(0)
        _cam_hdr = QHBoxLayout()
        _cam_hdr.setContentsMargins(8, 5, 8, 5)
        _cam_title = QLabel("◈  CAMERA FEED")
        _cam_title.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        _cam_title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        _cam_hdr.addWidget(_cam_title)
        _cam_hdr.addStretch()
        _cam_x = QPushButton("✕  CLOSE")
        _cam_x.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        _cam_x.setCursor(Qt.CursorShape.PointingHandCursor)
        _cam_x.setStyleSheet(f"""
            QPushButton {{
                color: {C.TEXT_DIM}; background: transparent;
                border: none; padding: 2px 6px;
            }}
            QPushButton:hover {{ color: {C.PRI}; }}
        """)
        _cam_x.clicked.connect(self.stop_camera_stream)
        _cam_hdr.addWidget(_cam_x)
        _cam_v.addLayout(_cam_hdr)
        self._cam_live_lbl = QLabel()
        self._cam_live_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cam_live_lbl.setStyleSheet("background: transparent;")
        self._cam_live_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        _cam_v.addWidget(self._cam_live_lbl, stretch=1)

        # Centre view stack — the one place features open, exactly like the live
        # camera. Page 0 is the animated HUD (the default face), page 1 the live
        # camera; the research browser, image studio and project agent add their
        # own page the first time they are opened (_show_center_view). Nothing
        # floats over the window: the workspace takes the centre column and the
        # panels around it stay usable.
        self._center_stack = QStackedWidget()
        self._center_stack.addWidget(self.hud)
        self._center_stack.addWidget(_cam_cont)
        self._cam_view = _cam_cont
        self._view_before_camera: QWidget | None = None

        self._center_split = QSplitter(Qt.Orientation.Vertical)
        self._center_split.setStyleSheet(f"""
            QSplitter::handle {{
                background: rgba(255, 215, 0, 30);
                height: 2px;
            }}
            QSplitter::handle:hover {{
                background: rgba(255, 215, 0, 90);
            }}
        """)
        self._center_split.addWidget(self._center_stack)
        self._center_split.addWidget(self._content_panel)
        self._center_split.setStretchFactor(0, 3)
        self._center_split.setStretchFactor(1, 1)
        self._center_split.setCollapsible(0, False)
        body.addWidget(self._center_split, stretch=5)

        # The Research Browser is the workspace's live web + research + preview
        # surface. It opens into the centre column the same way the image studio
        # does, and the creation workspace's preview is moving there (see the
        # preview-move notes in CROWN_CODE_INTEGRATION.md).

        self._right_panel = self._build_right_panel()
        body.addWidget(self._right_panel, stretch=0)

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_command_bar())
        root.addWidget(self._build_footer())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        # Metrik güncelleme timer'ı
        self._metrics = _metrics          # shared snapshot feed (also used by the mini overlay)
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        self._log_sig.connect(self._log.append_log)
        self._state_sig.connect(self._apply_state)
        self._content_sig.connect(self._show_content)
        self._coding_log_sig.connect(self._append_coding_log)
        self._coding_clear_sig.connect(self._clear_coding_log)
        self._cr_begin_sig.connect(self._on_cr_begin)
        self._cr_event_sig.connect(self._on_cr_event)
        self._cr_file_sig.connect(self._on_cr_file)
        self._cr_setfile_sig.connect(self._on_cr_setfile)
        self._cr_code_sig.connect(self._on_cr_code)
        self._cr_codeset_sig.connect(self._on_cr_codeset)
        self._cr_progress_sig.connect(self._on_cr_progress)
        self._cr_phase_sig.connect(self._on_cr_phase)
        self._cr_error_sig.connect(self._on_cr_error)
        self._cr_complete_sig.connect(self._on_cr_complete)
        self._cr_reset_sig.connect(self._on_cr_reset)
        self._cr_preview_sig.connect(self._on_cr_preview)
        # NOTE: web/code preview was moved into the Research Browser. ``show_preview``
        # still emits here for backward compatibility; the browser workspace is the
        # live preview surface (CROWN_CODE_INTEGRATION.md preview-move notes).
        self._term_output_sig.connect(self._on_term_output)
        self._hud_level_sig.connect(lambda lv: self.hud.set_hud_level(lv))
        self._status_line_sig.connect(self._on_status_line)
        # Cross-thread calls into the GUI thread (must be queued — the caller
        # is usually a tool running on a thread-pool worker).
        self._gui_call_sig.connect(self._run_gui_call, Qt.ConnectionType.QueuedConnection)
        self._term_clear_sig.connect(self._on_term_clear)
        self._term_cmd_sig.connect(self._on_term_cmd)
        self._term_stop_sig.connect(self._on_term_stop)
        self._creation_ws.terminalCommandSubmitted.connect(self._term_cmd_sig.emit)
        self._creation_ws.stopRequested.connect(self._term_stop_sig.emit)
        # Clicking a file chip in the timeline shows that file, even while the
        # agent is writing something else.
        self._creation_ws.fileClicked.connect(self._creation_ws.user_show_file)
        self._term_cmd_handler = None
        self._term_stop_handler = None
        self._dec_ask_sig.connect(self._on_dec_ask)
        self._dec_perm_sig.connect(self._on_dec_perm)
        self._reconfig_sig.connect(self._show_setup)
        self._camera_sig.connect(self._show_camera_frame)
        self._cam_stream_sig.connect(self._on_cam_stream)
        self._cam_frame_sig.connect(self._on_cam_frame)
        self._show_req_sig.connect(self._bring_to_front)
        self._google_sig.connect(self._on_google_result)
        self._google_busy = False
        self._cam_stop = threading.Event()
        self._coding_active = False  # tracks if content panel is in a coding session

        # Camera preview overlay (child of the HUD surface, positioned in resizeEvent)
        self._cam_preview = _CameraPreview(self._backdrop)

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)
        sc_intr = QShortcut(QKeySequence("Escape"), self)
        sc_intr.activated.connect(self._do_interrupt)
        sc_mini = QShortcut(QKeySequence("F5"), self)
        sc_mini.activated.connect(self._toggle_mini)
        # F6 — the shortcut listed in the F1 cheat-sheet. It was never wired
        # up, so a console that failed to open meant restarting the app.
        sc_code = QShortcut(QKeySequence("F6"), self)
        sc_code.activated.connect(self._toggle_live_coding)

        # F1 — the demo cheat-sheet (shortcuts + feature list).
        self._help = ShortcutsOverlay(self)

        def _toggle_help():
            if self._help.isVisible():
                self._help.hide()
            else:
                self._help.recenter(self)
                self._help.show()
                self._help.raise_()

        sc_help = QShortcut(QKeySequence("F1"), self)
        sc_help.activated.connect(_toggle_help)

        # F2 — memory panel; Ctrl+K — command palette. Both are overlays on the
        # main window, so they never steal focus from the assistant for long.
        self._memory_panel = MemoryPanel(self)
        self._palette = CommandPalette(self)

        def _toggle_memory():
            if self._memory_panel.isVisible():
                self._memory_panel.hide()
            else:
                self._memory_panel.refresh()
                self._memory_panel.recenter(self)
                self._memory_panel.show()
                self._memory_panel.raise_()

        def _toggle_palette():
            if self._palette.isVisible():
                self._palette.hide()
            else:
                self._palette.recenter(self)
                self._palette.show()
                self._palette.raise_()
                self._palette.focus_input()

        # F3 — full-window feature showcase, made for live demonstrations.
        self._presentation = PresentationOverlay(self)

        def _toggle_presentation():
            if self._presentation.isVisible():
                self._presentation.hide()
            else:
                self._presentation.start(self)

        sc_pres = QShortcut(QKeySequence("F3"), self)
        sc_pres.activated.connect(_toggle_presentation)

        # F9 — cycle the HUD theme (retints the avatar + rings, persisted).
        try:
            from memory.config_manager import get_theme, save_theme
        except Exception:
            def get_theme():
                return "gold"

            def save_theme(_name):
                pass

        self._theme_idx = 0
        try:
            _applied = apply_theme(get_theme())
            self._theme_idx = THEME_ORDER.index(_applied)
        except Exception:
            pass

        def _cycle_theme():
            self._theme_idx = (self._theme_idx + 1) % len(THEME_ORDER)
            name = apply_theme(THEME_ORDER[self._theme_idx])
            try:
                save_theme(name)
            except Exception:
                pass
            try:
                self.hud.update()
            except Exception:
                pass
            self._status_line_sig.emit(f"theme: {name}")

        sc_theme = QShortcut(QKeySequence("F9"), self)
        sc_theme.activated.connect(_cycle_theme)

        def _palette_commands():
            return [
                ("Show shortcuts & features   (F1)", _toggle_help),
                ("Feature showcase   (F3)", _toggle_presentation),
                ("Cycle HUD theme   (F9)", _cycle_theme),
                ("Open memory panel   (F2)", _toggle_memory),
                ("Mute / unmute microphone   (F4)", self._toggle_mute),
                ("Toggle mini overlay   (F5)", self._toggle_mini),
                ("Fullscreen   (F11)", self._toggle_fullscreen),
                ("Interrupt Keys.ai   (Esc)", self._do_interrupt),
                ("AI Image Studio  (local image generation)", self._open_image_studio),
                ("Agent Control settings", self._open_agent_settings),
                ("Google accounts", self._open_google_accounts),
                ("Setup", self._show_setup),
            ]

        self._palette.set_commands(_palette_commands())
        sc_mem = QShortcut(QKeySequence("F2"), self)
        sc_mem.activated.connect(_toggle_memory)
        sc_pal = QShortcut(QKeySequence("Ctrl+K"), self)
        sc_pal.activated.connect(_toggle_palette)
        # Custom title-bar window controls
        _tb = self._chrome.title_bar
        _tb.minimizeRequested.connect(self.showMinimized)
        _tb.maximizeRequested.connect(self._toggle_maximize)
        _tb.closeRequested.connect(self.close)
        _tb.refresh_state()

        self._refresh_google_btn()

        # ── Agent Control Mode: control overlay + status pill + history ──
        self._ctrl_bridge = ControlOverlayBridge()
        self._ctrl_overlay = ControlOverlay(self._ctrl_bridge)
        # Full-screen targeting grid — drawn while the agent moves the mouse:
        # the user sees which grid cell the cursor is heading to, plus a live
        # crosshair that tracks the real mouse during the move.
        self._grid_overlay = GridTargetOverlay()
        self._ctrl_bridge.gridRequested.connect(self._grid_overlay.show_grid)
        self._ctrl_bridge.gridPointRequested.connect(self._grid_overlay.stream_point)
        self._ctrl_bridge.gridHideRequested.connect(self._grid_overlay.hide_grid)
        self._ctrl_bridge.statusChanged.connect(self._on_ctrl_status)
        self._ctrl_bridge.historyEntry.connect(self._on_ctrl_history)
        self._ctrl_overlay.pauseClicked.connect(self._ctrl_pause)
        self._ctrl_overlay.stopClicked.connect(self._ctrl_stop)
        self._ctrl_overlay.takeControlClicked.connect(self._ctrl_takeover)
        self._ctrl_bridge.set_rect_provider(self._ctrl_window_rect)
        self._ctrl_settings: AgentSettingsOverlay | None = None

        # ── Irreversible-action confirmation gate (core/confirm.py) ──────
        # Reuses the agent-control _ConfirmPanel — the exact same dialog the
        # control overlay already shows, hosted over this HUD so the gate
        # covers app-wide actions (restart/shutdown/WiFi) too. No new visual
        # language is introduced; the panel is invisible until a gate asks.
        try:
            from agent_control.overlay import _ConfirmPanel as _GatePanel
            self._gate_panel = _GatePanel(self)
            self._gate_panel.resolved.connect(self._on_gate_resolved)
            self._gate_panel.hide()
        except Exception as e:
            self._gate_panel = None
            print(f"[ui] Confirm gate panel unavailable: {e}")
        self._confirm_show_sig.connect(self._on_gate_show)
        self._confirm_hide_sig.connect(self._on_gate_hide)
        self._gate_timer: QTimer | None = None

    def _on_status_line(self, text: str) -> None:
        """Slot — thread-safe status line update for the HUD."""
        try:
            self.hud.status_line = text or ""
            self.hud.update()
        except Exception:
            pass

    def _toggle_maximize(self) -> None:
        """Custom title-bar maximize/restore (also toggled by double-click)."""
        if self.isMaximized() or self.isFullScreen():
            self.showNormal()
        else:
            self.showMaximized()
        self._chrome.title_bar.refresh_state()

    def changeEvent(self, e):
        super().changeEvent(e)
        # The FramelessWindowHint flags are set before self._chrome exists;
        # WindowStateChange can fire synchronously during setWindowFlags, so
        # guard until the chrome is constructed.
        if getattr(self, "_chrome", None) is None:
            return
        if e.type() == QEvent.Type.WindowStateChange:
            # Max/fullscreen drops the chrome band so the HUD fills the work
            # area; restore re-adds it. Also keeps the □/❐ glyph in sync.
            self._chrome.set_maximized(self.isMaximized() or self.isFullScreen())
            self._chrome.title_bar.refresh_state()
        elif e.type() == QEvent.Type.ActivationChange:
            # Dim the frame slightly while the window is inactive.
            self._chrome.set_active(self.isActiveWindow())

    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, "_start_maximized", False):
            self._start_maximized = False
            self.showMaximized()

    def _bring_to_front(self) -> None:
        """Slot (GUI thread): restore, raise, and focus the main window."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _show_camera_frame(self, img_bytes: bytes):
        """Slot — display camera preview overlay (main thread)."""
        self._cam_preview.show_frame(img_bytes)
        cw = self._backdrop
        pw = _CameraPreview._W
        ph = self._cam_preview.height()
        self._cam_preview.setGeometry(
            cw.width() - _RIGHT_W - pw - 12,
            cw.height() - _CMD_BAR_H - ph - 14,
            pw, ph,
        )

    # --- Live camera stream in HUD area ------------------------------------
    def _on_cam_stream(self, start: bool) -> None:
        if start:
            # Remember what was on screen so a vision capture gives it back
            # instead of dumping the user out of an open workspace.
            self._view_before_camera = self._center_stack.currentWidget()
            self._center_stack.setCurrentWidget(self._cam_view)
        else:
            back = self._view_before_camera or self.hud
            self._view_before_camera = None
            self._center_stack.setCurrentWidget(back)
            self._cam_live_lbl.clear()

    def _on_cam_frame(self, data: bytes) -> None:
        px = QPixmap()
        px.loadFromData(data)
        if not px.isNull():
            w, h = self._cam_live_lbl.width(), self._cam_live_lbl.height()
            if w > 1 and h > 1:
                self._cam_live_lbl.setPixmap(
                    px.scaled(w, h,
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
                )

    def start_camera_stream(self) -> None:
        self._cam_stop.clear()
        self._cam_stream_sig.emit(True)
        t = threading.Thread(target=self._cam_loop, daemon=True, name="cam-stream")
        t.start()

    def _cam_loop(self) -> None:
        try:
            import cv2
            # Reuse camera index detected by screen_processor (cached in api_keys.json)
            cam_idx = 0
            try:
                import json as _j
                cfg = _j.loads((CONFIG_DIR / "api_keys.json").read_text())
                cam_idx = int(cfg.get("camera_index", 0))
            except Exception:
                pass
            try:
                backend = cv2.CAP_DSHOW if _OS == "Windows" else cv2.CAP_ANY
            except AttributeError:
                backend = 0
            cap = cv2.VideoCapture(cam_idx, backend)
            if not cap.isOpened():
                cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                return
            # warm-up frames
            for _ in range(5):
                cap.read()
            while not self._cam_stop.wait(0.033) and cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
                    self._cam_frame_sig.emit(buf.tobytes())
            cap.release()
        except Exception as e:
            print(f"[Camera] Stream error: {e}")
        finally:
            self._cam_stream_sig.emit(False)

    def stop_camera_stream(self) -> None:
        self._cam_stop.set()

    # ------------------------------------------------------------------
    # Icon generation — arc-reactor style, rendered with Pillow
    # ------------------------------------------------------------------
    @staticmethod
    def _build_keysai_icon(out_path: Path) -> bool:
        """
        Render a Keys.ai icon at 4× resolution and downsample
        for crisp results at all sizes. Saves a multi-res .ico to out_path.
        Returns True on success.
        """
        try:
            import math
            import PIL.Image
            import PIL.ImageDraw
            import PIL.ImageFilter
        except ImportError:
            return False

        CYAN   = (0, 212, 255)
        DIM    = (0, 100, 140)
        DARK   = (0, 6, 10)
        GLOW   = (0, 160, 200)
        WHITE  = (220, 240, 255)

        def _render(sz: int) -> PIL.Image.Image:
            S  = sz * 4                     # draw at 4× then downscale
            img = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            d   = PIL.ImageDraw.Draw(img)
            cx = cy = S // 2

            # ── filled background circle ──────────────────────────────────
            R = S // 2 - 2
            d.ellipse([cx-R, cy-R, cx+R, cy+R], fill=(*DARK, 255))

            # ── outer border ring ─────────────────────────────────────────
            lw = max(2, S // 40)
            d.ellipse([cx-R, cy-R, cx+R, cy+R],
                      outline=(*CYAN, 220), width=lw)

            # ── mid decorative ring ───────────────────────────────────────
            R2 = int(R * 0.72)
            d.ellipse([cx-R2, cy-R2, cx+R2, cy+R2],
                      outline=(*DIM, 180), width=max(1, lw // 2))

            # ── 6 radial spokes (hex bolt) ────────────────────────────────
            R_inner = int(R * 0.30)
            R_outer = int(R * 0.62)
            spoke_w = max(1, S // 80)
            for i in range(6):
                angle = math.radians(i * 60 - 30)
                x1 = cx + int(R_inner * math.cos(angle))
                y1 = cy + int(R_inner * math.sin(angle))
                x2 = cx + int(R_outer * math.cos(angle))
                y2 = cy + int(R_outer * math.sin(angle))
                d.line([x1, y1, x2, y2], fill=(*GLOW, 200), width=spoke_w)

            # ── 6 tick marks on outer ring ────────────────────────────────
            for i in range(6):
                angle = math.radians(i * 60)
                for dr in range(lw * 2):
                    rx = (R - lw - dr)
                    d.point(
                        [cx + int(rx * math.cos(angle)),
                         cy + int(rx * math.sin(angle))],
                        fill=(*WHITE, 220),
                    )

            # ── inner glowing ring ────────────────────────────────────────
            Ri = int(R * 0.26)
            d.ellipse([cx-Ri, cy-Ri, cx+Ri, cy+Ri],
                      outline=(*CYAN, 255), width=max(2, lw))

            # ── bright glow soft blur applied before core ─────────────────
            # (draw a slightly larger cyan circle on a separate layer)
            glow_layer = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            gd = PIL.ImageDraw.Draw(glow_layer)
            Rc = int(R * 0.13)
            gd.ellipse([cx-Rc*2, cy-Rc*2, cx+Rc*2, cy+Rc*2],
                       fill=(*CYAN, 110))
            glow_layer = glow_layer.filter(PIL.ImageFilter.GaussianBlur(S // 14))
            img = PIL.Image.alpha_composite(img, glow_layer)
            d   = PIL.ImageDraw.Draw(img)

            # ── core dot ──────────────────────────────────────────────────
            d.ellipse([cx-Rc, cy-Rc, cx+Rc, cy+Rc], fill=(*WHITE, 255))

            # ── downscale to target size ──────────────────────────────────
            return img.resize((sz, sz), PIL.Image.LANCZOS)

        try:
            sizes  = [256, 128, 64, 48, 32, 16]
            frames = [_render(s) for s in sizes]
            frames[0].save(
                out_path,
                format="ICO",
                append_images=frames[1:],
                sizes=[(s, s) for s in sizes],
            )
            return True
        except Exception as e:
            print(f"[Shortcut] ⚠️  Icon generation failed: {e}")
            return False

    @staticmethod
    def _create_lnk_windows(lnk: str, target: str, args: str,
                             work_dir: str, icon_loc: str) -> None:
        """
        Create a Windows .lnk shortcut WITHOUT launching PowerShell or cmd.
        Tries win32com (pywin32) first; falls back to wscript.exe + VBScript.
        wscript.exe is a GUI-mode host — it never opens a console window.
        """
        # ── Option 1: pywin32 (pure Python COM, zero subprocess) ──────────
        try:
            from win32com.client import Dispatch   # type: ignore
            sh = Dispatch("WScript.Shell")
            sc = sh.CreateShortCut(lnk)
            sc.TargetPath       = target
            sc.Arguments        = f'"{args}"'
            sc.WorkingDirectory = work_dir
            sc.Description      = "Keys.ai AI Assistant"
            sc.IconLocation     = icon_loc
            sc.save()
            return
        except ImportError:
            pass

        # ── Option 2: wscript.exe + VBScript (always available on Windows,
        #    GUI-mode executable — never opens a console window) ────────────
        vbs = "\n".join([
            'Set ws = CreateObject("WScript.Shell")',
            f'Set sc = ws.CreateShortcut("{lnk}")',
            f'sc.TargetPath = "{target}"',
            f'sc.Arguments = Chr(34) & "{args}" & Chr(34)',
            f'sc.WorkingDirectory = "{work_dir}"',
            'sc.Description = "Keys.ai AI Assistant"',
            f'sc.IconLocation = "{icon_loc}"',
            'sc.Save',
        ])
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".vbs")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(vbs)
            proc = subprocess.Popen(
                ["wscript.exe", "/nologo", tmp],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            )
            proc.wait(timeout=10)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    def _create_desktop_shortcut(self):
        """
        Create a desktop shortcut on Windows / macOS / Linux.
        Never opens a terminal, console, or PowerShell window on any platform.
        """
        import stat as _stat
        script  = Path(__file__).resolve().parent / "main.py"
        python  = Path(sys.executable)
        desktop = Path.home() / "Desktop"

        # Arc-reactor icon (.ico — also exported as .png for Linux/macOS)
        ico_path = Path(__file__).resolve().parent / "config" / "keysai.ico"
        if not ico_path.exists():
            self._build_keysai_icon(ico_path)

        try:
            _os = platform.system()

            # ── Windows ───────────────────────────────────────────────────────
            if _os == "Windows":
                pythonw  = python.parent / "pythonw.exe"
                target   = str(pythonw if pythonw.exists() else python)
                lnk      = str(desktop / "Keys.ai.lnk")
                icon_loc = str(ico_path) if ico_path.exists() else f"{target},0"
                self._create_lnk_windows(lnk, target, str(script),
                                         str(script.parent), icon_loc)

            # ── macOS — proper .app bundle (no Terminal window) ───────────────
            elif _os == "Darwin":
                app     = desktop / "Keys.ai.app"
                mac_dir = app / "Contents" / "MacOS"
                res_dir = app / "Contents" / "Resources"
                mac_dir.mkdir(parents=True, exist_ok=True)
                res_dir.mkdir(exist_ok=True)

                # Launcher executable (bash — runs as background process,
                # macOS does NOT open Terminal for executables inside .app bundles)
                launcher = mac_dir / "Keys AI"
                launcher.write_text(
                    "#!/usr/bin/env bash\n"
                    f'cd "{script.parent}"\n'
                    f'exec "{python}" "{script}"\n'
                )
                launcher.chmod(launcher.stat().st_mode
                               | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)

                # Minimal Info.plist (required for .app recognition)
                (app / "Contents" / "Info.plist").write_text(
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0"><dict>\n'
                    '  <key>CFBundleExecutable</key><string>Keys.ai</string>\n'
                    '  <key>CFBundleIdentifier</key>'
                    '<string>com.keysai.assistant</string>\n'
                    '  <key>CFBundleName</key><string>Keys.ai</string>\n'
                    '  <key>CFBundlePackageType</key><string>APPL</string>\n'
                    '  <key>CFBundleVersion</key><string>1.0</string>\n'
                    '</dict></plist>\n'
                )

                # Optional: copy icon as .icns (skip silently if Pillow is missing)
                try:
                    import PIL.Image
                    icns = res_dir / "AppIcon.icns"
                    PIL.Image.open(ico_path).save(icns, format="ICNS")
                    # Inject icon reference into plist
                    plist = app / "Contents" / "Info.plist"
                    txt = plist.read_text()
                    plist.write_text(
                        txt.replace(
                            '</dict></plist>',
                            '  <key>CFBundleIconFile</key>'
                            '<string>AppIcon</string>\n</dict></plist>\n',
                        )
                    )
                except Exception:
                    pass  # icon is optional

            # ── Linux — .desktop file (Terminal=false, no console) ────────────
            else:
                # Export .ico → .png for better desktop integration
                png_path = ico_path.with_suffix(".png")
                if not png_path.exists() and ico_path.exists():
                    try:
                        import PIL.Image
                        PIL.Image.open(ico_path).resize(
                            (256, 256), PIL.Image.LANCZOS
                        ).save(png_path, format="PNG")
                    except Exception:
                        png_path = ico_path  # fallback to .ico

                icon_line = f"Icon={png_path}\n" if png_path.exists() else ""
                desk = desktop / "Keys.ai.desktop"
                desk.write_text(
                    "[Desktop Entry]\n"
                    "Name=Keys.ai\n"
                    f"Exec={python} {script}\n"
                    f"Path={script.parent}\n"
                    "Type=Application\n"
                    "Terminal=false\n"
                    "Categories=Utility;\n"
                    + icon_line
                )
                desk.chmod(desk.stat().st_mode | 0o755)

            self._log.append_log("SYS: Desktop shortcut created.")
        except Exception as e:
            self._log.append_log(f"ERR: Shortcut failed — {e}")

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cw = self._backdrop
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 390
            self._overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        # Camera preview — bottom-right corner of the center/HUD area
        pw = _CameraPreview._W
        ph = self._cam_preview.height() or _CameraPreview._H
        self._cam_preview.setGeometry(
            cw.width() - _RIGHT_W - pw - 12,
            cw.height() - _CMD_BAR_H - ph - 14,
            pw, ph,
        )
    def _update_metrics(self):
        import psutil
        snap = _metrics.snapshot()

        # CPU
        cpu = snap["cpu"]
        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")

        # MEM
        mem = snap["mem"]
        self._bar_mem.set_value(mem, f"{mem:.0f}%")

        # NET
        net = snap["net"]
        if net < 1.0:
            net_str = f"{net*1024:.0f}KB/s"
        else:
            net_str = f"{net:.1f}MB/s"
        net_pct = min(100, net * 25)  # 4 MB/s = %100 — keeps the NET graph alive
        self._bar_net.set_value(net_pct, net_str)

        # GPU
        gpu = snap["gpu"]
        if gpu >= 0:
            self._bar_gpu.set_value(gpu, f"{gpu:.0f}%")
        else:
            self._bar_gpu.set_value(0, "N/A")

        # TMP
        tmp = snap["tmp"]
        if tmp >= 0:
            tmp_pct = min(100, (tmp / 100) * 100)
            self._bar_tmp.set_value(tmp_pct, f"{tmp:.0f}°C")
        else:
            self._bar_tmp.set_value(0, "N/A")

        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            self._uptime_lbl.setText("UP  --:--")

        try:
            proc_count = len(psutil.pids())
            self._proc_lbl.setText(f"PROC  {proc_count}")
        except Exception:
            self._proc_lbl.setText("PROC  --")


    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(54)
        w.setStyleSheet("background: transparent; border-bottom: 1px solid rgba(255, 215, 0, 40);")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 0, 16, 0)

        def _badge(txt, color=C.TEXT_MED):
            l = QLabel(txt)
            l.setFont(QFont("Courier New", 8))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_badge("ACENDENCE VII [GEN I]", C.PRI_DIM))
        lay.addStretch()

        mid = QVBoxLayout(); mid.setSpacing(1)
        title = QLabel("KEYS.AI")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Courier New", 17, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        mid.addWidget(title)
        sub = QLabel("ACENDENCE VII [GEN I]")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setFont(QFont("Courier New", 7))
        sub.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        mid.addWidget(sub)
        lay.addLayout(mid)
        lay.addStretch()

        right_col = QVBoxLayout(); right_col.setSpacing(2)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont("Courier New", 7))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)

        # Google account: sign in / sign out right from the header.
        self._google_btn = QPushButton("◉ SIGN IN WITH GOOGLE")
        self._google_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._google_btn.setFixedHeight(20)
        self._google_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._google_btn.setStyleSheet(f"""
            QPushButton {{
                color: {C.PRI_DIM}; background: transparent;
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
                padding: 0 8px;
            }}
            QPushButton:hover {{
                color: {C.PRI}; border: 1px solid {C.PRI};
                background: {C.PRI_GHO};
            }}
            QPushButton:disabled {{ color: {C.TEXT_DIM}; border-color: {C.BORDER}; }}
        """)
        self._google_btn.clicked.connect(self._toggle_google)
        right_col.addWidget(self._google_btn, 0, Qt.AlignmentFlag.AlignRight)

        lay.addLayout(right_col)
        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))
        # Keep the header Google button in sync with voice-triggered sign-ins
        # (google_account tool) — cheap file check, throttled to ~5 s.
        if getattr(self, "_google_btn", None) is not None:
            now = time.monotonic()
            if now - getattr(self, "_google_last_refresh", 0.0) > 5.0:
                self._google_last_refresh = now
                self._refresh_google_btn()

    # ── Google sign in / out (header button) ────────────────────────────────
    def _toggle_google(self):
        """Header button: open the Google Accounts manager — a proper UI to
        add MULTIPLE accounts, switch the active one, remove or sign out."""
        self._open_google_accounts()

    # ── Centre views: the one place features open ────────────────────────
    #
    # The camera opened in the middle of the HUD and every other workspace
    # floated over the whole window instead. They all open here now: the view
    # replaces the HUD in the centre column, the panels around it stay usable,
    # and CLOSE (or the right-panel button again) brings the HUD back.
    def _show_center_view(self, attr: str, factory, label: str):
        """Make the workspace held under `attr` the visible centre view.

        Built once, lazily, on first open — a broken optional module reports
        itself in the activity log instead of stopping the main window.
        """
        view = getattr(self, attr, None)
        if view is None:
            try:
                view = factory()
            except Exception as exc:
                self._log.append_log(f"ERR: {label} unavailable — {exc}")
                return None
            view.setParent(self._center_stack)
            setattr(self, attr, view)
            closed = getattr(view, "closed", None)
            if closed is not None:
                closed.connect(lambda: self._show_hud_view())
            self._center_stack.addWidget(view)
        self._center_stack.setCurrentWidget(view)
        self._sync_globe_rendering(attr)
        return view

    def _show_hud_view(self):
        """Back to the animated HUD face."""
        self._center_stack.setCurrentWidget(self.hud)
        self._sync_globe_rendering("")

    def _sync_globe_rendering(self, visible_attr: str = "") -> None:
        """Only a globe that is on screen may render.

        The globe page parks itself when Chromium reports it hidden, but a page
        swapped out of the centre stack is never reported hidden — so without
        this the globe keeps drawing at full rate behind the HUD and the whole
        window competes with a globe nobody is looking at.
        """
        try:
            globe_ws = getattr(self, "_globe_ws", None)
            if globe_ws is None:
                return
            if visible_attr == "_globe_ws":
                globe_ws.resume()
            else:
                globe_ws.pause()
        except Exception:
            # A window assembled without full Qt initialisation (the UI tests do
            # this) has no globe widget to synchronise; nothing to do.
            pass

    # ── AI Image Studio (local ComfyUI generation) ──────────────────────
    def _open_image_studio(self):
        """Open the local image-generation studio in the centre view.

        Imported lazily: PyQt6, Pillow and requests are already loaded, but the
        studio module also references the ComfyUI client — keeping the import
        inside this method means a broken optional piece can never prevent the
        main window from starting.
        """
        def _factory():
            from core.image_studio.studio_ui import ImageStudioPanel
            return ImageStudioPanel()

        self._show_center_view("_image_studio", _factory, "AI Image Studio")

    def _open_research_browser(self):
        """Open the browser workspace in the centre view.

        Imported lazily so a missing optional engine can never stop the main
        window from starting; the browser service is shared with the agent's
        tools, so both act on the same page.

        This is now the app's live research + web-preview surface: research
        tasks drive it through ``core.research_browser.tools``, and built pages
        are previewed here instead of in the creation workspace's below section.
        """
        try:
            from core.research_browser import tools as _rb_tools
            _rb_tools.register_ui(self)
        except Exception:
            pass

        def _factory():
            from core.research_browser.workspace_ui import BrowserWorkspace
            return BrowserWorkspace()

        self._show_center_view("_research_browser", _factory, "Research Browser")
    def run_on_gui_thread(self, fn, timeout: float = 180.0):
        """Run `fn` on the Qt GUI thread and return its result (any thread)."""
        app = QApplication.instance()
        if app is None or QThread.currentThread() is app.thread():
            return fn()
        box: dict = {}
        done = threading.Event()

        def _job():
            try:
                box["value"] = fn()
            except BaseException as exc:       # re-raised in the calling thread
                box["error"] = exc
            finally:
                done.set()

        self._gui_call_sig.emit(_job)          # queued → runs in the Qt event loop
        if not done.wait(timeout):
            raise TimeoutError("The UI did not answer in time.")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def _run_gui_call(self, job) -> None:
        job()

    def _open_research_browser(self):
        """Open the browser workspace in the centre view.

        Imported lazily so a missing optional engine can never stop the main
        window from starting; the browser service is shared with the agent's
        tools, so both act on the same page.

        This is now the app's live research + web-preview surface: research
        tasks drive it through ``core.research_browser.tools``, and built pages
        are previewed here instead of in the creation workspace's below section.
        """
        try:
            from core.research_browser import tools as _rb_tools
            _rb_tools.register_ui(self)
        except Exception:
            pass

        def _factory():
            from core.research_browser.workspace_ui import BrowserWorkspace
            return BrowserWorkspace()

        self._show_center_view("_research_browser", _factory, "Research Browser")

    @staticmethod
    def _open_research_tab(url: str) -> object:
        """Open a tab in the research browser from any thread (agent-facing).

        Thin wrapper over the browser tools so Crown Code's research step can
        open pages without importing tool internals directly. Returns the tab
        id object the tools use; the caller should prefer the higher-level
        ``core.research_browser.tools`` actions for anything beyond open/navigate.
        """
        from core.research_browser.tools import execute
        return execute({"action": "open_tab", "url": url}, player=None)

    # ── God's Eye View (globe) ──────────────────────────────────────────
    # There is no globe button, by design. The workspace is opened only by the
    # agent — from the `globe` tool, which text and voice commands both reach.
    def _open_globe_workspace(self, url: str) -> dict:
        """Show the globe workspace in the centre view, pointed at `url`.

        Called on the Qt GUI thread by globe.service. Returns a plain dict so
        the service can report a real failure instead of a silent no-op.
        """
        try:
            from globe import tools as _globe_tools
            _globe_tools.register_ui(self)
        except Exception as exc:
            self._log.append_log(f"ERR: globe module unavailable — {exc}")
            return {"ok": False, "error": f"The globe module is unavailable: {exc}"}

        def _factory():
            from globe.workspace_ui import GlobeWorkspace
            return GlobeWorkspace()

        view = self._show_center_view("_globe_ws", _factory, "God's Eye View")
        if view is None:
            return {"ok": False, "error": "The globe workspace could not be created."}
        if not getattr(view, "available", False):
            return {
                "ok": False,
                "error": "QtWebEngine is not installed, so the globe cannot render.",
            }
        view.load(url)
        return {"ok": True, "url": url}

    @staticmethod
    def _open_globe(url: str = "") -> dict:
        """Open the globe from any thread (agent-facing)."""
        from globe import tools as _globe_tools
        params = {"action": "open"}
        if url:
            params["location"] = url
        return {"spoken": _globe_tools.globe(params)}

    def _open_google_accounts(self):
        if (getattr(self, "_google_overlay", None) is not None
                and self._google_overlay.isVisible()):
            self._google_overlay.close()
            self._google_overlay = None
            return
        ov = GoogleAccountsOverlay(self._backdrop)
        cw = self._backdrop
        ow, oh = 470, 440
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.on_change = self._on_google_result
        ov.show()
        self._google_overlay = ov

    def _on_google_result(self, msg: str):
        self._google_busy = False
        self._google_btn.setEnabled(True)
        self._refresh_google_btn()
        self._log.append_log(f"SYS: {msg[:160]}")
        ov = getattr(self, "_google_overlay", None)
        if ov is not None and ov.isVisible():
            ov.refresh()

    def _refresh_google_btn(self):
        # Don't clobber the "OPENING BROWSER…" / "SIGNING OUT…" label while an
        # in-flight operation is showing.
        if getattr(self, "_google_busy", False):
            return
        try:
            from core import firebase_client as fb
            signed = fb.is_signed_in()
        except Exception:
            signed = False
        if signed:
            self._google_btn.setText("✓ GOOGLE: ON")
            self._google_btn.setToolTip("Signed in with Google — click to sign out")
            self._google_btn.setStyleSheet(f"""
                QPushButton {{
                    color: {C.GREEN}; background: rgba(0, 255, 136, 12);
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                    padding: 0 8px;
                }}
                QPushButton:hover {{ background: rgba(0, 255, 136, 30); }}
            """)
        else:
            self._google_btn.setText("◉ SIGN IN WITH GOOGLE")
            self._google_btn.setToolTip("Connect your Google account — click to sign in")
            self._google_btn.setStyleSheet(f"""
                QPushButton {{
                    color: {C.PRI_DIM}; background: transparent;
                    border: 1px solid {C.PRI_DIM}; border-radius: 3px;
                    padding: 0 8px;
                }}
                QPushButton:hover {{
                    color: {C.PRI}; border: 1px solid {C.PRI};
                    background: {C.PRI_GHO};
                }}
            """)

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(6)

        hdr = QLabel("◈ SYS MONITOR")
        hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent; "
                          "border-bottom: 1px solid rgba(255, 215, 0, 45); padding-bottom: 4px;")
        lay.addWidget(hdr)
        lay.addSpacing(2)

        self._bar_cpu = MetricGraph("CPU", C.PRI)
        self._bar_mem = MetricGraph("MEM", C.ACC2)
        self._bar_net = MetricGraph("NET", C.GREEN)
        self._bar_gpu = MetricGraph("GPU", C.ACC)
        self._bar_tmp = MetricGraph("TMP", "#ff6688")

        for bar in [self._bar_cpu, self._bar_mem, self._bar_net,
                    self._bar_gpu, self._bar_tmp]:
            lay.addWidget(bar)

        lay.addSpacing(4)

        info_panel = QWidget()
        info_panel.setStyleSheet(
            "background: rgba(17, 17, 17, 55); border: 1px solid rgba(255, 215, 0, 50);"
            " border-radius: 4px;"
        )
        ip_lay = QVBoxLayout(info_panel)
        ip_lay.setContentsMargins(6, 5, 6, 5)
        ip_lay.setSpacing(3)

        self._uptime_lbl = QLabel("UP  --:--")
        self._uptime_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._uptime_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent; border: none;")
        ip_lay.addWidget(self._uptime_lbl)

        self._proc_lbl = QLabel("PROC  --")
        self._proc_lbl.setFont(QFont("Courier New", 8))
        self._proc_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        ip_lay.addWidget(self._proc_lbl)

        os_name = {"Windows": "WIN", "Darwin": "macOS", "Linux": "LINUX"}.get(_OS, _OS.upper())
        os_lbl = QLabel(f"OS  {os_name}")
        os_lbl.setFont(QFont("Courier New", 8))
        os_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent; border: none;")
        ip_lay.addWidget(os_lbl)

        lay.addWidget(info_panel)
        lay.addSpacing(4)

        lay.addStretch()

        for txt, col in [
            ("AI CORE\nACTIVE",     C.GREEN),
            ("SEC\nCLEARED",        C.PRI),
        ]:

            lbl = QLabel(txt)
            lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"color: {col}; background: rgba(17, 17, 17, 55);"
                f"border: 1px solid rgba(255, 193, 7, 80); border-radius: 3px; padding: 4px;"
            )
            lay.addWidget(lbl)

        return w
    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        def _sec(txt):
            l = QLabel(f"▸ {txt}")
            l.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            l.setStyleSheet(
                f"color: {C.PRI}; background: rgba(255, 215, 0, 12);"
                " border: 1px solid rgba(255, 215, 0, 45); border-radius: 3px;"
                " padding: 2px 6px;"
            )
            return l

        lay.addWidget(_sec("ACTIVITY LOG"))
        self._log = LogWidget()
        lay.addWidget(self._log, stretch=3)

        sep0 = QFrame(); sep0.setFrameShape(QFrame.Shape.HLine)
        sep0.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep0)

        # ── Agent Control Mode: status pill + history + controls ─────────
        lay.addWidget(_sec("AGENT CONTROL"))
        self._ctrl_pill = QLabel("KEYS.AI • CONTROL RELEASED")
        self._ctrl_pill.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._ctrl_pill.setStyleSheet(f"""
            QLabel {{
                color: {C.GREEN}; background: rgba(5, 6, 10, 85);
                border: 1px solid {C.GREEN_D}; border-radius: 3px;
                padding: 3px 6px;
            }}
        """)
        lay.addWidget(self._ctrl_pill)

        ctrl_row = QHBoxLayout(); ctrl_row.setSpacing(4)
        _pause_btn = QPushButton("⏸ PAUSE")
        _stop_btn = QPushButton("■ STOP")
        for b, col in ((_pause_btn, C.PRI), (_stop_btn, C.RED)):
            b.setFixedHeight(24)
            b.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(5,6,10,85); color: {col};
                    border: 1px solid {col}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: rgba(255,255,255,14); }}
            """)
        _pause_btn.clicked.connect(self._ctrl_pause)
        _stop_btn.clicked.connect(self._ctrl_stop)
        ctrl_row.addWidget(_pause_btn)
        ctrl_row.addWidget(_stop_btn)
        lay.addLayout(ctrl_row)

        hist_hdr = QHBoxLayout(); hist_hdr.setSpacing(4)
        hist_lbl = QLabel("CONTROL HISTORY")
        hist_lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hist_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        hist_hdr.addWidget(hist_lbl)
        hist_hdr.addStretch()
        clear_btn = QPushButton("CLEAR")
        clear_btn.setFixedHeight(18)
        clear_btn.setFont(QFont("Courier New", 7))
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 2px; padding: 0 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        clear_btn.clicked.connect(self._ctrl_history_clear)
        hist_hdr.addWidget(clear_btn)
        lay.addLayout(hist_hdr)

        self._ctrl_history = _FadeTextEdit()
        self._ctrl_history.setReadOnly(True)
        self._ctrl_history.setFont(QFont("Courier New", 7))
        self._ctrl_history.setFixedHeight(96)
        self._ctrl_history.setPlaceholderText("(control history is empty)")
        self._ctrl_history.setStyleSheet(f"""
            QTextEdit {{
                background: rgba(5, 6, 10, 80); color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px;
            }}
            QScrollBar:vertical {{ background: transparent; width: 4px; border: none; }}
            QScrollBar::handle:vertical {{
                background: rgba(217, 182, 80, 110); border-radius: 2px;
            }}
        """)
        lay.addWidget(self._ctrl_history)

        set_btn = QPushButton("⚙  AGENT SETTINGS  (humour / confirmations)")
        set_btn.setFixedHeight(24)
        set_btn.setFont(QFont("Courier New", 7))
        set_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{
                color: {C.ACC2}; border: 1px solid {C.BORDER_B};
            }}
        """)
        set_btn.clicked.connect(self._open_agent_settings)
        lay.addWidget(set_btn)

        api_btn = QPushButton("◈  AI PROVIDER / API KEY")
        api_btn.setFixedHeight(24)
        api_btn.setFont(QFont("Courier New", 7))
        api_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        api_btn.setStyleSheet("""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{
                color: {C.ACC2}; border: 1px solid {C.BORDER_B};
            }}
        """.format(C=C))
        api_btn.clicked.connect(self._show_setup)
        lay.addWidget(api_btn)

        studio_btn = QPushButton("◈  AI IMAGE STUDIO")
        studio_btn.setFixedHeight(24)
        studio_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        studio_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        studio_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI};
            }}
        """)
        studio_btn.clicked.connect(self._open_image_studio)
        lay.addWidget(studio_btn)


        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        fs_btn = QPushButton("⛶  FULLSCREEN  [F11]")
        fs_btn.setFixedHeight(26)
        fs_btn.setFont(QFont("Courier New", 7))
        fs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fs_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{
                color: {C.PRI}; border: 1px solid {C.BORDER_B};
            }}
        """)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(fs_btn)

        sc_btn = QPushButton("⊞  CREATE DESKTOP SHORTCUT")
        sc_btn.setFixedHeight(26)
        sc_btn.setFont(QFont("Courier New", 7))
        sc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sc_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{
                color: {C.ACC2}; border: 1px solid {C.BORDER_B};
            }}
        """)
        sc_btn.clicked.connect(self._create_desktop_shortcut)
        lay.addWidget(sc_btn)

        return w

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(5)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command or question…")
        self._input.setFont(QFont("Courier New", 9))
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(0, 13, 20, 90); color: {C.WHITE};
                border: 1px solid rgba(255, 215, 0, 60); border-radius: 3px; padding: 3px 7px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(30, 30)
        send.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 215, 0, 25); color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: rgba(255, 215, 0, 55); border: 1px solid {C.PRI}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_command_bar(self) -> QWidget:
        """Full-width bottom command bar — chat input, interrupt, and mute."""
        w = QWidget()
        w.setFixedHeight(_CMD_BAR_H)
        w.setStyleSheet("background: transparent; border-top: 1px solid rgba(255, 215, 0, 40);")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(8)

        lay.addLayout(self._build_input_row(), stretch=1)

        self._interrupt_btn = QPushButton("✋  INTERRUPT  [ESC]")
        self._interrupt_btn.setFixedHeight(34)
        self._interrupt_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._interrupt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._interrupt_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(20, 0, 8, 90); color: {C.MUTED_C};
                border: 1px solid rgba(136, 136, 136, 140); border-radius: 3px;
            }}
            QPushButton:hover {{
                background: rgba(40, 0, 16, 140); border: 1px solid #ff6688;
            }}
            QPushButton:pressed {{
                background: rgba(60, 0, 24, 160);
            }}
        """)
        self._interrupt_btn.clicked.connect(self._do_interrupt)
        lay.addWidget(self._interrupt_btn)

        self._mute_btn = QPushButton("🎙  MICROPHONE ACTIVE")
        self._mute_btn.setFixedHeight(34)
        self._mute_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        self._mini_btn = QPushButton("◆  MINI OVERLAY  [F5]")
        self._mini_btn.setFixedHeight(34)
        self._mini_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._mini_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mini_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(10, 20, 10, 90); color: #8FE3A0;
                border: 1px solid rgba(140, 227, 160, 130); border-radius: 3px;
            }}
            QPushButton:hover {{
                background: rgba(16, 40, 24, 140); border: 1px solid #8FE3A0;
            }}
            QPushButton:pressed {{
                background: rgba(20, 60, 34, 160);
            }}
        """)
        self._mini_btn.clicked.connect(self._toggle_mini)
        lay.addWidget(self._mini_btn)

        return w

    def _build_content_panel(self) -> QWidget:
        """
        Stacked panel below the HUD:
          Index 0 — Original content panel (search, news, briefings, coding activity)
          Index 1 — Creation Workspace (live creation with split Activity|Code)
        Hidden by default; appears when show_content() or a creation starts.
        """
        self._content_stack = QStackedWidget()
        self._content_stack.setStyleSheet("background: transparent;")

        # ── Index 0: Original content panel (search/news/briefing) ────────────
        w = QWidget()
        w.setObjectName("ContentPanel")
        w.setStyleSheet(f"""
            QWidget#ContentPanel {{
                background: rgba(10, 10, 10, 80);
                border-top: 1px solid rgba(255, 215, 0, 45);
            }}
        """)
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 7, 12, 8)
        lay.setSpacing(5)

        hdr = QHBoxLayout(); hdr.setSpacing(6)
        dot = QLabel("◈")
        dot.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        dot.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(dot)
        self._content_title_lbl = QLabel("BRIEFING")
        self._content_title_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._content_title_lbl.setStyleSheet(
            f"color: {C.PRI}; background: transparent; letter-spacing: 1px;"
        )
        hdr.addWidget(self._content_title_lbl)
        hdr.addStretch()
        self._content_ts_lbl = QLabel("")
        self._content_ts_lbl.setFont(QFont("Courier New", 7))
        self._content_ts_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        hdr.addWidget(self._content_ts_lbl)
        dismiss = QPushButton("DISMISS  ✕")
        dismiss.setFont(QFont("Courier New", 7))
        dismiss.setFixedHeight(18)
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_DIM}; border: 1px solid {C.BORDER}; border-radius: 2px; padding: 0 5px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        dismiss.clicked.connect(w.hide)
        hdr.addWidget(dismiss)
        lay.addLayout(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); lay.addWidget(sep)

        self._content_display = _FadeTextEdit()
        self._content_display.setReadOnly(True)
        self._content_display.setFont(QFont("Courier New", 8))
        self._content_display.setMinimumHeight(60)
        self._content_display.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._content_display.setStyleSheet(f"""
            QTextEdit {{ background: transparent; color: {C.TEXT}; border: none; padding: 6px 8px; selection-background-color: {C.PRI_GHO}; }}
            QScrollBar:vertical {{ background: transparent; width: 6px; border: none; }}
            QScrollBar::handle:vertical {{ background: rgba(255, 215, 0, 140); border-radius: 3px; min-height: 16px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; }}
        """)
        lay.addWidget(self._content_display)
        self._content_panel = w
        self._content_stack.addWidget(w)  # index 0

        # ── Index 1: Creation Workspace ───────────────────────────────────────
        self._creation_ws = CreationWorkspace()
        self._content_stack.addWidget(self._creation_ws)  # index 1
        self._content_stack.setCurrentIndex(0)
        self._content_stack.hide()  # hidden until content or creation starts

        return self._content_stack

    def _show_content(self, title: str, text: str):
        """Slot — runs on Qt main thread. Updates and shows the content panel."""
        import time as _time
        # If creation workspace is active, don't interrupt it with search results
        if self._creation_ws.isVisible():
            return
        self._content_title_lbl.setText(title.upper()[:48])
        self._content_ts_lbl.setText(_time.strftime("%H:%M:%S"))
        self._content_display.setPlainText(text)
        self._content_display.moveCursor(
            self._content_display.textCursor().MoveOperation.Start
        )
        self._content_stack.setCurrentIndex(0)
        first_show = not self._content_stack.isVisible()
        self._content_stack.show()
        self._content_panel.show()
        if first_show:
            total = self._center_split.height()
            self._center_split.setSizes([max(total - 260, 120), 260])

    def _clear_coding_log(self):
        """Clear the coding activity panel — called at the start of each new user turn."""
        self._coding_active = False
        self._content_display.clear()
        self._content_title_lbl.setText("CODING ACTIVITY")

    # ── Creation workspace slots (connected to signals) ────────────────────
    def _on_cr_begin(self, mode: str, name: str, path: str):
        self._creation_ws.begin(mode, name, path)
        self._content_stack.setCurrentIndex(1)
        self._content_stack.show()
        total = self._center_split.height()
        self._center_split.setSizes([max(total - 340, 120), 340])

    def _on_cr_event(self, icon: str, text: str, file_or_empty: str):
        self._creation_ws.add_event(icon, text, file_or_empty or None)

    def _on_cr_file(self, path: str, lines: int, status: str):
        self._creation_ws.add_file(path, lines, status)

    def _on_cr_setfile(self, path: str):
        self._creation_ws.set_current_file(path)

    def _on_cr_code(self, chunk: str):
        self._creation_ws.append_code(chunk)

    def _on_cr_codeset(self, content: str):
        self._creation_ws.set_code(content)

    def _on_cr_progress(self, pct: float):
        self._creation_ws.set_progress(pct)

    def _on_cr_phase(self, name: str, pct: float, eta: float):
        self._creation_ws.set_phase(name, pct, eta)

    def _on_cr_error(self, text: str):
        self._creation_ws.error(text)

    def _on_cr_complete(self, summary: str):
        self._creation_ws.complete(summary)

    def _on_cr_reset(self):
        self._creation_ws.reset()
        self._content_stack.hide()
        self._center_split.setSizes([1, 0])

    def _toggle_live_coding(self):
        """F6 — show/hide the Live Coding console without discarding a run.

        The console opens by itself when a build starts; this is the way back
        to it when it was dismissed, or when a run has not reached its first
        event yet.
        """
        stack = self._content_stack
        # isHidden(), not isVisible(): a child of a minimised or not-yet-shown
        # window reports not-visible even when it is the wanted panel, which
        # would make F6 a no-op exactly when the user needs it.
        if stack.currentIndex() == 1 and not stack.isHidden():
            stack.hide()
            self._center_split.setSizes([1, 0])
            return
        if self._creation_ws.isHidden():
            self._creation_ws.show()
        stack.setCurrentIndex(1)
        stack.show()
        total = self._center_split.height()
        self._center_split.setSizes([max(total - 340, 120), 340])

    # ── Embedded terminal slots ────────────────────────────────────────────
    def _on_term_output(self, chunk: str, stream: str, origin: str):
        self._creation_ws.terminal_write(chunk, stream)

    def _on_term_clear(self):
        self._creation_ws.terminal_clear()

    def _on_term_cmd(self, command: str):
        handler = getattr(self, "_term_cmd_handler", None)
        if handler:
            try:
                handler(command)
            except Exception as e:
                self._creation_ws.terminal_write(f"[error] {e}\n", "stderr")

    def _on_term_stop(self):
        handler = getattr(self, "_term_stop_handler", None)
        if handler:
            try:
                handler()
            except Exception:
                pass

    def _on_cr_preview(self, url: str):
        """Preview a built site in the Research Browser.

        Keys.AI does not keep a second browser for previews: the research
        browser already hosts a real Chromium view, so the page that was just
        built is opened in the one surface the agent and the user share.
        """
        if not url:
            return
        try:
            self._open_research_browser()
            from core.research_browser.tools import execute as _rb_execute
            reply = str(_rb_execute({"action": "navigate_to_url", "url": url}, player=self))
            if reply.startswith("Could not navigate"):
                # A preview that was refused must say so instead of leaving an
                # empty page that looks like a broken build.
                self.add_event("!", f"Preview failed: {reply}", color="#F0A500")
                return
            try:
                self.add_event("🌐", f"Preview opened in the Research Browser: {url}",
                               color="#648CFF")
            except Exception:
                pass
        except Exception as exc:
            try:
                self.add_event("!", f"Preview failed: {exc}", color="#F0A500")
            except Exception:
                pass

    # ── Decision handlers ────────────────────────────────────────────────
    def _on_dec_ask(self, question: str, options: list, show_why: bool, why_text: str):
        """Show a DecisionWidget in the creation workspace activity panel."""
        if not self._creation_ws.isVisible():
            self._creation_ws.begin("code", "Decision", "")
        widget = DecisionWidget(question, options, show_why, why_text)
        # Insert before the stretch in the event layout
        self._creation_ws._event_layout.insertWidget(
            self._creation_ws._event_layout.count() - 1, widget)
        self._creation_ws._event_widgets.append(widget)
        # Scroll to it
        sb = self._creation_ws._event_scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
        # Connect answer signal
        widget.chosen.connect(self._on_dec_answer)
        # Show the creation workspace if hidden
        self._content_stack.setCurrentIndex(1)
        self._content_stack.show()

    def _on_dec_perm(self, action: str, reason: str, location: str):
        """Show a PermissionWidget in the creation workspace activity panel."""
        if not self._creation_ws.isVisible():
            self._creation_ws.begin("code", "Permission", "")
        widget = PermissionWidget(action, reason, location)
        self._creation_ws._event_layout.insertWidget(
            self._creation_ws._event_layout.count() - 1, widget)
        self._creation_ws._event_widgets.append(widget)
        sb = self._creation_ws._event_scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
        widget.decided.connect(self._on_dec_answer)
        self._content_stack.setCurrentIndex(1)
        self._content_stack.show()

    def _on_dec_answer(self, answer: str):
        """Store the answer and unblock the waiting thread."""
        self._dec_answer_val = answer
        self._dec_answered.set()

    def _append_coding_log(self, text: str):
        """Append a coding activity line to the content panel.
        Auto-shows the panel on first line; stays visible until next user turn."""
        import time as _time

        # Show panel on first coding line
        if not self._coding_active:
            self._coding_active = True
            self._content_title_lbl.setText("CODING ACTIVITY")
            self._content_display.clear()
            self._content_panel.show()
            total = self._center_split.height()
            self._center_split.setSizes([max(total - 220, 120), 220])

        self._content_ts_lbl.setText(_time.strftime("%H:%M:%S"))

        # Color-code the line
        cur = self._content_display.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        if "Writing" in text or "write" in text.lower():
            col = qcol(C.GREEN)
        elif "Running" in text or "run" in text.lower():
            col = qcol(C.ACC)
        elif "Output" in text or "output" in text.lower():
            col = qcol(C.TEXT_MED)
        elif "error" in text.lower() or "failed" in text.lower():
            col = qcol(C.RED)
        elif "fix" in text.lower() or "retry" in text.lower():
            col = qcol(C.ACC2)
        else:
            col = qcol(C.TEXT)
        fmt = cur.charFormat()
        fmt.setForeground(QBrush(col))
        cur.insertText(text + "\n", fmt)
        self._content_display.setTextCursor(cur)
        self._content_display.ensureCursorVisible()

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(22)
        w.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(w); lay.setContentsMargins(14, 0, 14, 0)

        def _fl(txt, color=C.TEXT_MED):
            l = QLabel(txt); l.setFont(QFont("Courier New", 7))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_fl("[F4] Mute  ·  [F11] Fullscreen"))
        lay.addStretch()
        lay.addWidget(_fl("Harman Sadhwani  ·  ACENDENCE VII [GEN I]  ·  CLASSIFIED"))
        lay.addStretch()
        lay.addWidget(_fl("@CrownPierce.co.in", C.PRI_DIM))
        return w

    def _do_interrupt(self):
        if self.on_interrupt:
            self.on_interrupt()

    def _toggle_mini(self):
        """Enable/disable the background push-to-talk mini overlay (F5)."""
        mini = self._mini
        if mini is None:
            return
        if mini.is_enabled():
            mini.set_enabled(False)
            self._mini_btn.setText("◇  MINI OFF  [F5]")
            self._log.append_log("SYS: Mini overlay disabled.")
        else:
            mini.set_enabled(True)
            self._mini_btn.setText("◆  MINI OVERLAY  [F5]")
            self._log.append_log("SYS: Mini overlay enabled — hold K to talk.")
        tray_act = getattr(self, "_tray_mini_act", None)
        if tray_act is not None:
            tray_act.blockSignals(True)
            tray_act.setText(f"Mini overlay: {'ON' if mini.is_enabled() else 'OFF'}")
            tray_act.setChecked(mini.is_enabled())
            tray_act.blockSignals(False)

    # ── Agent Control Mode ─────────────────────────────────────────────
    def _ctrl_engine(self):
        return get_control_engine(bridge=self._ctrl_bridge)

    # ── Irreversible-action confirmation gate ──────────────────────────
    def _on_gate_show(self, title: str, detail: str) -> None:
        """Qt-thread slot: display the shared CONFIRM panel for a core.confirm
        request. The panel's TAKE CONTROL button acts as CANCEL here — it
        resolves to 'takeover', which the gate treats as not-confirmed."""
        panel = getattr(self, "_gate_panel", None)
        if panel is None:
            return
        try:
            from core import confirm as _gate
            if _gate.pending_title() == "":
                return   # request already resolved/expired before this shown
        except Exception:
            pass
        if self._gate_timer is not None:
            self._gate_timer.stop()
            self._gate_timer = None
        try:
            panel._title.setText(str(title).upper())
            panel._prompt.setText(str(detail))
            panel.adjustSize()
            par = panel.parentWidget()
            if par is not None:
                panel.move((par.width() - panel.width()) // 2,
                           (par.height() - panel.height()) // 2)
            panel.show()
            panel.raise_()
            self.show()
            self.raise_()
        except Exception as e:
            print(f"[ui] gate show failed: {e}")
        # Auto-expiry mirrors the gate's own TIMEOUT_SECONDS — after it, the
        # buttons stop meaning anything, so stop showing them.
        self._gate_timer = QTimer(self)
        self._gate_timer.setSingleShot(True)
        self._gate_timer.timeout.connect(self._on_gate_hide)
        self._gate_timer.start(90_000)

    def _on_gate_hide(self) -> None:
        panel = getattr(self, "_gate_panel", None)
        if panel is not None:
            try:
                panel.hide()
            except Exception:
                pass
        if self._gate_timer is not None:
            self._gate_timer.stop()
            self._gate_timer = None

    def _on_gate_resolved(self, result: str) -> None:
        """CONFIRM pressed — hand the answer to core.confirm.resolve(). Any
        other button (CANCEL / TAKE CONTROL) is not a confirmation."""
        self._on_gate_hide()
        try:
            from core import confirm as _gate
            _gate.resolve(str(result).lower() == "confirm")
        except Exception as e:
            print(f"[ui] gate resolve failed: {e}")

    def _ctrl_window_rect(self):
        """Rect provider for the overlay follow-timer (engine thread-safe read)."""
        try:
            eng = self._ctrl_engine()
            if getattr(eng, "_session_hwnd", 0):
                return eng._window_rect()
        except Exception:
            pass
        return None

    def _on_ctrl_status(self, text: str):
        """Bridge slot (Qt thread) — status pill + overlay status text."""
        t = str(text)
        self._ctrl_pill.setText(t)
        role = "#D9B650"   # gold
        up = t.upper()
        if "VERIFY" in up:
            role = "#4FD0E0"
        elif "USER" in up or "PAUSED" in up or "WAIT" in up:
            role = "#8FB8D8"
        elif "FAILED" in up or "STOP" in up:
            role = "#E5484D"
        elif "RELEASED" in up or "COMPLETED" in up:
            role = "#3DDC84"
        elif "RECOVER" in up:
            role = "#E09E50"
        self._ctrl_pill.setStyleSheet(f"""
            QLabel {{
                color: {role}; background: rgba(5, 6, 10, 85);
                border: 1px solid {role}; border-radius: 3px;
                padding: 3px 6px; font: bold 7pt 'Courier New';
            }}
        """)
        try:
            self._ctrl_overlay.set_status(t)
        except Exception:
            pass

    def _on_ctrl_history(self, entry: dict):
        """Bridge slot — one live history line into the panel."""
        try:
            icons = {"SUCCESS": "✓", "RUNNING": "●", "WAITING": "⚠",
                     "FAILED": "✕", "PAUSED": "⏸", "STOPPED": "■"}
            cols = {"SUCCESS": "#3DDC84", "RUNNING": "#E5C368",
                    "WAITING": "#8FB8D8", "FAILED": "#E5484D",
                    "PAUSED": "#A9B2C0", "STOPPED": "#E5484D"}
            st = entry.get("status", "RUNNING")
            line = (f"<span style='color:#6E7686'>{entry.get('time', '')}</span> "
                    f"<span style='color:{cols.get(st, '#E5C368')}'>{icons.get(st, '●')}</span> "
                    f"<span style='color:#8A6D2F'>{entry.get('app', '')}</span> "
                    f"{entry.get('action', '')}")
            if entry.get("detail"):
                line += f" <span style='color:#7A8494'>— {entry.get('detail')}</span>"
            self._ctrl_history.append(line)
            self._ctrl_history.verticalScrollBar().setValue(
                self._ctrl_history.verticalScrollBar().maximum())
        except Exception:
            pass

    def _ctrl_pause(self):
        try:
            self._ctrl_engine().pause(why="paused from the UI")
        except Exception as e:
            self._log.append_log(f"ERR: pause failed — {e}")

    def _ctrl_stop(self):
        try:
            self._ctrl_engine().stop()
            self._log.append_log("SYS: Agent control STOPPED from the UI.")
        except Exception as e:
            self._log.append_log(f"ERR: stop failed — {e}")

    def _ctrl_takeover(self):
        try:
            self._ctrl_engine().user_takeover()
        except Exception as e:
            self._log.append_log(f"ERR: takeover failed — {e}")

    def _ctrl_history_clear(self):
        try:
            from agent_control.action_log import get_history
            get_history().clear()
            self._ctrl_history.clear()
        except Exception as e:
            self._log.append_log(f"ERR: clear history failed — {e}")

    def _open_agent_settings(self):
        if self._ctrl_settings is not None:
            self._ctrl_settings.hide()
        ov = AgentSettingsOverlay(self._backdrop)
        cw = self._backdrop
        ow, oh = 380, 430
        ov.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)
        ov.show()
        self._ctrl_settings = ov

    def closeEvent(self, e):
        """Closing the main window hides it — the overlay keeps running in the tray.
        Also persists the current window geometry for next launch."""
        save_window_state(self, CONFIG_DIR / "window_state.json")
        self.hide()
        e.ignore()

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted.")
        else:
            self._apply_state("HOLD K TO TALK")
            self._log.append_log("SYS: Microphone active — hold K to talk.")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("🔇  MICROPHONE MUTED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(20, 0, 6, 170); color: {C.MUTED_C};
                    border: 1px solid rgba(136, 136, 136, 140); border-radius: 3px;
                }}
            """)
        else:
            self._mute_btn.setText("🎙  MICROPHONE ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(0, 20, 10, 170); color: {C.GREEN};
                    border: 1px solid rgba(0, 255, 136, 150); border-radius: 3px;
                }}
                QPushButton:hover {{ background: rgba(0, 31, 16, 210); }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_state(self, state: str):
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")
        tb = getattr(getattr(self, "_chrome", None), "title_bar", None)
        if tb is not None:
            tb.set_status(state, speaking=self.hud.speaking)

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            from core import api_config
            d = api_config.load_config()
            if not d.get("os_system"):
                return False
            return api_config.has_api_key(d.get("llm_provider") or "gemini")
        except Exception:
            return False

    def _show_setup(self):
        """Open the AI provider / API-key overlay (first boot or manual)."""
        from core import api_config
        ov = SetupOverlay(self._backdrop, initial=api_config.load_config())
        cw = self._backdrop
        ow, oh = 500, 560
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _on_setup_done(self, provider: str, key: str, model: str,
                       base_url: str, os_name: str):
        from core import api_config
        api_config.set_provider(provider, model=model, api_key=key,
                                base_url=base_url)
        api_config.save_config({"os_system": os_name})   # merge, never wipe
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("HOLD K TO TALK")
        self._log.append_log(
            f"SYS: Initialised. Provider={provider} model={model} OS={os_name.upper()}."
        )

class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()



class KeysAIUI:
    def __init__(self, face_path: str, size=None, show_main: bool = True):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        # Keep the process alive when the main window is hidden — the mini
        # overlay keeps running in the background on its own.
        self._app.setQuitOnLastWindowClosed(False)
        _ensure_gui_imports()
        self._win = MainWindow(face_path)
        if show_main:
            self._win.show()
        self.root = _RootShim(self._app)
        # Background push-to-talk overlay — rides the same engine session.
        # Enabled by default, but tucked away until K is pressed.
        self._mini = MiniOverlay(self._win)
        self._win._mini = self._mini
        self._mini.show_ready()
        self._app.aboutToQuit.connect(self._mini.shutdown)
        self._app.aboutToQuit.connect(self._shutdown_image_studio)
        self._setup_tray()
        self._setup_agent_control()

    def _shutdown_image_studio(self) -> None:
        """Stop studio timers and cancel in-flight generations on app exit.

        A ComfyUI server started by Keys.AI is terminated by the backend
        manager's own atexit hook — only that child process, never another.
        """
        for attr in ("_image_studio", "_research_browser", "_globe_ws"):
            overlay = getattr(self._win, attr, None)
            if overlay is not None:
                try:
                    overlay.shutdown()
                except Exception:
                    pass
        # The globe runs as its own local Node service. Stopping it here stops
        # only a server Keys.AI started; an adopted one is left alone.
        try:
            from globe import get_service as _globe_service
            _globe_service().shutdown()
        except Exception:
            pass
        try:
            from universal_agent import get_service as _agent_service
            _agent_service().cancel_all()
        except Exception:
            pass
        try:
            from core.image_studio import get_service
            get_service().shutdown()
        except Exception:
            pass
        try:
            from core.research_browser import get_service as _rb_service
            _rb_service().shutdown()
        except Exception:
            pass

    def _setup_agent_control(self) -> None:
        """Create the AppControlEngine bound to the UI bridge, refresh the
        control-history panel and start the global ESC emergency hook."""
        try:
            from agent_control.app_control import init_control_system
            from agent_control.action_log import get_history
            init_control_system(bridge=self._win._ctrl_bridge, player=self)
            # initial history fill (past entries may predate the UI)
            for e in get_history().recent(40):
                self._win._on_ctrl_history(e)
            self._win._log.append_log(
                "SYS: Agent Control Mode ready — ESC / STOP always wins.")
        except Exception as e:
            print(f"[Keys.ai] Agent Control init failed: {e}")
            try:
                self._win._log.append_log(f"SYS: Agent Control unavailable — {e}")
            except Exception:
                pass

    def _setup_tray(self):
        """System tray icon so the overlay survives with the main UI hidden."""
        self._tray = None
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return
            self._tray = QSystemTrayIcon(self._app)
            self._tray.setIcon(self._win.windowIcon())
            menu = QMenu()
            act_show = menu.addAction("Show KeysAI")
            act_show.triggered.connect(self._show_main_win)
            self._tray_mini_act = menu.addAction("Mini overlay: ON")
            self._tray_mini_act.setCheckable(True)
            self._tray_mini_act.setChecked(True)
            self._tray_mini_act.toggled.connect(self._tray_toggle_mini)
            menu.addSeparator()
            act_quit = menu.addAction("Quit")
            act_quit.triggered.connect(self._app.quit)
            self._tray.setContextMenu(menu)
            self._tray.setToolTip("Keys.ai — hold K to talk")
            self._tray.show()
            self._win._tray_mini_act = self._tray_mini_act
        except Exception as e:
            print(f"[Keys.ai] Tray unavailable: {e}")
            self._tray = None

    def _show_main_win(self):
        # Tray menu path — reuse the same signal as show_main_window.
        self._win._show_req_sig.emit()

    def show_main_window(self) -> None:
        """Thread-safe: bring the main UI window to the front from any thread.
        Used by the open_app tool when the user asks to open Keys.ai / the main UI."""
        self._win._show_req_sig.emit()

    def _tray_toggle_mini(self, on: bool):
        mini = self._win._mini
        if mini is None or mini.is_enabled() == on:
            return
        self._win._toggle_mini()

    @property
    def main_ptt_active(self) -> bool:
        return self._win.main_ptt_active

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_interrupt(self):
        return self._win.on_interrupt

    @on_interrupt.setter
    def on_interrupt(self, cb):
        self._win.on_interrupt = cb

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def set_status_line(self, text: str):
        """One dim line under the HUD showing what the assistant is doing"""
        self._win._status_line_sig.emit(str(text or ""))

    def set_hud_level(self, level: float):
        """Push a live audio level into the HUD avatar (thread-safe)."""
        self._win._hud_level_sig.emit(float(level))

    def run_on_gui_thread(self, fn, timeout: float = 180.0):
        """Run `fn` on the Qt GUI thread and return its result (thread-safe).

        Needed by anything that has to touch QtWebEngine, which is GUI-thread
        only — see MainWindow.run_on_gui_thread.
        """
        return self._win.run_on_gui_thread(fn, timeout=timeout)

    def avatar_glance(self, dx: float, dy: float, hold: float = 1.1):
        """Ask the avatar to look toward (dx, dy) for a moment (thread-safe)."""
        try:
            self._win.hud.avatar_glance(dx, dy, hold)
        except Exception:
            pass

    def write_log(self, text: str):
        self._win._log_sig.emit(text)
        # Clear coding panel at the start of each new user turn
        if text.startswith("You:"):
            try:
                self._win._coding_clear_sig.emit()
            except Exception:
                pass
        # Auto-push coding activity to the content panel below the HUD
        if text.startswith("[Code]") or text.startswith("[DevAgent]"):
            try:
                self._win._coding_log_sig.emit(text)
            except Exception:
                pass

    def set_elevation_status(self, status: dict):
        """Surface the current privilege state in the UI (title-bar badge).
        Called from main() at startup and refreshable anytime."""
        self._elevation = status or {}
        try:
            tb = self._win._chrome.title_bar
            if self._elevation.get("elevated"):
                tb.set_status("ADMIN MODE", speaking=False)
                tb.set_privilege(True)
            else:
                tb.set_status("ONLINE", speaking=False)
                tb.set_privilege(False)
        except Exception:
            pass

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def show_content(self, title: str, text: str):
        """Thread-safe: display content in the panel below the HUD."""
        self._win._content_sig.emit(title[:48], text[:4000])

    def prompt_reconfig(self):
        """Thread-safe: show the API key setup overlay (e.g. after an auth error)."""
        self._win._ready = False
        self._win._reconfig_sig.emit()

    def show_camera_frame(self, img_bytes: bytes):
        """Thread-safe: show a webcam frame in the small overlay (screen captures)."""
        self._win._camera_sig.emit(img_bytes)

    def start_camera_stream(self) -> None:
        """Thread-safe: start live camera feed in the full HUD area."""
        self._win.start_camera_stream()

    def stop_camera_stream(self) -> None:
        """Thread-safe: stop the live camera feed."""
        self._win.stop_camera_stream()

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("HOLD K TO TALK")

    # ── Creation Workspace API (thread-safe) ───────────────────────────────
    def begin_creation(self, mode: str, project_name: str, project_path: str):
        """Start a live creation session. mode: code|ppt|excel|doc|txt"""
        self._win._cr_begin_sig.emit(mode, project_name, project_path)

    def creation_event(self, icon: str, text: str, file: str = None):
        """Add an event to the creation timeline. icon: ✓→!✕"""
        self._win._cr_event_sig.emit(icon, text, file or "")

    def creation_file_add(self, path: str, lines: int = 0, status: str = "done"):
        """Register a file in the file list."""
        self._win._cr_file_sig.emit(path, lines, status)

    def creation_file_set_active(self, path: str):
        """Switch the active file in the code viewer."""
        self._win._cr_setfile_sig.emit(path)

    def creation_code_append(self, chunk: str):
        """Stream a chunk of code to the live viewer."""
        self._win._cr_code_sig.emit(chunk)

    def creation_code_set(self, content: str):
        """Replace the entire code viewer content."""
        self._win._cr_codeset_sig.emit(content)

    def creation_progress(self, pct: float):
        """Update creation progress (0.0 to 1.0)."""
        self._win._cr_progress_sig.emit(pct)

    def creation_error(self, text: str):
        """Show an error in the creation timeline."""
        self._win._cr_error_sig.emit(text)

    def creation_phase(self, name: str, pct: float = -1.0, eta: float = 0.0):
        """Show the build phase, percent and ETA in the creation header."""
        self._win._cr_phase_sig.emit(name or "", float(pct), float(eta))

    def creation_complete(self, summary: str = ""):
        """Mark creation as complete."""
        self._win._cr_complete_sig.emit(summary)

    def creation_preview(self, url: str):
        """Load a URL in the web preview panel."""
        self._win._cr_preview_sig.emit(url)

    def creation_reset(self):
        """Clear and hide the creation workspace."""
        self._win._cr_reset_sig.emit()

    # ── Embedded terminal API (thread-safe) ────────────────────────────────
    def terminal_output(self, chunk: str, stream: str = "stdout", origin: str = "agent"):
        """Stream terminal output into the embedded terminal panel."""
        self._win._term_output_sig.emit(chunk or "", stream or "stdout", origin or "agent")

    def terminal_clear(self):
        self._win._term_clear_sig.emit()

    def set_terminal_command_handler(self, cb):
        """Register the callable that executes user-typed terminal commands."""
        self._win._term_cmd_handler = cb

    def set_terminal_stop_handler(self, cb):
        """Register the callable that stops the running task/command."""
        self._win._term_stop_handler = cb

    # ── Decision/Permission API (thread-safe, blocking) ──────────────────
    def ask_decision(self, question: str, options: list[str],
                     show_why: bool = False, why_text: str = "") -> str:
        """Ask the user a question with clickable options. Blocks until answered."""
        self._win._dec_answered.clear()
        self._win._dec_answer_val = ""
        self._win._dec_ask_sig.emit(question, options, show_why, why_text)
        # Block until user clicks an option (timeout 300s = 5 min)
        self._win._dec_answered.wait(timeout=300)
        return self._win._dec_answer_val or options[0] if options else ""

    def ask_permission(self, action: str, reason: str = "",
                       location: str = "") -> str:
        """Ask permission to perform an action. Blocks until approved/denied."""
        self._win._dec_answered.clear()
        self._win._dec_answer_val = ""
        self._win._dec_perm_sig.emit(action, reason, location)
        self._win._dec_answered.wait(timeout=300)
        return self._win._dec_answer_val or "deny"