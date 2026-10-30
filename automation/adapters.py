"""Lightweight per-application adapters (spec 29, 7, 8).

Adapters expose GENERIC capabilities — focus / find_element / read_text /
click / type / wait_for — and are registered with the NativeBackend so the
hybrid controller can reach apps through their OWN automation surface before
falling back to coordinates.

Priority inside an adapter (spec 7): filesystem/CLI-level operation first,
keyboard shortcuts second, vision never when avoidable.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional

from automation.base import Backend, Element, Rect
from automation.native_backend import NativeAdapter


def _quiet(*args, **kwargs):
    pass


def _run(cmd: list[str], timeout: float = 6.0) -> Optional[str]:
    """Run a CLI command quietly; returns stdout or None."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=0x08000000 if __import__("platform").system() == "Windows" else 0)
        return (r.stdout or "").strip()
    except Exception:
        return None


class VSCodeAdapter(NativeAdapter):
    """VS Code — filesystem/CLI-first (code.exe), keyboard-second."""

    app_keywords = ("code", "visual studio code")

    def __init__(self) -> None:
        self._code_cli = None

    def _cli(self) -> Optional[str]:
        if self._code_cli is not None:
            return self._code_cli or None
        for cand in ("code", r"C:\Users\{u}\AppData\Local\Programs\Microsoft VS Code\bin\code.cmd"):
            try:
                import os
                cand = cand.format(u=os.environ.get("USERNAME", ""))
                if _run([cand, "--version"]):
                    self._code_cli = cand
                    return cand
            except Exception:
                continue
        self._code_cli = ""
        return None

    def open_file(self, path: str) -> bool:
        cli = self._cli()
        p = Path(path).expanduser()
        if not p.exists():
            return False
        if cli:
            _run([cli, str(p)])
            return True
        return False

    def open_folder(self, path: str) -> bool:
        cli = self._cli()
        p = Path(path).expanduser()
        if not p.is_dir():
            return False
        if cli:
            _run([cli, str(p)])
            return True
        return False

    def new_file(self, path: str, content: str = "") -> bool:
        p = Path(path).expanduser()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return self.open_file(str(p))
        except Exception:
            return False

    def toggle_terminal(self, motion=None) -> bool:
        if motion is None:
            from automation.motion import MouseTrajectory
            motion = MouseTrajectory()
        return motion.hotkey(["ctrl", "`"])

    def run_code(self, motion=None) -> bool:
        if motion is None:
            from automation.motion import MouseTrajectory
            motion = MouseTrajectory()
        return motion.hotkey(["ctrl", "f5"])

    def show_diagnostics(self, motion=None) -> bool:
        if motion is None:
            from automation.motion import MouseTrajectory
            motion = MouseTrajectory()
        return motion.hotkey(["ctrl", "shift", "m"])

    def quick_open(self, motion=None) -> bool:
        if motion is None:
            from automation.motion import MouseTrajectory
            motion = MouseTrajectory()
        return motion.hotkey(["ctrl", "p"])


class TerminalAdapter(NativeAdapter):
    """Windows Terminal / PowerShell / CMD — command entry, completion wait,
    interruption, output readback via clipboard (pragmatic + reliable)."""

    app_keywords = ("windows terminal", "powershell", "command prompt", "cmd.exe")

    def __init__(self) -> None:
        self._shell = ""

    def detect_shell(self, title: str) -> str:
        t = (title or "").lower()
        if "powershell" in t:
            self._shell = "powershell"
        elif "terminal" in t or "cmd" in t:
            self._shell = "cmd"
        return self._shell

    def type_command(self, command: str, motion=None) -> bool:
        if motion is None:
            from automation.motion import MouseTrajectory
            motion = MouseTrajectory()
        ok = motion.type_text(command)
        if ok:
            time.sleep(0.05)
            ok = motion.hotkey(["enter"])
        return bool(ok)

    def paste(self, text: str, motion=None) -> bool:
        if motion is None:
            from automation.motion import MouseTrajectory
            motion = MouseTrajectory()
        try:
            import pyperclip
            pyperclip.copy(text)
        except Exception:
            return False
        return motion.hotkey(["ctrl", "v"])

    def interrupt(self, motion=None) -> bool:
        if motion is None:
            from automation.motion import MouseTrajectory
            motion = MouseTrajectory()
        return motion.hotkey(["ctrl", "c"])

    def clear(self, motion=None) -> bool:
        if motion is None:
            from automation.motion import MouseTrajectory
            motion = MouseTrajectory()
        return motion.hotkey(["ctrl", "l"])

    def read_output(self) -> str:
        """Select-all + copy the terminal buffer, then read the clipboard."""
        from automation.motion import MouseTrajectory
        motion = MouseTrajectory()
        try:
            import pyperclip
            before = pyperclip.paste()
        except Exception:
            before = ""
        if not motion.hotkey(["ctrl", "a"]) or not motion.hotkey(["ctrl", "c"]):
            return ""
        time.sleep(0.2)
        try:
            import pyperclip
            text = pyperclip.paste() or ""
            pyperclip.copy(before)
            return text[-4000:]
        except Exception:
            return ""

    def wait_for_prompt(self, timeout: float = 12.0) -> bool:
        """State-based wait: terminal output stops growing => prompt is back."""
        from automation.verify import wait_until
        last = self.read_output()

        def _settled():
            nonlocal last
            now = self.read_output()
            settled = now == last and bool(now.strip())
            last = now
            return settled

        return wait_until(_settled, timeout, interval=0.6)


class ExplorerAdapter(NativeAdapter):
    """File Explorer — open folders / drive paths directly (no UI clicking)."""

    app_keywords = ("file explorer", "explorer.exe", "windows explorer")

    def open_path(self, path: str) -> bool:
        try:
            import subprocess
            subprocess.Popen(["explorer.exe", str(Path(path).expanduser())],
                             creationflags=0x08000000)
            return True
        except Exception:
            return False

    def focus_address_bar(self, motion=None) -> bool:
        if motion is None:
            from automation.motion import MouseTrajectory
            motion = MouseTrajectory()
        return motion.hotkey(["ctrl", "l"])

    def navigate_to(self, path: str, motion=None) -> bool:
        if motion is None:
            from automation.motion import MouseTrajectory
            motion = MouseTrajectory()
        if not self.focus_address_bar(motion):
            return False
        motion.type_text(str(Path(path).expanduser()))
        return motion.hotkey(["enter"])


def register_app_adapters(backend) -> None:
    """Attach the app adapters to a NativeBackend instance."""
    for adapter in (VSCodeAdapter(), TerminalAdapter(), ExplorerAdapter()):
        try:
            backend.register(adapter)
        except Exception:
            pass
