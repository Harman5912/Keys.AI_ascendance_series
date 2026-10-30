"""Build two of every artifact type Keys.ai can build, with its own local models.

Phases:
  pages  portfolio ×2, marketing site ×2  -> core.site_builder (qwen2.5-coder:3b plan)
  apps   dashboard ×2, python desktop ×2, electron ×2, android ×2, mysql ×2
         -> crown_code -> Crown Code agent (qwen3:8b tool loop)

    python qa_artifacts/build_two_of_each.py --pages
    python qa_artifacts/build_two_of_each.py --apps
    python qa_artifacts/build_two_of_each.py            # both

Each app build is capped in wall-clock time; whatever it produced is verified
afterwards, and a build that did not finish is reported as unfinished, never as
a success.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

OUT = BASE / "examples" / "generated" / "two_of_each"
REPORT = BASE / "qa_artifacts" / "reports" / "two_of_each.json"
STATE_DIR = BASE / "qa_artifacts" / "reports" / "two_of_each_state"

PAGES = [
    ("portfolio_01_arjun_mehta", "portfolio", "brutalist",
     "Portfolio website for Arjun Mehta, a backend engineer in Pune. Dark, "
     "type-led, four projects with measurable outcomes."),
    ("portfolio_02_hollis_park", "portfolio", "editorial",
     "Portfolio website for Hollis Park, a landscape architecture studio in "
     "Melbourne. Calm, light, three built projects with locations."),
    ("marketing_01_sable_coffee", "website", "organic",
     "Marketing website for Sable Coffee Roasters, a two-person roastery in "
     "Leeds. Warm, tactile, subscription offer with prices."),
    ("marketing_02_halo_notes", "website", "newsroom",
     "Marketing website for Halo Notes, an offline-first note app for field "
     "researchers. Confident, technical, clear pricing."),
]

SELLING = [
    {
        "slug": "store_01_sable_coffee",
        "kind": "ecommerce",
        "brief": "Build a selling store for Sable Coffee Roasters: a catalog of real coffee products, a cart, checkout and order history.",
        "requirements":
            "data source: SQLite file `sable.db` in the project folder (no server needed); "
            "catalog: 6 labelled coffee products with name, description, price, origin and stock; "
            "cart in the server session persisted to the database per order; "
            "checkout writes an order row and decrements stock in one transaction; "
            "payment: no payment provider credentials are available, so no card details are collected at all \u2014 "
            "checkout ends at an order confirmation screen that says Payment pending: no card was collected and the order record says payment=pending; "
            "invented statistics are not acceptable: every number on the catalog is the product's real data; "
            "stack: Flask API + vanilla HTML/CSS/JS with inline SVG, no CDN; "
            "scope: local single user browsing as itself, no login, no multi-user; port 5073.",
    },
    {
        "slug": "store_02_quiet_index_editorial",
        "kind": "ecommerce",
        "brief": "Build a selling store that combines product catalog with editorial storytelling: a slow-made goods shop with a story-driven homepage and a real cart.",
        "requirements":
            "data source: SQLite file `shop.db` in the project folder; "
            "catalog: 5 labelled handcrafted goods with name, material, maker, price, stock; "
            "cart persisted to the database per order, checkout decrements stock in one transaction; "
            "checkout is a real order: it writes an order row and an order line for each item; "
            "payment: no payment provider credentials are available — no card details are collected; "
            "the order confirmation says Order received: payment pending; no card was collected and notes the sample-data caveat; "
            "stack: Flask API + vanilla HTML/CSS/JS with inline SVG, no CDN; "
            "scope: local single user, no login, no multi-user; port 5074.",
    },
]

DOCUMENTS = [
    ("Quarterly Business Review — Northwind Logistics", "Q3 review for Northwind Logistics: revenue up 14% year on year, two lost contracts, a driver retention problem and three recommended actions.", "docx",
     "A four-section Word document: Revenue Update, Lost Contracts, Driver Retention Problem, Recommendations — with one table in the Revenue Update and real numbers throughout."),
    ("Supplier Risk Memo — Atlas Parts", "Risk memo for Atlas Parts' Southeast Asia supplier base: one supplier disrupted by port closures, two single-source components, three recommended mitigations.", "docx",
     "Four sections with one action-owner table: Supplier Disruption, Single-Source Exposure, Mitigations, and a Risks snapshot table."),
    ("Staffing Plan — Pulse Clinic Q4", "Q4 staffing plan for Pulse Clinic: a new nurse triage lane adding 4 roles, one vacancy remaining, and a headcount, wage and capacity table.", "pptx",
     "A 5-slide deck: the opening, the new lane, the roles table (Capacity, Role, Q4 headcount, Wage), the vacancy, and the ask."),
    ("Three-Year Plan — Fern Flint Organics", "Three-year plan for Fern Flint Organics: move into the second market, open a second grow site, reach a revenue target with the milestones.", "pptx",
     "A 5-slide deck: vision, the two markets, the grow-site timeline, the targets table, and the ask."),
    ("Revenue and Coverage Snapshot — Meridian Newsroom", "A revenue and coverage snapshot for Meridian Newsroom: four sections (driven revenue, underperformers, opportunity, decision) with a revenue-by-line table.", "docx",
     "Four sections with one revenue table, real numbers, no placeholder text."),
    ("Stock Cover and Low-Stock Report — Goods Co", "A stock cover and low-stock report for Goods Co: warehouse, sku, current stock, reorder point, cover in weeks, and a chart.", "xlsx",
     "A workbook with a stock-levels worksheet (live formulas for cover in weeks and cover status) and a reorder-point bar chart, plus a cover-by-warehouse chart."),
]

APPS = [
    {
        "slug": "dashboard_01_fleet",
        "kind": "dashboard",
        "brief": "Build a fleet-operations dashboard: vehicles, trips, fuel and "
                 "maintenance costs. Real JSON API, charts and a table.",
        "requirements":
            "data source: MySQL database `fleet_ops`, tables seeded with labelled sample rows; "
            "connect with pymysql from .env (DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME); "
            "metrics: distance per day, fuel cost per vehicle, maintenance cost, overdue services; "
            "charts: line for distance per day, bar for cost per vehicle, KPI cards, table of vehicles; "
            "stack: Flask API + vanilla HTML/CSS/JS with inline SVG charts, no CDN; "
            "scope: local single user, no login, sample data, port 5071.",
    },
    {
        "slug": "dashboard_02_newsroom",
        "kind": "dashboard",
        "brief": "Build a newsroom analytics dashboard: articles, reads, "
                 "subscriptions and the editorial task board.",
        "requirements":
            "data source: MySQL database `newsroom_ops`, seeded sample rows, pymysql, .env credentials; "
            "metrics: reads, read-through rate, subscriptions, open editorial tasks; "
            "charts: line for reads per day, horizontal bars per section, funnel from read to subscribe, "
            "and a task list with owner, status and due date; "
            "stack: Flask API + vanilla HTML/CSS/JS, inline SVG, no CDN; "
            "scope: local single user, no login, sample data, port 5072.",
    },
    {
        "slug": "python_01_ledger",
        "kind": "python-desktop",
        "brief": "Python desktop app: a small ledger with entries, search and totals.",
        "requirements":
            "stack: PyQt6 with a QMainWindow, table, add form and status bar; "
            "storage: SQLite file in the project folder (no server needed); "
            "include a --selftest flag that builds the window offscreen and prints OK; "
            "python desktop app, must run with `python main.py`; "
            "scope: local single user, no login, no multi-user.",
    },
    {
        "slug": "python_02_inventory",
        "kind": "python-desktop",
        "brief": "Python desktop app: a shop inventory tool with stock levels and low-stock warnings.",
        "requirements":
            "stack: PyQt6 QMainWindow with a table, search box, add-item form and a low-stock highlight; "
            "storage: SQLite file in the project folder; "
            "include a --selftest flag that builds the window offscreen and prints OK; "
            "scope: local single user, no login, no multi-user.",
    },
    {
        "slug": "electron_01_notes",
        "kind": "electron",
        "brief": "Electron desktop app: quick notes that persist to disk.",
        "requirements":
            "stack: Electron with contextIsolation on, nodeIntegration off, a narrow preload bridge; "
            "IPC: notes:list and notes:save writing JSON into app.getPath('userData'); "
            "UI: plain HTML/CSS/JS, no bundler; must pass node --check on every JS file; "
            "scope: local single user, no login, no multi-user.",
    },
    {
        "slug": "electron_02_timer",
        "kind": "electron",
        "brief": "Electron desktop app: a focus timer with sessions saved to disk.",
        "requirements":
            "stack: Electron, contextIsolation on, nodeIntegration off, preload bridge; "
            "IPC: sessions:list, sessions:add; store JSON in userData; "
            "UI: plain HTML/CSS/JS with start/pause/reset and a session list; "
            "scope: local single user, no login, no multi-user.",
    },
    {
        "slug": "android_01_tasks",
        "kind": "android",
        "brief": "Android app: a simple task list with add and complete.",
        "requirements":
            "stack: Kotlin, Gradle Kotlin DSL, one Activity, ViewBinding, SQLite helper; "
            "package com.keysai.tasks; compileSdk 34, minSdk 24; "
            "no SDK on this machine, so provide a README with the exact open-and-run steps; "
            "scope: local single user offline on the phone, no login, no multi-user.",
    },
    {
        "slug": "android_02_habits",
        "kind": "android",
        "brief": "Android app: a daily habit tracker with streaks.",
        "requirements":
            "stack: Kotlin, Gradle Kotlin DSL, one Activity, ViewBinding, SQLite helper; "
            "package com.keysai.habits; compileSdk 34, minSdk 24; "
            "no SDK on this machine, so provide a README with the exact open-and-run steps; "
            "scope: local single user offline on the phone, no login, no multi-user.",
    },
    {
        "slug": "mysql_01_shop",
        "kind": "mysql",
        "brief": "MySQL database: a small shop with customers, products, orders and order items.",
        "requirements":
            "MySQL 8, database `demo_shop`, CREATE DATABASE IF NOT EXISTS, FKs, indexes; "
            "seed.sql with labelled sample rows; queries.sql with a join, a CTE and a window function; "
            "connect.py reading .env credentials; no password in any file; "
            "scope: local single user demo, no login.",
    },
    {
        "slug": "mysql_02_library",
        "kind": "mysql",
        "brief": "MySQL database: a library with books, members, loans and reservations.",
        "requirements":
            "MySQL 8, database `demo_library`, FKs and indexes; seed.sql with labelled sample rows; "
            "queries.sql with overdue loans, most-borrowed titles and a window function; "
            "connect.py reading .env credentials; no password in any file; "
            "scope: local single user demo, no login.",
    },
]

APP_TIMEOUT = 600       # per build, seconds


def _state_path(slug: str) -> Path:
    return STATE_DIR / f"{slug}.json"


def _save_state(entry: dict) -> None:
    """Persist one artifact's result the moment it finishes.

    A batch that dies half way (session ended, model hung, machine slept)
    must not lose the artifacts that already succeeded: every item writes its
    own state file, and the merged report is rebuilt from those files.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _state_path(entry["slug"]).write_text(
        json.dumps(entry, indent=2, default=str), encoding="utf-8")


