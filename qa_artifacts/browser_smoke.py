"""Quick smoke run for the research browser against a local page.

    QT_QPA_PLATFORM=offscreen python qa_artifacts/browser_smoke.py
"""

from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PAGE = b"""<!doctype html><html><head><title>Smoke Page</title>
<meta name="description" content="smoke"></head>
<body><h1 id="h">Research</h1><p id="p">The quick brown fox.</p>
<a id="next" href="/second">Second</a>
<table><thead><tr><th>Name</th><th>Value</th></tr></thead>
<tbody><tr><td>alpha</td><td>1</td></tr></tbody></table>
<img id="pic" src="/pixel.png" alt="a pixel" width="64" height="64">
</body></html>"""

PIXEL = b""


def make_png() -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/pixel.png":
            body, ctype = PIXEL, "image/png"
        elif self.path == "/second":
            body = b"<html><head><title>Second</title></head><body><h1>Two</h1></body></html>"
            ctype = "text/html"
        else:
            body, ctype = PAGE, "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    global PIXEL
    PIXEL = make_png()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from core.research_browser import get_service, library, paths

    app = QApplication(sys.argv)
    view = QWebEngineView()
    view.resize(1000, 700)
    view.show()
    service = get_service()
    service.attach_view(view)

    checks = []
    tab = service.active_tab() or service.open_tab("")
    result = service.navigate(tab, base + "/")
    checks.append(("navigate", result.get("ok"), result))
    state = service.state(tab)
    checks.append(("state-url", state.get("url", "").startswith(base), state.get("url")))
    checks.append(("title", service.page_title(tab).get("title") == "Smoke Page",
                   service.page_title(tab).get("title")))
    text = service.page_text(tab)
    checks.append(("text", "quick brown fox" in (text.get("text") or ""),
                   (text.get("text") or "")[:60]))
    structure = service.page_structure(tab)
    checks.append(("headings", structure.get("headings", [{}])[0].get("text") == "Research",
                   structure.get("headings", [])[:1]))
    checks.append(("table", (structure.get("tables") or [{}])[0].get("headers") ==
                   ["Name", "Value"], (structure.get("tables") or [{}])[:1]))
    images = service.list_page_images(tab)
    checks.append(("images", any(i["src"].endswith("pixel.png")
                                 for i in images.get("images", [])),
                   [i["src"] for i in images.get("images", [])]))
    shot = service.capture_screenshot(tab)
    checks.append(("screenshot", shot.get("ok") and Path(shot.get("path", "")).is_file(),
                   shot.get("path")))
    clicked = service.click_element(tab, selector="#next")
    checks.append(("click", clicked.get("ok") and "/second" in service.state(tab)["url"],
                   clicked))
    back = service.go_back(tab)
    checks.append(("back", back.get("ok") and service.state(tab)["url"].endswith("/"),
                   service.state(tab)["url"]))
    blocked = service.navigate(tab, "file:///C:/Windows/win.ini")
    checks.append(("blocked-scheme", blocked.get("ok") is False, blocked.get("error")))
    failed = service.navigate(tab, "http://127.0.0.1:1/none")
    checks.append(("unreachable", failed.get("ok") is False or
                   (service.state(tab).get("error") or ""), service.state(tab).get("error")))

    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    library.clear_task("smoke")
    service.shutdown()
    server.shutdown()
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
