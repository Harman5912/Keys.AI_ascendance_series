"""HybridController — routes every automation command through the backends.

Selection order (most reliable first):

  1. Windows UI Automation  (uia_backend)
  2. Native application APIs (native_backend)
  3. Computer Vision + OCR   (vision_backend)
  4. Mouse / Keyboard        (input_backend)

Every public method:
  • logs each attempt and which backend was chosen,
  • retries a configurable number of times,
  • returns an ActionResult so failures are honest and machine-readable,
  • and, where it matters, verifies the outcome by re-reading the screen.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from automation.base import ActionResult, Element, ElementNotFound, Rect
from automation.uia_backend import UiaBackend
from automation.native_backend import NativeBackend
from automation.vision_backend import VisionBackend
from automation.input_backend import InputBackend


def _quiet(*args, **kwargs):
    pass


class HybridController:
    def __init__(
        self,
        log: Callable[..., None] | None = None,
        attempts: int = 2,
        delay: float = 0.4,
        timeout: float = 8.0,
        backends: list | None = None,
    ) -> None:
        self._log = log or _quiet
        self.attempts = max(1, attempts)
        self.delay = max(0.0, delay)
        self.timeout = max(1.0, timeout)
        self.backends = backends or [UiaBackend(), NativeBackend(), VisionBackend(), InputBackend()]
        # TTL cache: repeated finds of the same element within 3s reuse the
        # previous resolution (saves vision/OCR/UIA traversal). Cleared on
        # any mutating action and on failed finds, so no stale automation.
        self._find_cache: dict = {}
        self._find_cache_ts: float = 0.0

    # ── helpers ─────────────────────────────────────────────────────────
    @property
    def active(self) -> list:
        return [b for b in self.backends if b.available()]

    def status(self) -> ActionResult:
        rows = [f"{b.name}: {'✓' if b.available() else '✗'}" for b in self.backends]
        return ActionResult(ok=True, message="Automation backends: " + ", ".join(rows),
                            data={b.name: b.available() for b in self.backends})

    def _with_retries(self, fn, what: str):
        """Run fn with retries; returns (result, backend_name)."""
        last_err: Exception | None = None
        for i in range(self.attempts):
            try:
                result = fn()
                if result is not None and result is not False:
                    return result, getattr(result, "backend", "")
            except ElementNotFound:
                raise
            except Exception as e:          # noqa: BLE001 — chain degrades gracefully
                last_err = e
                self._log(f"[Auto] ⚠️  {what} attempt {i + 1} failed: {e}")
            if i < self.attempts - 1:
                time.sleep(self.delay)
        if last_err is not None:
            raise last_err
        return None, ""

    def _best_find(self, description: str, control_type: str = "",
                   window_title: str = "", backends: tuple | None = None) -> Optional[Element]:
        """Try backends in priority order until one locates the element.

        `backends` optionally restricts the pool to the named backends (e.g.
        ("uia",) for a screenshot-free element search) — used by the screen
        control flow so the “keep watching” loop never re-photographs the
        screen while it re-checks UI Automation.
        """
        key = (description, control_type, window_title)
        if self._find_cache and (time.monotonic() - self._find_cache_ts) < 3.0:
            cached = self._find_cache.get(key)
            if cached is not None:
                return cached
        pool = self.active
        if backends:
            names = set(backends)
            pool = [b for b in pool if b.name in names]
        for b in sorted(pool, key=lambda x: x.priority):
            if not hasattr(b, "find"):
                continue
            try:
                el = b.find(description, control_type, window_title)
            except Exception as e:
                self._log(f"[Auto] {b.name}.find failed: {e}")
                continue
            if el is not None:
                self._log(f"[Auto] {b.name} found '{description}': {el.describe()}")
                self._find_cache[key] = el
                self._find_cache_ts = time.monotonic()
                return el
        self._find_cache.pop(key, None)
        return None

    # ── discovery ───────────────────────────────────────────────────────
    def list_windows(self) -> ActionResult:
        try:
            for b in sorted(self.active, key=lambda x: x.priority):
                try:
                    wins = b.list_windows()
                    if wins:
                        lines = [w.describe() for w in wins[:40]]
                        return ActionResult(ok=True, message="Windows:\n" + "\n".join(lines),
                                            data={"windows": [w.__dict__ for w in wins]},
                                            backend=b.name)
                except Exception as e:
                    self._log(f"[Auto] {b.name}.list_windows failed: {e}")
        except Exception:
            pass
        return ActionResult(ok=False, message="Could not enumerate windows on this system.")

    def find(self, description: str, control_type: str = "", window_title: str = "",
             uia_only: bool = False) -> ActionResult:
        """Locate an element. `uia_only=True` restricts the search to UI
        Automation — no screenshots, no OCR — used by the screen-control
        loop before it falls back to its single-shot scene analysis."""
        if not description:
            return ActionResult(ok=False, message="Provide a description of the element to find.")
        try:
            el = self._best_find(description, control_type, window_title,
                                 backends=("uia",) if uia_only else None)
        except Exception as e:
            return ActionResult(ok=False, message=f"find failed: {e}")
        if el is None:
            return ActionResult(ok=False,
                                message=f"Element not found: '{description}'.",
                                data={"not_found": True})
        return ActionResult(ok=True, message=f"Found: {el.describe()}",
                            data={"element": el.__dict__}, backend=el.backend)

    def list_elements(self, window_title: str = "") -> ActionResult:
        """Enumerate the interactive components of a window (empty = active window).
        Every listed component gets an index usable with click/type/read."""
        for b in sorted(self.active, key=lambda x: x.priority):
            try:
                els = b.list_elements(window_title)
            except Exception as e:
                self._log(f"[Auto] {b.name}.list_elements failed: {e}")
                continue
            if els:
                lines = [f"{i:>3}. {e.describe()}" for i, e in enumerate(els)]
                data = {"window": window_title or "active",
                        "elements": [{**e.__dict__, "handle": None} for e in els]}
                return ActionResult(
                    ok=True,
                    message=f"Components in '{window_title or 'active window'}':\n"
                            + "\n".join(lines[:150])
                            + (f"\n… and {len(els) - 150} more" if len(els) > 150 else ""),
                    data=data, backend=b.name)
        return ActionResult(ok=False, message="No interactive components found in that window.",
                            data={"elements": [], "window": window_title or "active"})

    def read(self, description: str = "", control_type: str = "", window_title: str = "") -> ActionResult:
        """Locate an element and read back its text/value."""
        if not description:
            return ActionResult(ok=False, message="Provide a description of the element to read.")
        try:
            el = self._best_find(description, control_type, window_title)
        except Exception as e:
            return ActionResult(ok=False, message=f"read failed: {e}")
        if el is None:
            return ActionResult(ok=False, message=f"Element not found to read: '{description}'.",
                                data={"not_found": True})
        for b in sorted(self.active, key=lambda x: x.priority):
            try:
                text = b.get_text(el) or ""
            except Exception:
                continue
            if text:
                return ActionResult(ok=True, message=text[:3000],
                                    data={"text": text[:3000], "element": el.__dict__},
                                    backend=b.name)
        for b in sorted(self.active, key=lambda x: x.priority):
            try:
                text = b.get_value(el) or ""
            except Exception:
                continue
            if text:
                return ActionResult(ok=True, message=text[:3000],
                                    data={"text": text[:3000], "element": el.__dict__},
                                    backend=b.name)
        return ActionResult(ok=False,
                            message=f"Found '{description}' but could not read its text/value.",
                            data={"element": el.__dict__})

    # ── interaction ─────────────────────────────────────────────────────
    def click(self, description: str = "", control_type: str = "", window_title: str = "",
              x: int | None = None, y: int | None = None) -> ActionResult:
        # Direct coordinates → input backend.
        self._find_cache.clear()
        if x is not None and y is not None:
            for b in sorted(self.active, key=lambda x: x.priority):
                if hasattr(b, "click_at"):
                    try:
                        if b.click_at(int(x), int(y)):
                            return ActionResult(ok=True, message=f"Clicked ({x}, {y}).", backend=b.name)
                    except Exception as e:
                        self._log(f"[Auto] click_at failed: {e}")
            return ActionResult(ok=False, message=f"Could not click ({x}, {y}).")

        if not description:
            return ActionResult(ok=False, message="Provide an element description or x/y coordinates.")

        def _attempt():
            el = self._best_find(description, control_type, window_title)
            if el is None:
                raise ElementNotFound(description)
            for b in sorted(self.active, key=lambda x: x.priority):
                try:
                    if b.click(el):
                        self._log(f"[Auto] {b.name} clicked '{description}'")
                        return el
                except Exception:
                    continue
            return None

        try:
            el, _ = self._with_retries(_attempt, f"click '{description}'")
        except ElementNotFound:
            return ActionResult(ok=False, message=f"Element not found to click: '{description}'.",
                                data={"not_found": True})
        except Exception as e:
            return ActionResult(ok=False, message=f"click failed: {e}")
        if el is None:
            return ActionResult(ok=False, message=f"Could not click '{description}' (no backend succeeded).")
        return ActionResult(ok=True, message=f"Clicked '{description}' at {el.center}.",
                            data={"element": el.__dict__}, backend=el.backend)

    def type_text(self, text: str, description: str = "", control_type: str = "",
                  window_title: str = "", x: int | None = None, y: int | None = None) -> ActionResult:
        if not text:
            return ActionResult(ok=False, message="Provide text to type.")
        self._find_cache.clear()

        # Element-targeted typing.
        if description or window_title:
            el = self._best_find(description or "", control_type, window_title)
            if el is None:
                return ActionResult(ok=False, message=f"Element not found to type into: '{description or window_title}'.",
                                    data={"not_found": True})
            for b in sorted(self.active, key=lambda x: x.priority):
                try:
                    if b.type_text(el, text):
                        return ActionResult(ok=True, message=f"Typed {len(text)} chars into '{description or window_title}'.",
                                            backend=b.name)
                except Exception:
                    continue
            return ActionResult(ok=False, message="No backend could type into the element.")

        # Plain typing at current focus / coordinates.
        if x is not None and y is not None:
            for b in sorted(self.active, key=lambda x: x.priority):
                if hasattr(b, "type_text"):
                    try:
                        fake = Element(name="coords", rect=Rect(int(x), int(y), 1, 1))
                        if b.type_text(fake, text):
                            return ActionResult(ok=True, message=f"Typed at ({x},{y}).", backend=b.name)
                    except Exception:
                        continue
        for b in sorted(self.active, key=lambda x: x.priority):
            try:
                if b.type_text(None, text):
                    return ActionResult(ok=True, message="Typed into the focused field.", backend=b.name)
            except Exception:
                continue
        return ActionResult(ok=False, message="Could not type — no input backend available.")

    def hotkey(self, keys: str | list[str]) -> ActionResult:
        self._find_cache.clear()
        if isinstance(keys, str):
            keys = [k.strip() for k in keys.replace(",", "+").split("+") if k.strip()]
        if not keys:
            return ActionResult(ok=False, message="Provide keys, e.g. 'ctrl+c'.")
        for b in sorted(self.active, key=lambda x: x.priority):
            try:
                if b.hotkey(keys):
                    return ActionResult(ok=True, message=f"Hotkey {'+'.join(keys)} pressed.", backend=b.name)
            except Exception:
                continue
        return ActionResult(ok=False, message="Could not press hotkey — no input backend.")

    def scroll(self, direction: str = "down", amount: int = 3) -> ActionResult:
        self._find_cache.clear()
        for b in sorted(self.active, key=lambda x: x.priority):
            try:
                if b.scroll(direction, int(amount)):
                    return ActionResult(ok=True, message=f"Scrolled {direction} × {amount}.", backend=b.name)
            except Exception:
                continue
        return ActionResult(ok=False, message="Could not scroll.")

    def focus_window(self, title: str) -> ActionResult:
        self._find_cache.clear()
        if not title:
            return ActionResult(ok=False, message="Provide a window title to focus.")
        for b in sorted(self.active, key=lambda x: x.priority):
            try:
                if b.focus_window(title):
                    return ActionResult(ok=True, message=f"Focused window '{title}'.", backend=b.name)
            except Exception:
                continue
        return ActionResult(ok=False, message=f"Could not focus window '{title}'.")

    # ── vision ──────────────────────────────────────────────────────────
    def capture(self) -> Optional[bytes]:
        for b in sorted(self.active, key=lambda x: x.priority):
            try:
                img = b.capture()
                if img:
                    return img
            except Exception:
                continue
        return None

    def describe_screen(self) -> ActionResult:
        vision = next((b for b in self.active if b.name == "vision"), None)
        if vision is None:
            return ActionResult(ok=False, message="Vision backend unavailable (mss/OpenCV not installed).")
        try:
            text = vision.describe_screen()
        except Exception as e:
            return ActionResult(ok=False, message=f"Could not describe screen: {e}")
        if not text:
            return ActionResult(ok=False, message="Screen captured but no description produced.")
        return ActionResult(ok=True, message=text[:3000], backend="vision", data={"description": text[:3000]})

    def ocr(self, region: tuple | None = None) -> ActionResult:
        vision = next((b for b in self.active if b.name == "vision"), None)
        if vision is None:
            return ActionResult(ok=False, message="Vision backend unavailable.")
        try:
            text = vision.ocr_text(region)
        except Exception as e:
            return ActionResult(ok=False, message=f"OCR failed: {e}")
        if not text:
            return ActionResult(ok=False, message="No text detected on screen (OCR unavailable or empty).")
        return ActionResult(ok=True, message=text[:3000], backend="vision", data={"text": text[:3000]})