def _load_states() -> list[dict]:
    out: list[dict] = []
    if STATE_DIR.exists():
        for path in sorted(STATE_DIR.glob("*.json")):
            try:
                out.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
    return out


def _report(results: list[dict] | None = None) -> None:
    """Write the merged report from every state file (plus new results)."""
    merged = {e.get("slug"): e for e in _load_states() if e.get("slug")}
    for entry in (results or []):
        if entry.get("slug"):
            merged[entry["slug"]] = entry
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({"results": list(merged.values())}, indent=2,
                                 default=str), encoding="utf-8")


def _missing_recipe_files(kind: str, workspace: Path) -> list[str]:
    """Which files the recipe for this kind still expects, and are not on disk.

    The agent's own "status: done" is a claim; this is the evidence. An app
    whose recipe files are missing is reported as unfinished no matter what
    the model said about it.
    """
    from core.build_recipes import RECIPES

    recipe = RECIPES.get(kind)
    if not recipe or not workspace.exists():
        return list(recipe["files"]) if recipe else []
    present = {p.name for p in workspace.rglob("*") if p.is_file()}
    missing = []
    for spec in recipe["files"]:
        clean = spec.split("(")[0].strip().rstrip("/")
        if "/" in clean:
            if not (workspace / clean).exists():
                missing.append(clean)
        elif clean not in present:
            missing.append(clean)
    return missing


