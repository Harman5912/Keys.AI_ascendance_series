"""URL parsing and navigation policy for the Research Browser.

Two jobs, both security-relevant:

* turn what the user typed into a URL or a search, the way a browser does;
* refuse anything that is not a normal web page. ``file:`` would let a page (or
  an agent prompt) read local files, ``javascript:``/``data:`` are script
  injection, and ``chrome:``/``view-source:`` reach browser internals. Only
  http, https and the internal blank page are allowed to load.
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlparse

ALLOWED_SCHEMES = {"http", "https"}
INTERNAL_BLANK = "about:blank"
SEARCH_URLS = {
    "duckduckgo": "https://duckduckgo.com/?q={q}",
    "google": "https://www.google.com/search?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
}


_DOMAIN = re.compile(r"^(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?::\d+)?(?:/|$)")
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")


class UrlError(ValueError):
    """A URL the browser refuses to load (message is user-facing)."""


def has_scheme(text: str) -> bool:
    return bool(_SCHEME.match(str(text or "").strip()))


def is_allowed(url: str) -> tuple[bool, str]:
    """(allowed, reason). The internal blank page is allowed; nothing else odd."""
    text = str(url or "").strip()
    if not text:
        return False, "empty URL"
    if text == INTERNAL_BLANK:
        return True, ""
    scheme = urlparse(text).scheme.lower()
    if not scheme:
        return False, "URL has no scheme"
    if scheme not in ALLOWED_SCHEMES:
        return False, (f"The '{scheme}:' scheme is blocked. Only http and https "
                       "pages can be opened in the research browser.")
    host = urlparse(text).hostname or ""
    if not host:
        return False, "URL has no host"
    return True, ""


def to_search(query: str, engine: str = "google") -> str:
    template = SEARCH_URLS.get(str(engine or "").lower()) or SEARCH_URLS["google"]
    return template.format(q=quote(str(query or "").strip()))


def normalise_input(text: str, engine: str = "google") -> tuple[str, str]:
    """('url'|'search', target). Raises UrlError for a blocked scheme."""
    raw = str(text or "").strip()
    if not raw:
        raise UrlError("Type a URL or a search query.")
    if has_scheme(raw):
        scheme = raw.split(":", 1)[0].lower()
        if scheme in ALLOWED_SCHEMES:
            return "url", raw
        if raw == INTERNAL_BLANK:
            return "url", raw
        raise UrlError(
            f"'{scheme}:' links cannot be opened here. Use an http(s) address.")
    if raw.startswith("//"):
        return "url", "https:" + raw
    if _DOMAIN.match(raw) and " " not in raw:
        return "url", "https://" + raw
    if raw.startswith(("localhost", "127.0.0.1")):
        return "url", "http://" + raw
    return "search", to_search(raw, engine)


def domain(url: str) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower()
    except Exception:
        return ""


def is_local_host(url: str) -> bool:
    return domain(url) in ("localhost", "127.0.0.1", "::1", "0.0.0.0")


__all__ = ["ALLOWED_SCHEMES", "INTERNAL_BLANK", "SEARCH_URLS", "UrlError",
           "is_allowed", "normalise_input", "to_search", "domain",
           "has_scheme", "is_local_host"]
