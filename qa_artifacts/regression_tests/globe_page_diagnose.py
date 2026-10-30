"""Diagnostic: what does the globe page actually do inside QtWebEngine?

Loads the running God's Eye View server in a QtWebEngine view, records every
console message and JS error, and reports the DOM state after a wait. Use this
when ``globe_live_probe.py`` says the app never published its runner.

    python qa_artifacts/regression_tests/globe_page_diagnose.py [seconds]
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--use-gl=swiftshader --enable-unsafe-swiftshader --no-sandbox --disable-gpu-sandbox",
)

from PyQt6.QtCore import QEventLoop, QTimer, QUrl        # noqa: E402
from PyQt6.QtWebEngineCore import QWebEnginePage         # noqa: E402
from PyQt6.QtWebEngineWidgets import QWebEngineView      # noqa: E402
from PyQt6.QtWidgets import QApplication                 # noqa: E402


class LoggingPage(QWebEnginePage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.messages: list[str] = []

    def javaScriptConsoleMessage(self, level, message, line, source):
        self.messages.append(f"[{level}] {message} ({source}:{line})")


def main() -> int:
    wait_s = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
    app = QApplication.instance() or QApplication(sys.argv)

    from globe.service import GlobeServer
    server = GlobeServer()
    status = server.ensure(timeout=240)
    print("server:", json.dumps(status))
    if not status.get("running"):
        return 1

    view = QWebEngineView()
    page = LoggingPage(view)
    view.setPage(page)
    view.resize(1280, 800)

    loaded = {}
    loop = QEventLoop()
    view.loadFinished.connect(lambda ok: (loaded.setdefault("ok", ok), loop.quit()))
    view.setUrl(QUrl(status["url"]))
    timer = QTimer(); timer.setSingleShot(True); timer.timeout.connect(loop.quit)
    timer.start(int(60_000))
    loop.exec()
    timer.stop()
    print("loadFinished:", loaded.get("ok"))

    deadline = time.time() + wait_s
    state = {}
    while time.time() < deadline:
        result = {}
        probe = QEventLoop()

        def _cb(value):
            result["v"] = value
            probe.quit()

        page.runJavaScript(
            "JSON.stringify({"
            "title: document.title,"
            "app: !!window.__godsEyeView,"
            "runner: !!(window.__godsEyeView && window.__godsEyeView.voiceCommands"
            "  && typeof window.__godsEyeView.voiceCommands.runner === 'function'),"
            "loader: (document.querySelector('.loader-status') || {}).textContent || '',"
            "loaderVisible: !!document.getElementById('loading-screen'),"
            "webgl: (function(){var c=document.createElement('canvas');"
            "  try{return !!(c.getContext('webgl2')||c.getContext('webgl'));}"
            "  catch(e){return false;}})(),"
            "bodyChildren: document.body ? document.body.children.length : -1"
            "})", _cb)
        pt = QTimer(); pt.setSingleShot(True); pt.timeout.connect(probe.quit)
        pt.start(5000)
        probe.exec()
        pt.stop()
        try:
            state = json.loads(result.get("v") or "{}")
        except ValueError:
            state = {}
        if state.get("runner"):
            break
        time.sleep(1.0)

    print("page state:", json.dumps(state, indent=2))
    print("\nconsole messages (last 40):")
    for line in page.messages[-40:]:
        print(" ", line)
    print(f"\ntotal console messages: {len(page.messages)}")
    view.setUrl(QUrl("about:blank"))
    return 0 if state.get("runner") else 1


if __name__ == "__main__":
    sys.exit(main())
