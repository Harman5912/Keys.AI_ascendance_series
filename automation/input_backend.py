"""Backend #4 — Mouse / Keyboard fallback.

Direct input via pyautogui (with optional pynput). Only used after UI
Automation, native APIs, and vision have failed to reach an element — or to
execute an action at coordinates that a higher backend already located.
"""

from __future__ import annotations

import time
from typing import Optional

from automation.base import Backend, Element, Rect


class InputBackend(Backend):
    name = "input"
    priority = 4

    def __init__(self) -> None:
        self._pyautogui = None
        try:
            import pyautogui  # noqa: F401
            self._pyautogui = True
        except Exception:
            self._pyautogui = False

    def available(self) -> bool:
        return bool(self._pyautogui)

    def _p(self):
        import pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05
        return pyautogui

    # ── click at coordinates ────────────────────────────────────────────
    def click(self, element: Element) -> bool:
        if not self._pyautogui or not element or not element.rect:
            return False
        cx, cy = element.rect.center
        try:
            self._p().click(cx, cy)
            return True
        except Exception:
            return False

    def type_text(self, element: Optional[Element], text: str) -> bool:
        if not self._pyautogui:
            return False
        try:
            py = self._p()
            if element and element.rect:
                cx, cy = element.rect.center
                py.click(cx, cy)
                time.sleep(0.1)
            if len(text) > 20:
                # Clipboard paste is faster and more reliable for long text.
                import pyperclip
                pyperclip.copy(text)
                py.hotkey("ctrl", "v")
            else:
                py.typewrite(text, interval=0.03)
            return True
        except Exception:
            return False

    def get_text(self, element: Element) -> str:
        return ""   # no reliable text reading at raw input level

    def hotkey(self, keys: list[str]) -> bool:
        if not self._pyautogui or not keys:
            return False
        try:
            self._p().hotkey(*keys)
            return True
        except Exception:
            return False

    def scroll(self, direction: str, amount: int) -> bool:
        if not self._pyautogui:
            return False
        try:
            clicks = amount if direction in ("up", "right") else -amount
            self._p().scroll(clicks)
            return True
        except Exception:
            return False

    def focus_window(self, title: str) -> bool:
        if not self._pyautogui:
            return False
        try:
            import pygetwindow
            wins = pygetwindow.getWindowsWithTitle(title)
            if wins:
                wins[0].activate()
                return True
        except Exception:
            pass
        return False

    def capture(self) -> Optional[bytes]:
        if not self._pyautogui:
            return None
        try:
            import io
            img = self._p().screenshot()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return None

    def click_at(self, x: int, y: int, button: str = "left", clicks: int = 1) -> bool:
        if not self._pyautogui:
            return False
        try:
            self._p().click(x, y, button=button, clicks=clicks)
            return True
        except Exception:
            return False

    def move(self, x: int, y: int) -> bool:
        if not self._pyautogui:
            return False
        try:
            self._p().moveTo(x, y, duration=0.2)
            return True
        except Exception:
            return False
