"""Shared fixtures for the research-browser tests.

A single local HTTP server serves every controlled page the tests need, so the
browser under test loads real HTML/JS/images over a real socket — no mocks of
the engine and no internet access.
"""

from __future__ import annotations

import io
import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402

# Must be imported before any QApplication exists (QtWebEngine requirement).
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: E402


def _png(size=(64, 48), colour=(200, 40, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    return buf.getvalue()


PIXEL = _png()
BIG = _png((800, 600), (20, 120, 200))
BROKEN = b"not an image at all"

INDEX = b"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Research Index</title>
<meta name="description" content="A controlled page for tests">
<meta property="og:title" content="Research Index OG">
</head><body>
<h1 id="title">Controlled research page</h1>
<h2>Section one</h2>
<p id="paragraph">The quick brown fox jumps over the lazy dog.</p>
<p>Second paragraph with a <a id="second-link" href="/second">second page link</a>.</p>
<a id="target-blank" href="/second" target="_blank">opens a new tab</a>
<a id="js-link" href="javascript:window.__pwned=1">js</a>
<a id="file-link" href="file:///C:/Windows/win.ini">local file</a>
<form id="form" action="/form" method="get">
  <input id="name" name="name" value="">
  <select id="colour" name="colour">
    <option value="red">Red</option><option value="blue">Blue</option>
  </select>
  <button id="submit" type="submit">Send</button>
</form>
<table id="table"><thead><tr><th>Name</th><th>Value</th></tr></thead>
<tbody><tr><td>alpha</td><td>1</td></tr><tr><td>beta</td><td>2</td></tr></tbody></table>
<img id="pixel" src="/pixel.png" alt="a red pixel">
<img id="big" src="/big.png" alt="a blue rectangle">
<img id="broken" src="/broken.png" alt="broken bytes">
<img id="fake" src="/fake.png" alt="html pretending to be png">
<picture><source srcset="/big.png 2x"><img id="responsive" src="/pixel.png" alt="responsive"></picture>
<div id="later"></div>
<script>
  setTimeout(() => {
    const p = document.createElement('p');
    p.id = 'dynamic'; p.textContent = 'Dynamically inserted text';
    document.body.appendChild(p);
  }, 300);
  window.addEventListener('beforeunload', () => {});
</script>
</body></html>"""

SECOND = b"""<!doctype html><html><head><title>Second Page</title></head>
<body><h1 id="h">Second page</h1><p>Second body text.</p>
<a id="back-link" href="/">back</a></body></html>"""

FORM = b"""<!doctype html><html><head><title>Form Result</title></head>
<body><h1>Submitted</h1><p id="echo">done</p></body></html>"""

SELECT = b"""<!doctype html><html><head><title>Selection Page</title></head>
<body><p id="sel" onclick="selectText()">Selectable sentence for collection.</p>
<script>function selectText(){const r=document.createRange();
r.selectNodeContents(document.getElementById('sel'));
const s=window.getSelection(); s.removeAllRanges(); s.addRange(r);}</script>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, body: bytes, ctype: str = "text/html", status: int = 200,
              extra: dict | None = None):
        self.send_response(status)
        headers = {"Content-Type": ctype, "Content-Length": str(len(body))}
        headers.update(extra or {})
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self._send(INDEX)
        if path == "/second":
            return self._send(SECOND)
        if path == "/form":
            return self._send(FORM)
        if path == "/selection":
            return self._send(SELECT)
        if path == "/long":
            body = (b"<html><head><title>Long Page</title></head><body>"
                    b"<h1>Long page</h1>"
                    + b"<p>filler line for scrolling</p>" * 400
                    + b"</body></html>")
            return self._send(body)
        if path == "/pixel.png":
            return self._send(PIXEL, "image/png")
        if path == "/big.png":
            return self._send(BIG, "image/png")
        if path == "/broken.png":
            return self._send(BROKEN, "image/png")
        if path == "/fake.png":
            return self._send(b"<html><body>login required</body></html>",
                              "image/png")
        if path == "/redirect":
            return self._send(b"", "text/html", 302,
                              {"Location": "/second"})
        if path == "/slow":
            time.sleep(4)
            return self._send(b"<html><title>Slow</title><body>slow</body></html>")
        if path == "/slow-image.png":
            time.sleep(3)
            return self._send(PIXEL, "image/png")
        if path == "/huge.bin":
            return self._send(b"x" * 1024, "application/octet-stream",
                              extra={"Content-Length": str(200 * 1024 * 1024)})
        if path == "/download":
            return self._send(b"%PDF-1.4 fake", "application/pdf",
                              extra={"Content-Disposition":
                                     'attachment; filename="file.pdf"'})
        if path == "/error":
            return self._send(b"<html><title>Boom</title>server error</html>",
                              "text/html", 500)
        if path == "/empty":
            return self._send(b"", "text/html")
        return self._send(b"<html><title>404</title>not found</html>", "text/html", 404)


class Site:
    def __init__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def url(self, path: str = "/") -> str:
        return self.base + path

    def stop(self) -> None:
        self.server.shutdown()


_APP = None
_SITE = None


def qt_app():
    global _APP
    if _APP is None:
        from PyQt6.QtWidgets import QApplication
        _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


def site() -> Site:
    global _SITE
    if _SITE is None:
        _SITE = Site()
    return _SITE


def stop_site() -> None:
    global _SITE
    if _SITE is not None:
        _SITE.stop()
        _SITE = None


class BrowserCase(unittest.TestCase):
    """One live engine, one visible view, a fresh tab per test class."""

    view = None
    service = None

    @classmethod
    def setUpClass(cls):
        qt_app()
        from core.research_browser import get_service
        cls.view = QWebEngineView()
        cls.view.resize(1100, 760)
        cls.view.show()
        cls.service = get_service()
        cls.service.attach_view(cls.view)
        cls.site = site()

    @classmethod
    def tearDownClass(cls):
        # Keep the engine alive between classes; just drop our tabs.
        for tab in cls.service.tabs() if cls.service else []:
            cls.service.close_tab(tab["tab_id"])

    def setUp(self):
        self.tab = self.service.open_tab("")
        self.service.select_tab(self.tab)

    def tearDown(self):
        try:
            self.service.close_tab(self.tab)
        except Exception:
            pass

    # helpers -----------------------------------------------------------
    def load(self, path: str = "/", timeout: float = 20.0) -> dict:
        result = self.service.navigate(self.tab, self.site.url(path),
                                       timeout=timeout)
        self.assertTrue(result.get("ok"), result)
        return result

    def wait_js(self, expr: str, timeout: float = 6.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            value = self.service._run_js(self.tab, expr)
            if value:
                return value
            time.sleep(0.05)
            qt_app().processEvents()
        return None
