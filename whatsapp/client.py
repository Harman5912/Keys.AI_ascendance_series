"""Persistent Playwright WhatsApp session (spec 23-25, 41).
One long-lived browser thread + event loop, reused across operations.
Persistent user-data dir => session survives restarts (no QR every launch).
Page-health checks before every major operation.
"""

from __future__ import annotations

import asyncio
import platform
import threading
import time
from pathlib import Path
from typing import Optional

WHATSAPP_URL = "https://web.whatsapp.com/"


def _profile_dir() -> Path:
    base = Path.home() / ".keysai_profiles" / "whatsapp"
    base.mkdir(parents=True, exist_ok=True)
    return base

class WhatsAppClient:
    """Long-lived persistent WhatsApp Web session."""

    def __init__(self, headless: bool = False, log=None):
        self.headless = headless
        self.log = log or (lambda _m: None)
        self._loop = None
        self._thread = None
        self._ready = threading.Event()
        self._pw = None
        self._context = None
        self._page = None
        self._profile = _profile_dir()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        # Fresh event: a previous run may have set it, which would make a
        # restart return before the new loop is actually up.
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop,
                                       daemon=True, name="WAThread")
        self._thread.start()
        self._ready.wait(timeout=30)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_init())
        except Exception as e:
            self.log(f"[WA] loop init error: {e}")
        finally:
            self._ready.set()
        self._loop.run_forever()

    async def _async_init(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()

    async def _launch(self):
        if self._context is not None:
            return
        from playwright.async_api import async_playwright
        engine = self._pw.chromium
        try:
            self._context = await engine.launch_persistent_context(
                str(self._profile),
                headless=self.headless,
                viewport=None,
                args=["--window-size=420,760"] if not self.headless else [],
                # Voice/video calls need real mic+camera access — grant the
                # permission up-front so the WebRTC call isn't blocked by a
                # stuck permission prompt inside the automated browser.
                permissions=["microphone", "camera"],
            )
        except Exception as e:
            if "executable doesn't exist" in str(e).lower():
                raise RuntimeError(
                    "Playwright's Chromium browser is not installed, so WhatsApp "
                    "automation cannot start. Fix with:\n"
                    "    python -m playwright install chromium\n"
                    "(or run install.py, which does this automatically)."
                ) from e
            raise
        self.log("[WA] persistent context launched (session preserved)")

    def run(self, coro, timeout: int = 90):
        if not self._loop:
            raise RuntimeError("WhatsApp client not started.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _get_or_create_page(self):
        if self._context is None:
            await self._launch()
        if self._page is None or self._page.is_closed():
            pages = self._context.pages
            self._page = pages[0] if pages else await self._context.new_page()
        return self._page

    async def _navigate(self):
        page = await self._get_or_create_page()
        try:
            await page.goto(WHATSAPP_URL, timeout=45000,
                            wait_until="domcontentloaded")
        except Exception as e:
            self.log(f"[WA] navigation error: {e}")
        return page

    def ensure_launched(self) -> object:
        self.start()
        return self.run(self._navigate())

    def page(self):
        self.start()
        return self.run(self._get_or_create_page())

    def browser_alive(self) -> bool:
        try:
            return self._context is not None and self._context.browser.is_connected()
        except Exception:
            return False

    def page_alive(self) -> bool:
        try:
            return self._page is not None and not self._page.is_closed()
        except Exception:
            return False

    def health(self) -> dict:
        return {
            "browser_alive": self.browser_alive(),
            "page_alive": self.page_alive(),
            "profile": str(self._profile),
        }

    async def _reload_page(self):
        if self.page_alive():
            await self._page.reload(timeout=45000)

    async def _restart_context(self):
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
        self._context = None
        self._page = None
        await self._launch()

    async def _restart_browser(self):
        await self._restart_context()

    def reload_page(self) -> bool:
        try:
            self.run(self._reload_page()); return True
        except Exception:
            return False

    def restart_context(self) -> bool:
        try:
            self.run(self._restart_context()); return True
        except Exception:
            return False

    def restart_browser(self) -> bool:
        try:
            self.run(self._restart_browser()); return True
        except Exception:
            return False

    def stop(self):
        """Full teardown: close context/playwright, stop the loop, join the
        browser thread. After stop(), start() can be called again cleanly."""
        if self._loop and self._thread and self._thread.is_alive():
            try:
                asyncio.run_coroutine_threadsafe(
                    self._async_stop(), self._loop).result(10)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        self._loop = None

    async def _async_stop(self):
        await self._async_close()
        try:
            self._loop.stop()
        except Exception:
            pass

    def close(self):
        """Alias for stop(): used by the adapter/tool teardown paths."""
        self.stop()

    async def _async_close(self):
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._context = None
        self._page = None


_client: Optional[WhatsAppClient] = None


def get_client(log=None) -> WhatsAppClient:
    global _client
    if _client is None:
        _client = WhatsAppClient(log=log)
    return _client
