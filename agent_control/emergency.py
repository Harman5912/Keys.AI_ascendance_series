"""Emergency stop + user takeover detection.

    EmergencyStop     — global WH_KEYBOARD_LL hook; ESC immediately cancels
                        active automation, releases control and removes the
                        overlay. Works even when the Keys.ai window is not
                        focused. Priority over normal agent execution.
    UserTakeoverDetector — WH_MOUSE_LL + WH_KEYBOARD_LL hooks. Injected
                        (agent-originated) input is filtered via LLMHF_INJECTED
                        so only REAL user input counts. When genuine user
                        activity happens while the agent is mid-action, the
                        engine pauses instead of fighting the user.

Non-Windows platforms: every function degrades to a safe no-op so the rest
of the agent-control layer still works (overlay buttons remain available).
"""

from __future__ import annotations

import platform
import threading
import time
from typing import Callable, Optional

_WINDOWS = platform.system() == "Windows"

VK_ESCAPE = 0x1B
LLMHF_INJECTED = 0x00000002

# Lazy-loaded ctypes — avoids permission prompts at startup
_user32 = None
_ctypes = None
_wintypes = None
_WH_KEYBOARD_LL = 13
_WH_MOUSE_LL = 14
_WM_KEYDOWN = 0x0100
_WM_SYSKEYDOWN = 0x0104
_KBDLLHOOKSTRUCT = None
_MSLLHOOKSTRUCT = None
_LL_HOOK_PROC = None


def _ensure_ctypes():
    """Lazy-load ctypes DLLs on first use."""
    global _user32, _ctypes, _wintypes, _KBDLLHOOKSTRUCT, _MSLLHOOKSTRUCT, _LL_HOOK_PROC
    if _user32 is not None or not _WINDOWS:
        return
    try:
        import ctypes as _ct
        from ctypes import wintypes as _wt
        _ctypes = _ct
        _wintypes = _wt
        _user32 = _ct.windll.user32
        _LL_HOOK_PROC = _ct.WINFUNCTYPE(_ct.c_long, _ct.c_int, _ct.c_size_t, _ct.c_ssize_t)

        class _KBDLLHOOKSTRUCT(_ct.Structure):
            _fields_ = [("vkCode", _ct.c_uint), ("scanCode", _ct.c_uint),
                        ("flags", _ct.c_uint), ("time", _ct.c_uint),
                        ("dwExtraInfo", _ct.c_size_t)]

        class _MSLLHOOKSTRUCT(_ct.Structure):
            _fields_ = [("pt", _wt.POINT), ("mouseData", _ct.c_uint),
                        ("flags", _ct.c_uint), ("time", _ct.c_uint),
                        ("dwExtraInfo", _ct.c_size_t)]
    except Exception as e:
        print(f"[emergency] Lazy ctypes init failed: {e}")


