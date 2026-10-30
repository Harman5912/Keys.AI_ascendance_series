"""
core/site_checks.py — validation and mechanical repair for generated web pages.

Two jobs, kept separate on purpose:

    check_html(path, kind)        structural / content rules a finished page
                                  must satisfy (same rules the QA harness uses)
    repair_html(path, kind, ...)  deterministic fixes for the failures that
                                  have exactly one correct fix (missing
                                  viewport meta, no focus styles, unclosed
                                  </html>, ...). Never rewrites the author's
                                  design or copy.

    browser_audit(path)           optional Chromium pass (Playwright): console
                                  errors, horizontal overflow at 375/1280 px,
                                  dead in-page anchors. Degrades to
                                  ("skipped", reason) when Playwright or its
                                  browser build is unavailable.

`Crown Code` runs this after every write so a page is never handed over with a
mechanical defect the agent could have fixed itself. Nothing here talks to a
model, so it is deterministic and cheap to unit-test.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

# Minimum finished-page size per artifact kind. Below this the file is a
# skeleton, not a page, regardless of what the model claims.
MIN_BYTES = {"website": 3500, "portfolio": 3500, "webapp": 3500, "page": 2500}

PLACEHOLDER_TEXT = re.compile(
    r"(feature\s*[1-9]\b|lorem ipsum|your company|company name|description here|"
    r"insert (?:text|content)|coming soon|placeholder)",
    re.I,
)

_BASE_CSS = """
/* crown-base: page-level correctness rules */
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;max-width:100%;overflow-x:hidden}
img,svg,video,canvas{max-width:100%;height:auto}
:focus-visible{outline:3px solid var(--crown-focus,#ffd166);outline-offset:3px;border-radius:2px}
a:focus-visible,button:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible{outline:3px solid var(--crown-focus,#ffd166);outline-offset:3px}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important;scroll-behavior:auto!important}}
""".strip()


# ── Checks ────────────────────────────────────────────────────────────────

def check_html(path: Path | str, kind: str = "website") -> tuple[bool, list[str]]:
    """Return (passed, problems) for one generated HTML artifact."""
    path = Path(path)
    problems: list[str] = []
    if not path.exists():
        return False, ["index.html was not created"]
    raw = path.read_text(encoding="utf-8", errors="replace")
    low = raw.lower()

    minimum = MIN_BYTES.get(kind, 3000)
    if len(raw) < minimum:
        problems.append(f"index.html is only {len(raw)} bytes (a finished page needs >= {minimum})")

    visible = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    visible = re.sub(r"<[^>]+>", " ", visible)
    filler = sorted({m.group(0).lower() for m in PLACEHOLDER_TEXT.finditer(visible)})
    if filler:
        problems.append(f"placeholder filler content: {filler[:3]}")

    if "<!doctype" not in low:
        problems.append("missing <!doctype html>")
    if "<html" not in low:
        problems.append("no <html> element")
    if "<title>" not in low:
        problems.append("no <title>")
    if 'name="viewport"' not in low and "name='viewport'" not in low:
        problems.append("no viewport meta (page will not scale on a phone)")
    if kind in ("website", "portfolio"):
        if "<footer" not in low:
            problems.append("no <footer> element")
        if "<button" not in low:
            problems.append("no <button> element")
    if ":focus" not in low:
        problems.append("no :focus / :focus-visible styles")
    if "box-sizing" not in low:
        problems.append("no box-sizing reset (padding can overflow the layout)")
    if kind == "webapp" and "<input" not in low:
        problems.append("no <input> controls")
    if re.search(r"<script[^>]+src=[\"']https?://", raw, re.I):
        problems.append("external script dependency")
    if re.search(r"<link[^>]+href=[\"']https?://", raw, re.I):
        problems.append("external stylesheet dependency")
    if re.search(r"<img[^>]+src=[\"']https?://", raw, re.I):
        problems.append("external image dependency")

    body = re.search(r"<body[^>]*>(.*)</body>", raw, re.S | re.I)
    min_text = 120 if kind == "webapp" else 200
    if not body or len(re.sub(r"<[^>]+>", "", body.group(1)).strip()) < min_text:
        problems.append("almost no visible text content")
    return (not problems), problems


def _labelled_inputs(raw: str) -> bool:
    """Every form control is reachable: wrapped in a <label>, has a label[for],
    or carries an aria-label / placeholder of its own."""
    for m in re.finditer(r"<(input|select|textarea)\b([^>]*)>", raw, re.I):
        attrs = m.group(2) or ""
        if re.search(r"type=[\"'](hidden|submit|button)[\"']", attrs, re.I):
            continue
        ident = re.search(r"\bid=[\"']([^\"']+)[\"']", attrs)
        if re.search(r"aria-label(?:ledby)?=", attrs, re.I):
            continue
        if ident and re.search(rf"<label[^>]+for=[\"']{re.escape(ident.group(1))}[\"']", raw, re.I):
            continue
        # wrapped by a label: the nearest preceding <label ...> is unclosed
        before = raw[max(0, m.start() - 400):m.start()]
        if re.search(r"<label\b[^>]*>(?:(?!</label>).)*$", before, re.I | re.S):
            continue
        return False
    return True


# ── Mechanical repair ─────────────────────────────────────────────────────

def _ensure_css(raw: str, marker: str, css: str) -> str:
    if marker in raw:
        return raw
    block = f"<style>{css}</style>"
    if "</head>" in raw.lower():
        i = raw.lower().rindex("</head>")
        return raw[:i] + block + raw[i:]
    return raw + block


def _ensure_doctype(raw: str) -> str:
    if re.search(r"<!doctype", raw, re.I):
        return raw
    return "<!DOCTYPE html>\n" + raw


def _ensure_viewport(raw: str) -> str:
    if re.search(r"<meta[^>]+name=[\"']viewport[\"']", raw, re.I):
        return raw
    tag = '<meta name="viewport" content="width=device-width, initial-scale=1">'
    if re.search(r"<head[^>]*>", raw, re.I):
        i = re.search(r"<head[^>]*>", raw, re.I).end()
        return raw[:i] + "\n" + tag + raw[i:]
    if "<html" in raw.lower():
        i = re.search(r"<html[^>]*>", raw, re.I).end()
        return raw[:i] + f"\n<head>{tag}</head>" + raw[i:]
    return f"<head>{tag}</head>\n" + raw


def _ensure_title(raw: str, brand: str = "") -> str:
    if re.search(r"<title>\s*\S", raw, re.I):
        return raw
    title = brand or "Untitled page"
    tag = f"<title>{title}</title>"
    if re.search(r"<title>\s*</title>", raw, re.I):
        return re.sub(r"<title>\s*</title>", tag, raw, count=1, flags=re.I)
    if re.search(r"<head[^>]*>", raw, re.I):
        return re.sub(r"(<head[^>]*>)", r"\1\n" + tag, raw, count=1, flags=re.I)
    return tag + raw


def _ensure_footer(raw: str, brand: str = "") -> str:
    if re.search(r"<footer", raw, re.I):
        return raw
    name = brand or "Crown Code"
    footer = (f'<footer style="padding:2rem 1.25rem;text-align:center;'
              f'border-top:1px solid rgba(255,255,255,.12);font-size:.85rem">'
              f'<p>© <span class="year">{name}</span> · Built with Crown Code</p></footer>')
    if "</body>" in raw.lower():
        i = raw.lower().rindex("</body>")
        return raw[:i] + footer + raw[i:]
    return raw + footer


def _ensure_buttons(raw: str, brand: str = "") -> str:
    if re.search(r"<button", raw, re.I):
        return raw
    cta = ('<button type="button" id="crown-cta" '
           'style="padding:.75rem 1.25rem;border-radius:.5rem;cursor:pointer">'
           f'Get in touch</button>')
    if "</body>" in raw.lower():
        i = raw.lower().rindex("</body>")
        return raw[:i] + f'<div style="padding:1rem">{cta}</div>' + raw[i:]
    return raw + cta


def _balance(raw: str) -> str:
    """Close a truncated file: model output often stops mid-tag."""
    low = raw.lower()
    for tag in ("style", "script"):
        if raw.lower().count(f"<{tag}") > raw.lower().count(f"</{tag}>"):
            raw += f"\n</{tag}>"
    if "</body>" not in raw.lower() and "<body" in raw.lower():
        raw += "\n</body>"
    if "</html>" not in raw.lower():
        raw += "\n</html>"
    return raw


def repair_html(path: Path | str, kind: str = "website",
                brand: str = "") -> list[str]:
    """Apply deterministic fixes for mechanical problems. Returns what it did."""
    path = Path(path)
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8", errors="replace")
    before = raw
    done: list[str] = []

    def step(label: str, fn, *a):
        nonlocal raw
        out = fn(raw, *a)
        if out != raw:
            raw = out
            done.append(label)

    step("closed truncated markup", _balance)
    step("added <!doctype html>", _ensure_doctype)
    step("added viewport meta", _ensure_viewport)
    step("added page-level base CSS (box-sizing, focus, reduced motion)", _ensure_css,
         "crown-base:", _BASE_CSS)
    if not re.search(r"<title>\s*\S", raw, re.I):
        step("added <title>", _ensure_title, brand)
    if kind in ("website", "portfolio"):
        step("added <footer>", _ensure_footer, brand)
        step("added a <button>", _ensure_buttons, brand)

    if raw != before:
        path.write_text(raw, encoding="utf-8")
    return done


# ── Acceptance checklist ──────────────────────────────────────────────────

def acceptance_checklist(html: str, kind: str = "website", plan: dict | None = None) -> list[dict]:
    """Turn the approved plan into the checklist the finished page is judged on.

    The same idea as the agent task lists in Claude Code / Cline Plan mode: the
    work is written down before it starts and each line is verified afterwards,
    so "done" means the plan's promises were checked, not just that a file
    exists.
    """
    low = html.lower()
    items: list[dict] = []

    def add(label: str, ok: bool) -> None:
        items.append({"item": label, "ok": bool(ok)})

    visible = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    visible = re.sub(r"<[^>]+>", " ", visible)

    add("document structure (doctype, html, head, body)",
        "<!doctype" in low and "<html" in low and "<head" in low and "<body" in low)
    add("viewport meta so the page scales on a phone", 'name="viewport"' in low)
    add("single h1 with section headings", low.count("<h1") == 1 and low.count("<h2") >= 2)
    add("footer", "<footer" in low)
    add("real <button> controls", "<button" in low)
    add("visible :focus-visible styles", ":focus-visible" in low)
    add("responsive layout rules (box-sizing, media query)",
        "box-sizing" in low and "@media" in low)
    add("no external assets (works offline)",
        not re.search(r"(?:src|href)=[\"']https?://", html, re.I))
    add("no placeholder copy", not PLACEHOLDER_TEXT.search(visible))
    add("javascript interactions", "<script" in low and "addeventlistener" in low)
    add("motion design (transitions/keyframes) with reduced-motion support",
        ("@keyframes" in low or "transition:" in low or "requestanimationframe" in low)
        and "prefers-reduced-motion" in low)

    for section in (plan or {}).get("sections", []):
        sid = str(section.get("id") or "").strip()
        heading = str(section.get("heading") or sid)
        if sid:
            add(f"section: {heading}", f'id="{sid}"' in html or f"id='{sid}'" in html)
        n = len(section.get("items") or [])
        kind_s = str(section.get("kind") or "")
        if n and kind_s in ("projects", "cards", "gallery"):
            rendered = len(re.findall(r'<(?:article|figure)\b', html, re.I))
            add(f"{heading}: {n} items rendered", rendered >= n)
        if kind_s == "faq":
            add("FAQ accordion", "<details" in low and "<summary" in low)
        if kind_s == "contact":
            add("contact form with validation", "<form" in low and "required" in low)
            add("form status announced (aria-live)", "aria-live" in low)
    return items


def checklist_summary(items: list[dict]) -> tuple[int, int, list[str]]:
    """(passed, total, failing labels) for a checklist."""
    fails = [i["item"] for i in items if not i["ok"]]
    return len(items) - len(fails), len(items), fails


# ── Optional browser audit ────────────────────────────────────────────────

#: A build must never wait forever on a browser. Chromium launch has been seen
#: to wedge — usually behind a driver leaked by an earlier audit that raised
#: before closing it — so the whole check runs under a deadline and reports
#: itself *skipped* when it overruns. Skipped is never a pass.
BROWSER_AUDIT_TIMEOUT = 45.0


def browser_audit(path: Path | str, widths: tuple[int, ...] = (375, 1280),
                  timeout: float = BROWSER_AUDIT_TIMEOUT) -> dict:
    """Load the page in headless Chromium and report real defects.

    Returns {"status": "ok"|"failed"|"skipped", "problems": [...], "details": {...}}.
    A skipped audit is never reported as a pass by callers, and an audit that
    overruns its deadline is skipped rather than allowed to hang the caller.
    """
    path = Path(path).resolve()
    box: dict = {}

    def _run() -> None:
        try:
            box["audit"] = _browser_audit_once(path, widths)
        except BaseException as exc:             # reported, never raised here
            box["error"] = exc

    worker = threading.Thread(target=_run, name="browser-audit", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return {"status": "skipped", "problems": [],
                "details": {"reason": f"browser audit exceeded {int(timeout)}s"}}
    if "error" in box:
        return {"status": "skipped", "problems": [],
                "details": {"reason": f"browser launch failed: {box['error']}"}}
    return box.get("audit") or {"status": "skipped", "problems": [],
                                 "details": {"reason": "browser audit returned nothing"}}


def _browser_audit_once(path: Path, widths: tuple[int, ...]) -> dict:
    """One Chromium pass. Closes the browser on every path, including errors."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:                      # pragma: no cover - env dependent
        return {"status": "skipped", "problems": [], "details": {"reason": f"playwright unavailable: {e}"}}

    problems: list[str] = []
    console: list[str] = []
    page_errors: list[str] = []
    overflow: dict[int, int] = {}
    has_focus = True
    dead: list = []
    title = ""
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, timeout=20_000)
            try:
                ctx = browser.new_context(viewport={"width": widths[0], "height": 900})
                page = ctx.new_page()
                page.on("console", lambda m: console.append(f"{m.type}: {m.text}") if m.type == "error" else None)
                page.on("pageerror", lambda e: page_errors.append(str(e)))
                page.goto(path.as_uri(), wait_until="load", timeout=20_000)
                for w in widths:
                    page.set_viewport_size({"width": w, "height": 900})
                    overflow[w] = page.evaluate(
                        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
                has_focus = page.evaluate(
                    "() => [...document.styleSheets].some(s => {try {return [...s.cssRules]"
                    ".some(r => (r.selectorText||'').includes('focus'))} catch {return false}})")
                dead = page.evaluate("""() => [...document.querySelectorAll('a[href^="#"]')]
                    .map(a => a.getAttribute('href'))
                    .filter(h => h && h.length > 1 && !document.querySelector(h))""")
                title = page.title().strip()
            finally:
                # Leaking a browser here is what makes the *next* audit hang.
                try:
                    browser.close()
                except Exception:
                    pass
    except Exception as e:                      # pragma: no cover - env dependent
        return {"status": "skipped", "problems": [], "details": {"reason": f"browser launch failed: {e}"}}

    for w, px in overflow.items():
        if px > 1:
            problems.append(f"horizontal overflow at {w}px ({px}px)")
    if console:
        problems.append(f"{len(console)} console error(s): {console[:2]}")
    if page_errors:
        problems.append(f"uncaught page error: {page_errors[:2]}")
    if not has_focus:
        problems.append("no focus styles reachable at runtime")
    if dead:
        problems.append(f"anchor(s) point at missing ids: {dead[:3]}")
    if not title:
        problems.append("empty document title")
    return {"status": "failed" if problems else "ok", "problems": problems,
            "details": {"console": console[:5], "page_errors": page_errors[:5],
                        "overflow": {str(k): v for k, v in overflow.items()}}}
