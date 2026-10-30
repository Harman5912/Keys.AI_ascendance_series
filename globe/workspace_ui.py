"""globe.workspace_ui — the in-app Chromium view that hosts God's Eye View.

The globe is a real web application that already exists. It is not re-drawn or
faked here: this widget is a Chromium surface (QtWebEngine, the same engine the
Research Browser uses) pointed at the local God's Eye View server, and the
agent drives the page that the user is looking at.

The widget owns *only* presentation — a slim status strip and the web view.
All lifecycle and command work lives in ``globe.service``, so the same service
can be exercised headlessly by tests without a visible window.
"""

from __future__ import annotations

import threading

from PyQt6.QtCore import QEventLoop, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton,
                             QVBoxLayout, QWidget)

# QtWebEngine refuses to initialise once a QApplication exists unless shared GL
# contexts were requested first — and the globe is always built long after the
# main window, from the agent's tool call. Asking here is honoured even at that
# point, and without it the import below raises and this module reports the
# globe as "not installed" on a machine where it is installed.
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
_WEBENGINE_ERROR = ""
try:
    from PyQt6.QtWebEngineCore import QWebEngineScript, QWebEngineSettings
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    _HAS_WEBENGINE = True
except Exception as _exc:                            # pragma: no cover - optional
    QWebEngineScript = None                          # type: ignore
    QWebEngineSettings = None                        # type: ignore
    QWebEngineView = None                            # type: ignore
    _HAS_WEBENGINE = False
    _WEBENGINE_ERROR = f"{type(_exc).__name__}: {_exc}"

#: God's Eye View opens a "choose your first view" card on a first visit. In
#: Keys.AI the user already asked for the globe, so that card is a modal over
#: the thing they wanted. This is the app's own suppression key.
_FIRST_RUN_KEY = "gev:first-run-mission:v1"
_SUPPRESS_FIRST_RUN_JS = (
    "try{localStorage.setItem('" + _FIRST_RUN_KEY + "','suppressed');}catch(e){}"
)
_DISMISS_FIRST_RUN_JS = (
    "(function(){var b=document.querySelector('[data-first-run-dismiss]');"
    "if(b)b.click();})()"
)


def webengine_error() -> str:
    """Why QtWebEngine is unavailable — empty when it loaded."""
    return _WEBENGINE_ERROR

_BG = "#05070c"
_PRI = "#FFD700"
_TEXT = "#c9d1e0"
_DIM = "#6b7480"