def _is_done(entry: dict) -> bool:
    return bool(entry.get("ok") or entry.get("finished"))


def build_pages() -> list[dict]:
    return build_pages_for(PAGES)


def build_pages_for(specs) -> list[dict]:
    from core.site_builder import build_site

    results = []
    for slug, kind, studio, brief in specs:
        out = OUT / "pages" / slug
        print(f"\n=== page {slug} ({kind}/{studio}) ===", flush=True)
        started = time.time()
        result = build_site(brief, out, kind=kind, studio=studio, speed="fast",
                            attempts=1, browser=True,
                            on_log=lambda line: print(f"  · {line}", flush=True))
        result.update({"slug": slug, "artifact": "page", "kind": kind,
                       "studio_requested": studio, "trimmed": False,
                       "seconds": result.get("seconds") or round(time.time() - started, 1),
                       "path": str(out / "index.html")})
        results.append(result)
        _save_state(result)
        _report(results)
        print(f"  → {'OK' if result.get('ok') else 'FAILED'} {result.get('bytes')}B "
              f"{result.get('seconds')}s", flush=True)
    return results


def build_apps() -> list[dict]:
    return build_apps_for(APPS)


def build_apps_for(specs) -> list[dict]:
    from actions import crown_code as cc
    from core import crown_bridge

    results = []
    for spec in specs:
        slug = spec["slug"]
        workspace = OUT / "apps" / slug
        print(f"\n=== app {slug} ({spec['kind']}) ===", flush=True)
        started = time.time()
        try:
            message = cc.crown_code({
                "description": spec["brief"],
                "requirements": spec["requirements"],
                "workspace": str(workspace),
                "wait": True,
                "timeout": APP_TIMEOUT,
            })
            finished = "status: done" in message.lower() or "done in" in message.lower()
        except Exception as err:                       # never stop the batch
            message = f"{type(err).__name__}: {err}"
            finished = False
        files = sorted(str(p.relative_to(workspace)) for p in workspace.rglob("*")
                       if p.is_file()) if workspace.exists() else []
        missing = _missing_recipe_files(spec["kind"], workspace)
        entry = {
            "slug": slug, "artifact": spec["kind"], "brief": spec["brief"],
            "model": crown_bridge.load_config().get("model") or "qwen3:8b",
            "seconds": round(time.time() - started, 1),
            "finished": finished and not missing,
            "agent_said_done": finished,
            "missing_files": missing,
            "message": message[-1200:], "files": files[:60],
        }
        results.append(entry)
        _save_state(entry)
        _report(results)
        print(f"  → {len(files)} files · {entry['seconds']}s · "
              f"{'finished' if finished else 'did not finish'}", flush=True)
    return results


