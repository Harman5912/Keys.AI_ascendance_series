"""globe.service — lifecycle and command adapter for God's Eye View.

Two jobs, both real:

1. **Run the app.** God's Eye View is a Vite application. This module starts it
   as a local service on a loopback port, waits until that port actually
   answers, and reuses a server that is already running instead of spawning a
   second one. A port that answers with the app is adopted (and never killed on
   shutdown, because Keys.AI did not start it).

2. **Drive the app that exists.** The running page already publishes its own
   control surface:

       window.__godsEyeView.voiceCommands.runner(name, arguments)

   ``user`` code — that is the real God's Eye View action runner
   (``src/voice/gevActions.js``), the same object its own voice agent calls,
   exposed by ``src/app/tools.js``. Every command below therefore goes through
   the application's real implementation. Nothing here re-implements a globe,
   invents an API, or generates JavaScript from a model: the action name comes
   from a fixed allow-list and the arguments are JSON-encoded numbers, booleans
   and strings.

Environment note: QtWebEngine may only be touched from the Qt GUI thread. Every
page operation here is marshalled through the UI's ``run_on_gui_thread`` exactly
like the Research Browser does.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QEventLoop, QThread, QTimer
from PyQt6.QtWidgets import QApplication

from globe import install as globe_install
from globe import intents

DEFAULT_PORT = 4173
PORT_SCAN = range(4173, 4200)
START_TIMEOUT = 180.0          # first `vite` start compiles on demand
READY_TIMEOUT = 45.0           # page load -> runner published
PROBE_TIMEOUT = 2.5
JS_TIMEOUT = 12.0
# A camera flight plus geocoding. Bundled cities answer in under a second; a
# name that needs the geocoder and a long flight needs considerably longer.
NAVIGATE_TIMEOUT = 60.0

#: Actions Keys.AI is allowed to send. Anything else is refused before it can
#: reach the page — this is the whole safety story for the adapter.
ALLOWED_ACTIONS = frozenset({
    "fly_to_location",
    "adjust_camera_zoom",
    "zoom_to_globe",
    "set_layer_visibility",
    "get_current_view_state",
    "show_data_layers_menu",
    "track_entity",
    "stop_tracking",
})

_state_lock = threading.RLock()
#: Serialises ``open()``. Deliberately a *different* lock from ``_state_lock``:
#: `open()` holds its lock across a round-trip to the GUI thread, and the job
#: it posts there calls `register_ui()` -> `get_service()`. With one lock for
#: both, the GUI thread waits for the worker and the worker waits for the GUI
#: until the 240s timeout fires — the window frozen for four minutes.
_open_lock = threading.Lock()
_service: "GlobeService | None" = None


def _log_path() -> Path:
    root = globe_install.project_root()
    logs = root / ".gev-logs"
    try:
        logs.mkdir(parents=True, exist_ok=True)
    except OSError:
        return root / "globe.log"
    return logs / "keysai-globe.log"


def _pidfile() -> Path:
    return globe_install.project_root() / "config" / "globe_server.json"


def _http_ok(port: int) -> bool:
    """True when `port` answers with God's Eye View."""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/", timeout=PROBE_TIMEOUT
        ) as response:
            if response.status != 200:
                return False
            body = response.read(8192).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        return False
    lowered = body.lower()
    return "gods-eye-view" in lowered or "god's eye view" in lowered or "/src/main.js" in lowered


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _port_for() -> int:
    """The port to use: an adopted running server first, else the first free one."""
    if _http_ok(DEFAULT_PORT):
        return DEFAULT_PORT
    for port in PORT_SCAN:
        if _port_free(port):
            return port
    raise RuntimeError(
        "No free local port for the globe "
        f"(tried {PORT_SCAN.start}-{PORT_SCAN.stop - 1})."
    )


