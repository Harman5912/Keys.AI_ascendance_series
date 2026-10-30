"""WhatsApp reliability subsystem facade (spec 38, 45).

WhatsAppAdapter = state machine + health monitor + adaptive waits +
browser driver + verification, exposed as a single object the tools and
the computer-use engine can call. Gemini provides intent; this adapter
performs it with state-based waits, never fixed sleeps.

The default driver is the Selenium backend (the PyWhatsAppWeb technique:
real Chrome + persistent profile + wa.me contact opening — see
whatsapp/selenium_client.py). When Selenium is unavailable the adapter
automatically falls back to the Playwright client. Set
KEYS_WHATSAPP_BACKEND=playwright (or pass backend="playwright") to force it.
"""

from __future__ import annotations

import os
import time
from typing import Optional

from whatsapp.state import StateMachine, WhatsAppState
from whatsapp.health import AdaptiveTiming
from whatsapp.waits import AdaptiveWaitEngine
from whatsapp.client import WhatsAppClient


class PlaywrightDriver:
    """Bridges the messaging engine to the persistent client thread.

    Playwright's ASYNC objects may only be touched on the client's event-loop
    thread, so every public method marshals a coroutine onto that loop via
    client.run(...) and returns the awaited result to the calling thread.
    Locator resolution walks the fallback chains (spec 27) — never a single
    hardcoded selector.
    """

    def __init__(self, client: WhatsAppClient, log=None):
        self.client = client
        self.log = log or (lambda _m: None)

    # ── async primitives (executed on the WAThread loop) ────────────────
    async def _page(self):
        return await self.client._get_or_create_page()

    async def _find(self, *names):
        """First matching selector across the named locator fallback chains."""
        from whatsapp.locators import get_locator
        page = await self._page()
        for name in names:
            loc = get_locator(name)
            if loc is None:
                continue
            for sel in loc.strategies:
                try:
                    if await page.locator(sel).count() > 0:
                        return sel
                except Exception:
                    continue
        return None

    async def _visible_async(self, name: str) -> bool:
        return (await self._find(name)) is not None

    async def _search_and_select_async(self, target: str) -> bool:
        page = await self._page()
        try:
            sel = await self._find("search_box")
            if not sel:
                return False
            box = page.locator(sel).first
            await box.click()
            await box.fill(target)
            # State-based wait: never sleep a fixed 0.6s (spec 26).
            row = page.locator("div[role=listitem]").first
            await row.wait_for(state="visible", timeout=8000)
            await row.click()
            return True
        except Exception as e:
            self.log(f"[WA] search_and_select error: {e}")
            return False

    async def _chat_title_async(self) -> str:
        try:
            sel = await self._find("chat_title")
            if sel:
                return (await (await self._page()).locator(sel).first.inner_text()).strip()
        except Exception:
            pass
        return ""

    async def _pane_visible_async(self) -> bool:
        return await self._visible_async("message_pane")

    async def _composer_ready_async(self) -> bool:
        return await self._visible_async("composer")

    async def _type_message_async(self, text: str) -> bool:
        page = await self._page()
        try:
            sel = await self._find("composer")
            if not sel:
                return False
            box = page.locator(sel).first
            await box.click()
            await box.type(text, delay=20)
            return True
        except Exception as e:
            self.log(f"[WA] type error: {e}")
            return False

    async def _send_async(self) -> bool:
        page = await self._page()
        try:
            btn = await self._find("send_button")
            if btn:
                await page.locator(btn).first.click()
                return True
            await page.keyboard.press("Enter")
            return True
        except Exception as e:
            self.log(f"[WA] send error: {e}")
            return False

    async def _outgoing_texts_async(self) -> list:
        page = await self._page()
        try:
            sel = await self._find("message_text")
            if not sel:
                return []
            return await page.locator(sel).all_inner_texts()
        except Exception:
            return []

    async def _composer_text_async(self) -> str:
        try:
            sel = await self._find("composer")
            if sel:
                return (await (await self._page()).locator(sel).first.inner_text()).strip()
        except Exception:
            pass
        return ""

    # ── call primitives REMOVED — calling features disabled ────────────

    async def _page_url_async(self) -> str:
        try:
            return (await self._page()).url or ""
        except Exception:
            return ""

    async def _page_title_async(self) -> str:
        try:
            return await (await self._page()).title()
        except Exception:
            return ""

    # ── chat reader primitives (WhatsApp-style UI feed) ───────────────────
    async def _chat_subtitle_async(self) -> str:
        """Last-seen / members subtitle under the conversation header title."""
        try:
            sel = await self._find("conversation_subtitle")
            if sel:
                return (await (await self._page()).locator(sel).first.inner_text()).strip()
        except Exception:
            pass
        return ""

    async def _list_chats_async(self, limit: int = 40) -> list:
        """Enumerate the chat list: title, preview, time, unread badge."""
        page = await self._page()
        try:
            sel = await self._find("chat_list_rows")
            if not sel:
                return []
            rows = await page.locator(sel).all()
            tsel = await self._find("chat_row_title")
            psel = await self._find("chat_row_preview")
            msel = await self._find("chat_row_time")
            usel = await self._find("chat_row_unread")
            chats = []
            for row in rows[:limit]:
                try:
                    title, preview, time_txt, unread = "", "", "", 0
                    if tsel:
                        for cand in await row.locator(tsel).all():
                            t = (await cand.inner_text()).strip()
                            if t:
                                title = t
                                break
                    if psel:
                        try:
                            preview = (await row.locator(psel).first.inner_text()).strip()
                        except Exception:
                            preview = ""
                    if msel:
                        try:
                            time_txt = (await row.locator(msel).first.inner_text()).strip()
                        except Exception:
                            time_txt = ""
                    if usel:
                        try:
                            raw = (await row.locator(usel).first.inner_text()).strip()
                            unread = int(raw) if raw.isdigit() else 0
                        except Exception:
                            unread = 0
                    # Robust fallback: parse the row's flattened text when the
                    # structured spans are missing or wrong. WhatsApp rows read
                    # like "Title\npreview…\n3:24 PM".
                    if not title or not preview or not time_txt:
                        raw_lines = [l.strip() for l in (await row.inner_text()).split("\n") if l.strip()]
                        if raw_lines:
                            if not title:
                                title = raw_lines[0]
                            if not time_txt and len(raw_lines) >= 2:
                                cand = raw_lines[-1]
                                if any(k in cand for k in
                                       (":", "AM", "PM", "Today", "Yesterday",
                                        "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
                                    time_txt = cand
                            if not preview and len(raw_lines) >= 2:
                                preview = raw_lines[1] if len(raw_lines) > 2 else raw_lines[0]
                                if preview == title:
                                    preview = ""
                    chats.append({
                        "title": title,
                        "preview": preview,
                        "time": time_txt,
                        "unread": unread,
                    })
                except Exception:
                    continue
            return chats
        except Exception as e:
            self.log(f"[WA] list_chats error: {e}")
            return []

    async def _read_messages_async(self, limit: int = 60) -> list:
        """Read visible messages of the open conversation newest-first markers.
        Returns dicts: {outgoing, text, time, sender, deleted}."""
        page = await self._page()
        try:
            sel = await self._find("message_containers")
            if not sel:
                return []
            containers = await page.locator(sel).all()
            tsel = await self._find("message_text_span")
            msel = await self._find("message_time")
            msgs = []
            for c in containers[-limit:]:
                try:
                    cls = (await c.get_attribute("class")) or ""
                    outgoing = "message-out" in cls
                    text = ""
                    if tsel:
                        try:
                            text = (await c.locator(tsel).first.inner_text()).strip()
                        except Exception:
                            text = ""
                    time_txt = ""
                    if msel:
                        try:
                            time_txt = (await c.locator(msel).first.inner_text()).strip()
                        except Exception:
                            time_txt = ""
                    sender = ""
                    try:
                        pre = await c.locator("div[data-pre-plain-text]").first.get_attribute("data-pre-plain-text")
                        if pre:
                            # format: "[HH:MM, DD/MM/YYYY] Sender Name: "
                            inner = pre.strip().strip("[]")
                            parts = inner.split("] ", 1)
                            if len(parts) == 2:
                                time_txt = parts[0].split(",")[0].strip()
                                sender = parts[1].rsplit(":", 1)[0].strip()
                    except Exception:
                        pass
                    deleted = ("deleted" in (text or "").lower()
                               and ("deleted this message" in text.lower()
                                    or "this message was deleted" in text.lower()))
                    msgs.append({
                        "outgoing": outgoing,
                        "text": text,
                        "time": time_txt,
                        "sender": sender,
                        "deleted": deleted,
                    })
                except Exception:
                    continue
            return msgs
        except Exception as e:
            self.log(f"[WA] read_messages error: {e}")
            return []

    # ── sync facade (safe to call from tool threads) ────────────────────
    def _any(self, *names):
        self.client.start()
        return self.client.run(self._find(*names))

    def search_and_select(self, target: str) -> bool:
        self.client.start()
        return self.client.run(self._search_and_select_async(target))

    def chat_title(self) -> str:
        self.client.start()
        return self.client.run(self._chat_title_async())

    def message_pane_visible(self) -> bool:
        self.client.start()
        return self.client.run(self._pane_visible_async())

    def composer_ready(self) -> bool:
        self.client.start()
        return self.client.run(self._composer_ready_async())

    def type_message(self, text: str) -> bool:
        self.client.start()
        return self.client.run(self._type_message_async(text))

    def send_message_action(self) -> bool:
        self.client.start()
        return self.client.run(self._send_async())

    def outgoing_texts(self) -> list:
        self.client.start()
        return self.client.run(self._outgoing_texts_async())

    def composer_text(self) -> str:
        self.client.start()
        return self.client.run(self._composer_text_async())

    # Call-related sync methods removed — calling features disabled

    def page_url(self) -> str:
        self.client.start()
        return self.client.run(self._page_url_async())

    def page_title(self) -> str:
        self.client.start()
        return self.client.run(self._page_title_async())

    def chat_subtitle(self) -> str:
        self.client.start()
        return self.client.run(self._chat_subtitle_async())

    # Incoming-call sync methods removed — calling features disabled

    def list_chats(self, limit: int = 40) -> list:
        self.client.start()
        return self.client.run(self._list_chats_async(limit))

    def read_messages(self, limit: int = 60) -> list:
        self.client.start()
        return self.client.run(self._read_messages_async(limit))


class WhatsAppAdapter:
    """High-level operations for the tools / computer-use engine."""

    def __init__(self, log=None, backend=None):
        self.log = log or (lambda _m: None)
        self.sm = StateMachine()
        self.timing = AdaptiveTiming()
        self.waits = AdaptiveWaitEngine(log=self.log)
        self.client = None
        self.driver = None
        self.queue = None
        self.sender = None
        self.backend = backend            # "selenium" | "playwright" | None
        self._last_call = None          # idempotency guard (spec 22)
        self._lazy()

    def _lazy(self):
        if self.client is not None:
            return
        from whatsapp.messaging import (WhatsAppQueue, SendVerifier,
                                        ChatOpener, MessageSender)
        self.queue = WhatsAppQueue()
        self._build_backend()
        self.sender = MessageSender(
            self.driver,
            ChatOpener(self.driver, self.log),
            SendVerifier(self.driver, self.log),
            self.queue, self.log)

    def _build_backend(self):
        """Pick the Web driver: Selenium (the PyWhatsAppWeb technique — the
        user's real Chrome + persistent profile + wa.me opening) by default,
        with the Playwright client as the automatic fallback when Selenium
        is not installed."""
        backend = self.backend or os.environ.get("KEYS_WHATSAPP_BACKEND", "selenium")
        if backend == "playwright":
            from whatsapp.client import WhatsAppClient
            self.client = WhatsAppClient(log=self.log)
            self.driver = PlaywrightDriver(self.client, self.log)
            self.backend = "playwright"
            self._log("backend: playwright")
            return
        # Selenium (default)
        try:
            from whatsapp.selenium_client import SeleniumWhatsAppClient, SeleniumDriver
            self.client = SeleniumWhatsAppClient(log=self.log)
            self.driver = SeleniumDriver(self.client, self.log)
            self.backend = "selenium"
            self._log("backend: selenium (real Chrome + wa.me)")
        except Exception as e:
            self._log(f"Selenium backend unavailable ({str(e)[:80]}); "
                      "falling back to Playwright")
            from whatsapp.client import WhatsAppClient
            self.client = WhatsAppClient(log=self.log)
            self.driver = PlaywrightDriver(self.client, self.log)
            self.backend = "playwright"
            self._log("backend: playwright (fallback)")

    def status(self) -> str:
        h = self.client.health()
        return (f"[WA] STATE: {self.sm.describe()} "
                f"| {self.timing.summary()} "
                f"| browser_alive: {h.get('browser_alive')} "
                f"| page_alive: {h.get('page_alive')} "
                f"| queue: {self.queue.count()} pending")

    def ensure_ready(self, timeout: float = 60.0) -> bool:
        """Launch + navigate, then multi-signal READY gate (spec 3, 25)."""
        self.sm.transition(WhatsAppState.BROWSER_LAUNCHING)
        self.client.ensure_launched()
        self.sm.transition(WhatsAppState.PAGE_LOADING)

        # Fast-fail: a QR/login screen means no persisted session — don't
        # burn the full readiness timeout; report so callers can fall back
        # (or ask the user to scan) instead of stalling for 75s (spec 23).
        if self._visible("qr_code") or self._visible("auth_screen"):
            self.sm.transition(WhatsAppState.QR_REQUIRED)
            self._log("STATE: QR_REQUIRED — scan the QR code to link WhatsApp Web")
            return False

        from whatsapp.waits import ReadinessSignals, is_loading
        sig = ReadinessSignals()
        sig.add(0.2, self.client.browser_alive, "browser alive")
        sig.add(0.2, self.client.page_alive, "page alive")
        sig.add(0.2, lambda: self.driver._any("app") is not None, "shell")
        sig.add(0.2, lambda: self.driver._any("sidebar") is not None, "sidebar")
        sig.add(0.2, lambda: not is_loading(self._visible), "no loader")

        ok = self.waits.wait_until_sync(sig.ready, timeout=timeout,
                                       what="whatsapp ready",
                                       state_hint="slow" if self.timing.machine.label == "SLOW" else "medium")
        self.sm.transition(WhatsAppState.READY if ok else WhatsAppState.UNKNOWN)
        self._log(f"STATE: {self.sm.state.value} | {sig.describe()}")
        return ok

    def _log(self, msg: str):
        self.log(f"[WA] {msg}")

    def _visible(self, name: str) -> bool:
        return self.driver._any(name) is not None

    def send_message(self, target: str, message: str) -> str:
        if not self.ensure_ready():
            return ("WhatsApp is still synchronizing or unavailable. "
                    "Waiting for the conversation to become ready.")
        self.sm.transition(WhatsAppState.SENDING)
        t0 = time.time()
        # Per-operation adaptive budget (spec 7, 32): slow machines and
        # degraded networks get more time; fast machines don't wait longer.
        budget = self.timing.budget("send_message", baseline=6.0, max_retries=2)
        ok, detail, op = self.sender.send(target, message, timeout=budget.timeout)
        self.timing.record("send_message", time.time() - t0)
        self._log(f"TARGET: {target} | {self.timing.summary()} | VERIFY: {detail}")
        if ok:
            self.sm.transition(WhatsAppState.READY)
            return f"Message confirmed sent to {target} (WhatsApp Web, verified)."
        return f"WhatsApp message to {target}: {detail}"

    def queue_status(self) -> str:
        n = self.queue.count()
        return f"WhatsApp queue: {n} pending message(s)" + (" (paused)" if self.queue.paused() else "")

    def flush_queue(self) -> str:
        if self.queue.paused():
            return "Queue paused - not sending until resumed."
        if not self.ensure_ready():
            return "WhatsApp not ready - queue paused."
        pending = self.queue.pending()
        if not pending:
            return "Queue empty."
        budget = self.timing.budget("send_message", baseline=6.0, max_retries=2)
        sent = 0
        for item in list(pending):
            ok, _d, _op = self.sender.send(item["target"], item["message"],
                                           timeout=budget.timeout)
            if ok:
                sent += 1
            else:
                break
        return f"Flushed {sent} of {len(pending)} queued message(s)."

    def make_call(self, contact: str, call_type: str = "voice") -> dict:
        """Calling features have been removed."""
        return {
            "success": False, "state": "CALL_FAILED",
            "contact": contact, "call_type": call_type,
            "detail": "Calling features have been removed. Keys.ai can only send messages.",
        }

    def pause_queue(self):
        self.queue.pause()
        return "WhatsApp queue paused."

    # ── chat reader (WhatsApp-style UI feed) ─────────────────────────────
    def list_chats(self) -> dict:
        """Real chat list from WhatsApp Web. Returns
        {ok, state, chats: [{title, preview, time, unread}]}."""
        ok = self.ensure_ready()
        if not ok:
            return {"ok": False, "state": self.sm.state.value, "chats": []}
        try:
            return {"ok": True, "state": self.sm.state.value,
                    "chats": self.driver.list_chats()}
        except Exception as e:
            self._log(f"list_chats error: {e}")
            return {"ok": False, "state": self.sm.state.value, "chats": []}

    def open_chat(self, title: str, timeout: float = 20.0) -> dict:
        """Open + verify a conversation, returning {ok, detail}."""
        from whatsapp.messaging import ChatOpener
        try:
            opened, detail = ChatOpener(self.driver, self.log).open(title, timeout=timeout)
            return {"ok": opened, "detail": detail, "title": title}
        except Exception as e:
            return {"ok": False, "detail": str(e)[:150], "title": title}

    def read_messages(self, limit: int = 60) -> dict:
        """Messages of the currently-open conversation."""
        try:
            return {"ok": True, "messages": self.driver.read_messages(limit)}
        except Exception as e:
            self._log(f"read_messages error: {e}")
            return {"ok": False, "messages": [], "detail": str(e)[:120]}

    def chat_meta(self) -> dict:
        """Title + subtitle (last seen / members) of the open chat."""
        try:
            return {"title": self.driver.chat_title(),
                    "subtitle": self.driver.chat_subtitle()}
        except Exception:
            return {"title": "", "subtitle": ""}

    def send_text(self, target: str, message: str) -> dict:
        """Send a message and verify; {ok, detail}."""
        if not self.ensure_ready():
            return {"ok": False, "detail": "WhatsApp not ready"}
        t0 = time.time()
        budget = self.timing.budget("send_message", baseline=6.0, max_retries=2)
        ok, detail, _op = self.sender.send(target, message, timeout=budget.timeout)
        self.timing.record("send_message", time.time() - t0)
        self.sm.transition(WhatsAppState.READY if ok else WhatsAppState.UNKNOWN)
        return {"ok": ok, "detail": detail}

    # Incoming-call handling removed — calling features disabled

    def pause_queue(self):
        self.queue.pause()
        return "WhatsApp queue paused."

    def resume_queue(self):
        self.queue.resume()
        return "WhatsApp queue resumed."

    def _ready_with_retry(self, timeout: float = 60.0) -> bool:
        """Spec 15: before giving up on readiness, repair once — reload the
        page and re-check (browser may be unhealthy or WhatsApp mid-sync)."""
        if self.ensure_ready(timeout=timeout):
            return True
        try:
            if self.client.reload_page():
                self.sm.transition(WhatsAppState.PAGE_LOADING)
                self._log("STATE: page reloaded — re-checking readiness")
                return self.ensure_ready(timeout=min(timeout, 30.0))
        except Exception:
            pass
        return False

    def call_status(self) -> str:
        return "Calling features are disabled. Keys.ai can only send messages."

    def close(self):
        try:
            self.client.close()
        except Exception:
            pass


_adapter: Optional[WhatsAppAdapter] = None


def get_adapter(log=None, backend=None) -> WhatsAppAdapter:
    global _adapter
    if _adapter is None or (backend is not None
                            and _adapter.backend != backend):
        _adapter = WhatsAppAdapter(log=log, backend=backend)
    return _adapter


__all__ = ["WhatsAppAdapter", "get_adapter", "PlaywrightDriver"]
