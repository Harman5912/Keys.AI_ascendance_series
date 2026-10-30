"""The globe must never park the window while it opens.

The report was "asked it to open the globe, the whole app lagged and stopped
responding". The cause was structural: every wait in ``globe.service`` was
executed *on the Qt GUI thread* through ``run_on_gui_thread``, so opening the
app (server start, page load, readiness polling) held that thread inside nested
event loops for up to three minutes.

These tests hold the fix in place with a heartbeat: while ``open()`` runs on a
worker thread — exactly how ``main.py`` dispatches the tool — a 30 ms timer must
keep firing on the GUI thread. A regression shows up as one enormous gap.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from globe.service import GlobeService  # noqa: E402
from globe.workspace_ui import GlobeWorkspace  # noqa: E402


class _Bridge(QObject):
    """Delivers a callable to the GUI thread, like MainWindow does."""

    call = pyqtSignal(object)


class _FakePage:
    """Answers the three scripts the service asks, on the GUI thread."""

    def __init__(self):
        self.asked: list[str] = []

    def runJavaScript(self, script, callback):   # noqa: N802 - Qt's name
        self.asked.append(script)
        if "__godsEyeView" in script and "voiceCommands" in script:
            reply = {"ok": True, "state": "ready"}
        elif "document.readyState" in script:
            reply = {"ready": "complete", "url": "http://127.0.0.1:4173/"}
        else:
            reply = {"pending": False, "ok": True, "result": {"moved": True}}
        QTimer.singleShot(10, lambda: callback(json.dumps(reply)))


class _FakeWorkspace:
    """A page that takes its time, so a blocking wait would be visible."""

    def __init__(self, load_seconds: float = 1.2, ready_seconds: float = 1.0):
        self.page_obj = _FakePage()
        self.load_seconds = load_seconds
        self.ready_seconds = ready_seconds
        self._load_event = threading.Event()
        self._load_ok = None
        self.url = ""

    def page(self):
        return self.page_obj

    def load(self, url: str) -> None:
        self.url = url
        self._load_ok = None
        self._load_event.clear()

        def _finish():
            self._load_ok = True
            self._load_event.set()

        timer = threading.Timer(self.load_seconds, _finish)
        timer.daemon = True
        timer.start()

    def wait_for_load_threaded(self, timeout: float = 90.0) -> bool:
        if not self._load_event.wait(timeout):
            return False
        return bool(self._load_ok)

    def wait_for_load(self, timeout: float = 90.0) -> bool:   # GUI-thread variant
        return self.wait_for_load_threaded(timeout)

    def shutdown(self) -> None:
        return None


class _FakeServer:
    def __init__(self, url: str = "http://127.0.0.1:4173/"):
        self.url = url
        self.port = 4173
        self.ensure_calls = 0

    def ensure(self, timeout: float = 0.0) -> dict:
        self.ensure_calls += 1
        time.sleep(0.6)                     # stands in for a Vite cold start
        return self.status()

    def status(self) -> dict:
        return {"running": True, "owned": False, "port": self.port,
                "url": self.url, "pid": 0, "error": "", "uptime_s": 1.0}


class _FakeWindow:
    """The slice of MainWindow the service uses, with real thread marshalling."""

    def __init__(self, workspace):
        self._globe_ws = workspace
        self._win = self
        self._bridge = _Bridge()
        self._bridge.call.connect(self._run, Qt.ConnectionType.QueuedConnection)
        self.hidden = False

    def _run(self, job) -> None:
        job()

    def run_on_gui_thread(self, fn, timeout: float = 180.0):
        done = threading.Event()
        box: dict = {}

        def _job():
            try:
                box["value"] = fn()
            except BaseException as exc:        # re-raised in the caller
                box["error"] = exc
            finally:
                done.set()

        self._bridge.call.emit(_job)
        if not done.wait(timeout):
            raise TimeoutError("The UI did not answer in time.")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def _open_globe_workspace(self, url: str) -> dict:
        self._globe_ws.load(url)
        return {"ok": True, "url": url}

    def _show_hud_view(self) -> None:
        self.hidden = True


class TestGlobeKeepsTheWindowAlive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _open_with_heartbeat(self, service):
        """Run open() on a worker thread; measure GUI stalls meanwhile."""
        gaps: list[float] = []
        last = [time.perf_counter()]

        def tick():
            now = time.perf_counter()
            gaps.append(now - last[0])
            last[0] = now

        beat = QTimer()
        beat.setInterval(30)
        beat.timeout.connect(tick)
        beat.start()

        box: dict = {}

        def work():
            box["result"] = service.open(timeout=20)

        worker = threading.Thread(target=work, daemon=True)
        worker.start()

        deadline = time.perf_counter() + 40
        while worker.is_alive() and time.perf_counter() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        beat.stop()
        worker.join(timeout=5)
        return box.get("result"), (max(gaps) if gaps else 0.0), len(gaps)

    def test_open_does_not_freeze_the_gui_thread(self):
        workspace = _FakeWorkspace(load_seconds=1.2, ready_seconds=1.0)
        window = _FakeWindow(workspace)
        service = GlobeService()
        service.server = _FakeServer()
        service.attach(window)

        result, worst_gap, beats = self._open_with_heartbeat(service)

        self.assertTrue(result and result.get("ok"),
                        f"open failed: {result}")
        self.assertEqual(result.get("action"), "OPEN_GLOBE")
        # A page that takes ~2.2 s to become ready must not hold the GUI for
        # more than a fraction of that; the heartbeat ran throughout.
        self.assertGreater(beats, 40, "the heartbeat barely ran")
        self.assertLess(worst_gap, 0.4,
                        f"the GUI thread stalled for {worst_gap * 1000:.0f} ms")

    def test_reopen_reuses_the_page_instead_of_reloading_it(self):
        workspace = _FakeWorkspace(load_seconds=0.4, ready_seconds=0.4)
        window = _FakeWindow(workspace)
        service = GlobeService()
        service.server = _FakeServer()
        service.attach(window)

        first, _, _ = self._open_with_heartbeat(service)
        self.assertTrue(first.get("ok"), first)
        asked = len(workspace.page_obj.asked)
        second, worst_gap, _ = self._open_with_heartbeat(service)
        self.assertTrue(second.get("ok"), second)
        self.assertLess(worst_gap, 0.4)
        # The second open still talks to the live page, and does not reload it.
        self.assertGreater(len(workspace.page_obj.asked), asked)


class TestWorkspaceDoesNotReloadItself(unittest.TestCase):
    """`load()` on the URL already on screen is a no-op, not a reload."""

    def test_same_url_is_not_loaded_twice(self):
        loaded: list[str] = []

        class View:
            def __init__(self):
                self._url = "http://127.0.0.1:4173/"

            def url(self):
                return type("U", (), {"toString": lambda self: _url_holder[0]})()

            def setUrl(self, url):      # noqa: N802 - Qt's name
                loaded.append(url.toString())
                _url_holder[0] = url.toString()

        _url_holder = ["http://127.0.0.1:4173/"]
        ws = GlobeWorkspace.__new__(GlobeWorkspace)
        ws.view = View()
        ws._load_ok = True
        ws._load_event = threading.Event()
        ws._load_event.set()
        ws.set_status = lambda text: None

        ws.load("http://127.0.0.1:4173/")
        self.assertEqual(loaded, [], "an already-loaded page was reloaded")

        ws.load("http://127.0.0.1:4173/?x=1")
        self.assertEqual(loaded, ["http://127.0.0.1:4173/?x=1"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