class GlobeServer:
    """The local God's Eye View service process."""

    def __init__(self, install_dir: Path | None = None):
        self.install_dir = Path(install_dir) if install_dir else globe_install.default_dir()
        self.port: int = 0
        self._process: subprocess.Popen | None = None
        self._owned = False
        self._log_handle = None
        self._error = ""
        self._started_at = 0.0

    # ── State ─────────────────────────────────────────────────────────────
    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/" if self.port else ""

    @property
    def running(self) -> bool:
        if not self.port:
            return False
        if self._owned and self._process is not None and self._process.poll() is not None:
            return False
        return _http_ok(self.port)

    @property
    def owned(self) -> bool:
        return self._owned

    def status(self) -> dict:
        return {
            "running": self.running,
            "owned": self._owned,
            "port": self.port,
            "url": self.url,
            "pid": self._process.pid if self._process is not None else 0,
            "error": self._error,
            "uptime_s": round(time.time() - self._started_at, 1) if self._started_at else 0.0,
            "log": str(_log_path()),
        }

    # ── Start / stop ──────────────────────────────────────────────────────
    def ensure(self, timeout: float = START_TIMEOUT) -> dict:
        """Make sure a server is reachable. Returns a status dict."""
        if self.running:
            self._error = ""
            return self.status()

        check = globe_install.check(self.install_dir)
        if not check.ok:
            self._error = "; ".join(check.problems)
            result = self.status()
            result["problems"] = check.problems
            result["hints"] = check.hints
            return result

        # A server left running by a previous session is adopted, not killed.
        if _http_ok(DEFAULT_PORT):
            self.port = DEFAULT_PORT
            self._owned = False
            self._error = ""
            self._started_at = time.time()
            return self.status()

        self.port = _port_for()
        self._spawn()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._process is not None and self._process.poll() is not None:
                self._error = (
                    "The globe server exited during startup "
                    f"(code {self._process.returncode}). See {_log_path()}."
                )
                return self.status()
            if _http_ok(self.port):
                self._error = ""
                self._remember()
                return self.status()
            time.sleep(0.4)

        self._error = (
            f"The globe server did not answer on port {self.port} within "
            f"{int(timeout)}s. See {_log_path()}."
        )
        return self.status()

    def _spawn(self) -> None:
        npm = "npm.cmd" if os.name == "nt" else "npm"
        env = dict(os.environ)
        env["PORT"] = str(self.port)
        env["HOST"] = "127.0.0.1"
        env.setdefault("BROWSER", "none")
        env["FORCE_COLOR"] = "0"
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            self._log_handle = open(_log_path(), "a", encoding="utf-8", errors="replace")
            self._log_handle.write(
                f"\n=== Keys.AI starting the globe on port {self.port} "
                f"at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
            )
            self._log_handle.flush()
            self._process = subprocess.Popen(
                [npm, "run", "dev", "--", "--port", str(self.port), "--strictPort"],
                cwd=str(self.install_dir),
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=creationflags,
            )
            self._owned = True
            self._started_at = time.time()
        except OSError as exc:
            self._error = f"Could not start the globe server: {exc}"
            self._process = None
            self._owned = False
            self._close_log()

    def _remember(self) -> None:
        try:
            _pidfile().write_text(json.dumps(self.status(), indent=2), encoding="utf-8")
        except OSError:
            pass

    def _close_log(self) -> None:
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None

    def stop(self) -> dict:
        """Stop the server, but only when Keys.AI started it."""
        if self._owned and self._process is not None:
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(self._process.pid), "/T", "/F"],
                        capture_output=True, timeout=20,
                    )
                else:
                    self._process.terminate()
                    try:
                        self._process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        self._process.kill()
            except (OSError, subprocess.SubprocessError):
                try:
                    self._process.kill()
                except OSError:
                    pass
        stopped = self._owned
        self._process = None
        self._owned = False
        self._close_log()
        try:
            _pidfile().unlink()
        except OSError:
            pass
        if stopped:
            self.port = 0
        return self.status()


