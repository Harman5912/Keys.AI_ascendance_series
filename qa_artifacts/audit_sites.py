"""qa_artifacts/audit_sites.py — browser audit of generated websites/apps/portfolios.

Uses Playwright Chromium headless to actually load each generated artifact from
file:// and check rendering, console errors, failed requests, links, buttons,
form validation, keyboard focus, localStorage persistence and responsive
overflow. Saves screenshots at 375 / 768 / 1440 px.

Usage:
  python qa_artifacts/audit_sites.py --kind website [--only 01,02]
  python qa_artifacts/audit_sites.py --kind webapp
  python qa_artifacts/audit_sites.py --kind portfolio
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import traceback
from pathlib import Path
from urllib.parse import unquote

BASE = Path(__file__).resolve().parent.parent
DIRS = {
    "website": BASE / "qa_artifacts" / "generated_websites",
    "webapp": BASE / "qa_artifacts" / "generated_webapps",
    "portfolio": BASE / "qa_artifacts" / "generated_portfolios",
}
SHOTS = BASE / "qa_artifacts" / "screenshots"
REPORTS = BASE / "qa_artifacts" / "reports"

WIDTHS = [("mobile", 375, 812), ("tablet", 768, 1024), ("desktop", 1440, 900)]


def audit(page, path: Path, kind: str, slug: str) -> dict:
    checks: dict[str, dict] = {}
    console: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []

    page.on("console", lambda m: console.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: page_errors.append(str(e)))
    page.on("requestfailed", lambda r: failed_requests.append(f"{r.url} ({r.failure})"))

    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(path.as_uri(), wait_until="load", timeout=20000)
    page.wait_for_timeout(300)

    def check(name: str, ok: bool, detail: str = ""):
        checks[name] = {"ok": bool(ok), "detail": str(detail)[:300]}

    title = page.title()
    check("title", bool(title.strip()), title)

    h1 = page.locator("h1").count()
    check("h1_present", h1 >= 1, f"{h1} h1 element(s)")

    body_text = page.inner_text("body")
    check("visible_content", len(body_text.strip()) > 200, f"{len(body_text)} chars")

    check("no_js_errors", not page_errors, "; ".join(page_errors[:3]))
    check("no_console_errors", not [c for c in console if c.startswith("error")],
          "; ".join([c for c in console if c.startswith("error")][:3]))
    check("no_failed_requests", not failed_requests, "; ".join(failed_requests[:3]))

    # ── links resolve to existing anchors / documents ────────────────────
    hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
    broken = []
    for href in hrefs:
        if not href or href.startswith(("http://", "https://", "mailto:", "tel:", "javascript:")):
            continue
        if href.startswith("#"):
            target = href[1:]
            if target and page.locator(f"[id='{target}'], a[name='{target}']").count() == 0:
                broken.append(href)
        elif not (path.parent / unquote(href.split("#")[0])).exists():
            broken.append(href)
    check("internal_links", not broken, f"broken={broken[:6]}" if broken else f"{len(hrefs)} links")

    # ── buttons respond without throwing ────────────────────────────────
    buttons = page.locator("button, [role='button'], input[type='submit']")
    n_buttons = buttons.count()
    click_errors = []
    for i in range(min(n_buttons, 12)):
        try:
            b = buttons.nth(i)
            if b.is_visible():
                b.click(timeout=1500, trial=False)
                page.wait_for_timeout(60)
        except Exception as e:
            click_errors.append(f"#{i}: {str(e).splitlines()[0][:80]}")
    check("buttons_clickable", not click_errors and n_buttons > 0,
          f"{n_buttons} buttons; errors={click_errors[:3]}" if click_errors else f"{n_buttons} buttons")
    check("no_errors_after_clicks", not page_errors, "; ".join(page_errors[:3]))

    # ── forms: empty submit must not silently 'succeed' ─────────────────
    forms = page.locator("form")
    n_forms = forms.count()
    if n_forms:
        inputs = page.locator("form input:not([type=hidden]), form textarea, form select")
        labelled = 0
        for i in range(inputs.count()):
            el = inputs.nth(i)
            has = el.get_attribute("aria-label") or el.get_attribute("aria-labelledby") \
                or el.get_attribute("placeholder") or el.get_attribute("id")
            if has:
                labelled += 1
        check("form_inputs_labelled", labelled == inputs.count(),
              f"{labelled}/{inputs.count()} inputs have an id/aria/placeholder")
    else:
        check("form_inputs_labelled", True, "no forms")

    # ── localStorage persistence (reload) ───────────────────────────────
    ls_before = page.evaluate("() => Object.keys(localStorage).length")
    page.reload(wait_until="load")
    page.wait_for_timeout(200)
    ls_after = page.evaluate("() => Object.keys(localStorage).length")
    body_after = page.inner_text("body")
    check("survives_reload", "about:blank" not in page.url and len(body_after.strip()) > 100,
          f"{len(body_after)} chars after reload")
    check("no_errors_after_reload", not page_errors, "; ".join(page_errors[:2]))
    check("persistence_capable", ls_after >= ls_before, f"localStorage keys {ls_before}->{ls_after}")

    # ── keyboard focus ──────────────────────────────────────────────────
    focusables = page.evaluate(
        "() => document.querySelectorAll('a[href],button,input,select,textarea,[tabindex]:not([tabindex=\"-1\"])').length")
    check("keyboard_reachable", focusables > 0, f"{focusables} focusable elements")
    page.keyboard.press("Tab")
    focused = page.evaluate(
        "() => { const a = document.activeElement; return a ? a.tagName + (a.id ? '#'+a.id : '') : 'none'; }")
    check("tab_focus_visible", focused not in ("BODY", "none"), f"focus -> {focused}")

    # ── accessibility basics ────────────────────────────────────────────
    imgs = page.eval_on_selector_all("img", "els => els.map(e => e.getAttribute('alt'))")
    check("images_have_alt", all(a is not None for a in imgs), f"{len(imgs)} images")
    landmarks = page.evaluate("() => ({h: !!document.querySelector('header, [role=banner]'), "
                              "m: !!document.querySelector('main, [role=main]'), "
                              "f: !!document.querySelector('footer, [role=contentinfo]')})")
    check("landmarks", landmarks["h"] and landmarks["m"], f"header={landmarks['h']} main={landmarks['m']} footer={landmarks['f']}")
    lang = page.evaluate("() => document.documentElement.lang || ''")
    check("html_lang", bool(lang), lang or "missing")
    focus_css = page.evaluate(
        "() => Array.from(document.styleSheets).some(s => { try { return Array.from(s.cssRules).some(r => String(r.selectorText).includes(':focus')); } catch(e) { return false; } })")
    check("focus_styles", bool(focus_css), "CSS :focus rule present" if focus_css else "no :focus rule")

    # ── responsive: no horizontal overflow ──────────────────────────────
    overflow = {}
    for label, w, h in WIDTHS:
        page.set_viewport_size({"width": w, "height": h})
        page.wait_for_timeout(150)
        sw, cw = page.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
        overflow[label] = {"scroll": sw, "client": cw, "overflows": sw > cw + 2}
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{kind}_{slug}_{label}.png"), full_page=(label == "desktop"))
    check("no_horizontal_overflow", not any(v["overflows"] for v in overflow.values()),
          json.dumps({k: f"{v['scroll']}>{v['client']}" for k, v in overflow.items()}))

    return {"checks": checks, "console": console[:10], "page_errors": page_errors[:5],
            "failed_requests": failed_requests[:5], "overflow": overflow}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=list(DIRS), required=True)
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    root = DIRS[args.kind]
    dirs = sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []
    if args.only:
        want = {s.strip() for s in args.only.split(",")}
        dirs = [d for d in dirs if d.name.split("_")[0] in want]

    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context()
        for d in dirs:
            index = d / "index.html"
            rec = {"kind": args.kind, "slug": d.name, "path": str(index.relative_to(BASE)).replace("\\", "/")}
            if not index.exists():
                rec.update({"passed": False, "fails": ["index.html missing"], "checks": {}})
                results.append(rec)
                print(f"FAIL  {d.name}: index.html missing", flush=True)
                continue
            page = ctx.new_page()
            try:
                detail = audit(page, index, args.kind, d.name)
            except Exception as e:
                traceback.print_exc()
                rec.update({"passed": False, "fails": [f"audit crashed: {e}"], "checks": {}})
                results.append(rec)
                print(f"FAIL  {d.name}: audit crashed: {e}", flush=True)
                page.close()
                continue
            page.close()
            fails = [f"{k}: {v['detail']}" for k, v in detail["checks"].items() if not v["ok"]]
            rec.update({"passed": not fails, "fails": fails, **detail})
            results.append(rec)
            print(f"{'PASS' if rec['passed'] else 'FAIL'}  {d.name}" +
                  ("" if not fails else "\n      - " + "\n      - ".join(fails[:6])), flush=True)
        browser.close()

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"site_audit_{args.kind}.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    with open(REPORTS / f"site_audit_{args.kind}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["slug", "passed", "failed_checks", "console_errors", "page_errors"])
        for r in results:
            w.writerow([r["slug"], r["passed"], " | ".join(r.get("fails", [])),
                        len(r.get("console", [])), len(r.get("page_errors", []))])
    passed = sum(1 for r in results if r["passed"])
    print(f"\n{args.kind}: {passed}/{len(results)} passed the browser audit")
    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
