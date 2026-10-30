"""ComfyUI backend discovery, start/stop and guided installation.

Design constraints that shaped this module:

* Keys.AI must never install into an arbitrary directory or overwrite a Python
  environment. Detection only *looks*; installation requires an explicit target
  the user chooses, creates an isolated venv there, and refuses a non-empty
  folder.
* A process is only ever stopped when this module started it. No PID is guessed
  and no unrelated Python process is touched.
* "Installed" means ``main.py`` exists; "running" means ``GET /system_stats``
  answers. Nothing else is reported as success.
"""

from __future__ import annotations

import atexit
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from core.image_studio.comfy_client import ComfyClient

INSTALL_TIMEOUT_S = 180.0
LOG_FILE_NAME = "comfyui.log"


class InstallError(RuntimeError):
    pass


# ── detection ──────────────────────────────────────────────────────────────
def candidate_dirs(configured: str = "") -> list[Path]:
    """Places a ComfyUI checkout plausibly lives. Read-only probing."""
    out: list[Path] = []

    def _add(p):
        try:
            p = Path(os.path.expandvars(os.path.expanduser(str(p))))
            if p not in out:
                out.append(p)
        except Exception:
            pass

    if configured:
        _add(configured)
        _add(Path(configured) / "ComfyUI")
    home = Path.home()
    _add(home / "ComfyUI")
    _add(home / "ComfyUI_windows_portable" / "ComfyUI")
    _add(home / "Documents" / "ComfyUI")
    _add(home / "Desktop" / "ComfyUI")
    _add(home / "OneDrive" / "Desktop" / "ComfyUI")
    _add(Path(os.environ.get("LOCALAPPDATA", home)) / "KeysAI" / "ComfyUI")
    # Portable bundle unpacked by hand (the reliable route on Windows, where a
    # Store-installed Python cannot build a usable venv).
    _add(Path(os.environ.get("LOCALAPPDATA", home)) / "KeysAI" / "ComfyUI_portable")
    _add(Path(os.environ.get("LOCALAPPDATA", home)) / "KeysAI"
         / "ComfyUI_portable" / "ComfyUI_windows_portable" / "ComfyUI")
    _add(home / "AppData" / "Local" / "Programs" / "ComfyUI")
    if os.name == "nt":
        _add(Path("C:/ComfyUI"))
        _add(Path("C:/ComfyUI_windows_portable/ComfyUI"))
    else:
        _add(Path("/opt/ComfyUI"))
    return out


def _python_for(root: Path) -> str:
    """The interpreter that can actually run this checkout."""
    for rel in ("venv/Scripts/python.exe", "venv/bin/python",
                "python_embeded/python.exe", ".venv/Scripts/python.exe",
                ".venv/bin/python"):
        p = root / rel
        if p.exists():
            return str(p)
    # A portable bundle keeps ComfyUI/ one level down from python_embeded/.
    parent = root.parent
    for rel in ("python_embeded/python.exe", "venv/Scripts/python.exe"):
        p = parent / rel
        if p.exists():
            return str(p)
    return ""


def detect(configured: str = "") -> dict:
    """{'found', 'path', 'python', 'models_dir', 'checked'} — never raises."""
    checked = candidate_dirs(configured)
    for cand in checked:
        try:
            if not cand.is_dir():
                continue
            main_py = cand / "main.py"
            if not main_py.is_file():
                # Portable bundles: <root>/ComfyUI/main.py
                nested = cand / "ComfyUI" / "main.py"
                if nested.is_file():
                    cand = cand / "ComfyUI"
                    main_py = nested
                else:
                    continue
            return {
                "found": True,
                "path": str(cand),
                "main": str(main_py),
                "python": _python_for(cand),
                "models_dir": str(cand / "models"),
                "checked": [str(c) for c in checked],
            }
        except Exception:
            continue
    return {"found": False, "path": "", "python": "", "models_dir": "",
            "checked": [str(c) for c in checked]}


