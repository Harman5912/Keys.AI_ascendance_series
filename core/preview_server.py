"""Serve a built project folder to the Research Browser for previews.

The Research Browser only loads http(s) pages — ``file:`` is refused on
purpose (see ``core.research_browser.urls``), so a freshly built page opened as
``file:///…`` showed nothing. A built site is served from a local, read-only
static server instead: one server per folder, reused for later previews, bound
to loopback on an ephemeral port.
"""

from __future__ import annotations

import atexit
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_SERVERS: dict[str, tuple[ThreadingHTTPServer, str]] = {}
_LOCK = threading.Lock()


class _QuietHandler(SimpleHTTPRequestHandler):
    """Static handler that keeps request lines out of the app log."""

    def log_message(self, fmt: str, *args) -> None:   # noqa: A003 - stdlib API
        pass


def serve_directory(folder: str | Path) -> str:
    """Start (or reuse) a server for `folder`; return its base URL."""
    path = Path(folder).resolve()
    if not path.is_dir():
        raise NotADirectoryError(f"Not a folder: {path}")
    key = str(path)
    with _LOCK:
        existing = _SERVERS.get(key)
        if existing is not None:
            return existing[1]
        handler = partial(_QuietHandler, directory=str(path))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}"
        threading.Thread(
            target=server.serve_forever,
            name=f"preview-server-{port}",
            daemon=True,
        ).start()
        _SERVERS[key] = (server, url)
        return url


def preview_url(folder: str | Path, entry: str) -> str:
    """Base URL + the HTML entry inside `folder`, ready for the browser."""
    from urllib.parse import quote

    base = serve_directory(folder)
    relative = str(entry or "").replace("\\", "/").lstrip("/")
    return f"{base}/{quote(relative)}"


def stop_all() -> None:
    """Stop every preview server (called at interpreter exit)."""
    with _LOCK:
        servers = list(_SERVERS.values())
        _SERVERS.clear()
    for server, _url in servers:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass


atexit.register(stop_all)

__all__ = ["preview_url", "serve_directory", "stop_all"]
