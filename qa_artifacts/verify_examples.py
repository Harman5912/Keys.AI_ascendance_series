"""Verify every example build and write a report.

For each generated page: the deterministic checks, the real Chromium audit, the
studio that rendered it, and a hash — two pages with the same hash would not be
"different sites". For the runnable examples: import/py_compile plus their own
selftests.

    python qa_artifacts/verify_examples.py
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

GEN = BASE / "examples" / "generated" / "sites"
REPORT = BASE / "qa_artifacts" / "reports" / "example_build_verification.json"

PAGES = [
    ("01_portfolio_riya_dev", "portfolio"),
    ("02_portfolio_atelier_nord", "portfolio"),
    ("03_portfolio_maya_photo", "portfolio"),
    ("04_marketing_verdant", "website"),
    ("05_marketing_rocketpay", "website"),
]


def page_report(slug: str, kind: str) -> dict:
    from core.site_checks import browser_audit, check_html

    index = GEN / slug / "index.html"
    if not index.exists():
        return {"slug": slug, "exists": False}
    html = index.read_text(encoding="utf-8", errors="replace")
    ok, problems = check_html(index, kind)
    audit = browser_audit(index) if ok else {"status": "skipped"}
    generator = re.search(r'name="generator" content="([^"]+)"', html)
    return {
        "slug": slug,
        "exists": True,
        "ok": ok,
        "problems": problems,
        "browser": audit.get("status", "not run"),
        "browser_problems": audit.get("problems", []),
        "studio": generator.group(1) if generator else "",
        "bytes": index.stat().st_size,
        "sha256": hashlib.sha256(html.encode("utf-8")).hexdigest()[:16],
        "has_charts_or_api": bool(re.search(r"<canvas|<svg|fetch\(", html)),
    }


def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, timeout=180)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def main() -> int:
    report = {"pages": [page_report(slug, kind) for slug, kind in PAGES], "examples": []}

    checks = [
        ("dashboard_flask", [sys.executable, "-c",
                             "import app, db; db.seed(); c=app.app.test_client();"
                             "assert c.get('/api/kpis').status_code==200;"
                             "assert c.get('/api/series?symbol=BTC').status_code==200;"
                             "print('api ok', db.backend_name())"],
         BASE / "examples" / "web" / "01_market_pulse_dashboard"),
        ("dashboard_marketing_flask", [sys.executable, "-c",
                                       "import app, db; db.seed(); c=app.app.test_client();"
                                       "assert c.get('/api/overview').status_code==200;"
                                       "assert c.get('/api/tasks').status_code==200;"
                                       "print('api ok', db.backend_name())"],
         BASE / "examples" / "web" / "05_campaign_command_dashboard"),
        ("dashboard_node", ["node", "--check", "server.js"],
         BASE / "examples" / "web" / "02_ops_hive_dashboard"),
        ("dashboard_node_bi", ["node", "--check", "server.js"],
         BASE / "examples" / "web" / "06_signal_room_dashboard"),
        ("electron", ["node", "--check", "main.js"],
         BASE / "examples" / "desktop" / "electron_app"),
        ("python_desktop", [sys.executable, "main.py", "--selftest"],
         BASE / "examples" / "desktop" / "python_app"),
        ("mysql_helper", [sys.executable, "-m", "py_compile", "connect.py"],
         BASE / "examples" / "database" / "mysql"),
    ]
    env_note = ""
    for name, cmd, cwd in checks:
        code, out = run(cmd, cwd)
        report["examples"].append({"name": name, "ok": code == 0,
                                   "output": out.splitlines()[-1] if out else ""})

    android = BASE / "examples" / "android" / "app" / "src" / "main" / "java"
    report["android"] = {
        "files_present": android.exists() and (BASE / "examples/android/settings.gradle.kts").exists(),
        "compiled": False,
        "note": "No Android SDK / gradlew on this machine — structure verified only.",
    }

    hashes = [p.get("sha256") for p in report["pages"] if p.get("exists")]
    report["summary"] = {
        "pages_built": len(hashes),
        "pages_passing": sum(1 for p in report["pages"] if p.get("ok")),
        "all_pages_distinct": len(set(hashes)) == len(hashes),
        "studios": [p.get("studio") for p in report["pages"]],
        "examples_passing": sum(1 for e in report["examples"] if e["ok"]),
        "examples_total": len(report["examples"]),
    }
    report["env_note"] = env_note

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    for page in report["pages"]:
        print(f"{page['slug']:<28} ok={page.get('ok')} browser={page.get('browser')} "
              f"{page.get('studio', '')} {page.get('sha256', '')}")
    for example in report["examples"]:
        print(f"{example['name']:<28} ok={example['ok']}  {example['output'][:70]}")
    print("android:", report["android"]["note"])
    return 0 if all(p.get("ok") for p in report["pages"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