def port_open(url: str, timeout: float = 1.0) -> bool:
    try:
        parsed = urlparse(url if "://" in url else "http://" + url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def health(url: str) -> dict:
    """Backend health via the real API. Never raises."""
    try:
        data = ComfyClient(url).health()
        data["reachable"] = True
        return data
    except Exception as exc:
        return {"reachable": False, "url": url, "error": str(exc)[:300],
                "device": {}, "running": 0, "pending": 0}


# ── guided installation ────────────────────────────────────────────────────
def default_install_target() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "KeysAI" / "ComfyUI"


def manual_steps(target: Path | None = None) -> list[str]:
    target = target or default_install_target()
    return [
        "1. Download ComfyUI_windows_portable_nvidia.7z (2 GB):",
        "   https://github.com/comfyanonymous/ComfyUI/releases",
        "   Portable builds bundle Python and PyTorch — nothing else to install,",
        "   and they work even when Keys.AI runs on the Microsoft Store Python.",
        "2. Unzip it somewhere stable, e.g. " + str(target),
        "3. Put a checkpoint in ComfyUI/models/checkpoints/",
        "   (this app can download Stable Diffusion 1.5 for you under Models).",
        "4. Start it with run_nvidia_gpu.bat, then press RECHECK here.",
        "Manual alternative (git + Python 3.12):",
        f"   git clone https://github.com/comfyanonymous/ComfyUI \"{target}\"",
        f"   cd \"{target}\" && python -m venv venv",
        "   venv\\Scripts\\pip install torch torchvision torchaudio",
        "   venv\\Scripts\\pip install -r requirements.txt",
        "   venv\\Scripts\\python main.py --listen 127.0.0.1 --port 8188",
    ]


def _run(cmd: list[str], cwd: Path, on_log, should_stop, timeout: float | None = None) -> None:
    """Run a command, streaming merged output to ``on_log``."""
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    on_log(f"$ {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=creationflags,
    )
    started = time.monotonic()
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        if should_stop and should_stop():
            proc.terminate()
            raise InstallError("Installation cancelled.")
        text = line.rstrip()
        on_log(text)
        if text:
            tail.append(text)
            del tail[:-12]
        if timeout and time.monotonic() - started > timeout:
            proc.terminate()
            raise InstallError(f"Step timed out after {timeout:.0f}s: {cmd[0]}")
    code = proc.wait()
    if code != 0:
        # The last lines of a failing pip/venv step usually name the real cause;
        # without them the user only sees an opaque exit code.
        detail = "\n".join(tail[-6:])
        raise InstallError(
            f"'{Path(cmd[0]).name}' exited with code {code}."
            + (f"\nLast output:\n{detail}" if detail else ""))


def _venv_works(python: Path, cwd: Path) -> tuple[bool, str]:
    """Can this interpreter actually start and find its own standard library?

    A Store/MSIX Python creates the venv inside its package sandbox; the
    launcher in the requested folder then dies with "No pyvenv.cfg file".
    Checking up front turns that into a clear message instead of a failed pip.
    """
    try:
        proc = subprocess.run(
            [str(python), "-c", "import sys, sysconfig; print(sys.prefix)"],
            cwd=str(cwd), capture_output=True, text=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if os.name == "nt" else 0)
    except Exception as exc:
        return False, str(exc)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip().splitlines()
        return False, msg[-1] if msg else f"exit code {proc.returncode}"
    return True, (proc.stdout or "").strip()


def install_comfy(target: Path, *, on_log=None, should_stop=None) -> dict:
    """Clone ComfyUI and build an isolated venv at ``target``.

    This runs for several minutes and streams output; it never touches the
    Keys.AI virtualenv or the system Python's packages. Raises InstallError
    with the concrete reason on any failure.
    """
    on_log = on_log or (lambda _m: None)
    should_stop = should_stop or (lambda: False)
    target = Path(os.path.expanduser(str(target))).resolve()

    if target.exists() and any(target.iterdir()):
        raise InstallError(
            f"{target} already contains files. Choose an empty folder so an "
            "existing install cannot be overwritten.")
    if shutil.which("git") is None:
        raise InstallError(
            "Git was not found on PATH. Install Git, or use the portable "
            "release (see the manual steps below).")
    py = sys.executable
    if not py:
        raise InstallError("No Python interpreter is available to build the venv.")

    try:
        target.mkdir(parents=True, exist_ok=True)
        on_log(f"Installing ComfyUI into {target}")
        _run(["git", "clone", "--depth", "1",
              "https://github.com/comfyanonymous/ComfyUI.git", str(target)],
             target.parent, on_log, should_stop, timeout=900)
        venv_dir = target / "venv"
        on_log("Creating an isolated virtual environment…")
        _run([py, "-m", "venv", str(venv_dir)], target, on_log, should_stop,
             timeout=300)
        vpy = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not vpy.exists():
            raise InstallError("The virtual environment could not be created.")
        ok, detail = _venv_works(vpy, target)
        if not ok:
            raise InstallError(
                f"The virtual environment at {venv_dir} cannot start "
                f"({detail}). This happens when Keys.AI runs on the Microsoft "
                "Store build of Python, which creates venvs inside its own "
                "sandbox. Use the portable ComfyUI release instead: download "
                "ComfyUI_windows_portable_nvidia.7z from "
                "https://github.com/comfyanonymous/ComfyUI/releases, unpack it "
                "(7-Zip), and point Keys.AI at the ComfyUI folder inside it. "
                "Nothing was changed outside " + str(target) + ".")
        _run([str(vpy), "-m", "pip", "install", "--upgrade", "pip"],
             target, on_log, should_stop, timeout=600)
        on_log("Installing PyTorch (Windows wheels include CUDA)…")
        _run([str(vpy), "-m", "pip", "install",
              "torch", "torchvision", "torchaudio"],
             target, on_log, should_stop, timeout=3600)
        on_log("Installing ComfyUI requirements…")
        _run([str(vpy), "-m", "pip", "install", "-r",
              str(target / "requirements.txt")],
             target, on_log, should_stop, timeout=3600)
        if not (target / "main.py").is_file():
            raise InstallError("Installation finished but main.py is missing.")
        return {"ok": True, "path": str(target), "python": str(vpy)}
    except InstallError:
        raise
    except Exception as exc:
        raise InstallError(f"Installation failed: {exc}") from exc


# ── process control ────────────────────────────────────────────────────────
class BackendManager:
    """Starts/stops a ComfyUI process, but only one it started itself."""

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._url = ""
        self._lock = threading.RLock()
        self._log_path: Path | None = None
        atexit.register(self.stop_quietly)

    @property
    def started_by_us(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def log_tail(self, lines: int = 40) -> str:
        path = self._log_path
        if not path or not path.exists():
            return ""
        try:
            data = path.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(data[-lines:])
        except Exception:
            return ""

    def start(self, url: str, install: dict, on_log=None,
              wait_s: float = INSTALL_TIMEOUT_S) -> dict:
        on_log = on_log or (lambda _m: None)
        with self._lock:
            if health(url).get("reachable"):
                return {"ok": True, "already_running": True, "url": url}
            if not install.get("found"):
                raise InstallError(
                    "ComfyUI is not installed. Run the guided install, or point "
                    "Keys.AI at an existing ComfyUI folder.")
            python = install.get("python") or ""
            root = Path(install["path"])
            if not python or not Path(python).exists():
                python = sys.executable
                on_log("No bundled venv found — trying the app's interpreter "
                       "(ComfyUI's dependencies may be missing there).")
            parsed = urlparse(url if "://" in url else "http://" + url)
            host = parsed.hostname or "127.0.0.1"
            port = str(parsed.port or 8188)
            log_path = root / LOG_FILE_NAME
            cmd = [python, "main.py", "--listen", host, "--port", port,
                   "--disable-auto-launch"]
            on_log("$ " + " ".join(cmd))
            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                log_fh = open(log_path, "a", encoding="utf-8", errors="replace")
            except Exception:
                log_fh = subprocess.DEVNULL
            self._log_path = log_path
            try:
                self._proc = subprocess.Popen(
                    cmd, cwd=str(root), stdout=log_fh, stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
            except Exception as exc:
                raise InstallError(f"Could not start ComfyUI: {exc}") from exc
            finally:
                if log_fh is not subprocess.DEVNULL:
                    try:
                        log_fh.close()
                    except Exception:
                        pass
            self._url = url

        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise InstallError(
                    "ComfyUI exited during startup:\n" + self.log_tail())
            if health(url).get("reachable"):
                return {"ok": True, "already_running": False, "url": url,
                        "pid": self._proc.pid if self._proc else None}
            time.sleep(1.5)
        raise InstallError(
            "ComfyUI did not answer /system_stats within "
            f"{wait_s:.0f}s. Recent log:\n" + self.log_tail())

    def stop(self) -> dict:
        with self._lock:
            proc = self._proc
            self._proc = None
            if proc is None:
                return {"ok": False,
                        "message": "Keys.AI did not start this ComfyUI process, "
                                   "so it will not stop it."}
            if proc.poll() is not None:
                return {"ok": True, "message": "ComfyUI was already stopped."}
            try:
                proc.terminate()
                proc.wait(timeout=15)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            return {"ok": True, "message": "ComfyUI stopped."}

    def stop_quietly(self) -> None:
        try:
            proc = self._proc
            if proc is not None and proc.poll() is None:
                proc.terminate()
        except Exception:
            pass


manager = BackendManager()

__all__ = ["detect", "health", "port_open", "install_comfy", "manual_steps",
           "manager", "default_install_target", "InstallError",
           "BackendManager"]
