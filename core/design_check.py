"""Objective design checks for a generated project.

"Make it well designed" is only enforceable if it is measurable. This module
measures the things that can be measured on a finished build, and refuses to
pretend the rest was verified:

* every text/background colour pair clears WCAG 2.2 SC 1.4.3 (4.5:1 body,
  3:1 large text and UI boundaries) — the same thresholds
  ``core/design_system.py`` guarantees when it generates a palette
* no lorem ipsum, no "your text here", no TODO left in visible copy
* every local image the page references exists on disk
* the type and spacing scales are actually scales, not twenty arbitrary values

Findings are split into ``error`` (the build must not claim success) and
``warning`` (worth reporting, not blocking). Nothing here inspects a rendered
pixel: it reads the source the build wrote, so it catches the mistakes that
source can show.

    python -m core.design_check <project folder>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from core.design_system import AA_LARGE, AA_TEXT, contrast_ratio

TEXT_KEYS = ("ink", "text", "fg", "foreground", "body", "content")
MUTED_KEYS = ("muted", "dim", "subtle", "secondary")
BG_KEYS = ("bg", "background", "surface", "panel", "card", "base")
ON_ACCENT_KEYS = ("on-accent", "onaccent", "accent-ink", "accent-fg",
                  "accent-text")

QT_CONSTANTS = {
    "INK": "text", "MUTED": "muted", "BG": "bg", "PANEL": "bg",
    "ACCENT": "accent", "ON_ACCENT": "on_accent", "WARN": "accent",
    "GOOD": "accent",
}

_CSS_VAR = re.compile(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\b")
_QT_CONST = re.compile(
    r"^([A-Z][A-Z0-9_]*)\s*=\s*[\"'](#[0-9a-fA-F]{3,8})[\"']", re.M)

_PLACEHOLDERS = (
    "lorem ipsum",
    "your text here",
    "your headline here",
    "insert text here",
    "sample text",
    "placeholder text",
    "dolor sit amet",
)
_TODO = re.compile(r"\bTODO\b|\bFIXME\b")

_IMG_SRC = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", re.I)
_FONT_SIZE = re.compile(r"font-size\s*:\s*(\d+(?:\.\d+)?)px", re.I)
_SPACING = re.compile(
    r"(?:margin|padding|gap|row-gap|column-gap)(?:-[a-z]+)?\s*:\s*([^;{}]+)", re.I)


class Finding:
    def __init__(self, level: str, code: str, message: str,
                 file: str = "", line: int = 0) -> None:
        self.level = level
        self.code = code
        self.message = message
        self.file = file
        self.line = line

    def as_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message,
                "file": self.file, "line": self.line}

    def __str__(self) -> str:
        where = f" ({self.file}{':' + str(self.line) if self.line else ''})" \
            if self.file else ""
        return f"[{self.level}] {self.code}: {self.message}{where}"


class Report:
    def __init__(self) -> None:
        self.findings: list[Finding] = []
        self.checked_files: list[str] = []

    def add(self, level: str, code: str, message: str,
            file: str = "", line: int = 0) -> None:
        self.findings.append(Finding(level, code, message, file, line))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if not self.findings:
            return (f"Design gate passed: {len(self.checked_files)} file(s), "
                    "no issues.")
        head = ("Design gate passed" if self.ok else "Design gate FAILED")
        lines = [f"{head}: {len(self.errors)} error(s), "
                 f"{len(self.warnings)} warning(s), "
                 f"{len(self.checked_files)} file(s) checked."]
        lines += [f"  {f}" for f in self.findings[:20]]
        if len(self.findings) > 20:
            lines.append(f"  … {len(self.findings) - 20} more")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {"ok": self.ok, "files": list(self.checked_files),
                "errors": [f.as_dict() for f in self.errors],
                "warnings": [f.as_dict() for f in self.warnings]}


# ── colour ───────────────────────────────────────────────────────────────────

def _classify(name: str) -> str | None:
    key = name.strip().lower().lstrip("-")
    if key in ON_ACCENT_KEYS:
        return "on_accent"
    if key in MUTED_KEYS:
        return "muted"
    if key in TEXT_KEYS:
        return "text"
    if key in BG_KEYS:
        return "bg"
    if key == "accent":
        return "accent"
    return None


def check_colour_map(colours: dict[str, str], report: Report,
                     file: str = "") -> None:
    """Check every named text/surface pair in one palette."""
    text = {k: v for k, v in colours.items() if _classify(k) == "text"}
    muted = {k: v for k, v in colours.items() if _classify(k) == "muted"}
    bgs = {k: v for k, v in colours.items() if _classify(k) == "bg"}
    on_accent = {k: v for k, v in colours.items() if _classify(k) == "on_accent"}
    accent = {k: v for k, v in colours.items() if _classify(k) == "accent"}

    for fg_name, fg in list(text.items()) + list(muted.items()):
        for bg_name, bg in bgs.items():
            ratio = contrast_ratio(fg, bg)
            if ratio < AA_TEXT:
                report.add("error", "contrast",
                           f"{fg_name} {fg} on {bg_name} {bg} is {ratio:.2f}:1, "
                           f"needs {AA_TEXT}:1 for body text", file)
    for fg_name, fg in on_accent.items():
        for bg_name, bg in accent.items():
            ratio = contrast_ratio(fg, bg)
            if ratio < AA_TEXT:
                report.add("error", "contrast",
                           f"{fg_name} {fg} on {bg_name} {bg} is {ratio:.2f}:1, "
                           f"needs {AA_TEXT}:1 for button text", file)
    for fg_name, fg in accent.items():
        for bg_name, bg in bgs.items():
            ratio = contrast_ratio(fg, bg)
            if ratio < AA_LARGE:
                report.add("error", "contrast",
                           f"{fg_name} {fg} on {bg_name} {bg} is {ratio:.2f}:1, "
                           f"needs {AA_LARGE}:1 to be visible as a UI boundary",
                           file)


def colours_from_css(text: str) -> dict[str, str]:
    return {name: value for name, value in _CSS_VAR.findall(text)}


def colours_from_qt(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for const, value in _QT_CONST.findall(text):
        kind = QT_CONSTANTS.get(const)
        if kind is None:
            continue
        # Two constants can mean the same role (BG and PANEL); keep both names
        # so the message points at real identifiers.
        found[const.lower() if const != "BG" else "bg"] = value
    return found


# ── content ──────────────────────────────────────────────────────────────────

def _visible_text(html: str) -> str:
    """Strip tags, <script> and <style> so attributes are not read as copy."""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def check_placeholders(html: str, report: Report, file: str = "") -> None:
    visible = _visible_text(html).lower()
    for phrase in _PLACEHOLDERS:
        if phrase in visible:
            report.add("error", "placeholder",
                       f"placeholder copy in the page: {phrase!r}", file)
    for match in _TODO.finditer(visible.upper()):
        report.add("error", "placeholder",
                   f"unfinished marker in the page: {match.group(0)!r}", file)


def check_images(html: str, base: Path, report: Report,
                 file: str = "") -> None:
    for src in _IMG_SRC.findall(html):
        value = src.strip()
        if not value or value.startswith(("http://", "https://", "data:",
                                          "//")):
            continue
        cleaned = value.split("?", 1)[0].split("#", 1)[0]
        if cleaned.startswith("/"):
            # Served from the project root by Flask/static server.
            candidate = base / cleaned.lstrip("/")
        else:
            candidate = (base / cleaned).resolve()
        if not candidate.exists():
            report.add("error", "broken-image",
                       f"image does not exist: {value}", file)


def check_scales(css: str, report: Report, file: str = "") -> None:
    sizes = sorted({float(v) for v in _FONT_SIZE.findall(css)})
    if len(sizes) > 8:
        report.add("warning", "type-scale",
                   f"{len(sizes)} distinct font sizes ({', '.join(f'{s:g}' for s in sizes[:10])})"
                   " — a scale has ~6 steps", file)

    off_scale: set[float] = set()
    for value in _SPACING.findall(css):
        for number in re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)px", value):
            px = float(number)
            if px not in (0, 1) and px % 4 != 0:
                off_scale.add(px)
    if len(off_scale) >= 3:
        sample = ", ".join(f"{s:g}px" for s in sorted(off_scale)[:8])
        report.add("warning", "spacing-scale",
                   f"spacing values off the 4px scale: {sample}", file)


def check_dead_links(html: str, report: Report, file: str = "") -> None:
    dead = len(re.findall(r"""(?i)<a\b[^>]*?\bhref\s*=\s*["']#["']""", html))
    if dead:
        report.add("warning", "dead-link",
                   f"{dead} link(s) point at '#' and go nowhere", file)


# ── entry points ─────────────────────────────────────────────────────────────

def check_text(name: str, content: str, base: Path | None = None,
               report: Report | None = None) -> Report:
    """Check one file's contents (path only used for messages and images)."""
    report = report or Report()
    lower = name.lower()
    if lower.endswith((".css",)):
        check_colour_map(colours_from_css(content), report, name)
        check_scales(content, report, name)
    elif lower.endswith((".html", ".htm")):
        inline = "\n".join(re.findall(r"(?is)<style[^>]*>(.*?)</style>", content))
        colours = colours_from_css(inline)
        if colours:
            check_colour_map(colours, report, name)
        if inline:
            check_scales(inline, report, name)
        check_placeholders(content, report, name)
        check_images(content, base or Path("."), report, name)
        check_dead_links(content, report, name)
    elif lower.endswith(".py"):
        colours = colours_from_qt(content)
        if colours:
            check_colour_map(colours, report, name)
        elif "STYLESHEET" in content or "QPushButton" in content:
            # A theme module whose palette is still a template placeholder
            # cannot be verified; say so instead of passing it silently.
            report.add("warning", "palette-unverified",
                       "theme module has no literal palette to check — "
                       "contrast was not verified", name)
    return report


def check_project(workspace: str | Path, *, max_files: int = 400) -> Report:
    """Check a generated project folder (html, css, and Qt theme modules)."""
    root = Path(workspace)
    report = Report()
    if not root.exists():
        report.add("error", "missing", f"project folder does not exist: {root}")
        return report

    skipped_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv",
                    "dist", "build", ".gev-cache"}
    seen = 0
    for path in sorted(root.rglob("*")):
        if seen >= max_files:
            report.add("warning", "limit",
                       f"stopped after {max_files} files")
            break
        if not path.is_file():
            continue
        if any(part in skipped_dirs for part in path.parts):
            continue
        if path.suffix.lower() not in (".html", ".htm", ".css", ".py"):
            continue
        # Only theme modules carry a palette worth checking.
        if path.suffix.lower() == ".py" and path.name not in ("theme.py",
                                                              "styles.py"):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:                     # pragma: no cover
            report.add("warning", "unreadable", f"{path}: {exc}")
            continue
        seen += 1
        report.checked_files.append(str(path.relative_to(root)))
        check_text(path.name, content, base=path.parent, report=report)

    if not report.checked_files:
        # Nothing checked is not the same as nothing wrong. A gate that passes
        # on an empty folder would let a build that wrote no UI claim success.
        report.add("error", "nothing-checked",
                   f"no HTML, CSS or theme file to check under {root}")
    return report


