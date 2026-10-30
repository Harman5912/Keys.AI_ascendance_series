"""Administrator mode — legitimate Windows elevation.

    • is_elevated()          — is the CURRENT process running elevated?
    • restart_elevated()     — relaunch ourselves with 'runas' (UAC prompt).
    • process_elevated(pid)  — privilege level of any process (for discovery).
    • secure_desktop_active  — True while the UAC secure desktop is up; the
                               engine must PAUSE automation then, never touch it.

Hard rules (spec §10–11): use the OS elevation mechanism only, never bypass
UAC, never touch the secure desktop, never modify security settings.
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Optional

_WINDOWS = platform.system() == "Windows"

_SEE_MASK_NOCLOSEPROCESS = 0x00000040


def is_elevated() -> bool:
    """True when this process runs with an elevated (high-integrity) token."""
    if not _WINDOWS:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        adv = ctypes.windll.advapi32
        kernel = ctypes.windll.kernel32

        class _TOKEN_ELEVATION(ctypes.Structure):
            _fields_ = [("TokenIsElevated", wintypes.DWORD)]

        handle = kernel.GetCurrentProcess()
        tok = wintypes.HANDLE()
        adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.HANDLE)]
        if not adv.OpenProcessToken(handle, 0x0008, ctypes.byref(tok)):
            return False
        try:
            elev = _TOKEN_ELEVATION()
            size = wintypes.DWORD()
            adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                ctypes.c_void_p, wintypes.DWORD,
                                                ctypes.POINTER(wintypes.DWORD)]
            if adv.GetTokenInformation(tok, 20, ctypes.byref(elev),
                                       ctypes.sizeof(elev), ctypes.byref(size)):
                return bool(elev.TokenIsElevated)
            return False
        finally:
            kernel.CloseHandle(tok)
    except Exception:
        return False


def process_elevated(pid: int) -> Optional[bool]:
    """Privilege level of another process; None when unreadable (UIPI limits)."""
    if not _WINDOWS or not pid:
        return None
    try:
        from automation.win32_native import NativeController
        return NativeController.process_elevated(int(pid))
    except Exception:
        return None


def secure_desktop_active() -> bool:
    """True while the secure desktop (UAC prompt) is on top.

    When True, Keys.ai must stop all automation and wait — the user is looking
    at a UAC prompt that we must never attempt to interact with.
    """
    if not _WINDOWS:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        h = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_READOBJECTS
        if not h:
            return False
        try:
            buf = ctypes.create_unicode_buffer(256)
            needed = wintypes.DWORD()
            user32.GetUserObjectInformationW(h, 2, buf, 256, ctypes.byref(needed))
            name = (buf.value or "").lower()
            return "winlogon" in name or "secure" in name
        finally:
            user32.CloseDesktop(h)
    except Exception:
        return False


def current_executable() -> str:
    """Best-effort path of the running Keys.ai binary (frozen exe or python)."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return str(Path(sys.executable).resolve())


def restart_elevated(args: Optional[list[str]] = None) -> bool:
    """Relaunch the current process elevated via ShellExecuteW 'runas'.

    Returns True once the elevated process was spawned (the UAC prompt will
    appear). Returns False when elevation is not possible/needed (e.g. already
    elevated). Never modifies any security setting.
    """
    if not _WINDOWS:
        return False
    if is_elevated():
        return False
    try:
        import ctypes
        # ShellExecuteW returns an HINSTANCE (pointer-sized on 64-bit); the
        # default c_int restype would truncate it and break the >32 check.
        ctypes.windll.shell32.ShellExecuteW.restype = ctypes.c_void_p
        exe = current_executable()
        args_list = [a for a in (args or sys.argv[1:]) if a]
        params = " ".join(f'"{a}"' if " " in a else a for a in args_list)
        res = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe, params, None, 1)   # SW_SHOWNORMAL
        # >32 means success; 5 (ERROR_ACCESS_DENIED) means the user cancelled UAC.
        return int(res) > 32
    except Exception:
        return False


def elevation_status() -> dict:
    """Machine-readable elevation summary for the UI / tools / telemetry."""
    elevated = is_elevated()
    return {
        "elevated": elevated,
        "windows": _WINDOWS,
        "secure_desktop": secure_desktop_active(),
        "label": "ADMIN" if elevated else ("NORMAL" if _WINDOWS else "N/A"),
    }