class GlobeService:
    """Owns the globe server and the in-app page, and answers commands."""

    def __init__(self):
        self.server = GlobeServer()
        self._ui = None
        self._page_getter = None
        self._token = 0
        self._last = ""
        self._history: list[dict] = []

    # ── Wiring ────────────────────────────────────────────────────────────
    def attach(self, ui) -> None:
        """Bind to the main window; called once at startup."""
        self._ui = ui

    def _gui(self, fn, timeout: float = 240.0):
        """Run `fn` on the Qt GUI thread (QtWebEngine requirement)."""
        app = QApplication.instance()
        if app is None or QThread.currentThread() is app.thread():
            return fn()
        for candidate in (self._ui, getattr(self._ui, "_win", None)):
            runner = getattr(candidate, "run_on_gui_thread", None)
            if callable(runner):
                return runner(fn, timeout)
        raise RuntimeError("The globe needs the Keys.AI UI to reach the Qt thread.")

    @staticmethod
    def _on_gui() -> bool:
        """True when the *caller* is already the Qt GUI thread.

        A wait that pumps the event loop is only correct on that thread; on a
        worker thread anything but a plain sleep is wasted work, and pumping a
        loop that is not ours is a re-entrancy bug waiting to happen.
        """
        app = QApplication.instance()
        return app is None or QThread.currentThread() is app.thread()

    def _await(self, event: threading.Event, timeout: float) -> bool:
        """Wait for `event` without freezing the window.

        From a worker thread this is a blocking wait — the GUI keeps painting by
        itself. From the GUI thread it pumps the event loop in short slices, so
        the window still repaints and still handles input while the globe starts.
        """
        if not self._on_gui():
            return event.wait(timeout)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if event.is_set():
                return True
            self._pump(50)
        return event.is_set()

    def _workspace(self):
        return getattr(self._ui, "_globe_ws", None)

    def _page(self):
        workspace = self._workspace()
        return workspace.page() if workspace is not None else None

    # ── Page open / close ─────────────────────────────────────────────────
    def open(self, timeout: float = READY_TIMEOUT) -> dict:
        """Open the globe workspace and wait until it can accept commands."""
        with _open_lock:
            server = self._ensure_server()
            if not server.get("running"):
                return _fail(
                    self._error_message(server),
                    stage="server",
                    details=server,
                )

            # Creates the view once and points it at the server. Cheap on the
            # GUI thread: it hands the URL to Chromium and returns.
            opened = self._gui(lambda: self._open_workspace(server["url"]))
            if not opened.get("ok"):
                return opened

            loaded = self._wait_load(timeout)
            if not loaded.get("ok"):
                return loaded

            ready = self._wait_ready(timeout)
            if not ready.get("ok"):
                return ready

            self._record(intents.OPEN_GLOBE, {"url": server["url"]})
            return {
                "ok": True,
                "action": intents.OPEN_GLOBE,
                "url": server["url"],
                "server": self.server.status(),
                "view": ready.get("view", {}),
            }

    def _open_workspace(self, url: str) -> dict:
        """Create (once) and show the globe workspace. GUI thread only."""
        window = self._ui
        opener = getattr(window, "_open_globe_workspace", None)
        if not callable(opener):
            return _fail("The Keys.AI window does not expose a globe workspace.")
        return opener(url)

    def _ensure_server(self) -> dict:
        """Start or adopt the local server without freezing the caller.

        ``GlobeServer.ensure`` sleeps and polls for up to three minutes while
        Vite compiles. Run from the GUI thread that would be a freeze, so it is
        moved to a worker thread whenever this is reached from there.
        """
        if not self._on_gui():
            return self.server.ensure()
        done = threading.Event()
        box: dict = {}

        def _run():
            try:
                box["status"] = self.server.ensure()
            except Exception as exc:               # reported, never raised here
                box["error"] = exc
            finally:
                done.set()

        threading.Thread(target=_run, name="globe-server-start",
                         daemon=True).start()
        if not self._await(done, START_TIMEOUT + 30):
            return {"running": False,
                    "error": "The globe server did not finish starting."}
        if "error" in box:
            return {"running": False, "error": str(box["error"])}
        return box.get("status") or {}

    def _wait_load(self, timeout: float) -> dict:
        """Wait for the page's own load-finished signal.

        The wait happens on the calling thread. On the GUI thread the window is
        pumped meanwhile; on a worker thread it is a plain event wait, so the
        window never waits for a page it is not being asked about.
        """
        workspace = self._workspace()
        if workspace is None:
            return _fail("The globe workspace is not open.")
        waiter = (getattr(workspace, "wait_for_load_threaded", None)
                  if not self._on_gui()
                  else getattr(workspace, "wait_for_load", None))
        if not callable(waiter):
            return {"ok": True}
        if waiter(min(timeout, 150.0)):
            return {"ok": True}
        return _fail(
            "The globe page did not finish loading in time. Check that the "
            f"local server is healthy ({self.server.url or 'not started'}).",
            stage="load",
        )

    def close(self) -> dict:
        """Return to the assistant. The server keeps running for a fast reopen."""
        def _job():
            workspace = self._workspace()
            if workspace is None:
                return {"ok": True, "action": intents.CLOSE_GLOBE, "was_open": False}
            try:
                workspace.shutdown()
            except Exception:
                pass
            window = self._ui
            back = getattr(window, "_show_hud_view", None)
            if callable(back):
                back()
            return {"ok": True, "action": intents.CLOSE_GLOBE, "was_open": True}

        result = self._gui(_job)
        self._record(intents.CLOSE_GLOBE, {})
        return result

    def shutdown(self, stop_server: bool = True) -> None:
        """App exit: tear the page down, then stop a server Keys.AI started."""
        try:
            self._gui(lambda: self._shutdown_workspace())
        except Exception:
            pass
        if stop_server:
            try:
                self.server.stop()
            except Exception:
                pass

    def _shutdown_workspace(self) -> dict:
        workspace = self._workspace()
        if workspace is not None:
            try:
                workspace.shutdown()
            except Exception:
                pass
        return {"ok": True}

    # ── Readiness ─────────────────────────────────────────────────────────
    _READY_JS = r"""
(function () {
  try {
    var g = window.__godsEyeView;
    if (!g) return JSON.stringify({ok: false, state: 'no-app'});
    var vc = g.voiceCommands;
    if (!vc || typeof vc.runner !== 'function') {
      return JSON.stringify({ok: false, state: 'no-runner'});
    }
    return JSON.stringify({ok: true, state: 'ready', layers:
      (g.dataManager && typeof g.dataManager.getLayerState === 'function')
        ? null : null});
  } catch (e) { return JSON.stringify({ok: false, state: 'error',
    error: String(e && e.message || e)}); }
})()
"""

    @staticmethod
    def _pump(milliseconds: int) -> None:
        """Let the Qt event loop run for a moment.

        Chromium's page work is driven by that loop. Sleeping instead of
        pumping stalls a loading page indefinitely when this runs on the GUI
        thread — which is exactly what a wait loop on the agent's worker
        thread looks like once the page is hosted in the main window.
        """
        app = QApplication.instance()
        if app is None or QThread.currentThread() is not app.thread():
            time.sleep(milliseconds / 1000.0)
            return
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(int(milliseconds))
        loop.exec()
        timer.stop()

    _DOCUMENT_JS = (
        "JSON.stringify({ready: document.readyState, "
        "url: location.href, title: document.title, "
        "loader: ((document.querySelector('.loader-status')||{}).textContent||'').slice(0,200)})"
    )

    #: Asked once, only when readiness fails — creating a WebGL context to test
    #: for WebGL is itself expensive and leaks a context per call.
    _WEBGL_JS = (
        "JSON.stringify({webgl: (function(){try{var c=document.createElement('canvas');"
        "return !!(c.getContext('webgl2')||c.getContext('webgl'));}"
        "catch(e){return false;}})(), "
        "ctxLost: typeof window.__godsEyeView === 'boolean'})"
    )

    def _wait_ready(self, timeout: float) -> dict:
        """Wait for the app inside the page to publish its command runner.

        Document load has already been awaited; this is the second, separate
        readiness gate. The runner exists only once the scene, data manager and
        controls are all live, so its presence — not an HTTP 200 — is what
        makes a globe command safe to send.
        """
        deadline = time.time() + timeout
        detail: dict = {}
        while time.time() < deadline:
            detail = self._js(self._DOCUMENT_JS, timeout=8.0) or detail
            probe = self._js(self._READY_JS, timeout=8.0)
            if probe.get("ok"):
                return {"ok": True, "view": probe}
            self._pump(1000)

        hint = ""
        webgl = (self._js(self._WEBGL_JS, timeout=6.0) or {}).get("webgl")
        if webgl is False:
            hint = (
                " Cesium needs WebGL and this Chromium build reports none; start "
                "Keys.AI with QTWEBENGINE_CHROMIUM_FLAGS=\"--enable-unsafe-swiftshader\" "
                "to fall back to software rendering."
            )
        return _fail(
            "The globe page loaded but never published its command runner "
            f"within {int(timeout)}s.{hint}",
            stage="app",
            details=detail,
        )

    # ── JavaScript bridge ─────────────────────────────────────────────────
    def _js(self, script: str, timeout: float = JS_TIMEOUT) -> dict:
        """Run `script` on the visible globe page and return its JSON result.

        ``runJavaScript`` needs the GUI thread only long enough to hand the
        script to Chromium. The answer arrives on a later turn of that same
        loop, so a slow page is waited for on the *caller's* thread and never
        with the GUI thread parked in a nested loop. That parked loop is what
        made the whole window stop responding while the globe was starting.
        """
        if not self._on_gui():
            return self._js_threaded(script, timeout)

        def _job():
            page = self._page()
            if page is None:
                return {"ok": False, "error": "The globe workspace is not open."}
            loop = QEventLoop()
            box: dict = {}

            def _callback(value):
                box["value"] = value
                loop.quit()

            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(int(timeout * 1000))
            page.runJavaScript(script, _callback)
            loop.exec()
            timer.stop()
            if "value" not in box:
                return {"ok": False, "error": "The globe page did not answer in time."}
            return _parse_reply(box["value"])

        try:
            return _job()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _js_threaded(self, script: str, timeout: float) -> dict:
        """`_js` for callers that are not the GUI thread."""
        done = threading.Event()
        box: dict = {}

        def _callback(value):
            box["value"] = value
            done.set()

        def _schedule():
            page = self._page()
            if page is None:
                return False
            page.runJavaScript(script, _callback)
            return True

        try:
            scheduled = self._gui(_schedule, timeout=30.0)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if not scheduled:
            return {"ok": False, "error": "The globe workspace is not open."}
        if not done.wait(timeout):
            return {"ok": False, "error": "The globe page did not answer in time."}
        if "value" not in box:
            return {"ok": False, "error": "The globe page returned nothing."}
        return _parse_reply(box["value"])

    def _invoke(self, action: str, arguments: dict, timeout: float = JS_TIMEOUT) -> dict:
        """Call the app's own action runner and wait for its real result."""
        if action not in ALLOWED_ACTIONS:
            return _fail(f"Refused unknown globe action: {action}")
        if not self._page():
            opened = self.open()
            if not opened.get("ok"):
                return opened

        self._token += 1
        token = f"keysai{self._token}"
        payload = json.dumps(arguments, ensure_ascii=False)
        script = _runner_script(action, payload, token)
        start = self._js(script, timeout=timeout)
        if "ok" not in start:
            # A transport failure (no page, no answer, unreadable reply).
            return start
        if not start.get("ok"):
            return _fail(str(start.get("error") or "The globe refused the action."))
        if start.get("done"):
            return _from_runner(start.get("result"))

        # The runner returned a promise: poll the slot the script fills.
        poll_script = _poll_script(token)
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._pump(150)
            slot = self._js(poll_script, timeout=5.0)
            if "ok" not in slot and slot.get("pending") is None:
                return slot
            if slot.get("pending"):
                continue
            if slot.get("ok"):
                return _from_runner(slot.get("result"))
            return _fail(str(slot.get("error") or "The globe action failed."))
        return _fail(
            f"The globe did not finish '{action}' within {int(timeout)}s."
        )

    # ── Commands ──────────────────────────────────────────────────────────
    def navigate(self, location: str = "", latitude: float | None = None,
                 longitude: float | None = None, view_mode: str = "") -> dict:
        """Fly to a place, or to explicit coordinates."""
        args: dict = {"waitForArrival": True}
        if latitude is not None and longitude is not None:
            args["latitude"] = float(latitude)
            args["longitude"] = float(longitude)
        elif location:
            args["query"] = str(location)
        else:
            return _fail("No location or coordinates were given.")
        if view_mode in ("close", "overview"):
            args["viewMode"] = view_mode
        result = _with_action(self._fly(args), intents.NAVIGATE_TO_LOCATION)
        self._record(intents.NAVIGATE_TO_LOCATION, args)
        return result

    def _fly(self, args: dict, attempts: int = 2) -> dict:
        """Run fly_to_location, retrying once if the app cancelled it.

        A command issued while the app is still performing its own startup
        camera restoration comes back ``{cancelled: true}`` — the app refuses to
        run two flights at once. That is a real, recoverable condition, not a
        failure, so it is retried once after a pause. Anything else is reported
        exactly as the app answered it.
        """
        result = self._invoke("fly_to_location", args, timeout=NAVIGATE_TIMEOUT)
        if result.get("cancelled") and attempts > 1:
            self._pump(1500)
            result = self._invoke("fly_to_location", args,
                                  timeout=NAVIGATE_TIMEOUT)
        if result.get("cancelled"):
            return _fail(
                "The globe cancelled the move — another camera flight is "
                "already running. Ask again in a moment."
            )
        return result

    def search(self, query: str) -> dict:
        """Run the app's own place search and fly there."""
        if not str(query or "").strip():
            return _fail("Nothing to search for.")
        result = _with_action(
            self._fly({"query": str(query), "waitForArrival": True}),
            intents.SEARCH_GLOBE)
        self._record(intents.SEARCH_GLOBE, {"query": query})
        return result

    def zoom(self, direction: str, amount: str = "medium") -> dict:
        if direction not in ("in", "out"):
            return _fail("Zoom direction must be 'in' or 'out'.")
        if amount not in ("little", "medium", "lot"):
            amount = "medium"
        result = self._invoke("adjust_camera_zoom",
                              {"direction": direction, "amount": amount})
        result = _with_action(
            result,
            intents.ZOOM_IN if direction == "in" else intents.ZOOM_OUT)
        self._record(result["action"], {"amount": amount})
        return result

    def reset(self) -> dict:
        result = _with_action(self._invoke("zoom_to_globe", {}),
                              intents.RESET_GLOBE)
        self._record(intents.RESET_GLOBE, {})
        return result

    def layer(self, layer_id: str, enabled: bool = True) -> dict:
        if not str(layer_id or "").strip():
            return _fail("No layer was named.")
        result = _with_action(
            self._invoke("set_layer_visibility",
                         {"layerId": str(layer_id), "enabled": bool(enabled)}),
            intents.TOGGLE_DATA_LAYER)
        self._record(intents.TOGGLE_DATA_LAYER,
                     {"layerId": layer_id, "enabled": bool(enabled)})
        return result

    def status(self) -> dict:
        server = self.server.status()
        page: dict = {}
        if self._page() is not None:
            view = self._invoke("get_current_view_state", {})
            page = view
        return {
            "ok": bool(server.get("running")),
            "action": intents.GET_GLOBE_STATUS,
            "server": server,
            "page": page,
            "last_command": self._last,
            "commands_run": len(self._history),
        }

    # ── Dispatch ──────────────────────────────────────────────────────────
    def execute(self, command: intents.GlobeCommand) -> dict:
        """Run one parsed command."""
        action = command.action
        if action == intents.OPEN_GLOBE:
            result = self.open()
            if result.get("ok") and command.location:
                return self.navigate(command.location)
            return result
        if action == intents.CLOSE_GLOBE:
            return self.close()
        if action == intents.NAVIGATE_TO_LOCATION:
            return self.navigate(command.location, command.latitude,
                                 command.longitude)
        if action == intents.SEARCH_GLOBE:
            return self.search(command.query or command.location)
        if action == intents.ZOOM_IN:
            return self.zoom("in", command.amount)
        if action == intents.ZOOM_OUT:
            return self.zoom("out", command.amount)
        if action == intents.RESET_GLOBE:
            return self.reset()
        if action == intents.TOGGLE_DATA_LAYER:
            return self.layer(command.layer, command.enabled)
        if action == intents.GET_GLOBE_STATUS:
            return self.status()
        return _fail(f"Unsupported globe action: {action}")

    def handle_text(self, text: str) -> dict | None:
        """Parse an utterance and run it. None when it is not a globe request."""
        command = intents.try_parse(text)
        if command is None:
            return None
        result = self.execute(command)
        result["said"] = intents.describe(command)
        return result

    # ── Bookkeeping ───────────────────────────────────────────────────────
    def _record(self, action: str, arguments: dict) -> None:
        self._last = action
        self._history.append({
            "action": action,
            "arguments": arguments,
            "at": time.time(),
        })
        del self._history[:-40]

    def _error_message(self, server: dict) -> str:
        problems = server.get("problems") or []
        if problems:
            return problems[0]
        return str(server.get("error") or "The globe server is not available.")