class UserTakeoverDetector:
    """Tracks genuine user input so the agent never fights the user.

    Hooks ignore injected events (LLMHF_INJECTED) — the agent's own clicks
    and key presses never count as user takeover.
    """

    def __init__(self) -> None:
        _ensure_ctypes()   # define _LL_HOOK_PROC before it is called below
        self._lock = threading.Lock()
        self._last_user_input = 0.0          # monotonic
        self._last_agent_action = 0.0        # monotonic — marked by the engine
        self._agent_active_until = 0.0       # monotonic — inputs inside this
                                             # window are the agent's own
                                             # (SetCursorPos events are NOT
                                             # reliably flagged LLMHF_INJECTED)
        self._hooks: list = []
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._started = False
        self._cbs: list = []           # ESC callbacks
        self._key_cbs: dict[int, list[Callable]] = {}  # vk -> callbacks
        # keep refs so the ctypes callbacks don't get GC'd
        self._kb_cb = _LL_HOOK_PROC(self._kb_callback) if _WINDOWS else None
        self._ms_cb = _LL_HOOK_PROC(self._ms_callback) if _WINDOWS else None

    # ── lifecycle ──────────────────────────────────────────────────────
    def start(self) -> bool:
        if not _WINDOWS:
            return False
        if self._started:
            return True
        self._stop.clear()
        try:
            for proc, hook_id in ((self._kb_cb, WH_KEYBOARD_LL),
                                  (self._ms_cb, WH_MOUSE_LL)):
                h = _user32.SetWindowsHookExW(
                    hook_id, proc,
                    ctypes.windll.kernel32.GetModuleHandleW(None), 0)
                if h:
                    self._hooks.append(h)
                    t = threading.Thread(target=self._pump,
                                         args=(h,), daemon=True,
                                         name="agent-input-hook")
                    t.start()
                    self._threads.append(t)
            self._started = True
            return bool(self._hooks)
        except Exception:
            return False

    def stop(self) -> None:
        self._stop.set()
        if _WINDOWS:
            try:
                for h in self._hooks:
                    _user32.UnhookWindowsHookEx(h)
            except Exception:
                pass
        self._hooks = []
        self._started = False

    def _pump(self, hook) -> None:
        try:
            msg = wintypes.MSG()
            while not self._stop.is_set():
                if _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    _user32.TranslateMessage(ctypes.byref(msg))
                    _user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    time.sleep(0.012)
        except Exception:
            pass

    # ── hook callbacks (hook thread) ───────────────────────────────────
    def _kb_callback(self, nCode, wParam, lParam):
        try:
            if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                st = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                injected = bool(st.flags & LLMHF_INJECTED)
                if not injected:
                    if st.vkCode == VK_ESCAPE:
                        for cb in list(self._cbs):
                            try:
                                cb("esc")
                            except Exception:
                                pass
                    # Dispatch registered per-key callbacks (e.g. F6)
                    for cb in list(self._key_cbs.get(st.vkCode, [])):
                        try:
                            cb()
                        except Exception:
                            pass
                    self._mark_user_input()
        except Exception:
            pass
        try:
            return _user32.CallNextHookEx(None, nCode, wParam, lParam)
        except Exception:
            return 0

    def _ms_callback(self, nCode, wParam, lParam):
        try:
            if nCode >= 0 and wParam in (0x0200, 0x0201, 0x0202, 0x0204, 0x0205,
                                         0x020A, 0x0207, 0x0208, 0x0206):  # move/click/wheel/down/up
                st = ctypes.cast(lParam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
                if not (st.flags & LLMHF_INJECTED):
                    self._mark_user_input()
        except Exception:
            pass
        try:
            return _user32.CallNextHookEx(None, nCode, wParam, lParam)
        except Exception:
            return 0

    # ── state ──────────────────────────────────────────────────────────
    def _mark_user_input(self) -> None:
        now = time.monotonic()
        with self._lock:
            # Inputs arriving while the agent is acting are the agent's own
            # (smooth SetCursorPos moves don't reliably set LLMHF_INJECTED).
            if now < self._agent_active_until:
                return
            self._last_user_input = now

    def mark_agent_action(self) -> None:
        """Engine calls this around its own input so self-input never counts.
        Opens a short 'agent acting' window so hook events generated by the
        agent's own smooth moves/clicks are ignored too."""
        now = time.monotonic()
        with self._lock:
            self._last_agent_action = now
            self._agent_active_until = now + 1.5

    def user_intervened(self, window: float = 1.2) -> bool:
        """True when genuine user input happened AFTER the agent last acted
        (within `window` seconds)."""
        with self._lock:
            if self._last_user_input <= 0:
                return False
            since_agent = self._last_user_input - self._last_agent_action
            fresh = time.monotonic() - self._last_user_input <= window
            return fresh and since_agent > 0.18

    def on_escape(self, cb: Callable[[str], None]) -> None:
        """Register an ESC handler (engine wires its stop() here)."""
        self._cbs.append(cb)

    def on_key(self, vk_code: int, cb: Callable[[], None]) -> None:
        """Register a callback for a specific virtual-key code.
        Fires on key-down, only for real (non-injected) user input."""
        self._key_cbs.setdefault(vk_code, []).append(cb)


class EmergencyStop:
    """Global ESC handler — cancels active automation with priority."""

    def __init__(self, detector: Optional[UserTakeoverDetector] = None) -> None:
        self._detector = detector or UserTakeoverDetector()
        self._handler: Optional[Callable[[], None]] = None
        self._detector.on_escape(lambda _k: self._fire())

    def start(self) -> bool:
        return self._detector.start()

    def stop(self) -> None:
        self._detector.stop()

    def set_handler(self, handler: Optional[Callable[[], None]]) -> None:
        self._handler = handler

    def _fire(self) -> None:
        if self._handler is not None:
            try:
                self._handler()
            except Exception:
                pass

    @property
    def detector(self) -> UserTakeoverDetector:
        return self._detector


_emergency: Optional[EmergencyStop] = None
_emergency_lock = threading.Lock()


def get_emergency() -> EmergencyStop:
    """Shared singleton emergency-stop controller."""
    global _emergency
    if _emergency is None:
        with _emergency_lock:
            if _emergency is None:
                _emergency = EmergencyStop()
    return _emergency


def reset_emergency() -> None:
    global _emergency
    with _emergency_lock:
        if _emergency is not None:
            try:
                _emergency.stop()
            except Exception:
                pass
        _emergency = None
