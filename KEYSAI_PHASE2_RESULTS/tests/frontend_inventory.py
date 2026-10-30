"""End-to-end browser test of the inventory front end.

Starts the real Flask server on a free port against a temporary database, seeds
it with the specified dataset, then drives the page in Chromium: dashboard
figures, product list, search, add, invalid-input feedback, edit, delete, stock
movement — and fails on any console error.

Run:  python KEYSAI_PHASE2_RESULTS/tests/frontend_inventory.py
Out:  KEYSAI_PHASE2_RESULTS/logs/frontend_inventory.json
      KEYSAI_PHASE2_RESULTS/screenshots/inventory_dashboard.png
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
OUT = BASE / "KEYSAI_PHASE2_RESULTS"
PROJECT = OUT / "projects" / "inventory_system"
REPORT = OUT / "logs" / "frontend_inventory.json"
SHOT = OUT / "screenshots" / "inventory_dashboard.png"
PY = sys.executable


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_ready(base: str, seconds: float = 30) -> bool:
    started = time.time()
    while time.time() - started < seconds:
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def main() -> int:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": str(detail)[:600]})
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))

    tmp = tempfile.TemporaryDirectory()
    db = Path(tmp.name) / "frontend.db"
    env = dict(os.environ, INVENTORY_DB=str(db), PYTHONIOENCODING="utf-8")
    env["PYTHONPATH"] = str(PROJECT)

    seed = subprocess.run([PY, "seed.py"], cwd=PROJECT, env=env,
                          capture_output=True, text=True, timeout=120)
    check("seed.py exits 0", seed.returncode == 0, seed.stderr[-300:])

    port = free_port()
    env["PORT"] = str(port)
    server = subprocess.Popen([PY, "app.py"], cwd=PROJECT, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True)
    base = f"http://127.0.0.1:{port}"
    try:
        ready = wait_ready(base)
        check("server answers /api/health", ready)
        if not ready:
            return 1

        from playwright.sync_api import sync_playwright

        console_errors: list[str] = []
        expected_errors: list[str] = []
        # One test deliberately submits invalid input, which correctly produces
        # a 400 and therefore a browser console entry. That entry is evidence
        # the error path works, not a defect, so it is collected separately.
        expecting_failure = {"on": False}

        def on_console(message):
            if message.type != "error":
                return
            target = expected_errors if expecting_failure["on"] else console_errors
            target.append(message.text)

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 1100})
            page.on("console", on_console)
            page.on("pageerror", lambda e: (expected_errors
                                            if expecting_failure["on"]
                                            else console_errors).append(str(e)))
            page.on("dialog", lambda d: d.accept())
            page.goto(base, wait_until="networkidle")
            page.wait_for_selector("#products tbody tr")

            # ── dashboard ────────────────────────────────────────────────
            check("KPI total value is 54,200.00",
                  page.inner_text("#kpi-value").strip() == "54,200.00",
                  page.inner_text("#kpi-value"))
            check("KPI product count is 5",
                  page.inner_text("#kpi-products").strip() == "5",
                  page.inner_text("#kpi-products"))
            check("KPI low-stock count is 2",
                  page.inner_text("#kpi-low").strip() == "2",
                  page.inner_text("#kpi-low"))

            rows = page.locator("#products tbody tr")
            check("table shows 5 products", rows.count() == 5, str(rows.count()))
            check("2 rows flagged low stock",
                  page.locator("#products tbody tr.low").count() == 2,
                  str(page.locator("#products tbody tr.low").count()))
            body_text = page.inner_text("#products tbody")
            check("Mouse and Laptop Stand are the low-stock rows",
                  "Mouse" in body_text and "Laptop Stand" in body_text)

            # ── search ───────────────────────────────────────────────────
            page.fill("#search", "Mouse")
            page.wait_for_function(
                "document.querySelectorAll('#products tbody tr').length === 1")
            check("search narrows to one row",
                  page.locator("#products tbody tr").count() == 1)
            page.click("#reset-filters")
            page.wait_for_function(
                "document.querySelectorAll('#products tbody tr').length === 5")

            # ── category filter ──────────────────────────────────────────
            page.select_option("#category", "Displays")
            page.wait_for_function(
                "document.querySelectorAll('#products tbody tr').length === 1")
            check("category filter shows only Monitor",
                  "Monitor" in page.inner_text("#products tbody"))
            page.click("#reset-filters")
            page.wait_for_function(
                "document.querySelectorAll('#products tbody tr').length === 5")

            # ── invalid input ────────────────────────────────────────────
            expecting_failure["on"] = True
            page.fill("#f-name", "")
            page.fill("#f-category", "Test")
            page.fill("#f-price", "")
            page.click("#save")
            page.wait_for_selector("#form-error", state="visible")
            expecting_failure["on"] = False
            check("invalid form shows a field error",
                  "name" in page.inner_text("#form-error").lower()
                  or "unit_price" in page.inner_text("#form-error").lower(),
                  page.inner_text("#form-error"))

            # ── add ──────────────────────────────────────────────────────
            page.fill("#f-name", "Webcam")
            page.fill("#f-category", "Accessories")
            page.fill("#f-quantity", "3")
            page.fill("#f-price", "450")
            page.fill("#f-reorder", "1")
            page.click("#save")
            page.wait_for_function(
                "document.querySelectorAll('#products tbody tr').length === 6")
            check("add product appears in the table",
                  "Webcam" in page.inner_text("#products tbody"))
            check("KPI total updated to 55,550.00",
                  page.inner_text("#kpi-value").strip() == "55,550.00",
                  page.inner_text("#kpi-value"))

            # ── edit ─────────────────────────────────────────────────────
            webcam_row = page.locator("#products tbody tr",
                                      has_text="Webcam").first
            webcam_row.locator("button", has_text="Edit").click()
            page.fill("#f-quantity", "1")
            page.click("#save")
            page.wait_for_function(
                "document.querySelector('#kpi-low').textContent === '3'")
            check("edit changes the quantity and the low-stock count",
                  page.inner_text("#kpi-low").strip() == "3",
                  page.inner_text("#kpi-low"))

            # ── movement ─────────────────────────────────────────────────
            page.select_option("#m-product", label="Webcam (1)")
            page.fill("#m-change", "5")
            page.fill("#m-reason", "delivery")
            page.click("#record-movement")
            # The list shows a placeholder <li> until a movement exists, so the
            # wait must be on the recorded reason, not on element count.
            page.wait_for_function(
                "document.querySelector('#movements').innerText.includes('delivery')",
                timeout=15000)
            check("movement is recorded and listed",
                  "delivery" in page.inner_text("#movements"),
                  page.inner_text("#banner"))
            check("movement updated the product quantity",
                  "Webcam (6)" in page.inner_text("#m-product"),
                  page.inner_text("#m-product"))

            # ── delete ───────────────────────────────────────────────────
            page.locator("#products tbody tr", has_text="Webcam").first \
                .locator("button", has_text="Delete").click()
            page.wait_for_function(
                "document.querySelectorAll('#products tbody tr').length === 5")
            check("delete removes the row",
                  "Webcam" not in page.inner_text("#products tbody"))

            page.screenshot(path=str(SHOT), full_page=True)
            browser.close()

        check("no unexpected console errors", not console_errors,
              "; ".join(console_errors[:3]))
        check("the intentional bad request produced a handled error",
              bool(expected_errors), "; ".join(expected_errors[:2]))
    finally:
        try:
            server.terminate()
            server.wait(timeout=10)
        except Exception:
            try:
                server.kill()
            except Exception:
                pass
        tmp.cleanup()

    passed = sum(1 for c in checks if c["ok"])
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "checks": checks,
        "passed": passed,
        "total": len(checks),
        "screenshot": str(SHOT) if SHOT.exists() else "",
    }, indent=2), encoding="utf-8")
    print(f"\n{passed}/{len(checks)} frontend checks passed")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
