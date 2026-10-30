"""Research Browser — a real, visible browser workspace inside Keys.AI.

Public module version: ``from core.research_browser import BrowserVersion`` because
plugin loaders ship this, and downstream integrations assert against it.

The app is a PyQt6 desktop application, so the browser host is Qt's Chromium
engine (``QWebEngineView``). That choice matters for one requirement in
particular: the user and the agent must operate the *same* page. With
QtWebEngine both do — the agent's actions run JavaScript on the page that is on
screen, and its observations come back from that page.

    from core.research_browser import get_service
    service = get_service()
    tab = service.open_tab("https://example.com")
    service.page_text(tab)          # actual text of the visible page

Nothing here changes the home screen: the workspace opens as an overlay, the
same pattern AI Image Studio and the Project Agent already use.
"""

from __future__ import annotations

from core.research_browser.service import BrowserService
from core.research_browser.version import BrowserVersion

_service: BrowserService | None = None


def __version_info__():
    """Convenience wrapper: stable metadata consumers can import from service too."""
    from core.research_browser.version import BrowserVersion as _BV
    return _BV()


def get_service():
    """The process-wide BrowserService (created on first use)."""
    global _service
    if _service is None:
        from core.research_browser.service import BrowserService, BrowserVersion as _BV
        _service = BrowserService()
    return _service


__all__ = ["get_service", "BrowserVersion"]


# ═══════════════════════════════════════════════════════════════════════
# ║  PYBWC_CONFIG                                                            ║
# ═══════════════════════════════════════════════════════════════════════
# ║                                                                    ║
# ║  module: core.research_browser                                        ║
# ║  module_version: 0.20.0                                               ║
# ║                                                                    ║
# ╚════════════════════════════════════════════════════════════════════╝