# ── JS builders ────────────────────────────────────────────────────────────
def _js_str(value: str) -> str:
    """A JS string literal that cannot break out of its quotes."""
    out = (str(value).replace("\\", "\\\\").replace("'", "\\'")
           .replace("\n", "\\n").replace("\r", "\\r").replace("</", "<\\/"))
    return "'" + out + "'"


def _runner_script(action: str, arguments_json: str, token: str) -> str:
    """Start one action on the app's runner and stash the outcome in a slot.

    The runner may return a promise; ``runJavaScript`` cannot await one, so the
    script records the settled value on ``window`` and the Python side polls
    for it. The slot is keyed by a per-call token so a slow earlier call can
    never be read as the answer to a later one.
    """
    return (
        "(function () {\n"
        "  try {\n"
        "    var g = window.__godsEyeView;\n"
        "    if (!g || !g.voiceCommands || typeof g.voiceCommands.runner !== 'function')\n"
        "      return JSON.stringify({ok: false, error: 'the globe is not ready'});\n"
        f"    var token = {_js_str(token)};\n"
        f"    var name = {_js_str(action)};\n"
        f"    var args = {arguments_json};\n"
        "    window.__keysaiGlobeSlots = window.__keysaiGlobeSlots || {};\n"
        "    window.__keysaiGlobeSlots[token] = {pending: true};\n"
        "    var out = g.voiceCommands.runner(name, args);\n"
        "    if (out && typeof out.then === 'function') {\n"
        "      out.then(function (r) {\n"
        "        window.__keysaiGlobeSlots[token] = {pending: false, ok: true, result: r};\n"
        "      }, function (e) {\n"
        "        window.__keysaiGlobeSlots[token] = {pending: false, ok: false,\n"
        "          error: String(e && e.message || e)};\n"
        "      });\n"
        "      return JSON.stringify({ok: true, done: false});\n"
        "    }\n"
        "    window.__keysaiGlobeSlots[token] = {pending: false, ok: true, result: out};\n"
        "    return JSON.stringify({ok: true, done: true, result: out});\n"
        "  } catch (e) {\n"
        "    return JSON.stringify({ok: false,\n"
        "      error: String(e && e.message || e)});\n"
        "  }\n"
        "})()"
    )


