"""Build two dashboards and two Python desktop apps through the real tool path.

This is the counterpart to `build_two_of_each.py` for the two artifact kinds
that used to be handed to the local coding agent and came back unfinished. It
drives the public interface (`crown_code`) with `wait=True`, so what it measures
is what a user gets, not a private shortcut.

Each build is verified by the same code the tool uses — compile, seed, serve
every endpoint, render the page in Chromium — and the report records the checks
that actually ran. A build that fails is written to the report as a failure.

    python qa_artifacts/build_recipe_apps.py
    python qa_artifacts/build_recipe_apps.py --only dashboard_01_fleet

Output:  examples/generated/recipe_apps/<slug>/
Report:  qa_artifacts/reports/recipe_apps.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

OUT = BASE / "examples" / "generated" / "recipe_apps"
REPORT = BASE / "qa_artifacts" / "reports" / "recipe_apps.json"
SHOTS = BASE / "qa_artifacts" / "screenshots"

BUILDS = [
    {
        "slug": "dashboard_01_fleet",
        "kind": "dashboard",
        "brief": ("Build a fleet-operations dashboard: vehicles, trips, fuel and "
                  "maintenance costs. Real JSON API, charts and a table."),
        "requirements": ("data source: SQLite file in the project folder\n"
                         "metrics: cost per day, cost per category, open issues\n"
                         "charts: line for cost per day, bars per category\n"
                         "stack: Flask API + vanilla HTML/CSS/JS, inline SVG\n"
                         "scope: local single user, no login, sample data"),
    },
    {
        "slug": "dashboard_02_newsroom",
        "kind": "dashboard",
        "brief": ("Build a newsroom analytics dashboard: articles, reads and "
                  "subscriptions, with a table of recent stories."),
        "requirements": ("data source: SQLite file in the project folder\n"
                         "metrics: reads per day, reads per section, open items\n"
                         "charts: line for reads per day, bars per section\n"
                         "stack: Flask API + vanilla HTML/CSS/JS, inline SVG\n"
                         "scope: local single user, no login, sample data"),
    },
    {
        "slug": "python_01_ledger",
        "kind": "python-desktop",
        "brief": ("Python desktop app: a small ledger with entries, search and "
                  "totals."),
        "requirements": ("stack: PyQt6 QMainWindow with table, search, add form "
                         "and running total\n"
                         "storage: SQLite file in the project folder\n"
                         "include a --selftest flag that builds the window "
                         "offscreen and prints OK\n"
                         "scope: local single user, no login"),
    },
    {
        "slug": "python_02_inventory",
        "kind": "python-desktop",
        "brief": ("Python desktop app: a shop inventory tool with stock levels "
                  "and low-stock warnings."),
        "requirements": ("stack: PyQt6 QMainWindow with table, search and add form\n"
                         "storage: SQLite file in the project folder\n"
                         "highlight rows at or below the reorder level\n"
                         "include a --selftest flag that prints OK\n"
                         "scope: local single user, no login"),
    },
]


def build_one(spec: dict) -> dict:
    from actions import crown_code as cc

    workspace = OUT / spec["slug"]
    if workspace.exists():
        shutil.rmtree(workspace)

    started = time.time()
    reply = cc.crown_code({
        "description": spec["brief"],
        "requirements": spec["requirements"],
        "workspace": str(workspace),
        "wait": True,
        # A recipe build takes a couple of seconds. The ceiling is only there
        # so a routing mistake costs two minutes instead of ten before the
        # report says the build failed.
        "timeout": 120,
    })
    files = sorted(str(p.relative_to(workspace)) for p in workspace.rglob("*")
                   if p.is_file()) if workspace.exists() else []
    ok = "verified" in reply.lower()
    return {
        "slug": spec["slug"],
        "kind": spec["kind"],
        "brief": spec["brief"],
        "ok": ok,
        "seconds": round(time.time() - started, 1),
        "files": files,
        "file_count": len(files),
        "reply": reply[-1600:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="",
                        help="comma-separated slugs to build")
    args = parser.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    results = []
    for spec in BUILDS:
        if only and spec["slug"] not in only:
            continue
        print(f"\n=== {spec['slug']} ({spec['kind']}) ===", flush=True)
        entry = build_one(spec)
        print(f"  → {'PASS' if entry['ok'] else 'FAIL'} · "
              f"{entry['file_count']} files · {entry['seconds']}s", flush=True)
        results.append(entry)

        # A dashboard build writes this; keep a stable copy for the repo.
        shot = OUT / spec["slug"] / "dashboard.png"
        if shot.exists():
            SHOTS.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(shot, SHOTS / f"{spec['slug']}.png")

        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps({"results": results}, indent=2,
                                     default=str), encoding="utf-8")

    passed = sum(1 for r in results if r["ok"])
    print(f"\n{passed}/{len(results)} builds verified")
    for entry in results:
        print(f"  {entry['slug']:<26} {entry['kind']:<16} "
              f"{'ok' if entry['ok'] else 'FAILED':<8} {entry['seconds']}s")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
