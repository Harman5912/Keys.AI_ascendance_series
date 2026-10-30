"""scripts/build_site_showcase.py — build the ten-studio showcase.

Renders every curated site through core.site_studio, verifies each one with the
same static checks the live pipeline uses, audits it in Chromium (console
errors, overflow at 375/1280, dead anchors), captures a screenshot for the
gallery and writes crown_sites/showcase/index.html.

Usage:
  python scripts/build_site_showcase.py            # build + audit + screenshots
  python scripts/build_site_showcase.py --static   # no browser (fast, offline)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.site_checks import browser_audit, check_html  # noqa: E402
from core.site_studio import SAMPLE_SITES, render_gallery, render_site  # noqa: E402

OUT = BASE / "crown_sites" / "showcase"
SHOTS = OUT / "_shots"
REPORT = BASE / "qa_artifacts" / "reports" / "site_showcase.json"


def capture(path: Path, dest: Path) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900},
                                    device_scale_factor=1)
            page.goto(path.resolve().as_uri(), wait_until="load")
            page.wait_for_timeout(900)
            dest.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(dest), full_page=False, type="jpeg", quality=82)
            browser.close()
        return True
    except Exception as exc:
        print(f"    screenshot failed: {exc}")
        return False


def interaction_audit(path: Path) -> dict:
    """Click the real controls and confirm they do something visible."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {"status": "skipped", "reason": "playwright unavailable"}
    report: dict = {"status": "ok", "checks": [], "problems": []}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(path.resolve().as_uri(), wait_until="load")
            page.wait_for_timeout(350)

            def check(name: str, ok: bool, detail: str = "") -> None:
                report["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
                if not ok:
                    report["problems"].append(name + (f": {detail}" if detail else ""))

            # nav toggle at phone width
            page.set_viewport_size({"width": 390, "height": 844})
            toggle = page.query_selector(".nav-toggle")
            if toggle and toggle.is_visible():
                before = page.eval_on_selector("#site-nav", "el => getComputedStyle(el).display")
                toggle.click()
                page.wait_for_timeout(120)
                after = page.eval_on_selector("#site-nav", "el => getComputedStyle(el).display")
                check("mobile nav opens", after != "none" and after != before, f"{before} -> {after}")
                toggle.click()
            page.set_viewport_size({"width": 1280, "height": 900})

            # filter buttons (if any)
            filt = page.query_selector(".filter[data-filter]")
            if filt:
                cards = page.query_selector_all("[data-tags]")
                if len(cards) > 1:
                    total = len(cards)
                    labels = [c.get_attribute("data-filter") for c in page.query_selector_all(".filter")]
                    target = next((l for l in labels if l != "all"), None)
                    if target:
                        page.click(f'.filter[data-filter="{target}"]')
                        page.wait_for_timeout(100)
                        hidden = page.eval_on_selector_all("[data-tags]", "els => els.filter(e => e.hidden).length")
                        check("category filter hides cards", hidden > 0, f"{hidden}/{total} hidden")

            # form validation + success (both must happen)
            if page.query_selector("form[data-contact]"):
                page.eval_on_selector("form[data-contact]", "f => f.scrollIntoView({block:'center'})")
                page.click("form[data-contact] button[type=submit]")
                page.wait_for_timeout(80)
                empty = page.eval_on_selector("[data-form-status]", "e => e.textContent.trim()")
                check("empty form is rejected", bool(empty), empty[:60])
                for name, value in (("name", "Test Reader"), ("email", "test@example.com"),
                                    ("message", "A real message")):
                    if page.query_selector(f'[name="{name}"]'):
                        page.fill(f'[name="{name}"]', value)
                # other required text fields (address, dates, etc.)
                for sel in page.query_selector_all("form[data-contact] input[required], form[data-contact] textarea[required]"):
                    if not sel.input_value():
                        sel.fill("Test value")
                page.click("form[data-contact] button[type=submit]")
                page.wait_for_timeout(100)
                done = page.eval_on_selector("[data-form-status]", "e => e.textContent.trim()")
                check("valid form confirms", "Thanks" in done, done[:80])

            # counters actually animate to their final value
            counter = page.query_selector("[data-count]")
            if counter:
                raw = counter.get_attribute("data-count") or ""
                text = counter.inner_text()
                check("counter renders a value", bool(text.strip()), f"{raw} -> {text}")

            # plot exists for the newsroom
            if page.query_selector(".spark"):
                pts = page.eval_on_selector(".spark polyline", "el => el.getAttribute('points')")
                check("sparkline has geometry", bool(pts and len(pts.split()) > 3), str(pts)[:40])

            # filmstrip scrolls
            strip = page.query_selector("[data-drag]")
            if strip:
                before = page.eval_on_selector("[data-drag]", "el => el.scrollLeft")
                page.eval_on_selector("[data-drag]", "el => el.scrollLeft = 240")
                after = page.eval_on_selector("[data-drag]", "el => el.scrollLeft")
                check("filmstrip scrolls", after > before, f"{before} -> {after}")

            # add-to-cart
            add = page.query_selector("[data-add]")
            if add and page.query_selector("[data-cart]"):
                page.eval_on_selector("[data-add]", "b => b.scrollIntoView({block:'center'})")
                before = page.eval_on_selector("[data-cart]", "e => e.textContent")
                add.click()
                page.wait_for_timeout(80)
                after = page.eval_on_selector("[data-cart]", "e => e.textContent")
                check("add-to-cart increments", int(after) == int(before) + 1, f"{before} -> {after}")

            check("no page errors", not errors, "; ".join(errors[:2]))
            browser.close()
    except Exception as exc:
        report["status"] = "failed"
        report["problems"].append(f"interaction audit crashed: {type(exc).__name__}: {exc}")
    if report["problems"]:
        report["status"] = "failed"
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--static", action="store_true", help="skip Chromium audit and screenshots")
    ap.add_argument("--only", default="", help="comma-separated site ids, e.g. 01,04")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)

    sites = SAMPLE_SITES
    if args.only:
        want = {s.strip() for s in args.only.split(",")}
        sites = [s for s in sites if str(s.get("id")) in want]

    results = []
    links: dict[str, str] = {}
    shots: dict[str, str] = {}
    all_ok = True

    print(f"Building {len(sites)} studio sites into {OUT}")
    for site in sites:
        sid = str(site["id"])
        folder = OUT / site["folder"]
        folder.mkdir(parents=True, exist_ok=True)
        index = folder / "index.html"
        t0 = time.time()
        html = render_site(site, site["studio"])
        index.write_text(html, encoding="utf-8")

        ok, problems = check_html(index, "website")
        audit = {"status": "skipped", "problems": [], "details": {}}
        interactions = {"status": "skipped", "checks": [], "problems": []}
        shot = ""
        if not args.static:
            audit = browser_audit(index)
            interactions = interaction_audit(index)
            dest = SHOTS / f"{site['folder']}.jpg"
            if capture(index, dest):
                shot = f"_shots/{dest.name}"
                shots[sid] = shot
            if audit.get("status") == "failed":
                ok = False
                problems = problems + audit.get("problems", [])
            if interactions.get("status") == "failed":
                ok = False
                problems = problems + interactions.get("problems", [])

        rec = {
            "id": sid, "brand": site["brand"], "studio": site["studio"],
            "folder": site["folder"], "bytes": len(html.encode("utf-8")),
            "lines": html.count("\n") + 1, "seconds": round(time.time() - t0, 2),
            "ok": ok, "problems": problems[:8],
            "browser": audit.get("status", "not run"),
            "overflow": (audit.get("details") or {}).get("overflow", {}),
            "interactions": interactions.get("checks", []),
            "screenshot": shot,
        }
        results.append(rec)
        links[sid] = f"{site['folder']}/index.html"
        all_ok = all_ok and ok
        mark = "PASS" if ok else "FAIL"
        print(f"[{sid}] {mark:4} {rec['bytes']:>6} bytes  {rec['seconds']:>5}s  "
              f"{site['brand']} · {site['studio']}  {audit.get('status')}  {problems[:2]}")

    gallery = render_gallery(SAMPLE_SITES, links, shots)
    (OUT / "index.html").write_text(gallery, encoding="utf-8")

    readme = ["# Crown Code Studio — 10 sites, 10 design systems", "",
              "Each folder is a complete, self-contained site. No external fonts,",
              "images or scripts; no shared template. Open `index.html` for the gallery.", ""]
    for r in results:
        readme.append(f"- `{r['folder']}/index.html` — {r['brand']} · {r['studio']} studio · "
                      f"{r['bytes']} bytes · {'PASS' if r['ok'] else 'FAIL'}")
    (OUT / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "all_ok": all_ok, "sites": results,
        "gallery": str((OUT / "index.html").relative_to(BASE)).replace("\\", "/"),
    }
    REPORT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    distinct = len({(r["studio"], r["bytes"]) for r in results})
    print(f"\n{sum(1 for r in results if r['ok'])}/{len(results)} sites passed · "
          f"{distinct} distinct studio/byte signatures · gallery: {OUT / 'index.html'}")
    print(f"report: {REPORT}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
