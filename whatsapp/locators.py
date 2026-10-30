"""Centralized WhatsApp Web locator registry (spec 27-28).

Every WhatsApp-specific selector lives HERE — never scattered through the
codebase. Each locator is a FALLBACK CHAIN (primary → secondary → structural)
so a single WhatsApp DOM change degrades gracefully instead of breaking the
whole subsystem. No brittle absolute XPath as the only strategy.

WhatsApp Web changes frequently; when a selector breaks, fix it in one place.
"""

from __future__ import annotations

from typing import Callable, Optional


class Locator:
    """A UI concept with an ordered list of selector strategies."""

    def __init__(self, name: str, strategies: list[str]) -> None:
        self.name = name
        self.strategies = strategies

    @property
    def primary(self) -> str:
        return self.strategies[0]

    def fallbacks(self) -> list[str]:
        return self.strategies[1:]

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Locator({self.name}: {len(self.strategies)} strategies)"


# ── the registry (single source of truth for WhatsApp selectors) ──────────
# Ordered: most stable / semantic first, structural fallbacks after.
WA_LOCATORS: dict[str, Locator] = {

    # page shell / app frame
    "app": Locator("app", [
        "div#app",
        "div[data-testid='app']",
        "#app",
    ]),
    "main_frame": Locator("main_frame", [
        "div#main",
        "div[data-testid='main']",
        "#main",
    ]),

    # sidebar / chat list
    "sidebar": Locator("sidebar", [
        "div#side",
        "div[data-testid='side']",
        "#side",
        "div[role='navigation']",
    ]),
    "chat_list": Locator("chat_list", [
        "div[data-testid='chat-list']",
        "div[role='list']",
        "#pane-side div[role='row']",
    ]),
    "chat_row": Locator("chat_row", [
        "div[role='listitem']",
        "div[role='row']",
        "#pane-side div[role='row']",
    ]),

    # search
    "search_box": Locator("search_box", [
        "div[data-testid='chat-list-search'] div[contenteditable='true']",
        "div[contenteditable='true'][data-tab='3']",
        "div[data-testid='search'] input",
        "div[contenteditable='true']",
    ]),

    # chat header / identity
    "chat_title": Locator("chat_title", [
        "div[data-testid='conversation-info-header']",
        "div[data-testid='conversation-title']",
        "header span[dir='auto']",
        "div#main header span[dir='auto']",
    ]),
    "conversation_header": Locator("conversation_header", [
        "div[data-testid='conversation-header']",
        "div#main header",
    ]),

    # message pane
    "message_pane": Locator("message_pane", [
        "div[data-testid='conversation-panel-messages']",
        "div#main div[role='application']",
        "div#main div[data-id]",
        "div#main",
    ]),

    # chat list rows (chat reader)
    "chat_list_rows": Locator("chat_list_rows", [
        "div[data-testid='chat-list'] div[role='listitem']",
        "div[role='listitem']",
        "#pane-side div[role='row']",
    ]),
    "chat_row_title": Locator("chat_row_title", [
        "div[data-testid='conversation-info'] span[dir='auto']",
        "span[dir='auto'][title]",
        "span[title]",
    ]),
    "chat_row_preview": Locator("chat_row_preview", [
        "div[data-testid='conversation-info'] span[data-testid='last-msg-status'] ~ span",
        "div[data-testid='conversation-info'] span[dir='auto']",
        "span[data-testid='last-msg-status'] + span",
    ]),
    "chat_row_time": Locator("chat_row_time", [
        "div[data-testid='conversation-info'] span[data-testid='last-msg-time']",
        "div[data-testid='conversation-info'] div[data-testid='msg-time']",
        "div[data-testid='conversation-info'] span[dir='ltr']",
    ]),
    "chat_row_unread": Locator("chat_row_unread", [
        "span[data-testid='icon-unread-count']",
        "div[data-testid='unread-count']",
        "div[data-testid='icon-unread-count']",
    ]),

    # conversation subtitle (last seen / members)
    "conversation_subtitle": Locator("conversation_subtitle", [
        "div[data-testid='conversation-info-header-chat-subtitle']",
        "div[data-testid='conversation-info-header-sub-title']",
        "header div[data-testid='conversation-info-header'] span[dir='auto']",
        "header span[title]",
    ]),

    # message containers (conversation reader)
    "message_containers": Locator("message_containers", [
        "div[data-testid='msg-container']",
        "div.message-in, div.message-out",
        "div[data-id].message-in, div[data-id].message-out",
    ]),
    "message_in": Locator("message_in", [
        "div.message-in[data-testid='msg-container']",
        "div.message-in",
    ]),
    "message_out": Locator("message_out", [
        "div.message-out[data-testid='msg-container']",
        "div.message-out",
    ]),
    "message_text_span": Locator("message_text_span", [
        "span.selectable-text",
        "span.copyable-text span",
        "span[data-testid='conversation-panel-messages'] span",
    ]),
    "message_time": Locator("message_time", [
        "span[data-testid='msg-meta']",
        "div[data-testid='msg-meta']",
        "span[data-testid='msg-time']",
    ]),
    "message_date_separators": Locator("message_date_separators", [
        "div[data-testid='msg-date']",
        "div[data-testid='conversation-panel-header']",
        "div[data-testid='msg-group-date']",
    ]),

    # composer / input
    "composer": Locator("composer", [
        "div[data-testid='conversation-composer-box-input']",
        "div[data-testid='conversation-composer-box'] div[contenteditable='true']",
        "footer div[contenteditable='true']",
        "div[contenteditable='true'][data-tab='10']",
        "div[contenteditable='true']",
    ]),
    "send_button": Locator("send_button", [
        "button[data-testid='composer-send-button']",
        "span[data-testid='send']",
        "button[aria-label='Send']",
    ]),

    # loading / transition signals
    "loading_indicators": Locator("loading_indicators", [
        "div[data-testid='conversation-panel-loading']",
        "span[data-testid='status-icons']",   # typing/connecting indicator
        "div[data-testid='icon']",            # generic spinner area
    ]),
    "blocking_loader": Locator("blocking_loader", [
        "div[data-testid='main-frame-loading']",
        "div[data-testid='app-loading']",
        "div[aria-label='Loading']",
        "canvas[aria-label='Loading']",
    ]),

    # auth / QR / reconnect
    # The new WhatsApp login page (2025+) uses link-device-qrcode-* testids
    # instead of the old data-testid='qrcode' — keep both so older DOM still
    # degrades gracefully (spec 27-28 fallback chains).
    "qr_code": Locator("qr_code", [
        "div[data-testid='qrcode']",
        "canvas[aria-label='Scan this QR code']",
        "img[data-testid='qrcode']",
        "div[data-testid='link-device-qrcode-alt-linking-help']",
        "div[data-testid='link-device-qrcode-alt-linking-hint']",
    ]),
    "auth_screen": Locator("auth_screen", [
        "div[data-testid='auth-screen']",
        "div[data-testid='app'] div[data-testid='login']",
        "div[data-testid='login']",
        "div[data-testid='link-device-qrcode-alt-linking-tc']",
        "div[data-testid='wa-logo']",
        "div[data-testid='link-device-qrcode-alt-linking-hint']",
    ]),
    "reconnect_banner": Locator("reconnect_banner", [
        "div[data-testid='reconnect']",
        "div[data-testid='refresh']",
        "div[role='button'][aria-label='Reconnect']",
        "div[data-testid='network-status']",
    ]),

    # outgoing messages / send verification
    "outgoing_messages": Locator("outgoing_messages", [
        "div[data-testid='msg-container'] div[data-id]",
        "div.message-out",
        "div[data-pre-plain-text][dir='ltr']",
    ]),
    "message_text": Locator("message_text", [
        "span.selectable-text",
        "span[data-testid='conversation-panel-messages'] span",
        "div.copyable-text",
    ]),
    "composer_placeholder": Locator("composer_placeholder", [
        "div[data-testid='conversation-composer-box-input'] [data-placeholder]",
        "div[data-testid='composer-placeholder']",
        "footer [data-placeholder]",
    ]),

    # call controls (single-call reliability)
    "voice_call_button": Locator("voice_call_button", [
        "div[data-testid='call']",
        "button[data-testid='call']",
        "span[data-testid='call']",
        "button[aria-label*='Voice call']",
        "div[aria-label*='Voice call']",
    ]),
    "video_call_button": Locator("video_call_button", [
        "div[data-testid='video-call']",
        "button[data-testid='video-call']",
        "span[data-testid='video-call']",
        "button[aria-label*='Video call']",
        "div[aria-label*='Video call']",
    ]),

    # call-state indicators (post-click verification)
    "call_panel": Locator("call_panel", [
        "div[data-testid='call-panel']",
        "div[data-testid='call-container']",
        "div[data-testid='conversation-panel'] div[data-testid='call']",
    ]),
}
# NOTE: call-related locators (call_timer, end_call_button, calling_banner,
# incoming_call_screen, call_accept_button, video_call_accept_button,
# call_reject_button, incoming_caller_name) have been removed.
# Calling features are disabled — Keys.ai can only send messages.


# ── resolution helpers ────────────────────────────────────────────────────
def get_locator(name: str) -> Optional[Locator]:
    return WA_LOCATORS.get(name)


def strategy(selector: str) -> Callable[[object], object]:
    """Wrap a selector into a Playwright-ish locator factory so callers can
    stay framework-agnostic: `strategy(s)(page)` returns page.locator(s) when
    the page supports it, else a tiny shim (testable without Playwright)."""
    def _loc(page):
        if page is None:
            return None
        loc = getattr(page, "locator", None)
        if loc is not None:
            return loc(selector)
        # Minimal shim for fake pages in tests.
        return getattr(page, "_fake_locator", lambda s: None)(selector)
    return _loc


def try_strategies(page, locator: Locator):
    """Yield (strategy_index, locator) for each strategy; the caller decides
    which is 'present' — this just walks the chain in order."""
    for idx, sel in enumerate(locator.strategies):
        yield idx, sel


def describe(name: str) -> str:
    loc = WA_LOCATORS.get(name)
    if not loc:
        return f"(unknown locator: {name})"
    return f"{name}: {len(loc.strategies)} strategy(ies); primary={loc.primary}"