SELLING_OUT = OUT / "selling"
GUIDE_DIRS = {
    "pptx": OUT / "documents" / "pptx",
    "docx": OUT / "documents" / "docx",
    "xlsx": OUT / "documents" / "xlsx",
}


def build_selling() -> list[dict]:
    return build_selling_for(SELLING)


def build_selling_for(specs) -> list[dict]:
    from actions import crown_code as cc

    results = []
    for spec in specs:
        slug = spec["slug"]
        workspace = SELLING_OUT / slug
        print(f"\n=== store {slug} ({spec['kind']}) ===", flush=True)
        started = time.time()
        try:
            message = cc.crown_code({
                "description": spec["brief"],
                "requirements": spec["requirements"],
                "workspace": str(workspace),
                "wait": True,
                "timeout": APP_TIMEOUT,
            })
            finished = "status: done" in message.lower() or "done in" in message.lower()
        except Exception as err:
            message = f"{type(err).__name__}: {err}"
            finished = False
        files = sorted(str(p.relative_to(workspace)) for p in workspace.rglob("*")
                       if p.is_file()) if workspace.exists() else []
        missing = _missing_recipe_files("ecommerce", workspace)
        entry = {
            "slug": slug, "artifact": spec["kind"], "brief": spec["brief"],
            "model": crown_bridge.load_config().get("model") or "qwen3:8b",
            "seconds": round(time.time() - started, 1),
            "finished": finished and not missing,
            "agent_said_done": finished,
            "missing_files": missing,
            "message": message[-1200:], "files": files[:60],
        }
        results.append(entry)
        _save_state(entry)
        _report(results)
        print(f"  → {len(files)} files · {entry['seconds']}s · "
              f"{'finished' if finished else 'did not finish'}", flush=True)
    return results


