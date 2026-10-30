"""
editor_control - open files in their real apps and edit them like Copilot.

When the user asks Keys.ai to edit a code file or a document, this tool does NOT
silently rewrite bytes. It:

  1. opens the file in its native application
     (VS Code for code/text, Word/Excel/PowerPoint for office documents),
  2. drives the application through the hybrid automation layer
     (select-all -> paste -> save) exactly like Copilot does,
  3. verifies the edit by re-reading the file from disk,
  4. falls back to a direct write + open if the UI cannot be driven.

actions:
  open    - open a file in its native app
  edit    - visual edit: replace the whole file content through the app
  insert  - open the app and paste text at the end of the file
  verify  - re-read the file from disk and confirm it matches expected content
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

from automation import get_controller

_CODE_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss", ".json",
    ".xml", ".md", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".sh", ".bat",
    ".ps1", ".c", ".cpp", ".h", ".hpp", ".java", ".cs", ".go", ".rs", ".rb",
    ".php", ".sql", ".txt", ".log", ".csv",
}
_DOC_EXTS = {".docx": "word", ".xlsx": "excel", ".pptx": "powerpoint"}

_APP_LABELS = {
    "vscode": "VS Code",
    "word": "Word",
    "excel": "Excel",
    "powerpoint": "PowerPoint",
    "default": "the default app",
}


# ---- helpers -------------------------------------------------------------
def _log(player, msg: str) -> None:
    print(f"[Editor] {msg}")
    if player is not None and hasattr(player, "write_log"):
        try:
            player.write_log(f"SYS: {msg[:150]}")
        except Exception:
            pass


def _pick_app(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _DOC_EXTS:
        return _DOC_EXTS[ext]
    if ext in _CODE_EXTS:
        return "vscode"
    return "default"


def _vscode_cmd():
    # Prefer the real Code.exe binary first: Popen works without a shell.
    exe_candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe",
        Path("C:/Program Files/Microsoft VS Code/Code.exe"),
        Path("C:/Program Files (x86)/Microsoft VS Code/Code.exe"),
    ]
    for c in exe_candidates:
        if c.exists():
            return [str(c)]
    # Fallback: the `code` CLI on PATH (may be a .cmd shim -> needs shell=True).
    try:
        p = shutil.which("code")
        if p:
            return [p]
    except Exception:
        pass
    return None


def _launch(path: Path, app: str) -> bool:
    if app == "vscode":
        cmd = _vscode_cmd()
        if cmd:
            try:
                exe = cmd[0]
                if exe.lower().endswith((".cmd", ".bat")):
                    subprocess.Popen(
                        f'"{exe}" "{path}"',
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    subprocess.Popen(
                        cmd + [str(path)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                return True
            except Exception:
                pass
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except Exception:
        return False


def _focus(controller, title_frag: str, attempts: int = 8) -> bool:
    for _ in range(attempts):
        try:
            res = controller.focus_window(title_frag)
            if res and getattr(res, "ok", False):
                return True
        except Exception:
            pass
        time.sleep(0.6)
    return False


def _paste(controller, text: str) -> bool:
    if _PYPERCLIP:
        try:
            pyperclip.copy(text)
            res = controller.hotkey(["ctrl", "v"])
            return bool(res and getattr(res, "ok", False))
        except Exception:
            pass
    try:
        res = controller.type_text(text)
        return bool(res and getattr(res, "ok", False))
    except Exception:
        return False


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _normalize(s: str) -> str:
    return (s or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _verify_on_disk(path: Path, expected: str) -> str:
    actual = _normalize(_read(path))
    if not actual:
        return f"Verify mismatch: {path.name} could not be read from disk."
    if _normalize(expected) == actual:
        return f"Verified: {path.name} on disk matches the new content."
    return f"Verify mismatch: {path.name} on disk differs from the expected content."


def _drive_visual_edit(controller, path: Path, content: str) -> str:
    """Select-all -> paste -> save inside the focused editor window."""
    if not _focus(controller, path.name):
        return ""
    time.sleep(0.5)
    try:
        controller.hotkey(["ctrl", "a"])
        time.sleep(0.25)
    except Exception:
        pass
    if not _paste(controller, content):
        return ""
    time.sleep(0.4)
    try:
        controller.hotkey(["ctrl", "s"])
    except Exception:
        pass
    time.sleep(0.9)
    return _verify_on_disk(path, content)


def _office_edit(path: Path, params: dict) -> str:
    """Office docs are edited via their libraries, then opened in the app."""
    from actions.file_processor import file_processor
    try:
        r = file_processor({
            "file_path": str(path),
            "action": "edit",
            "find": params.get("find", ""),
            "replace": params.get("replace", ""),
            "append_text": params.get("append_text", ""),
            "cell": params.get("cell", ""),
            "value": params.get("value", ""),
            "sheet": params.get("sheet", ""),
        })
        return r
    except Exception as e:
        return f"Office edit failed: {e}"


def _generate_content(path: Path, instruction: str) -> str:
    """Generate full new file content from a natural-language instruction."""
    try:
        from actions.code_helper import _read_file, _get_gemini, _clean_code
        current, err = _read_file(str(path))
        if err:
            return ""
        model = _get_gemini()
        prompt = (
            "Apply the following change to the code below.\n"
            "Return ONLY the complete updated code - no explanation, no markdown, no backticks.\n\n"
            f"Change: {instruction}\n\n"
            f"Original code:\n{current}\n\n"
            "Updated code:"
        )
        resp = model.generate_content(prompt)
        return _clean_code(resp.text)
    except Exception as e:
        print(f"[Editor] content generation failed: {e}")
        return ""


# ---- tool entry ----------------------------------------------------------
def editor_control(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    action = (params.get("action") or "").strip().lower()
    file_path = (params.get("file_path") or params.get("path") or "").strip()
    if not file_path:
        return "Provide a file_path to edit, sir."
    path = Path(file_path).expanduser()

    def _ctrl():
        return get_controller(log=lambda m: _log(player, m))

    # ---- open ------------------------------------------------------------
    if action == "open":
        app = _pick_app(path)
        if _launch(path, app):
            _log(player, f"Opened {path.name} in {app}")
            return f"Opened {path.name} in {app}."
        return f"Could not open {path.name}."

    # ---- verify ----------------------------------------------------------
    if action == "verify":
        expected = params.get("expected") or params.get("content") or ""
        if not expected:
            return _read(path)[:4000] or "File is empty or unreadable."
        return _verify_on_disk(path, expected)

    # ---- edit ------------------------------------------------------------
    if action == "edit":
        content = params.get("content") or ""
        if not content and params.get("instruction"):
            _log(player, "Generating new content from instruction...")
            content = _generate_content(path, params.get("instruction"))

        app = _pick_app(path)

        # Office documents: library edit, then show the file in the app.
        # Raw full-text 'content' cannot be applied to structured office
        # formats, so these edits REQUIRE find/replace (Word/PPT), cell/value
        # (Excel), or append_text (Word) - otherwise the edit would silently
        # do nothing while reporting success.
        if app in ("word", "excel", "powerpoint"):
            has_office_params = any(
                params.get(k) for k in ("find", "replace", "append_text", "cell", "value")
            )
            if not has_office_params:
                return (
                    "Structured office documents need a targeted edit: "
                    "find+replace (Word/PPT), cell+value (Excel), or append_text (Word). "
                    "Full-file content replacement is only supported for code/text files."
                )
            result = _office_edit(path, params)
            _launch(path, app)
            app_label = _APP_LABELS.get(app, app.capitalize())
            return f"{result}\nOpened {path.name} in {app_label} so you can see the change."

        # Code / text files need full content (or an instruction to generate it).
        if not content:
            return "Provide 'content' (or 'instruction') to edit the file, sir."

        # Code / text: drive the real editor like Copilot.
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            _launch(path, app)
            _log(player, f"Created and opened {path.name} in {app}")
            return f"Created and opened {path.name} in {app} - content written."

        controller = _ctrl()
        if _launch(path, app):
            msg = _drive_visual_edit(controller, path, content)
            if msg.startswith("Verified"):
                _log(player, f"Visual edit of {path.name} verified")
                return f"Edited {path.name} in {app} like Copilot. {msg}"
            # UI drive failed -> direct write + open so the user still sees it.
            path.write_text(content, encoding="utf-8")
            _launch(path, app)
            _log(player, f"Edited {path.name} directly (UI drive unavailable)")
            return f"Edited {path.name} (written directly, UI drive unavailable). {_verify_on_disk(path, content)}"

        path.write_text(content, encoding="utf-8")
        _log(player, f"Edited {path.name} directly (could not open {app})")
        return f"Edited {path.name} directly (could not open {app}). {_verify_on_disk(path, content)}"

    # ---- insert / append -------------------------------------------------
    if action in ("insert", "append"):
        text = params.get("text") or params.get("content") or ""
        if not text:
            return "Provide 'text' to insert, sir."
        app = _pick_app(path)
        controller = _ctrl()
        if path.exists() and _launch(path, app) and _focus(controller, path.name):
            time.sleep(0.4)
            try:
                controller.hotkey(["ctrl", "end"])
            except Exception:
                pass
            if _paste(controller, text):
                try:
                    controller.hotkey(["ctrl", "s"])
                except Exception:
                    pass
                time.sleep(0.6)
                if text.strip() in _read(path):
                    _log(player, f"Inserted text into {path.name} and saved (verified)")
                    return f"Inserted text into {path.name} and saved. Verified on disk."
                _log(player, f"Inserted text into {path.name}, could not verify on disk")
                return f"Inserted text into {path.name} and saved (could not verify on disk)."
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
        _log(player, f"Appended text to {path.name} directly")
        return f"Appended text to {path.name} directly."

    return f"Unknown editor_control action: '{action}'. Valid: open, edit, insert, verify."
