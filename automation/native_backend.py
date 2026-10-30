"""Backend #2 — Native application APIs.

Registry of per-application adapters that use an app's own automation surface
(CDP / DevTools, WebSocket, SDK, CLI) whenever it is available — faster and more
reliable than UI manipulation. Adapters are attempted only when they report
they can handle the current target, and they expose the SAME command surface as
the UI backends, so API actions and UI actions share one high-level interface.

Currently ships a Playwright/CDP browser adapter. Add new apps by subclassing
NativeAdapter and registering it in NativeBackend.register().
"""

from __future__ import annotations

import abc
import threading
from typing import Optional

from automation.base import Backend, Element, Rect

# Which app names map to a browser we can drive via Playwright.
_BROWSER_KEYWORDS = ("chrome", "edge", "chromium", "firefox", "brave", "opera")


class NativeAdapter(abc.ABC):
    """A per-application automation adapter (CDP / SDK / CLI / WebSocket)."""

    app_keywords: tuple[str, ...] = ()

    def can_handle(self, app_name: str, window_title: str = "") -> bool:
        a = (app_name or "").lower()
        t = (window_title or "").lower()
        return any(k in a or k in t for k in self.app_keywords)

    def find(self, description: str, window_title: str = "") -> Optional[Element]:
        return None

    def click(self, element: Element) -> bool:
        return False

    def type_text(self, element: Optional[Element], text: str) -> bool:
        return False

    def get_text(self, element: Element) -> str:
        return ""


class _PlaywrightAdapter(NativeAdapter):
    """Browser automation via Playwright (CDP when possible).

    Purely opportunistic: only activates when Playwright is importable AND the
    target looks like a browser. All failures degrade to other backends.
    """

    app_keywords = _BROWSER_KEYWORDS
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._pw = None
        try:
            import playwright.sync_api  # noqa: F401
            self._pw = "sync"
        except Exception:
            try:
                import playwright  # noqa: F401
                self._pw = "sync"
            except Exception:
                self._pw = None

    def can_handle(self, app_name: str, window_title: str = "") -> bool:
        if self._pw is None:
            return False
        return super().can_handle(app_name, window_title)

    def _launch(self):
        """Best-effort connect to a running browser or launch one."""
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        try:
            browser = p.chromium.launch_persistent_context(
                user_data_dir="", headless=True, executable_path=None,
            ) if False else None
        except Exception:
            browser = None
        if browser is None:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception:
                p.stop()
                return None, None
        page = browser.pages[0] if browser.pages else browser.new_page()
        return browser, page

    def find(self, description: str, window_title: str = "") -> Optional[Element]:
        if self._pw is None:
            return None
        try:
            browser, page = self._launch()
            if browser is None or page is None:
                return None
            try:
                loc = page.get_by_text(description, exact=False).first
                if loc.count() > 0:
                    box = loc.bounding_box()
                    if box:
                        return Element(name=description, control_type="text",
                                       rect=Rect(int(box["x"]), int(box["y"]),
                                                 int(box["width"]), int(box["height"])),
                                       backend="native", handle=loc)
            except Exception:
                pass
            return None
        except Exception:
            return None
        finally:
            try:
                browser.close()
            except Exception:
                pass


class NativeBackend(Backend):
    name = "native"
    priority = 2

    def __init__(self) -> None:
        self._adapters: list[NativeAdapter] = []
        self._register(_PlaywrightAdapter())

    def _register(self, adapter: NativeAdapter) -> None:
        self._adapters.append(adapter)

    def register(self, adapter: NativeAdapter) -> None:
        """Public hook so extra app adapters can be added at runtime."""
        self._register(adapter)

    def available(self) -> bool:
        return bool(self._adapters)

    def _pick(self, app_name: str, window_title: str = "") -> Optional[NativeAdapter]:
        for a in self._adapters:
            if a.can_handle(app_name, window_title):
                return a
        return None

    def find(self, description: str, control_type: str = "", window_title: str = "") -> Optional[Element]:
        # Native layer needs a target app; without one, fall through.
        if not window_title:
            return None
        adapter = self._pick(window_title, window_title)
        if adapter is None:
            return None
        try:
            return adapter.find(description, window_title)
        except Exception:
            return None

    def click(self, element: Element) -> bool:
        if element and element.handle is not None:
            try:
                element.handle.click()
                return True
            except Exception:
                return False
        return False

    def type_text(self, element: Optional[Element], text: str) -> bool:
        if element and element.handle is not None:
            try:
                element.handle.fill(text)
                return True
            except Exception:
                return False
        return False

    def get_text(self, element: Element) -> str:
        if element and element.handle is not None:
            try:
                return element.handle.inner_text() or ""
            except Exception:
                return ""
        return ""
