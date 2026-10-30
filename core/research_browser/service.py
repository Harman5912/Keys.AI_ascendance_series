"""BrowserService — the real, visible browser that the agent also drives.

One Chromium engine (QtWebEngine), many tabs. Each tab owns a live
``QWebEnginePage``; the overlay shows one ``QWebEngineView`` and swaps
``setPage()`` when the user changes tabs. Because the agent's operations run
JavaScript on those same pages, "what the agent sees" and "what the user sees"
cannot drift apart — there is no second hidden browser in this module.

Every operation returns a plain dict with ``ok`` and either data or ``error``.
Timeouts are real timeouts: a stalled page produces a failure, never a hang and
never a made-up success.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QEventLoop, QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import (QWebEngineDownloadRequest, QWebEnginePage,
                                   QWebEngineProfile, QWebEngineSettings)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication

from core.research_browser import paths, urls
from core.research_browser.version import BrowserVersion


def _browser_version() -> BrowserVersion:
    """Public stable metadata accessor used by plugin loaders and audit code."""
    return BrowserVersion()

DEFAULT_TIMEOUT = 20.0
MAX_TEXT_CHARS = 200_000
MAX_SCREENSHOT_HEIGHT = 6000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


PROFILE_NAME = "keysai_research"
_shared_profile: QWebEngineProfile | None = None
_active_service: BrowserService | None = None


def _js_string(value: str) -> str:
    """A JS string literal that cannot break out of its quotes."""
    out = (str(value).replace("\\", "\\\\").replace("'", "\\'")
           .replace("\n", "\\n").replace("\r", "\\r").replace("</", "<\\/"))
    return "'" + out + "'"


class _Page(QWebEnginePage):
    """A page that reports popups as tabs and never blocks on JS dialogs."""

    def __init__(self, profile, owner: "BrowserService", tab_id: str, parent=None):
        super().__init__(profile, parent)
        self._owner = owner
        self._tab_id = tab_id

    def createWindow(self, window_type):           # target="_blank", window.open
        page = self._owner._new_page_for_popup(self._tab_id)
        return page

    def javaScriptAlert(self, security_origin, msg):        # noqa: N802
        self._owner._log(f"page alert: {str(msg)[:300]}")

    def javaScriptConfirm(self, security_origin, msg):      # noqa: N802
        # Never let remote content confirm actions on the user's behalf.
        self._owner._log(f"page confirm auto-dismissed: {str(msg)[:300]}")
        return False

    def javaScriptPrompt(self, security_origin, msg, default):   # noqa: N802
        self._owner._log(f"page prompt auto-dismissed: {str(msg)[:300]}")
        return False, ""

    def certificateError(self, error):                      # noqa: N802
        self._owner._log(f"certificate error: {error.description()}")
        return False


class BrowserService(QObject):
    """Tab lifecycle, navigation, observation, and agent control."""

    tabs_changed = pyqtSignal()
    tab_state_changed = pyqtSignal(str)
    load_finished = pyqtSignal(str, bool)
    title_changed = pyqtSignal(str, str)
    url_changed = pyqtSignal(str, str)
    log_line = pyqtSignal(str)
    takeover_changed = pyqtSignal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        global _active_service
        self._tabs: dict[str, dict] = {}
        self._order: list[str] = []
        self._active: str = ""
        self._active_tab_state: dict[str, object] = {}
        self._view: QWebEngineView | None = None
        self._lock = threading.RLock()
        self.log_lines: list[str] = []
        self._takeover: dict[str, bool] = {}
        self._profile = _get_profile()
        _active_service = self

    # ── pause / resume wrapper (queue while paused) ──────────────────────
    async def run(self, task_id: str, fn, cancel_scope: "CancelScope | None" = None) -> Any:
        """Run an async browser operation, queued while paused for the task."""
        async with self._scopes(task_id, cancel_scope=cancel_scope):
            return await fn(self)

    def _wait_for_javascript(self, page: _Page, script: str, timeout: float = DEFAULT_TIMEOUT) -> Any:
        """Run a sync JS read on a page with a real timeout."""
        loop = QEventLoop()
        result_holder: dict[str, Any] = {}

        def _cb(val: Any) -> None:
            result_holder["value"] = val
            loop.quit()

        page.runJavaScript(script, 0, _cb)
        finished = loop.exec()
        if finished == 0:
            return result_holder.get("value")
        raise RuntimeError("javascript evaluation timed out")

    def capture_tab_state(self, tab_id: str) -> dict:
        """Snapshot the visible state needed to restore a tab later."""
        with self._lock:
            tab = self._tabs.get(tab_id)
            if tab is None:
                return {"ok": False, "error": f"unknown tab: {tab_id}"}
            try:
                scroll = self._wait_for_javascript(
                    tab["page"],
                    "(() => ({ scrollX: window.scrollX, scrollY: window.scrollY }))()",
                    DEFAULT_TIMEOUT,
                )
            except Exception:
                scroll = {}
            if not isinstance(scroll, dict):
                scroll = {}
            state = {
                "ok": True,
                "tab_id": tab_id,
                "title": tab.get("title", ""),
                "url": tab.get("url", ""),
                "scroll_x": int(scroll.get("scrollX", 0)),
                "scroll_y": int(scroll.get("scrollY", 0)),
                "zoom": float(tab.get("zoom", 1.0)),
            }
            self._active_tab_state[tab_id] = state
            return state

    def spatial_anchor_add(self, tab_id: str, name: str, *, position: dict | None = None) -> dict:
        with self._lock:
            tab = self._tabs.get(tab_id)
            if tab is None:
                return {"ok": False, "error": "unknown tab"}
            spatial = tab.get("spatial") or {
                "objects": [],
                "anchors": [],
                "root_pose": {"x": 0, "y": 0, "z": 0},
            }
            label = str(name or "").strip() or "unnamed"
            anchor = {
                "label": label,
                "kind": "manual",
                "position": position or {"x": 0, "y": 0, "z": 0},
            }
            for existing in spatial.get("anchors", []):
                if existing.get("label") == label:
                    existing.update(anchor)
                    return {"ok": True, "tab_id": tab_id, "anchor": existing}
            spatial.setdefault("anchors", []).append(anchor)
            tab["spatial"] = spatial
            return {"ok": True, "tab_id": tab_id, "anchor": anchor}

    def _run_js(self, tab_id: str, script: str, timeout: float = 8.0):
        page = self._page(tab_id)
        if page is None:
            raise RuntimeError("Unknown tab.")
        box: dict = {}
        loop = QEventLoop()

        def callback(value):
            box["value"] = value
            loop.quit()

        page.runJavaScript(script, 0, callback)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(int(max(0.1, timeout) * 1000))
        loop.exec()
        timer.stop()
        if "value" not in box:
            raise TimeoutError("The page did not answer a script request.")
        return box["value"]

    def capture_tab_state(self, tab_id: str) -> dict:
        """Snapshot the visible state needed to restore a tab later."""
        with self._lock:
            tab = self._tabs.get(tab_id)
            if tab is None:
                return {"ok": False, "error": f"unknown tab: {tab_id}"}
            try:
                scroll = self._wait_for_javascript(
                    tab["page"],
                    "(() => ({ scrollX: window.scrollX, scrollY: window.scrollY }))()",
                    DEFAULT_TIMEOUT,
                )
            except Exception:
                scroll = {}
            if not isinstance(scroll, dict):
                scroll = {}
            state = {
                "ok": True,
                "tab_id": tab_id,
                "title": tab.get("title", ""),
                "url": tab.get("url", ""),
                "scroll_x": int(scroll.get("scrollX", 0)),
                "scroll_y": int(scroll.get("scrollY", 0)),
                "zoom": float(tab.get("zoom", 1.0)),
            }
            self._active_tab_state[tab_id] = state
            return state

    def spatial_anchor_add(self, tab_id: str, name: str, *, position: dict | None = None) -> dict:
        with self._lock:
            tab = self._tabs.get(tab_id)
            if tab is None:
                return {"ok": False, "error": "unknown tab"}
            spatial = tab.get("spatial") or {"objects": [], "anchors": [], "root_pose": {"x": 0, "y": 0, "z": 0}}
            label = str(name or "").strip() or "unnamed"
            anchor = {"label": label, "kind": "manual", "position": position or {"x": 0, "y": 0, "z": 0}}
            for existing in spatial.get("anchors", []):
                if existing.get("label") == label:
                    existing.update(anchor)
                    return {"ok": True, "tab_id": tab_id, "anchor": existing}
            spatial.setdefault("anchors", []).append(anchor)
            tab["spatial"] = spatial
            return {"ok": True, "tab_id": tab_id, "anchor": anchor}

    # ── engine plumbing ───────────────────────────────────────────────────
    @staticmethod
    def _configure_settings(settings) -> None:
        for attr, value in (
            ("JavascriptEnabled", True),
            ("LocalContentCanAccessRemoteUrls", False),
            ("LocalContentCanAccessFileUrls", False),
            ("AllowRunningInsecureContent", False),
            ("JavascriptCanOpenWindows", True),
            ("PluginsEnabled", False),
            ("PdfViewerEnabled", True),
            ("FullScreenSupportEnabled", True),
            ("ErrorPageEnabled", True),
        ):
            flag = getattr(QWebEngineSettings.WebAttribute, attr, None)
            if flag is not None:
                settings.setAttribute(flag, value)

    def _on_download_requested(self, request: QWebEngineDownloadRequest) -> None:
        # Page-initiated downloads are cancelled; collection goes through
        # assets.fetch, which validates type, size and provenance first.
        name = request.downloadFileName()
        request.cancel()
        self._log(f"blocked in-page download: {name}")

    def _new_page_for_popup(self, opener_tab: str) -> QWebEnginePage:
        tab_id = self.open_tab("", task_id=self._tabs.get(opener_tab, {}).get("task_id", ""))
        page = self._tabs[tab_id]["page"]
        return page

    # ── view attachment (what the user sees) ──────────────────────────────
    def attach_view(self, view: QWebEngineView) -> None:
        self._view = view
        if not self._order:
            self.open_tab("")
        elif self._active:
            self._apply_active_tab_state()

    def detach_view(self) -> None:
        self._view = None

    def _apply_active_tab_state(self) -> None:
        tab = self._tabs.get(self._active)
        if tab is None or self._view is None:
            return
        if self._view.page() is not tab["page"]:
            self._view.setPage(tab["page"])
        self._view.setZoomFactor(tab.get("zoom", 1.0))
        state = self._active_tab_state.get(self._active)
        if state:
            if "scroll_x" in state and "scroll_y" in state:
                self._view.page().runJavaScript(
                    f"window.scrollTo({int(state['scroll_x'])}, {int(state['scroll_y'])});",
                    lambda *a: None,
                )
            if "zoom" in state:
                self._view.setZoomFactor(float(state["zoom"]))

    def _apply_active_page(self) -> None:
        self._apply_active_tab_state()

    # ── tabs ──────────────────────────────────────────────────────────────
    def open_tab(self, target: str = "", *, task_id: str = "",
                 activate: bool = True) -> str:
        tab_id = uuid.uuid4().hex[:10]
        page = _Page(self._profile, self, tab_id, parent=self)
        page.loadStarted.connect(lambda t=tab_id: self._on_load_started(t))
        page.loadFinished.connect(lambda ok, t=tab_id: self._on_load_finished(t, ok))
        page.loadProgress.connect(lambda _p, t=tab_id: self.tab_state_changed.emit(t))
        page.titleChanged.connect(
            lambda title, t=tab_id: self._on_title(t, title))
        page.urlChanged.connect(lambda url, t=tab_id: self._on_url(t, url))
        page.renderProcessTerminated.connect(
            lambda status, code, t=tab_id: self._on_crash(t, status, code))
        page.featurePermissionRequested.connect(self._on_permission)
        self._tabs[tab_id] = {
            "id": tab_id,
            "page": page,
            "title": "New tab",
            "url": "",
            "loading": False,
            "error": "",
            "task_id": task_id,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "zoom": 1.0,
            "crashed": False,
            "scroll_x": 0,
            "scroll_y": 0,
            "scroll_target_x": 0,
            "scroll_target_y": 0,
            "scroll_finished": False,
            "pinch_zoom": 1.0,
            "orientation": 0,
            "device_pixel_ratio": 1.0,
            "viewport_width": 0,
            "viewport_height": 0,
            "geom": {"x": 0, "y": 0, "w": 0, "h": 0},
            "spatial": {"objects": [], "anchors": [], "root_pose": {"x": 0, "y": 0, "z": 0}},
        }
        self._order.append(tab_id)
        if activate or not self._active:
            self._active = tab_id
            self._apply_active_page()
        if target:
            self.navigate(tab_id, target)
        self.tabs_changed.emit()
        return tab_id

    def close_tab(self, tab_id: str) -> dict:
        tab = self._tabs.pop(tab_id, None)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        self._order = [t for t in self._order if t != tab_id]
        self._takeover.pop(tab_id, None)
        if self._view is not None and self._view.page() is tab["page"]:
            self._view.setPage(None)
        page = tab["page"]
        page.setParent(None)
        page.deleteLater()
        if self._active == tab_id:
            self._active = self._order[-1] if self._order else ""
            if not self._order:
                self.open_tab("")
            else:
                self._apply_active_page()
        self.tabs_changed.emit()
        return {"ok": True, "tab_id": tab_id}

    def select_tab(self, tab_id: str) -> dict:
        if tab_id not in self._tabs:
            return {"ok": False, "error": "Unknown tab."}
        self._active = tab_id
        self._apply_active_page()
        self.tabs_changed.emit()
        self.tab_state_changed.emit(tab_id)
        return {"ok": True, "tab_id": tab_id}

    def active_tab(self) -> str:
        return self._active

    def tabs(self) -> list[dict]:
        out = []
        for tab_id in self._order:
            tab = self._tabs.get(tab_id) or {}
            out.append({
                "tab_id": tab_id,
                "title": tab.get("title") or "New tab",
                "url": tab.get("url") or "",
                "loading": bool(tab.get("loading")),
                "crashed": bool(tab.get("crashed")),
                "task_id": tab.get("task_id") or "",
                "active": tab_id == self._active,
                "can_go_back": bool(tab.get("page") and tab["page"].history().canGoBack()),
                "can_go_forward": bool(tab.get("page") and tab["page"].history().canGoForward()),
            })
        return out

    def _resolve(self, tab_id: str = "") -> dict | None:
        """The tab an operation targets. Never 'the first tab by accident'."""
        target = tab_id or self._active
        return self._tabs.get(target)

    def _page(self, tab_id: str = "") -> QWebEnginePage | None:
        tab = self._resolve(tab_id)
        return tab["page"] if tab else None

    # ── signals ───────────────────────────────────────────────────────────
    def _on_load_started(self, tab_id: str) -> None:
        tab = self._tabs.get(tab_id)
        if tab:
            tab["loading"] = True
            tab["error"] = ""
        self.tab_state_changed.emit(tab_id)

    def _on_load_finished(self, tab_id: str, ok: bool) -> None:
        tab = self._tabs.get(tab_id)
        if tab is None:
            return
        tab["loading"] = False
        if not ok:
            tab["error"] = ("The page did not finish loading (DNS failure, "
                            "connection refused, or a timeout).")
        self.load_finished.emit(tab_id, bool(ok))
        self.tab_state_changed.emit(tab_id)

    def _on_title(self, tab_id: str, title: str) -> None:
        tab = self._tabs.get(tab_id)
        if tab is not None:
            tab["title"] = title or tab.get("url") or "New tab"
        self.title_changed.emit(tab_id, title)
        self.tabs_changed.emit()

    def _on_url(self, tab_id: str, url: QUrl) -> None:
        tab = self._tabs.get(tab_id)
        if tab is not None:
            tab["url"] = url.toString()
        self.url_changed.emit(tab_id, url.toString())

    def _on_crash(self, tab_id: str, status, code: int) -> None:
        tab = self._tabs.get(tab_id)
        if tab is not None:
            tab["crashed"] = True
            tab["loading"] = False
            tab["error"] = f"Browser process terminated ({status}, code {code})."
        self._log(f"tab {tab_id}: renderer terminated ({status}, {code})")
        self.tab_state_changed.emit(tab_id)

    def _on_permission(self, url: QUrl, feature) -> None:
        page = self.sender()
        if page is not None:
            page.setFeaturePermission(
                url, feature, QWebEnginePage.PermissionPolicy.PermissionDeniedByUser)
        self._log(f"denied page permission {feature} for {url.toString()[:120]}")

    def _log(self, message: str) -> None:
        self.log_lines.append(message)
        del self.log_lines[:-500]
        print(f"[research_browser] {message}")
        self.log_line.emit(message)

    # ── navigation ────────────────────────────────────────────────────────
    def navigate(self, tab_id: str, target: str, *, engine: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT) -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        try:
            kind, url = urls.normalise_input(
                target, engine or paths.load().get("search_engine", "google"))
        except urls.UrlError as exc:
            return {"ok": False, "error": str(exc), "tab_id": tab["id"]}
        allowed, reason = urls.is_allowed(url)
        if not allowed:
            return {"ok": False, "error": reason, "tab_id": tab["id"]}
        tab["error"] = ""
        # Mark loading *before* calling load(): QWebEnginePage emits
        # loadStarted from its own event loop, and waiting on a flag that has
        # not been set yet returns instantly against an empty document.
        tab["loading"] = True
        tab["page"].load(QUrl(url))
        waited = self.wait_for_load(tab["id"], timeout=timeout) if timeout else {}
        if waited.get("timeout"):
            return {"ok": False, "tab_id": tab["id"], "url": url,
                    "error": waited.get("error"), "timeout": True}
        # Chromium renders its own error page for a refused connection and still
        # reports the load as finished; the loadFinished(false) flag is what
        # tells us the page never actually arrived.
        failure = self._tabs[tab["id"]].get("error", "")
        return {"ok": not failure, "tab_id": tab["id"], "url": url,
                "kind": kind, "error": failure,
                "title": self._tabs[tab["id"]].get("title", ""),
                "error_url": failure}

    def wait_for_load(self, tab_id: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        if not tab["loading"]:
            return {"ok": True, "loaded": True, "tab_id": tab["id"]}
        loop = QEventLoop()
        state = {"done": False}

        def finished(tid: str, ok: bool) -> None:
            if tid == tab_id:
                state["done"] = True
                loop.quit()

        self.load_finished.connect(finished)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(int(max(0.1, timeout) * 1000))
        loop.exec()
        try:
            self.load_finished.disconnect(finished)
        except Exception:
            pass
        timer.stop()
        if not state["done"]:
            tab["error"] = f"The page did not finish loading within {timeout:g}s."
            return {"ok": False, "error": tab["error"], "tab_id": tab["id"],
                    "timeout": True}
        return {"ok": True, "loaded": True, "tab_id": tab["id"],
                "title": tab.get("title", ""), "url": tab.get("url", ""),
                "load_error": tab.get("error", "")}

    def go_back(self, tab_id: str = "", wait: float = DEFAULT_TIMEOUT) -> dict:
        return self._history_action(tab_id, "back", wait)

    def go_forward(self, tab_id: str = "", wait: float = DEFAULT_TIMEOUT) -> dict:
        return self._history_action(tab_id, "forward", wait)

    def _history_action(self, tab_id: str, direction: str, wait: float) -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        history = tab["page"].history()
        if direction == "back":
            if not history.canGoBack():
                return {"ok": False, "error": "There is no earlier page in this tab."}
            tab["loading"] = True
            history.back()
        else:
            if not history.canGoForward():
                return {"ok": False, "error": "There is no later page in this tab."}
            tab["loading"] = True
            history.forward()
        if wait:
            self.wait_for_load(tab["id"], timeout=wait)
        return {"ok": True, "tab_id": tab["id"],
                "url": self._tabs[tab["id"]].get("url", "")}

    def reload_page(self, tab_id: str = "", wait: float = DEFAULT_TIMEOUT) -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        tab["crashed"] = False
        tab["loading"] = True
        tab["page"].triggerAction(QWebEnginePage.WebAction.ReloadAndBypassCache)
        if wait:
            self.wait_for_load(tab["id"], timeout=wait)
        return {"ok": True, "tab_id": tab["id"],
                "url": self._tabs[tab["id"]].get("url", "")}

    def stop_navigation(self, tab_id: str = "") -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        tab["page"].triggerAction(QWebEnginePage.WebAction.Stop)
        deadline = time.monotonic() + 2.0
        while tab.get("loading") and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.03)
        tab["loading"] = False
        return {"ok": True, "tab_id": tab["id"]}

    def state(self, tab_id: str = "") -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        page = tab["page"]
        return {
            "ok": True,
            "tab_id": tab["id"],
            "url": tab.get("url", ""),
            "title": tab.get("title", ""),
            "loading": bool(tab.get("loading")),
            "crashed": bool(tab.get("crashed")),
            "error": tab.get("error", ""),
            "can_go_back": page.history().canGoBack(),
            "can_go_forward": page.history().canGoForward(),
            "zoom": tab.get("zoom", 1.0),
            "takeover": bool(self._takeover.get(tab["id"])),
            "task_id": tab.get("task_id", ""),
        }

    def set_zoom(self, tab_id: str, factor: float) -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        factor = max(0.25, min(3.0, float(factor)))
        tab["zoom"] = factor
        if tab["id"] == self._active and self._view is not None:
            self._view.setZoomFactor(factor)
        return {"ok": True, "zoom": factor}

    def find_text(self, tab_id: str, text: str) -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        if not str(text or "").strip():
            return {"ok": False, "error": "Enter text to find."}
        tab["page"].findText(str(text))
        return {"ok": True, "query": str(text)}

    # ── observations (the same page the user sees) ────────────────────────
    def _run_js(self, tab_id: str, script: str, timeout: float = 8.0):
        page = self._page(tab_id)
        if page is None:
            raise RuntimeError("Unknown tab.")
        box: dict = {}
        loop = QEventLoop()

        def callback(value):
            box["value"] = value
            loop.quit()

        page.runJavaScript(script, 0, callback)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(int(max(0.1, timeout) * 1000))
        loop.exec()
        timer.stop()
        if "value" not in box:
            raise TimeoutError("The page did not answer a script request.")
        return box["value"]

    def page_text(self, tab_id: str = "", limit: int = MAX_TEXT_CHARS) -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        try:
            text = self._run_js(tab["id"], "document.body ? document.body.innerText : ''")
        except Exception as exc:
            return {"ok": False, "error": str(exc), "tab_id": tab["id"]}
        text = str(text or "")
        return {"ok": True, "tab_id": tab["id"], "url": tab.get("url", ""),
                "title": tab.get("title", ""), "text": text[:limit],
                "truncated": len(text) > limit, "chars": len(text)}

    def page_title(self, tab_id: str = "") -> dict:
        state = self.state(tab_id)
        return ({"ok": True, "title": state["title"], "url": state["url"],
                 "tab_id": state["tab_id"]} if state.get("ok")
                else state)

    def page_structure(self, tab_id: str = "") -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        script = """
        (() => {
          const abs = u => { try { return new URL(u, location.href).href } catch(e) { return '' } };
          const headings = [...document.querySelectorAll('h1,h2,h3')].slice(0, 200).map(h => ({
            level: Number(h.tagName[1]), text: (h.innerText || '').trim().slice(0, 300)
          }));
          const links = [...document.querySelectorAll('a[href]')].slice(0, 300).map(a => ({
            text: (a.innerText || '').trim().slice(0, 200), href: abs(a.getAttribute('href'))
          }));
          const tables = [...document.querySelectorAll('table')].slice(0, 20).map(t => {
            const headRow = (t.tHead && t.tHead.rows[0]) ? t.tHead.rows[0]
              : (!t.tBodies.length && t.rows[0] ? t.rows[0] : null);
            const headers = headRow
              ? [...headRow.cells].map(c => (c.innerText || '').trim().slice(0, 120))
              : [];
            const rows = [...t.rows]
              .filter(r => r !== headRow && r.parentElement && r.parentElement.tagName !== 'THEAD')
              .slice(0, 200)
              .map(r => [...r.cells].map(c => (c.innerText || '').trim().slice(0, 200)))
              .filter(r => r.length);
            return {headers, rows};
          });
          const images = [...document.images].slice(0, 200).map(i => ({
            src: abs(i.currentSrc || i.src), alt: i.alt || '',
            width: i.naturalWidth || 0, height: i.naturalHeight || 0
          }));
          const meta = {};
          document.querySelectorAll('meta[name], meta[property]').forEach(m => {
            const key = m.getAttribute('name') || m.getAttribute('property');
            if (key) meta[key] = (m.getAttribute('content') || '').slice(0, 500);
          });
          const root = document.documentElement;
          return {title: document.title, url: location.href, headings, links, tables,
                  images, meta, lang: (root && root.lang) || '',
                  description: (meta.description || meta['og:description'] || '')};
        })()
        """
        try:
            data = self._run_js(tab["id"], script)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "tab_id": tab["id"]}
        data = data or {}
        data.update({"ok": True, "tab_id": tab["id"]})
        return data

    def find_page_elements(self, tab_id: str, selector: str = "",
                           limit: int = 50) -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        sel = str(selector or "a,button,input,select,textarea,[role=button]")
        script = f"""
        (() => {{
          let nodes;
          try {{ nodes = [...document.querySelectorAll({_js_string(sel)})]; }}
          catch (e) {{ return {{error: 'Invalid CSS selector: ' + e.message}}; }}
          return nodes.slice(0, {int(max(1, min(500, limit)))}).map((el, i) => {{
            const r = el.getBoundingClientRect();
            return {{
              index: i, tag: el.tagName.toLowerCase(),
              id: el.id || '', classes: (el.className || '').toString().slice(0, 200),
              text: (el.innerText || el.value || el.placeholder || '').trim().slice(0, 200),
              name: el.getAttribute('name') || '',
              href: el.href || '', type: el.getAttribute('type') || '',
              role: el.getAttribute('role') || '',
              aria: el.getAttribute('aria-label') || '',
              rect: {{x: Math.round(r.x), y: Math.round(r.y),
                      width: Math.round(r.width), height: Math.round(r.height)}},
              visible: !!(r.width && r.height)
            }};
          }});
        }})()
        """
        try:
            data = self._run_js(tab["id"], script)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "tab_id": tab["id"]}
        if isinstance(data, dict) and data.get("error"):
            return {"ok": False, "error": data["error"], "tab_id": tab["id"]}
        return {"ok": True, "tab_id": tab["id"], "selector": sel,
                "elements": data or []}

    def click_element(self, tab_id: str, *, selector: str = "", index: int = 0,
                      text: str = "") -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        if self._takeover.get(tab["id"]):
            return {"ok": False, "error": ("The user has taken control of this tab; "
                                           "the agent cannot click until it is released.")}
        before = tab.get("url", "")
        if text:
            target = (f"(() => {{ const t = {_js_string(text)}.toLowerCase(); "
                      "const els = [...document.querySelectorAll('a,button,[role=button],"
                      "input[type=submit],input[type=button],li,span,div')];"
                      "const el = els.find(e => ((e.innerText||e.value||'').trim().toLowerCase()) === t)"
                      " || els.find(e => ((e.innerText||e.value||'').trim().toLowerCase()).includes(t));"
                      "if (!el) return {found:false}; el.scrollIntoView({block:'center'});"
                      "el.click(); return {found:true, tag: el.tagName.toLowerCase()}; })()")
        else:
            target = (f"(() => {{ let nodes; try {{ nodes = [...document.querySelectorAll("
                      f"{_js_string(selector or 'a,button,input[type=submit],[role=button]')})]; }}"
                      " catch (e) { return {error: e.message}; }"
                      f"const el = nodes[{int(max(0, index))}]; if (!el) return {{found:false}};"
                      "el.scrollIntoView({block:'center'}); el.click();"
                      "return {found:true, tag: el.tagName.toLowerCase()}; })()")
        try:
            result = self._run_js(tab["id"], target)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "tab_id": tab["id"]}
        if isinstance(result, dict) and result.get("error"):
            return {"ok": False, "error": result["error"], "tab_id": tab["id"]}
        if not (isinstance(result, dict) and result.get("found")):
            return {"ok": False, "error": "No matching element on the page.",
                    "tab_id": tab["id"]}
        self._wait_after_click(tab["id"], before)
        state = self.state(tab["id"])
        return {"ok": True, "tab_id": tab["id"], "clicked": result.get("tag"),
                "url_before": before, "url_after": state.get("url", ""),
                "navigated": before != state.get("url", "")}

    def _wait_after_click(self, tab_id: str, before_url: str,
                          timeout: float = 8.0) -> None:
        """Give a click time to navigate.

        A link click starts loading from the page's own event loop, so the
        tab's ``loading`` flag is not set yet when ``wait_for_load`` is called
        immediately afterwards. Poll for the URL change (or the loading flag)
        first, otherwise a successful click looks like a no-op.
        """
        deadline = time.monotonic() + max(0.3, timeout)
        while time.monotonic() < deadline:
            QApplication.processEvents()
            tab = self._tabs.get(tab_id)
            if tab is None:
                return
            if tab.get("loading") or tab.get("url", "") != before_url:
                self.wait_for_load(tab_id, timeout=timeout)
                return
            time.sleep(0.05)

    def fill_input(self, tab_id: str, selector: str, value: str,
                   *, submit: bool = False, clear: bool = True) -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        if self._takeover.get(tab["id"]):
            return {"ok": False, "error": "The user has taken control of this tab."}
        script = f"""
        (() => {{
          let el; try {{ el = document.querySelector({_js_string(selector)}); }}
          catch (e) {{ return {{error: e.message}}; }}
          if (!el) return {{found: false}};
          el.focus();
          if ({'true' if clear else 'false'}) el.value = '';
          el.value = {_js_string(value)};
          el.dispatchEvent(new Event('input', {{bubbles: true}}));
          el.dispatchEvent(new Event('change', {{bubbles: true}}));
          if ({'true' if submit else 'false'}) {{
            const form = el.form;
            if (form) {{ form.requestSubmit ? form.requestSubmit() : form.submit(); }}
            else el.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', bubbles: true}}));
          }}
          return {{found: true, value: el.value}};
        }})()
        """
        try:
            result = self._run_js(tab["id"], script)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "tab_id": tab["id"]}
        if not (isinstance(result, dict) and result.get("found")):
            return {"ok": False, "error": (result or {}).get("error",
                    f"No element matches {selector!r}."), "tab_id": tab["id"]}
        if submit:
            self._wait_after_click(tab["id"], tab.get("url", ""))
        return {"ok": True, "tab_id": tab["id"], "value": result.get("value", "")}

    def select_option(self, tab_id: str, selector: str, value: str) -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        script = f"""
        (() => {{
          const el = document.querySelector({_js_string(selector)});
          if (!el || el.tagName.toLowerCase() !== 'select') return {{found: false}};
          const wanted = {_js_string(value)};
          const opt = [...el.options].find(o => o.value === wanted || o.text.trim() === wanted);
          if (!opt) return {{found: false, options: [...el.options].map(o => o.value)}};
          el.value = opt.value;
          el.dispatchEvent(new Event('change', {{bubbles: true}}));
          return {{found: true, value: el.value}};
        }})()
        """
        try:
            result = self._run_js(tab["id"], script)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "tab_id": tab["id"]}
        if not (isinstance(result, dict) and result.get("found")):
            return {"ok": False, "error": f"No option {value!r} in {selector!r}.",
                    "options": (result or {}).get("options", []),
                    "tab_id": tab["id"]}
        return {"ok": True, "tab_id": tab["id"], "value": result.get("value", "")}

    def scroll_page(self, tab_id: str = "", direction: str = "down",
                    amount: int = 600) -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        delta = int(amount) * (-1 if str(direction).lower() in ("up", "top", "-") else 1)
        script = f"(() => {{ window.scrollBy(0, {delta}); return window.scrollY; }})()"
        try:
            y = self._run_js(tab["id"], script)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "tab_id": tab["id"]}
        return {"ok": True, "tab_id": tab["id"], "scroll_y": y}

    def wait_for_element(self, tab_id: str, selector: str,
                         timeout: float = 10.0) -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        deadline = time.monotonic() + max(0.2, timeout)
        script = (f"(() => document.querySelectorAll({_js_string(selector)}).length)()")
        last_error = ""
        while time.monotonic() < deadline:
            try:
                count = self._run_js(tab["id"], script, timeout=4.0)
            except Exception as exc:
                last_error = str(exc)
                count = 0
            if count:
                return {"ok": True, "tab_id": tab["id"], "count": int(count)}
            QApplication.processEvents()
            time.sleep(0.1)
        return {"ok": False, "tab_id": tab["id"],
                "error": (f"No element matched {selector!r} within {timeout:g}s."
                          + (f" {last_error}" if last_error else ""))}

    def extract_selection(self, tab_id: str = "") -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        try:
            text = self._run_js(tab["id"],
                                "window.getSelection ? window.getSelection().toString() : ''")
        except Exception as exc:
            return {"ok": False, "error": str(exc), "tab_id": tab["id"]}
        text = str(text or "")
        return {"ok": True, "tab_id": tab["id"], "text": text,
                "url": tab.get("url", ""), "title": tab.get("title", ""),
                "has_selection": bool(text.strip())}

    def list_page_images(self, tab_id: str = "") -> dict:
        structure = self.page_structure(tab_id)
        if not structure.get("ok"):
            return structure
        images = [i for i in structure.get("images") or [] if i.get("src")]
        return {"ok": True, "tab_id": structure["tab_id"], "images": images}

    def inspect_image_resource(self, tab_id: str, src: str) -> dict:
        """What the browser actually loaded for an <img>, not what it claims."""
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        script = f"""
        (() => {{
          const img = [...document.images].find(i =>
            (i.currentSrc || i.src) === {_js_string(src)} || i.src === {_js_string(src)});
          if (!img) return {{found: false}};
          return {{found: true, src: img.currentSrc || img.src, alt: img.alt || '',
                   width: img.naturalWidth, height: img.naturalHeight,
                   complete: img.complete,
                   srcset: img.getAttribute('srcset') || ''}};
        }})()
        """
        try:
            data = self._run_js(tab["id"], script)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "tab_id": tab["id"]}
        if not (isinstance(data, dict) and data.get("found")):
            return {"ok": False, "error": "That image is not on the current page.",
                    "tab_id": tab["id"]}
        data.update({"ok": True, "tab_id": tab["id"]})
        return data

    # ── screenshots (real pixels from this engine) ────────────────────────
    def capture_screenshot(self, tab_id: str = "", *, full_page: bool = False,
                           element: str = "", dest: str = "",
                           keep_active: bool = False) -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        view = self._view
        if view is None:
            return {"ok": False, "error": ("The browser view is not on screen, so "
                                           "there is nothing to capture. Open the "
                                           "Research Browser first.")}
        # One view shows one page: bring this tab to the screen while grabbing,
        # then put the user's tab back.
        previous = self._active
        switched = False
        if tab["id"] != previous:
            self.select_tab(tab["id"])
            switched = True
            QApplication.processEvents()
            time.sleep(0.15)
        if tab.get("loading"):
            self.wait_for_load(tab["id"], timeout=10.0)
        pixmap = None
        meta: dict = {}
        original_size = view.size()
        try:
            if element:
                info = self._run_js(tab["id"], f"""
                (() => {{ const el = document.querySelector({_js_string(element)});
                  if (!el) return null; el.scrollIntoView({{block: 'center'}});
                  const r = el.getBoundingClientRect();
                  return {{x: r.x, y: r.y, width: r.width, height: r.height}}; }})()
                """)
                if not info:
                    return {"ok": False, "error": f"No element matches {element!r}.",
                            "tab_id": tab["id"]}
                QApplication.processEvents()
                time.sleep(0.25)
                whole = view.grab()
                # Crop to the element's on-screen rectangle (page coordinates
                # are CSS pixels; the grab is at device pixels).
                ratio = whole.width() / max(1, view.width())
                rect = (int(info["x"] * ratio), int(info["y"] * ratio),
                        int(info["width"] * ratio), int(info["height"] * ratio))
                pixmap = whole.copy(*rect)
                meta = {"element": element, "rect": info}
            elif full_page:
                height = self._run_js(
                    tab["id"],
                    "Math.max(document.body ? document.body.scrollHeight : 0,"
                    " document.documentElement ? document.documentElement.scrollHeight : 0)")
                height = int(height or 0)
                if height <= 0:
                    return {"ok": False, "error": "The page reported no height.",
                            "tab_id": tab["id"]}
                width = max(320, view.width())
                view.resize(width, min(MAX_SCREENSHOT_HEIGHT, height))
                view.page().runJavaScript("window.scrollTo(0, 0)")
                deadline = time.monotonic() + 1.5
                while time.monotonic() < deadline:
                    QApplication.processEvents()
                    time.sleep(0.05)
                pixmap = view.grab()
                meta = {"full_page": True, "page_height": height,
                        "cropped": height > MAX_SCREENSHOT_HEIGHT,
                        "height": pixmap.height()}
            else:
                QApplication.processEvents()
                pixmap = view.grab()
                meta = {"full_page": False}
        finally:
            if full_page and view.size() != original_size:
                view.resize(original_size)
            if switched and previous and not keep_active:
                self.select_tab(previous)
        if pixmap is None or pixmap.isNull():
            return {"ok": False, "error": "The engine returned an empty image.",
                    "tab_id": tab["id"]}
        target = Path(dest) if dest else (
            paths.capture_dir() / f"capture_{time.strftime('%Y%m%d_%H%M%S')}_"
                                  f"{uuid.uuid4().hex[:6]}.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not pixmap.save(str(target), "PNG"):
            return {"ok": False, "error": f"Could not write {target}.",
                    "tab_id": tab["id"]}
        # Verify by reopening: a QPixmap that saved nothing must not be reported
        # as a screenshot.
        try:
            from PIL import Image
            with Image.open(target) as im:
                im.verify()
            with Image.open(target) as im:
                width, height = im.size
                fmt = im.format
        except Exception as exc:
            return {"ok": False, "error": f"Saved screenshot is unreadable: {exc}",
                    "path": str(target), "tab_id": tab["id"]}
        return {"ok": True, "tab_id": tab["id"], "path": str(target),
                "url": tab.get("url", ""), "title": tab.get("title", ""),
                "width": width, "height": height, "format": fmt,
                "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"), **meta}

    def capture_full_page(self, tab_id: str = "", dest: str = "") -> dict:
        return self.capture_screenshot(tab_id, full_page=True, dest=dest)

    # ── human takeover ───────────────────────────────────────────────────
    def request_human_takeover(self, tab_id: str = "", reason: str = "") -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        self._takeover[tab["id"]] = True
        self.takeover_changed.emit(tab["id"], True)
        self._log(f"human takeover on tab {tab['id']}" + (f": {reason}" if reason else ""))
        return {"ok": True, "tab_id": tab["id"], "takeover": True,
                "message": "The user has control. Agent actions are paused."}

    def release_takeover(self, tab_id: str = "") -> dict:
        tab = self._resolve(tab_id)
        if tab is None:
            return {"ok": False, "error": "Unknown tab."}
        self._takeover.pop(tab["id"], None)
        self.takeover_changed.emit(tab["id"], False)
        return {"ok": True, "tab_id": tab["id"], "takeover": False}

    # ── teardown ─────────────────────────────────────────────────────────
    def shutdown(self) -> None:
        self._view = None
        for tab_id in list(self._order):
            tab = self._tabs.pop(tab_id, None)
            if tab and tab.get("page") is not None:
                tab["page"].setParent(None)
                tab["page"].deleteLater()
        self._order = []
        self._active = ""
        self.tabs_changed.emit()


def _get_profile() -> QWebEngineProfile:
    """The one Chromium profile this process browses with.

    QtWebEngine keys persistent profiles by storage name globally: building a
    second profile with the same name shares the same data directory and Qt
    warns that the data may be corrupted, and pages created on the second
    profile stop loading once the first one is destroyed. A single shared
    profile keeps cookies (so a research session stays logged in) and keeps
    every BrowserService usable, including one built after another was shut
    down.
    """
    global _shared_profile
    if _shared_profile is not None:
        return _shared_profile
    profile = QWebEngineProfile(PROFILE_NAME)
    profile.setHttpUserAgent(USER_AGENT)
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
    BrowserService._configure_settings(profile.settings())
    profile.downloadRequested.connect(_block_page_download)
    _shared_profile = profile
    return profile


def _block_page_download(request: QWebEngineDownloadRequest) -> None:
    """Cancel page-initiated downloads for whichever service is live.

    Collection never writes a file the page chose: it goes through the asset
    service, which validates type, size and provenance first.
    """
    name = request.downloadFileName()
    request.cancel()
    service = _active_service
    if service is not None:
        service._log(f"blocked in-page download: {name}")


__all__ = ["BrowserService", "DEFAULT_TIMEOUT"]
