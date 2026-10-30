"""Attribute the globe-open stall to a single step, with mid-stall stacks.

The earlier probe proved the GUI thread went silent for 240 s while a worker
waited for it. A dump taken *after* the silence shows the wrong frames, so this
script does two things at once:

1. Times each step of opening the globe on the GUI thread and prints it
   immediately — whatever line prints last is the step that blocked.
2. Runs a sampler thread that notices the GUI heartbeat going stale and dumps
   every thread's Python frames *while it is stuck*, so the blocking call is
   named even if it never returns.

    python qa_artifacts/regression_tests/globe_open_cost.py
"""

from __future__ import annotations

import faulthandler
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

faulthandler.enable(all_threads=True)

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--enable-unsafe-swiftshader")

QA_DIR = ROOT / "qa_artifacts"
STACK_FILE = QA_DIR / "globe_open_stacks.txt"
REPORT_FILE = QA_DIR / "globe_open_report.txt"

URL = "http://127.0.0.1:4173/"
_lines: list[str] = []
_state = {"last_tick": time.time(), "phase": "startup", "dumps": 0}


def say(text: str) -> None:
    print(text, flush=True)
    _lines.append(text)


def sampler(stop: threading.Event) -> None:
    """Dump frames whenever the GUI heartbeat has been silent for a second."""
    while not stop.wait(0.1):
        silent = time.time() - _state["last_tick"]
        if silent < 1.0 or _state["dumps"] >= 3:
            continue
        _state["dumps"] += 1
        try:
            with open(STACK_FILE, "a", encoding="utf-8") as handle:
                handle.write(
                    f"\n=== GUI silent {silent:.1f}s during "
                    f"{_state['phase']} (sample {_state['dumps']}) ===\n"
                )
                faulthandler.dump_traceback(file=handle, all_threads=True)
        except OSError:
            pass


def main() -> int:
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    STACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        STACK_FILE.unlink()
    except OSError:
        pass

# `ui` imports QtWebEngine at module scope. Importing it BEFORE the
    # QApplication exists is what main.py's startup does, and the import order
    # is load-bearing: it is the difference between a live page and a globe
    # that silently reports itself unavailable.
    import ui

    app = QApplication.instance() or QApplication(sys.argv)
    ui._ensure_gui_imports()
    window = ui.MainWindow("icon.png")
    window.show()

    stop = threading.Event()
    threading.Thread(target=sampler, args=(stop,), daemon=True).start()
    # A 100 ms heartbeat: its silence is the definition of "stuck".
    beat = QTimer()
    beat.setInterval(100)
    beat.timeout.connect(lambda: _state.update(last_tick=time.time()))
    beat.start()

    def timed(name: str, fn):
        _state["phase"] = name
        say(f"[{time.strftime('%H:%M:%S')}] {name} …")
        t0 = time.perf_counter()
        value = fn()
        say(f"[{time.strftime('%H:%M:%S')}] {name} -> {time.perf_counter() - t0:.1f}s")
        QTimer.singleShot(0, lambda: _state.update(last_tick=time.time()))
        return value

    def run() -> None:
        try:
            from globe.workspace_ui import GlobeWorkspace

            from globe.workspace_ui import webengine_error

            say(f"    webengine: {webengine_error() or 'loaded'}")
            workspace = timed("1 construct GlobeWorkspace (QWebEngineView)",
                              lambda: GlobeWorkspace())
            if workspace is None:
                return
            say(f"    available={workspace.available}")

            def attach():
                workspace.setParent(window._center_stack)
                window._center_stack.addWidget(workspace)
                window._center_stack.setCurrentWidget(workspace)
                window._globe_ws = workspace

            timed("2 attach + show the stack page", attach)
            timed("3 setUrl", lambda: workspace.load(URL))
            ok = timed("4 wait_for_load(120)", lambda: workspace.wait_for_load(120))
            say(f"    load finished: {ok}")

            def probe():
                return workspace.view.page().runJavaScript(
                    "JSON.stringify({hidden: document.hidden,"
                    " glam: !!document.querySelector('canvas')})")

            timed("5 first runJavaScript", probe)
        except BaseException as exc:                    # reported, never hidden
            say(f"!! {type(exc).__name__}: {exc}")
        finally:
            _state["phase"] = "done"
            QTimer.singleShot(0, app.quit)

    window._center_stack = getattr(window, "_center_stack", None)
    if window._center_stack is None:
        say("!! MainWindow has no _center_stack")
        return 2

    QTimer.singleShot(1200, run)
    QTimer.singleShot(280_000, app.quit)
    app.exec()
    stop.set()

    say("")
    say("=" * 60)
    if STACK_FILE.exists():
        say(f"GUI-silence samples written to {STACK_FILE}")
    else:
        say("GUI never went silent for a full second")
    try:
        REPORT_FILE.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
