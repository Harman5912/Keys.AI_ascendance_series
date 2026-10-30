"""Shared primitives for the hybrid automation layer."""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


class AutomationError(Exception):
    """Base error for the automation layer."""


class ElementNotFound(AutomationError):
    """A UI element could not be located by any backend."""


class BackendUnavailable(AutomationError):
    """A backend cannot run in this environment (missing dependency / OS)."""


@dataclass
class Rect:
    """A screen rectangle in absolute (virtual-desktop) coordinates."""

    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return int(self.x + self.width / 2), int(self.y + self.height / 2)

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def __bool__(self) -> bool:
        return self.width > 0 and self.height > 0


@dataclass
class Element:
    """A located UI element, produced by any backend."""

    name: str = ""
    control_type: str = ""
    automation_id: str = ""
    rect: Optional[Rect] = None
    backend: str = ""                 # backend that found it ("uia" | "native" | "vision" | "input")
    confidence: float = 0.0
    enabled: bool = True              # whether the control accepts interaction
    handle: object = None             # backend-specific handle (pywinauto wrapper, playwright locator, ...)

    @property
    def center(self) -> Optional[tuple[int, int]]:
        return self.rect.center if self.rect else None

    def describe(self) -> str:
        bits = []
        if self.name:
            bits.append(f"name='{self.name}'")
        if self.control_type:
            bits.append(f"type={self.control_type}")
        if self.automation_id:
            bits.append(f"id='{self.automation_id}'")
        if self.rect:
            bits.append(f"rect=({self.rect.x},{self.rect.y} {self.rect.width}x{self.rect.height})")
        if not self.enabled:
            bits.append("(disabled)")
        return " ".join(bits) or "(unlabeled element)"


@dataclass
class WindowInfo:
    """Metadata about a top-level window."""

    title: str
    handle: int = 0
    rect: Optional[Rect] = None
    process: str = ""
    pid: int = 0

    def describe(self) -> str:
        return f"{self.title} (pid={self.pid})"


@dataclass
class ActionResult:
    """Unified result object for every automation command."""

    ok: bool
    message: str
    data: dict = field(default_factory=dict)
    backend: str = ""                 # backend that ultimately performed the action

    def as_str(self) -> str:
        return self.message


class Backend(abc.ABC):
    """Abstract backend. Subclasses implement the capabilities they support and
    raise BackendUnavailable (or return None) for everything else, so the
    orchestrator can fall through to the next backend cleanly."""

    name: str = "base"
    priority: int = 99                # lower number = tried first

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"

    # ── capability probe ────────────────────────────────────────────────
    @abc.abstractmethod
    def available(self) -> bool:
        """True when this backend can run on the current machine."""

    # ── discovery ───────────────────────────────────────────────────────
    def list_windows(self) -> list[WindowInfo]:
        raise BackendUnavailable(f"{self.name}: list_windows not supported")

    def find(self, description: str, control_type: str = "", window_title: str = "") -> Optional[Element]:
        raise BackendUnavailable(f"{self.name}: find not supported")

    def list_elements(self, window_title: str = "") -> list[Element]:
        """Enumerate the interactive controls of a window (empty title = active window)."""
        raise BackendUnavailable(f"{self.name}: list_elements not supported")

    # ── interaction ─────────────────────────────────────────────────────
    def click(self, element: Element) -> bool:
        raise BackendUnavailable(f"{self.name}: click not supported")

    def type_text(self, element: Optional[Element], text: str) -> bool:
        raise BackendUnavailable(f"{self.name}: type_text not supported")

    def get_text(self, element: Element) -> str:
        raise BackendUnavailable(f"{self.name}: get_text not supported")

    def get_value(self, element: Element) -> str:
        """Read the current value/state of an element (ValuePattern etc.)."""
        raise BackendUnavailable(f"{self.name}: get_value not supported")

    def hotkey(self, keys: list[str]) -> bool:
        raise BackendUnavailable(f"{self.name}: hotkey not supported")

    def scroll(self, direction: str, amount: int) -> bool:
        raise BackendUnavailable(f"{self.name}: scroll not supported")

    # ── window management ───────────────────────────────────────────────
    def focus_window(self, title: str) -> bool:
        raise BackendUnavailable(f"{self.name}: focus_window not supported")

    # ── vision / capture ────────────────────────────────────────────────
    def capture(self) -> Optional[bytes]:
        raise BackendUnavailable(f"{self.name}: capture not supported")

    def describe_screen(self) -> str:
        raise BackendUnavailable(f"{self.name}: describe_screen not supported")

    # ── helpers ─────────────────────────────────────────────────────────
    @staticmethod
    def retry(fn: Callable[[], Optional[object]], attempts: int = 2, delay: float = 0.4):
        """Small retry helper: returns the first truthy result or None."""
        last = None
        for _ in range(max(1, attempts)):
            try:
                result = fn()
                if result:
                    return result
                last = result
            except Exception as e:          # noqa: BLE001 — backends degrade, never crash the chain
                last = e
            time.sleep(delay)
        return last