def build_documents() -> list[dict]:
    return build_documents_for(DOCUMENTS)


def build_documents_for(specs) -> list[dict]:
    """Model-written Word/Excel/PowerPoint, using core.doc_builder + file_processor.

    Each document's actual content (sections, bullets, tables) comes from the
    local model; python-pptx / python-docx / openpyxl render the styling.
    """

    from core import crown_bridge
    import actions.file_processor as fp

    results = []
    for title, instruction, doc_type, detail in specs:
        subdir = GUIDE_DIRS[doc_type]
        slug = "doc_" + title.split(" — ")[0].replace(" ", "_")[:32]
        out = subdir / f"{slug}.{doc_type}"
        print(f"\n=== doc {slug}.{doc_type} · {title} ===", flush=True)
        started = time.time()
        try:
            # The detail IS the shape the document must have (section list,
            # the table, the slide count). Passing only the prose is how a
            # "five-slide deck with a roles table" comes back as three slides
            # with no table.
            message = fp.file_processor({
                "action": "create",
                "file_path": str(out),
                "doc_type": doc_type,
                "title": title,
                "instruction": f"{instruction}\n\nRequired shape: {detail}",
            })
            ok = out.exists() and out.stat().st_size > 1500
            finished = "Could not create" not in message and "failed:" not in message.lower()
        except Exception as err:
            message = f"document creation raised {type(err).__name__}: {err}"
            ok = False
            finished = False
        results.append({"slug": slug, "artifact": doc_type, "title": title,
                        "model": crown_bridge.load_config().get("model") or "qwen3:8b",
                        "seconds": round(time.time() - started, 1),
                        "ok": ok, "finished": finished,
                        "message": message[:900],
                        "path": str(out) if out.exists() else "",
                        "bytes": out.stat().st_size if out.exists() else 0})
        _save_state(results[-1])
        _report(results)
        print(f"  → {'OK' if ok else 'FAILED'} {results[-1]['bytes']}B "
              f"{results[-1]['seconds']}s", flush=True)
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", action="store_true")
    parser.add_argument("--apps", action="store_true")
    parser.add_argument("--selling", action="store_true")
    parser.add_argument("--docs", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--only", default="",
                        help="comma-separated slugs to build (default: all)")
    parser.add_argument("--force", action="store_true",
                        help="rebuild artifacts that already have a saved result")
    args = parser.parse_args()
    do_pages = args.pages or (not any([args.pages, args.apps, args.selling, args.docs, args.all]))
    do_apps = args.apps or args.all
    do_selling = args.selling or args.all
    do_docs = args.docs or args.all

    only = {s.strip() for s in args.only.split(",") if s.strip()}

    import actions.file_processor as fp         # doc builder path
    from actions import crown_code as cc        # app/selling path
    from core import crown_bridge

    done = {e.get("slug"): e for e in _load_states()}

    def skip(slug: str) -> bool:
        """True when this artifact is already built and should not be redone."""
        if only and slug not in only:
            return True
        if args.force:
            return False
        entry = done.get(slug)
        return bool(entry) and _is_done(entry)

    results = []
    if do_pages:
        for slug, kind, studio, brief in PAGES:
            if skip(slug):
                print(f"=== page {slug} — already built, skipping ===", flush=True)
                continue
            results += build_pages_for([(slug, kind, studio, brief)])
    if do_apps:
        results += build_apps_for([s for s in APPS if not skip(s["slug"])])
    if do_docs:
        results += build_documents_for([d for d in DOCUMENTS if not skip(
            "doc_" + d[0].split(" — ")[0].replace(" ", "_")[:32])])
    if do_selling:
        results += build_selling_for([s for s in SELLING if not skip(s["slug"])])
    _report(results)

    print("\nsummary")
    for r in _load_states():
        art = r.get("artifact") or ""
        label = r.get("title", "").strip() or r.get("brief", "")[:40]
        ok = _is_done(r)
        print(f"  {r.get('slug', '??'):<34} {art:<14}"
              f"  {'ok' if ok else 'incomplete':10} {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
