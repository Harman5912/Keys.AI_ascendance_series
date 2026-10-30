"""Selenium WhatsApp Web backend — the PyWhatsAppWeb technique.

Modeled on falahati/PyWhatsAppWeb: drive the user's REAL installed Chrome
(with a persistent user-data-dir profile, so WhatsApp Web is linked once
and the session survives restarts), open contacts straight from a wa.me
phone link (works even for numbers NOT saved in the address book), and
interact with WhatsApp Web through the DOM.

Why Selenium instead of the Playwright client? Playwright needs its own
bundled Chromium download (``python -m playwright install chromium``) and
its persistent profile lives in a separate folder. Selenium uses the
Chrome the user already has, which is exactly what PyWhatsAppWeb relies
on — and it is a strict superset here: every messaging/call primitive the
engine needs (search, wa.me open, type, send, call click, call-state
verification, incoming-call reading) is implemented on the SAME driver
interface as PlaywrightDriver, so ChatOpener / MessageSender /
SendVerifier / CallCoordinator / WhatsAppAdapter work unchanged.

Selenium is synchronous, so there is no event-loop marshaling: the client
owns a lock and every driver operation runs on the calling thread while
holding it (safe across the tool worker threads).
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

WHATSAPP_URL = "https://web.whatsapp.com/"


def _profile_dir() -> Path:
    base = Path.home() / ".keysai_profiles" / "whatsapp_selenium"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _clean_phone(target: str) -> str:
    """Return digits-only form if the target looks like an international
    phone number (>= 8 digits, <= 15), else '' — mirroring PyWhatsAppWeb's
    isPhoneNumber check (wa.me needs the number WITHOUT + or spaces)."""
    digits = re.sub(r"\D", "", target or "")
    if 8 <= len(digits) <= 15:
        return digits
    return ""


class SeleniumWhatsAppClient:
    """Owns the Selenium WebDriver + persistent Chrome profile.

    Lazy: nothing launches until ensure_launched(). One lock serializes all
    driver access so the tool worker threads can call safely.
    """

    def __init__(self, headless: bool = False,
                 log: Optional[Callable[[str], None]] = None):
        self.headless = headless
        self.log = log or (lambda _m: None)
        self._lock = threading.RLock()
        self._driver = None
        self._profile = _profile_dir()
        self._launch_error: Optional[str] = None

    # ── thread-safe execution ────────────────────────────────────────────
    def sync(self, fn, *args):
        """Run fn on the calling thread while holding the driver lock."""
        with self._lock:
            self.ensure_launched()
            return fn(*args)

    # ── lifecycle ────────────────────────────────────────────────────────
    def ensure_launched(self):
        """Launch Chrome (persistent profile) + navigate to WhatsApp Web.
        Idempotent; raises a clear error if Selenium/ChromeDriver is
        missing so callers can fall back to another backend."""
        if self._driver is not None:
            return self._driver
        with self._lock:
            if self._driver is not None:
                return self._driver
            try:
                self._launch()
            except Exception as e:
                msg = str(e)
                self._launch_error = (
                    "Selenium/ChromeDriver could not start, so WhatsApp "
                    "Web automation cannot run. Fix with:\n"
                    "    pip install selenium\n"
                    "(ChromeDriver is auto-managed by Selenium Manager). "
                    f"Detail: {msg[:120]}")
                self.log(f"[WA-SEL] {self._launch_error}")
                raise RuntimeError(self._launch_error) from e
            try:
                self._driver.get(WHATSAPP_URL)
            except Exception as e:
                self.log(f"[WA-SEL] navigation error: {str(e)[:120]}")
            return self._driver

    def _launch(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        opts = Options()
        opts.add_argument(f"user-data-dir={self._profile}")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        if self.headless:
            opts.add_argument("--headless=new")
        else:
            opts.add_argument("--window-size=420,760")
        # Grant mic + camera so WebRTC calls are not blocked by a stuck
        # permission prompt inside the automated browser.
        opts.add_experimental_option("prefs", {
            "profile.default_content_setting_values.media_stream_mic": 1,
            "profile.default_content_setting_values.media_stream_camera": 1,
        })
        self._driver = webdriver.Chrome(options=opts)
        self.log("[WA-SEL] Chrome launched with persistent profile "
                 f"({self._profile})")

    def browser_alive(self) -> bool:
        try:
            return self._driver is not None and bool(self._driver.session_id)
        except Exception:
            return False

    def page_alive(self) -> bool:
        try:
            if self._driver is None:
                return False
            self._driver.current_url          # raises when session is dead
            return True
        except Exception:
            return False

    def health(self) -> dict:
        return {
            "browser_alive": self.browser_alive(),
            "page_alive": self.page_alive(),
            "profile": str(self._profile),
        }

    def reload_page(self) -> bool:
        with self._lock:
            if self._driver is None:
                return False
            try:
                self._driver.refresh()
                return True
            except Exception:
                return False

    def close(self):
        with self._lock:
            if self._driver is not None:
                try:
                    self._driver.quit()
                except Exception:
                    pass
                self._driver = None

    def stop(self):
        """Alias for close(): matches the Playwright client API."""
        self.close()


class SeleniumDriver:
    """Selenium implementation of the exact sync interface PlaywrightDriver
    exposes (see whatsapp/__init__.py). Every public method is thread-safe
    through client.sync(); the private helpers assume the lock is held.
    """

    def __init__(self, client: SeleniumWhatsAppClient,
                 log: Optional[Callable[[str], None]] = None):
        self.client = client
        self.log = log or (lambda _m: None)

    # ── element resolution (locator fallback chains from whatsapp.locators)
    def _els(self, *names):
        from whatsapp.locators import get_locator
        from selenium.webdriver.common.by import By
        d = self.client.ensure_launched()
        for name in names:
            loc = get_locator(name)
            if loc is None:
                continue
            for sel in loc.strategies:
                try:
                    els = d.find_elements(By.CSS_SELECTOR, sel)
                    if els:
                        return sel, els
                except Exception:
                    continue
        return None, []

    def _els_in(self, root, *names):
        """First matching selector chain found UNDER a parent element (used
        for per-row / per-message nested locators, e.g. chat-row title/preview
        inside a listitem, or message text/time inside a container)."""
        from whatsapp.locators import get_locator
        from selenium.webdriver.common.by import By
        for name in names:
            loc = get_locator(name)
            if loc is None:
                continue
            for sel in loc.strategies:
                try:
                    els = root.find_elements(By.CSS_SELECTOR, sel)
                    if els:
                        return sel, els
                except Exception:
                    continue
        return None, []

    def _first(self, *names):
        _sel, els = self._els(*names)
        return els[0] if els else None

    def _visible(self, name: str) -> bool:
        _sel, els = self._els(name)
        if not els:
            return False
        try:
            return bool(els[0].is_displayed())
        except Exception:
            return False

    def _wait_raw(self, css_sel: str, timeout: float = 8.0):
        """Poll for a raw CSS selector (wa.me interstitial, etc.)."""
        from selenium.webdriver.common.by import By
        d = self.client.ensure_launched()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                els = d.find_elements(By.CSS_SELECTOR, css_sel)
                if els:
                    try:
                        if els[0].is_displayed():
                            return els[0]
                    except Exception:
                        return els[0]
            except Exception:
                pass
            time.sleep(0.3)
        return None

    def _wait_for(self, *names, timeout: float = 8.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            sel, els = self._els(*names)
            if els:
                try:
                    if els[0].is_displayed():
                        return sel, els[0]
                except Exception:
                    return sel, els[0]
            time.sleep(0.3)
        return None, None

    # ── sync facade (thread-safe; matches PlaywrightDriver) ──────────────
    def _any(self, *names):
        """First matching selector across the fallback chains, or None."""
        return self.client.sync(self._els, *names)[0]

    def search_and_select(self, target: str) -> bool:
        """PyWhatsAppWeb-style open: wa.me link for phone numbers first,
        then the classic search box. Returns True only when the chat pane
        is actually on screen."""
        return self.client.sync(self._search_and_select, target)

    def _search_and_select(self, target: str) -> bool:
        phone = _clean_phone(target)
        if phone:
            if self._open_via_wame(phone):
                return True
            self.log(f"[WA-SEL] wa.me open failed for {phone}; "
                     "falling back to search")
        return self._search_box(target)

    def _open_via_wame(self, phone: str) -> bool:
        """Open the chat via https://wa.me/<phone> (the PyWhatsAppWeb
        approach): click 'Continue to Chat', handle the 'use WhatsApp Web'
        interstitial, then confirm the message pane appeared."""
        try:
            d = self.client.ensure_launched()
            d.get(f"https://wa.me/{phone}")
            btn = self._wait_raw("#action-button", timeout=15)
            if btn is not None:
                try:
                    btn.click()
                except Exception:
                    pass
            # Some locales/versions show a 'use WhatsApp Web' link.
            link = self._wait_raw("a[href*='web.whatsapp.com']", timeout=6)
            if link is not None:
                try:
                    link.click()
                except Exception:
                    pass
            _sel, _el = self._wait_for("message_pane", timeout=25)
            return _sel is not None
        except Exception as e:
            self.log(f"[WA-SEL] wa.me open error: {str(e)[:120]}")
            return False

    def _search_box(self, target: str) -> bool:
        try:
            box = self._wait_for("search_box", timeout=10)[1]
            if box is None:
                return False
            box.click()
            box.send_keys(target)
            row = self._wait_raw("div[role='listitem']", timeout=8)
            if row is None:
                row = self._wait_raw("div[role='row']", timeout=4)
            if row is None:
                return False
            try:
                row.click()
            except Exception:
                pass
            _sel, _el = self._wait_for("message_pane", timeout=10)
            return _sel is not None
        except Exception as e:
            self.log(f"[WA-SEL] search error: {str(e)[:120]}")
            return False

    def chat_title(self) -> str:
        def _t():
            try:
                _sel, els = self._els("chat_title")
                for el in els:
                    t = (el.text or "").strip()
                    if t:
                        return t
                for el in els:
                    t = (el.get_attribute("title") or "").strip()
                    if t:
                        return t
            except Exception:
                pass
            return ""
        return self.client.sync(_t)

    def message_pane_visible(self) -> bool:
        return self.client.sync(self._visible, "message_pane")

    def composer_ready(self) -> bool:
        return self.client.sync(self._visible, "composer")

    def type_message(self, text: str) -> bool:
        def _t():
            try:
                box = self._first("composer")
                if box is None:
                    return False
                box.click()
                from selenium.webdriver.common.keys import Keys
                from selenium.webdriver.common.action_chains import ActionChains
                d = self.client.ensure_launched()
                parts = (text or "").split("\n")
                for i, part in enumerate(parts):
                    if part:
                        box.send_keys(part)
                    if i < len(parts) - 1:
                        # multiline: SHIFT+ENTER (PyWhatsAppWeb technique)
                        ActionChains(d).key_down(Keys.SHIFT).key_down(
                            Keys.ENTER).key_up(Keys.ENTER).key_up(Keys.SHIFT).perform()
                return True
            except Exception as e:
                self.log(f"[WA-SEL] type error: {str(e)[:120]}")
                return False
        return self.client.sync(_t)

    def send_message_action(self) -> bool:
        def _s():
            try:
                btn = self._first("send_button")
                if btn is not None:
                    btn.click()
                    return True
                from selenium.webdriver.common.keys import Keys
                d = self.client.ensure_launched()
                d.switch_to.active_element.send_keys(Keys.ENTER)
                return True
            except Exception as e:
                self.log(f"[WA-SEL] send error: {str(e)[:120]}")
                return False
        return self.client.sync(_s)

    def outgoing_texts(self) -> list:
        def _o():
            from selenium.webdriver.common.by import By
            try:
                _sel, els = self._els("outgoing_messages")
                out = []
                for el in els:
                    try:
                        spans = el.find_elements(By.CSS_SELECTOR,
                                                 "span.selectable-text")
                        if spans:
                            out.append(" ".join(s.text for s in spans).strip())
                        else:
                            t = (el.text or "").strip()
                            if t:
                                out.append(t)
                    except Exception:
                        continue
                return out
            except Exception:
                return []
        return self.client.sync(_o)

    def composer_text(self) -> str:
        def _c():
            try:
                el = self._first("composer")
                return (el.text or "").strip() if el is not None else ""
            except Exception:
                return ""
        return self.client.sync(_c)

    # ── call primitives (single-call reliability) ────────────────────────
    def element_actionable(self, sel: str) -> bool:
        def _a():
            try:
                from selenium.webdriver.common.by import By
                d = self.client.ensure_launched()
                el = d.find_element(By.CSS_SELECTOR, sel)
                return el.is_displayed() and el.is_enabled()
            except Exception:
                return False
        return self.client.sync(_a)

    def click_call_button(self, sel: str) -> bool:
        def _c():
            try:
                from selenium.webdriver.common.by import By
                d = self.client.ensure_launched()
                el = d.find_element(By.CSS_SELECTOR, sel)
                el.click()
                return True
            except Exception as e:
                self.log(f"[WA-SEL] call click error: {str(e)[:120]}")
                return False
        return self.client.sync(_c)

    def call_state_indicators(self) -> list:
        def _i():
            found = []
            for name in ("call_panel", "call_timer", "end_call_button",
                         "calling_banner"):
                if self._visible(name):
                    found.append(name)
            return found
        return self.client.sync(_i)

    def page_url(self) -> str:
        try:
            return self.client.ensure_launched().current_url or ""
        except Exception:
            return ""

    def page_title(self) -> str:
        try:
            return self.client.ensure_launched().title or ""
        except Exception:
            return ""

    def chat_subtitle(self) -> str:
        def _s():
            try:
                el = self._first("conversation_subtitle")
                return (el.text or "").strip() if el is not None else ""
            except Exception:
                return ""
        return self.client.sync(_s)

    # ── chat reader ──────────────────────────────────────────────────────
    def list_chats(self, limit: int = 40) -> list:
        """Enumerate the chat list through the structured locator chains:
        {title, preview, time, unread}. Falls back to the row's flattened
        text when a structured field is missing (WhatsApp rows read like
        'Title\npreview…\n3:24 PM')."""
        def _l():
            try:
                _sel, rows = self._els("chat_list_rows")
                chats = []
                for row in rows[:limit]:
                    try:
                        title, preview, time_txt, unread = "", "", "", 0
                        # structured locators first (fallback chains)
                        _s, els = self._els_in(row, "chat_row_title")
                        for el in els:
                            t = (el.text or "").strip()
                            if not t:
                                try:
                                    t = (el.get_attribute("title") or "").strip()
                                except Exception:
                                    t = ""
                            if t:
                                title = t
                                break
                        _s, els = self._els_in(row, "chat_row_preview")
                        for el in els:
                            t = (el.text or "").strip()
                            if t and t != title:
                                preview = t
                                break
                        _s, els = self._els_in(row, "chat_row_time")
                        for el in els:
                            t = (el.text or "").strip()
                            if t:
                                time_txt = t
                                break
                        _s, els = self._els_in(row, "chat_row_unread")
                        if els:
                            raw = (els[0].text or "").strip()
                            unread = int(raw) if raw.isdigit() else 0
                        # flattened-text fallback when structured fields are
                        # missing or wrong
                        if not title or not preview or not time_txt:
                            raw_lines = [l.strip() for l in
                                         (row.text or "").split("\n") if l.strip()]
                            if raw_lines:
                                if not title:
                                    title = raw_lines[0]
                                if not time_txt and len(raw_lines) >= 2:
                                    cand = raw_lines[-1]
                                    if any(k in cand for k in
                                           (":", "AM", "PM", "Today", "Yesterday",
                                            "Mon", "Tue", "Wed", "Thu", "Fri",
                                            "Sat", "Sun")):
                                        time_txt = cand
                                if not preview and len(raw_lines) >= 2:
                                    preview = (raw_lines[1] if len(raw_lines) > 2
                                               else raw_lines[0])
                                    if preview == title:
                                        preview = ""
                        chats.append({"title": title, "preview": preview,
                                      "time": time_txt, "unread": unread})
                    except Exception:
                        continue
                return chats
            except Exception:
                return []
        return self.client.sync(_l)

    def read_messages(self, limit: int = 60) -> list:
        """Read visible messages of the open conversation through the
        structured locator chains. Returns dicts:
        {outgoing, text, time, sender, deleted}."""
        def _r():
            try:
                _sel, containers = self._els("message_containers")
                msgs = []
                for c in containers[-limit:]:
                    try:
                        cls = (c.get_attribute("class") or "")
                        outgoing = "message-out" in cls
                        # text from the structured message-text chain
                        text = ""
                        _s, spans = self._els_in(c, "message_text_span")
                        if spans:
                            parts = []
                            for s in spans:
                                t = (s.text or "").strip()
                                if t:
                                    parts.append(t)
                            text = " ".join(parts)
                        # time from the structured msg-meta chain
                        time_txt = ""
                        _s, tels = self._els_in(c, "message_time")
                        for el in tels:
                            t = (el.text or "").strip()
                            if t:
                                time_txt = t
                                break
                        sender = ""
                        pre = c.get_attribute("data-pre-plain-text")
                        if pre:
                            inner = pre.strip().strip("[]")
                            parts = inner.split("] ", 1)
                            if len(parts) == 2:
                                time_txt = parts[0].split(",")[0].strip()
                                sender = parts[1].rsplit(":", 1)[0].strip()
                        deleted = ("deleted" in (text or "").lower()
                                   and ("deleted this message" in text.lower()
                                        or "this message was deleted" in text.lower()))
                        msgs.append({"outgoing": outgoing, "text": text,
                                     "time": time_txt, "sender": sender,
                                     "deleted": deleted})
                    except Exception:
                        continue
                return msgs
            except Exception:
                return []
        return self.client.sync(_r)

    # ── incoming-call primitives REMOVED — calling features disabled ─────

    def end_call(self) -> bool:
        def _e():
            try:
                el = self._wait_for("end_call_button", timeout=5)[1]
                if el is None:
                    return False
                el.click()
                return True
            except Exception:
                return False
        return self.client.sync(_e)


__all__ = ["SeleniumWhatsAppClient", "SeleniumDriver", "_clean_phone"]