def check_files(paths, *, root: str | Path | None = None) -> Report:
    """Check an explicit list of files — the ones a build actually produced.

    Verifying a whole tree judges code the build never touched: a project
    living inside another repository picked up the host's CSS and failed on
    colours nobody in this build wrote. The caller knows what it produced, so
    that is what is checked here.
    """
    report = Report()
    root_path = Path(root) if root else None
    for raw in paths or ():
        path = Path(raw)
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in (".html", ".htm", ".css", ".py"):
            continue
        if suffix == ".py" and path.name not in ("theme.py", "styles.py"):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:                     # pragma: no cover
            report.add("warning", "unreadable", f"{path}: {exc}")
            continue
        try:
            label = str(path.relative_to(root_path)) if root_path else str(path)
        except ValueError:
            label = str(path)
        report.checked_files.append(label)
        check_text(path.name, content, base=path.parent, report=report)

    if not report.checked_files:
        report.add("warning", "nothing-checked",
                   "no HTML, CSS or theme file was produced to check")
    return report


def check_rendered(url: str, *, timeout: float = 20.0,
                   settle: int = 700) -> Report:
    """Load a page in a real engine and report what only the runtime shows.

    The source checks cannot see an image whose file exists but whose path is
    wrong after the server resolves it, or a script that throws on load. This
    loads the page in QtWebEngine, asks the DOM which images actually failed,
    and records every console error.

    Qt is imported here rather than at module scope so the source checks stay
    usable on a machine without QtWebEngine.
    """
    report = Report()
    import threading
    if threading.current_thread() is not threading.main_thread():
        try:
            import json, subprocess
            cmd = [
                sys.executable, "-c",
                "import sys, json; from core.design_check import check_rendered; "
                "rep = check_rendered(sys.argv[1]); "
                "print(json.dumps({'ok': rep.ok, 'findings': [f.as_dict() for f in rep.findings]}))",
                url
            ]
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
            if p.returncode == 0 and p.stdout.strip():
                data = json.loads(p.stdout.strip().splitlines()[-1])
                for f in data.get("findings", []):
                    report.findings.append(Finding(
                        severity=f["severity"],
                        code=f["code"],
                        message=f["message"],
                        file=f.get("file", ""),
                        line=f.get("line", 0),
                        context=f.get("context", ""),
                    ))
                return report
        except Exception as exc:
            report.add("warning", "runtime-subprocess-failed", f"Subprocess check failed: {exc}")
            return report

    try:
        from PyQt6.QtCore import QEventLoop, QTimer, QUrl
        from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtWidgets import QApplication
    except Exception as exc:                     # pragma: no cover
        report.add("warning", "runtime-unavailable",
                   f"QtWebEngine is not available: {exc}")
        return report

    # Never an empty argv: QtWebEngine builds Chromium's command line from it,
    # and with no program name it logs "Argument list is empty" and then takes
    # the whole interpreter down with no Python traceback (exit 127).
    app = (QApplication.instance()
           or QApplication(sys.argv[:1] or ["keysai-design-check"]))   # noqa: F841
    console_errors: list[str] = []

    class _Page(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, message, line, source):
            try:
                if int(level) == int(
                        QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel):
                    console_errors.append(f"{message} ({source}:{line})")
            except Exception:
                pass

    view = QWebEngineView()
    page = _Page(view)
    view.setPage(page)
    view.resize(1280, 900)

    # Uncaught exceptions do not always reach javaScriptConsoleMessage, so catch
    # them at DocumentCreation and read the list back after load.
    hook = QWebEngineScript()
    hook.setName("keysai-runtime-error-hook")
    hook.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    hook.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    hook.setSourceCode(
        "window.__keysaiErrors = [];"
        "window.addEventListener('error', function (e) {"
        "  try { window.__keysaiErrors.push("
        "    (e.message || 'error') + ' at ' + (e.filename || '') + ':' + (e.lineno || 0)"
        "  ); } catch (_) {}"
        "});"
        # console.error is not forwarded by every engine configuration, so it
        # is wrapped here too: a library that logs an error still counts.
        "(function () {"
        "  var original = console.error;"
        "  console.error = function () {"
        "    try { window.__keysaiErrors.push("
        "      'console.error: ' + Array.prototype.join.call(arguments, ' ')"
        "    ); } catch (_) {}"
        "    return original.apply(console, arguments);"
        "  };"
        "})();"
    )
    page.scripts().insert(hook)

    loaded = {"ok": False}
    wait = QEventLoop()

    def _finished(ok: bool) -> None:
        loaded["ok"] = bool(ok)
        # Give the page a moment to run its own scripts before reading the DOM.
        QTimer.singleShot(settle, wait.quit)

    page.loadFinished.connect(_finished)
    QTimer.singleShot(int(timeout * 1000), wait.quit)
    view.load(QUrl(url))
    wait.exec()

    if not loaded["ok"]:
        report.add("error", "load-failed", f"the page did not load: {url}")
        return report

    # Ask the DOM what actually failed, rather than assuming from the HTML.
    broken: list[str] = []
    js = ("Array.from(document.images)"
          ".filter(function(i){return !i.complete || i.naturalWidth === 0;})"
          ".map(function(i){return i.currentSrc || i.src;})")
    result = QEventLoop()

    def _images(found) -> None:
        if isinstance(found, list):
            broken.extend(str(v) for v in found)
        result.quit()

    page.runJavaScript(js, _images)
    QTimer.singleShot(5000, result.quit)
    result.exec()

    thrown: list[str] = []
    errors_loop = QEventLoop()

    def _errors(found) -> None:
        if isinstance(found, list):
            thrown.extend(str(v) for v in found)
        errors_loop.quit()

    page.runJavaScript("window.__keysaiErrors || []", _errors)
    QTimer.singleShot(5000, errors_loop.quit)
    errors_loop.exec()

    for message in thrown:
        text = str(message)
        if text.startswith("console.error:"):
            text = text.split(":", 1)[1].strip()
            label = "console error"
        else:
            label = "uncaught script error"
        report.add("error", "console-error", f"{label}: {text}", url)
    for src in broken:
        report.add("error", "broken-image",
                   f"image failed to load at runtime: {src}", url)
    for message in console_errors:
        report.add("error", "console-error", message, url)

    report.checked_files.append(url)

    # Chromium releases the profile at interpreter exit and refuses to do it
    # while a page is still alive, which shows up as a segfault *after* the
    # tests have printed their results. Delete the page now and give Qt the
    # turns it needs to act on the deferred deletion.
    try:
        page.loadFinished.disconnect(_finished)
    except (TypeError, RuntimeError):
        pass
    try:
        view.stop()
        view.setUrl(QUrl("about:blank"))
    except RuntimeError:
        pass
    for target in (view, page):
        try:
            target.deleteLater()
        except RuntimeError:
            pass                        # already gone with its parent
    if app is not None:
        # Deferred deletes are posted, not run: without this they wait for a
        # main event loop that a headless caller never returns to, and the
        # process segfaults on exit instead.
        from PyQt6.QtCore import QCoreApplication, QEvent

        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    return report


def main(argv: list[str] | None = None) -> int:
    args = (argv if argv is not None else sys.argv[1:])
    target = args[0] if args else "."
    report = check_project(target)
    print(report.summary())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
