"""Native Win32 controller — application & window discovery, window management,
privilege detection. Pure ctypes (user32/kernel32/advapi32), zero third-party
deps, Windows-only (everything degrades gracefully elsewhere).

This is the "Native Win32 Controller" layer of the computer-use engine:

    • application discovery  — process / PID / executable / HWND / title /
                               visibility / min/max state / foreground state /
                               window rect / privilege level
    • window manager         — focus, minimize, maximize, restore, close, move,
                               resize, foreground & cursor queries
    • HWND is the stable target; multiple windows per process are disambiguated
      by title/class rather than picking the first match blindly.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Optional

_WINDOWS = platform.system() == "Windows"

# Lazy-loaded ctypes modules — loaded on first use, not at import time.
# This avoids triggering Windows permission prompts (UAC/camera/mic) at startup.
_user32 = None
_kernel32 = None
_ctypes = None
_wintypes = None
_EnumWindows = None
_EnumWindows_ready = False

SW_RESTORE = 9
SW_MINIMIZE = 6
SW_MAXIMIZE = 3
WM_CLOSE = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenElevation = 20
GWL_STYLE = -16
WS_VISIBLE = 0x10000000


def _ensure_win32():
    """Lazy-load ctypes DLLs on first use — avoids permission prompts at import."""
    global _user32, _kernel32, _ctypes, _wintypes, _EnumWindows, _EnumWindows_ready
    if _user32 is not None or not _WINDOWS:
        return
    try:
        import ctypes as _ct
        from ctypes import wintypes as _wt
        _ctypes = _ct
        _wintypes = _wt
        _user32 = _ct.windll.user32
        _kernel32 = _ct.windll.kernel32

        # ── signatures (64-bit HWND safety) ───────────────────────────────────
        _user32.GetWindowThreadProcessId.argtypes = [_wt.HWND, _ct.POINTER(_wt.DWORD)]
        _user32.GetWindowTextLengthW.argtypes = [_wt.HWND]
        _user32.GetWindowTextW.argtypes = [_wt.HWND, _wt.LPWSTR, _ct.c_int]
        _user32.GetClassNameW.argtypes = [_wt.HWND, _wt.LPWSTR, _ct.c_int]
        _user32.GetWindowRect.argtypes = [_wt.HWND, _ct.POINTER(_wt.RECT)]
        _user32.GetWindowLongW.argtypes = [_wt.HWND, _ct.c_int]
        _user32.GetForegroundWindow.restype = _wt.HWND
        _user32.GetCursorPos.argtypes = [_ct.POINTER(_wt.POINT)]
        _user32.SetForegroundWindow.argtypes = [_wt.HWND]
        _user32.ShowWindow.argtypes = [_wt.HWND, _ct.c_int]
        _user32.PostMessageW.argtypes = [_wt.HWND, _wt.UINT, _wt.WPARAM, _wt.LPARAM]
        _user32.MoveWindow.argtypes = [_wt.HWND, _ct.c_int, _ct.c_int,
                                       _ct.c_int, _ct.c_int, _wt.BOOL]
        _kernel32.OpenProcess.argtypes = [_wt.DWORD, _wt.BOOL, _wt.DWORD]
        _kernel32.OpenProcess.restype = _wt.HANDLE
        _kernel32.CloseHandle.argtypes = [_wt.HANDLE]

        _ENUM_CB = _ct.WINFUNCTYPE(_wt.BOOL, _wt.HWND, _wt.LPARAM)
        _user32.EnumWindows.argtypes = [_ENUM_CB, _wt.LPARAM]
        _EnumWindows = _ENUM_CB
        _EnumWindows_ready = True
    except Exception as e:
        print(f"[win32_native] Lazy ctypes init failed: {e}")
        _user32 = None  # mark as failed so we don't retry


@dataclass
class AppWindow:
    """A discovered top-level window, with its owning application's metadata."""

    hwnd: int = 0
    title: str = ""
    class_name: str = ""
    pid: int = 0
    process: str = ""                 # exe name, e.g. "Code.exe"
    executable: str = ""              # full path, when resolvable
    rect: tuple = (0, 0, 0, 0)        # (left, top, right, bottom)
    visible: bool = True
    minimized: bool = False
    maximized: bool = False
    foreground: bool = False
    elevated: Optional[bool] = None   # None = unknown / not queried
    owner: Optional[int] = None       # owner HWND if any

    @property
    def width(self) -> int:
        return max(0, self.rect[2] - self.rect[0])

    @property
    def height(self) -> int:
        return max(0, self.rect[3] - self.rect[1])

    @property
    def center(self) -> tuple[int, int]:
        return (self.rect[0] + self.width // 2, self.rect[1] + self.height // 2)

    def describe(self) -> str:
        bits = [f"'{self.title}'" if self.title else "(untitled)"]
        if self.process:
            bits.append(f"{self.process}[{self.pid}]")
        if self.hwnd:
            bits.append(f"hwnd={self.hwnd}")
        if self.minimized:
            bits.append("minimized")
        if self.maximized:
            bits.append("maximized")
        if self.foreground:
            bits.append("foreground")
        bits.append(f"({self.width}x{self.height})")
        return " ".join(bits)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["elevated"] = bool(self.elevated) if self.elevated is not None else None
        return d


class NativeController:
    """Thin, dependency-free controller over user32/kernel32 for discovery and
    window management. All methods return False / None / [] gracefully when the
    OS is not Windows or the call fails — the engine treats them as fallthrough
    signals, never crashes."""

    def __init__(self, use_psutil: bool = True) -> None:
        self._use_psutil = use_psutil
        self._psutil_ok = None

    # ── capability ────────────────────────────────────────────────────────
    @staticmethod
    def available() -> bool:
        return _WINDOWS
    # ── discovery ─────────────────────────────────────────────────────────
    def list_windows(self, visible_only: bool = True, limit: int = 200,
                     include_owner: bool = False) -> list[AppWindow]:
        """Enumerate top-level windows with full app metadata.

        Uses HWND as the stable key and attaches the owning process's exe path.
        Owned windows (popups/dialogs) are excluded by default so we don't
        report every dialog as a separate application.
        """
        if not _WINDOWS:
            return []
        out: list[AppWindow] = []
        fg = self.foreground_hwnd()
        state = {"limit": limit}

        def _cb(hwnd, _lparam):
            if len(out) >= state["limit"]:
                return False
            h = int(hwnd)
            try:
                owner = int(_user32.GetWindow(hwnd, 4))   # GW_OWNER
                if owner and not include_owner:
                    return True
                pid = wintypes.DWORD()
                _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                w = AppWindow(
                    hwnd=h,
                    title=self._window_text(h),
                    class_name=self._class_name(h),
                    pid=int(pid.value),
                    rect=self._window_rect(h),
                    visible=bool(_user32.GetWindowLongW(hwnd, _GWL_STYLE) & _WS_VISIBLE),
                    minimized=bool(_user32.IsIconic(hwnd)),
                    maximized=bool(_user32.IsZoomed(hwnd)),
                    foreground=(h == fg),
                    owner=owner,
                )
                if visible_only and not w.visible:
                    return True
                self._attach_process(w)
                out.append(w)
            except Exception:
                pass
            return True

        cb = _ENUM_CB(_cb)
        try:
            _user32.EnumWindows(cb, 0)
        except Exception:
            pass
        return out

    def window_by_title(self, fragment: str) -> Optional[AppWindow]:
        """Find the most relevant window for a title fragment.

        Prefers an exact match, then a foreground window, then the first
        visible match. Never blindly returns the first process hit.
        """
        fragment = (fragment or "").strip().lower()
        if not fragment:
            return None
        exact = fg_match = first = None
        for w in self.list_windows():
            t = (w.title or "").lower()
            if t == fragment:
                exact = w
                break
            if fragment in t:
                if w.foreground:
                    fg_match = w
                if first is None:
                    first = w
        return exact or fg_match or first

    def window_by_pid(self, pid: int, title_fragment: str = "") -> Optional[AppWindow]:
        """Pick the correct window of a process when it has several."""
        matches = [w for w in self.list_windows() if w.pid == pid]
        if not matches:
            return None
        if title_fragment:
            for w in matches:
                if title_fragment.lower() in (w.title or "").lower():
                    return w
        for w in matches:
            if w.foreground:
                return w
        return matches[0]

    def foreground_window(self) -> Optional[AppWindow]:
        h = self.foreground_hwnd()
        if not h:
            return None
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(wintypes.HWND(h), ctypes.byref(pid))
        w = AppWindow(
            hwnd=h, title=self._window_text(h), class_name=self._class_name(h),
            pid=int(pid.value), rect=self._window_rect(h), foreground=True,
        )
        self._attach_process(w)
        return w

    def cursor_pos(self) -> tuple[int, int]:
        if not _WINDOWS:
            return (0, 0)
        pt = wintypes.POINT()
        if _user32.GetCursorPos(ctypes.byref(pt)):
            return (int(pt.x), int(pt.y))
        return (0, 0)
    # ── window management ─────────────────────────────────────────────────
    def focus(self, hwnd: int) -> bool:
        """Reliably bring a window to the foreground.

        Uses the AttachThreadInput technique to defeat Windows' foreground
        lock, restores minimized windows first, then BringWindowToTop +
        SetForegroundWindow.
        """
        if not _WINDOWS or not hwnd:
            return False
        try:
            h = wintypes.HWND(hwnd)
            if self.foreground_hwnd() == hwnd:
                return True
            if _user32.IsIconic(h):
                _user32.ShowWindow(h, _SW_RESTORE)
            cur_tid = wintypes.DWORD()
            fg_tid = wintypes.DWORD()
            target_tid = _user32.GetWindowThreadProcessId(h, ctypes.byref(cur_tid))
            _user32.GetWindowThreadProcessId(self.foreground_hwnd(), ctypes.byref(fg_tid))
            if cur_tid.value and fg_tid.value and cur_tid.value != fg_tid.value:
                _user32.AttachThreadInput(cur_tid.value, fg_tid.value, True)
            try:
                _user32.BringWindowToTop(h)
                _user32.SetForegroundWindow(h)
                return self.foreground_hwnd() == hwnd
            finally:
                if cur_tid.value and fg_tid.value and cur_tid.value != fg_tid.value:
                    _user32.AttachThreadInput(cur_tid.value, fg_tid.value, False)
        except Exception:
            return False

    def minimize(self, hwnd: int) -> bool:
        if not _WINDOWS or not hwnd:
            return False
        try:
            return bool(_user32.ShowWindow(wintypes.HWND(hwnd), _SW_MINIMIZE))
        except Exception:
            return False

    def maximize(self, hwnd: int) -> bool:
        if not _WINDOWS or not hwnd:
            return False
        try:
            return bool(_user32.ShowWindow(wintypes.HWND(hwnd), _SW_MAXIMIZE))
        except Exception:
            return False

    def restore(self, hwnd: int) -> bool:
        if not _WINDOWS or not hwnd:
            return False
        try:
            return bool(_user32.ShowWindow(wintypes.HWND(hwnd), _SW_RESTORE))
        except Exception:
            return False

    def close(self, hwnd: int) -> bool:
        """Ask the window to close politely (WM_CLOSE) — never force-kill."""
        if not _WINDOWS or not hwnd:
            return False
        try:
            return bool(_user32.PostMessageW(wintypes.HWND(hwnd), _WM_CLOSE, 0, 0))
        except Exception:
            return False

    def move(self, hwnd: int, x: int, y: int) -> bool:
        if not _WINDOWS or not hwnd:
            return False
        try:
            l, t, r, b = self._window_rect(hwnd)
            return bool(_user32.MoveWindow(wintypes.HWND(hwnd), x, y, r - l, b - t, True))
        except Exception:
            return False

    def resize(self, hwnd: int, width: int, height: int) -> bool:
        if not _WINDOWS or not hwnd:
            return False
        try:
            l, t, _, _ = self._window_rect(hwnd)
            return bool(_user32.MoveWindow(wintypes.HWND(hwnd), l, t,
                                           max(50, width), max(50, height), True))
        except Exception:
            return False

    def window_rect(self, hwnd: int) -> tuple[int, int, int, int]:
        return self._window_rect(hwnd) if hwnd else (0, 0, 0, 0)

    # ── privilege ─────────────────────────────────────────────────────────
    @staticmethod
    def process_elevated(pid: int) -> Optional[bool]:
        """True/False when the process token can be read, None on failure."""
        if not _WINDOWS or not pid:
            return None
        try:
            handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return None
            tok = wintypes.HANDLE()
            try:
                adv = ctypes.windll.advapi32
                adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                 ctypes.POINTER(wintypes.HANDLE)]
                adv.OpenProcessToken(handle, _TOKEN_QUERY, ctypes.byref(tok))
                if not tok.value:
                    return None

                class _TOKEN_ELEVATION(ctypes.Structure):
                    _fields_ = [("TokenIsElevated", wintypes.DWORD)]

                elev = _TOKEN_ELEVATION()
                size = wintypes.DWORD()
                adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                    ctypes.c_void_p, wintypes.DWORD,
                                                    ctypes.POINTER(wintypes.DWORD)]
                if adv.GetTokenInformation(tok, _TokenElevation, ctypes.byref(elev),
                                           ctypes.sizeof(elev), ctypes.byref(size)):
                    return bool(elev.TokenIsElevated)
                return None
            finally:
                _kernel32.CloseHandle(tok)
                _kernel32.CloseHandle(handle)
        except Exception:
            return None

    # ── helpers ───────────────────────────────────────────────────────────
    def _attach_process(self, w: AppWindow) -> None:
        if not w.pid:
            return
        if self._psutil_ok is None:
            try:
                import psutil  # noqa: F401
                self._psutil_ok = self._use_psutil
            except Exception:
                self._psutil_ok = False
        if self._psutil_ok:
            try:
                import psutil
                try:
                    p = psutil.Process(w.pid)
                    w.process = p.name() or ""
                    try:
                        w.executable = p.exe() or ""
                    except Exception:
                        w.executable = ""
                except Exception:
                    pass
            except Exception:
                pass
        if not w.process:
            w.process = self._process_name(w.pid)

    @staticmethod
    def _process_name(pid: int) -> str:
        if not _WINDOWS or not pid:
            return ""
        try:
            handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                _kernel32.QueryFullProcessImageNameW.argtypes = [
                    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                    ctypes.POINTER(wintypes.DWORD)]
                if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    import os
                    return os.path.basename(buf.value)
            finally:
                _kernel32.CloseHandle(handle)
        except Exception:
            pass
        return ""

    @staticmethod
    def _window_text(hwnd) -> str:
        try:
            n = _user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return ""
            buf = ctypes.create_unicode_buffer(n + 1)
            _user32.GetWindowTextW(wintypes.HWND(hwnd), buf, n + 1)
            return buf.value or ""
        except Exception:
            return ""

    @staticmethod
    def _class_name(hwnd) -> str:
        try:
            buf = ctypes.create_unicode_buffer(256)
            _user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
            return buf.value or ""
        except Exception:
            return ""

    @staticmethod
    def _window_rect(hwnd) -> tuple[int, int, int, int]:
        try:
            r = wintypes.RECT()
            if _user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r)):
                return (int(r.left), int(r.top), int(r.right), int(r.bottom))
        except Exception:
            pass
        return (0, 0, 0, 0)

    @staticmethod
    def foreground_hwnd() -> int:
        if not _WINDOWS:
            return 0
        try:
            return int(_user32.GetForegroundWindow())
        except Exception:
            return 0