class GlobeWorkspace(QWidget):
    """Centre-view surface: God's Eye View plus a compact status strip."""

    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GlobeWorkspace")
        self.setStyleSheet(f"QWidget#GlobeWorkspace {{ background: {_BG}; }}")
        self._load_ok: bool | None = None
        self._load_loop = None
        self._load_signal = False
        #: Set by `loadFinished`. Lets a worker thread wait for the page
        #: without parking the GUI thread in a nested event loop.
        self._load_event = threading.Event()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Status strip ──────────────────────────────────────────────────
        bar = QWidget()
        bar.setFixedHeight(30)
        bar.setStyleSheet(
            "background: rgba(14,17,24,235); border-bottom: 1px solid rgba(255,215,0,45);"
        )
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(10, 0, 10, 0)
        bar_lay.setSpacing(8)

        dot = QLabel("◉")
        dot.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        dot.setStyleSheet(f"color: {_PRI}; background: transparent;")
        bar_lay.addWidget(dot)

        title = QLabel("GOD'S EYE VIEW")
        title.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        title.setStyleSheet(
            f"color: {_PRI}; background: transparent; letter-spacing: 1px;"
        )
        bar_lay.addWidget(title)

        self._status = QLabel("starting…")
        self._status.setFont(QFont("Courier New", 7))
        self._status.setStyleSheet(f"color: {_DIM}; background: transparent;")
        bar_lay.addWidget(self._status)
        bar_lay.addStretch()

        self._reload_btn = QPushButton("RELOAD")
        self._reload_btn.setFont(QFont("Courier New", 7))
        self._reload_btn.setFixedHeight(18)
        self._reload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reload_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {_DIM};"
            f" border: 1px solid rgba(255,215,0,45); border-radius: 2px;"
            f" padding: 0 6px; }}"
            f"QPushButton:hover {{ color: {_PRI}; }}"
        )
        self._reload_btn.clicked.connect(self.reload)
        bar_lay.addWidget(self._reload_btn)

        close = QPushButton("BACK  ✕")
        close.setFont(QFont("Courier New", 7))
        close.setFixedHeight(18)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {_DIM};"
            f" border: 1px solid rgba(255,255,255,30); border-radius: 2px;"
            f" padding: 0 6px; }}"
            f"QPushButton:hover {{ color: {_TEXT}; }}"
        )
        close.clicked.connect(self.closed.emit)
        bar_lay.addWidget(close)

        root.addWidget(bar)

        # ── Web view ──────────────────────────────────────────────────────
        self.view = None
        if _HAS_WEBENGINE:
            self.view = QWebEngineView(self)
            self.view.setStyleSheet(f"background: {_BG};")
            settings = self.view.settings()
            if settings is not None:
                settings.setAttribute(
                    QWebEngineSettings.WebAttribute.WebGLEnabled, True)
                settings.setAttribute(
                    QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
                settings.setAttribute(
                    QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                    True,
                )
            self.view.loadFinished.connect(self._on_load_finished)
            root.addWidget(self.view, 1)
        else:
            missing = QLabel(
                "  QtWebEngine is not available — the globe needs PyQt6-WebEngine."
                + (f"\n  ({_WEBENGINE_ERROR})" if _WEBENGINE_ERROR else "")
            )
            missing.setFont(QFont("Courier New", 8))
            missing.setStyleSheet(f"color: {_DIM}; background: {_BG};")
            root.addWidget(missing, 1)

    # ── Page control ────────────────────────────────────────────────────────
    @property
    def available(self) -> bool:
        return self.view is not None

    def page(self):
        """The live QWebEnginePage, or None when the engine is missing.

        Tolerant on purpose: the responsiveness tests drive this widget with a
        stand-in view that only implements load/url, and a view that cannot
        produce a page must read as "no page" rather than raise mid-load.
        """
        if self.view is None:
            return None
        getter = getattr(self.view, "page", None)
        return getter() if callable(getter) else None

    def load(self, url: str) -> None:
        if self.view is None:
            return
        current = self.view.url().toString()
        if (current and self._load_ok
                and current.rstrip("/") == str(url).rstrip("/")):
            # Reopening the page that is already loaded must not reload it:
            # Cesium pulls hundreds of modules and re-initialises WebGL, and
            # that reload is what made a second "open the globe" look frozen.
            self.set_status("ready")
            return
        self.set_status(f"loading {url}")
        self._load_ok = None
        self._load_event.clear()
        self._suppress_first_run()
        self.view.setUrl(QUrl(url))

    def wait_for_load(self, timeout: float = 90.0) -> bool:
        """Block on the GUI thread until the page finishes loading.

        Returns what Chromium reported. This is the honest readiness signal:
        it is emitted only once every module the document needs has arrived,
        which for this app is hundreds of ES modules — long before that, a
        navigation looks fine and the page can do nothing at all.
        """
        if self.view is None:
            return False
        if self._load_ok is not None:
            self._load_signal = False
            return bool(self._load_ok)
        loop = QEventLoop()
        self._load_signal = True
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(int(timeout * 1000))
        self._load_loop = loop
        loop.exec()
        timer.stop()
        self._load_signal = False
        self._load_loop = None
        return bool(self._load_ok)

    def wait_for_load_threaded(self, timeout: float = 90.0) -> bool:
        """Block the calling thread until Chromium reports load-finished.

        ``loadFinished`` is delivered on the GUI thread and only sets this
        event, so waiting here leaves the window free to paint. Call this from
        a worker thread; on the GUI thread use `wait_for_load`.
        """
        if self.view is None:
            return False
        if not self._load_event.wait(timeout):
            return False
        return bool(self._load_ok)

    def pause(self) -> None:
        """Stop rendering while the globe is not on screen.

        The page suspends its own render loop on ``visibilitychange``, but a
        QWebEngineView that is only swapped out of a stack page never fires
        that event. Cesium therefore keeps drawing at 60 fps behind the HUD and
        the whole window competes with a globe nobody is looking at.
        """
        self._set_render_loop(False)

    def resume(self) -> None:
        """Restore rendering and repaint the frame that was skipped."""
        self._set_render_loop(True)

    def _set_render_loop(self, running: bool) -> None:
        page = self.page()
        if page is None:
            return
        flag = "true" if running else "false"
        extra = (".requestRender('keysai-resume')" if running else "")
        page.runJavaScript(
            "(function(){var v=window.__godsEyeView;"
            "if(!v||!v.viewer)return;"
            f"v.viewer.useDefaultRenderLoop={flag};"
            f"v{extra};}})()"
        )

    def _suppress_first_run(self) -> None:
        """Keep the first-run card out of the embedded globe.

        The card is suppressed by a localStorage key the app itself writes, so
        the key is set at document creation — before the app reads it — rather
        than clicking the card after it has already covered the globe.
        """
        if self.view is None or QWebEngineScript is None:
            return
        page = self.page()
        if page is None or not hasattr(page, "scripts"):
            return
        try:
            if getattr(self, "_first_run_script", False):
                return
            script = QWebEngineScript()
            script.setName("keysai-suppress-first-run")
            script.setInjectionPoint(
                QWebEngineScript.InjectionPoint.DocumentCreation)
            script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            script.setRunsOnSubFrames(False)
            script.setSourceCode(_SUPPRESS_FIRST_RUN_JS)
            page.scripts().insert(script)
            self._first_run_script = True
        except Exception:
            pass

    def reload(self) -> None:
        if self.view is not None:
            self.view.reload()

    def set_status(self, text: str) -> None:
        self._status.setText(str(text)[:120])

    def _on_load_finished(self, ok: bool) -> None:
        self._load_ok = bool(ok)
        self._load_event.set()
        page = self.page() if ok else None
        if page is not None and hasattr(page, "runJavaScript"):
            # A page that loaded before the script was installed (or a profile
            # that kept an older key) can still be showing the card.
            page.runJavaScript(_DISMISS_FIRST_RUN_JS)
        self.set_status("ready" if ok else "load failed — see the activity log")
        loop = getattr(self, "_load_loop", None)
        if loop is not None and getattr(self, "_load_signal", False):
            loop.quit()

    def shutdown(self) -> None:
        """Stop the page before the process exits.

        Loading ``about:blank`` first lets Chromium tear the page down in the
        normal way; skipping it leaves GPU helper processes to be killed
        abruptly at exit, which is visible as a crash on some Windows drivers.
        """
        if self.view is None:
            return
        try:
            self.view.stop()
            self.view.setUrl(QUrl("about:blank"))
        except Exception:
            pass