def _poll_script(token: str) -> str:
    return (
        "(function () {\n"
        "  try {\n"
        "    var slots = window.__keysaiGlobeSlots || {};\n"
        f"    var slot = slots[{_js_str(token)}];\n"
        "    if (!slot) return JSON.stringify({pending: false, ok: false,\n"
        "      error: 'the globe lost the request'});\n"
        "    if (slot.pending) return JSON.stringify({pending: true});\n"
        "    delete slots[" + _js_str(token) + "];\n"
        "    return JSON.stringify({pending: false, ok: !!slot.ok,\n"
        "      result: slot.result === undefined ? null : slot.result,\n"
        "      error: slot.error || null});\n"
        "  } catch (e) {\n"
        "    return JSON.stringify({pending: false, ok: false,\n"
        "      error: String(e && e.message || e)});\n"
        "  }\n"
        "})()"
    )


def _with_action(result: dict, action: str) -> dict:
    """Give a result our logical action name, keeping the app's own.

    The app answers with its own action name (``fly_to_location``,
    ``adjust_camera_zoom``, ...). Callers switch on the logical command, so that
    is what the envelope carries; the app's name stays as ``globe_action`` so a
    report never loses what actually ran.
    """
    if not isinstance(result, dict):
        return result
    upstream = result.get("action")
    if upstream and upstream != action:
        result["globe_action"] = upstream
    result["action"] = action
    return result


def _parse_reply(raw) -> dict:
    """Turn one page reply into the dict the service works with."""
    if raw is None:
        return {"ok": False, "error": "The globe page returned nothing."}
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {"ok": False, "error": f"Unreadable globe reply: {raw!r}"}
    if not isinstance(parsed, dict):
        return {"ok": False, "error": f"Unexpected globe reply: {parsed!r}"}
    return parsed


def _from_runner(result) -> dict:
    """Normalise the app's own result envelope into ours."""
    if isinstance(result, dict):
        ok = result.get("ok")
        out = dict(result)
        if ok is None:
            out["ok"] = True
        out.setdefault("action", "")
        return out
    if result is None:
        return {"ok": True, "result": None}
    return {"ok": True, "result": result}


def _fail(message: str, **extra) -> dict:
    out = {"ok": False, "error": str(message)}
    out.update(extra)
    return out


def get_service() -> GlobeService:
    """The process-wide globe service.

    The common path takes no lock at all: this function is called from the GUI
    thread, from inside the job that ``open()`` posts there while holding its
    own lock. Blocking here would freeze the window.
    """
    global _service
    if _service is not None:
        return _service
    with _state_lock:
        if _service is None:
            _service = GlobeService()
        return _service
