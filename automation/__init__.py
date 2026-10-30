"""
automation — hybrid desktop-automation layer for Keys.ai.

Priority order (most reliable first):

  1. Windows UI Automation  (pywinauto / uiautomation)  — element-level control
  2. Native application APIs (CDP / Playwright / app SDKs / CLIs) — registry of adapters
  3. Computer Vision + OCR   (mss + OpenCV + EasyOCR + Gemini vision) — coordinates
  4. Mouse / Keyboard        (pyautogui / pynput) — last-resort direct input

Every high-level command is routed through the HybridController, which tries the
backends in that order, retries on failure, logs every step, and verifies actions
by re-reading the screen when possible.

Extend it by subclassing automation.base.Backend and registering it in
HybridController.backends (or the NativeBackend adapter registry).
"""

from automation.base import (
    AutomationError,
    ElementNotFound,
    BackendUnavailable,
    Rect,
    Element,
    WindowInfo,
    ActionResult,
    Backend,
)
from automation.orchestrator import HybridController
from automation.engine import ComputerUseEngine, get_engine

__all__ = [
    "AutomationError",
    "ElementNotFound",
    "BackendUnavailable",
    "Rect",
    "Element",
    "WindowInfo",
    "ActionResult",
    "Backend",
    "HybridController",
    "ComputerUseEngine",
    "get_engine",
]

# Convenience singleton — reused by the hybrid_control tool.
_controller: "HybridController | None" = None


def get_controller(log=None) -> "HybridController":
    """Return the shared controller (lazily created), with the lightweight
    app adapters (VS Code / Terminal / Explorer) registered on the native
    backend so the hybrid chain can reach apps through their own surface."""
    global _controller
    if _controller is None:
        _controller = HybridController(log=log)
        try:
            from automation.adapters import register_app_adapters
            for b in _controller.backends:
                if b.name == "native":
                    register_app_adapters(b)
                    break
        except Exception:
            pass
    return _controller
