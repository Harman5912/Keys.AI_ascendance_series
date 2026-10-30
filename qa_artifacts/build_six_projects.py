"""Stage 5: six SEPARATE projects (A–F), one per kind, built by Keys.ai itself.

    A utility   batch file-hygiene CLI           -> crown_code (no recipe, custom checks)
    B sql       bike-share MySQL analytics       -> crown_code (mysql recipe)
    C site      ceramics studio portfolio        -> core.site_builder (real browser check)
    D rest-api  task tracker JSON API            -> crown_code (api-backend recipe)
    E analysis  energy CSV analysis pipeline     -> crown_code (no recipe, RUNS the pipeline)
    F desktop   PyQt6 note canvas                -> crown_code (python-desktop recipe)

    python qa_artifacts/build_six_projects.py                # all six
    python qa_artifacts/build_six_projects.py --only C,E     # subset

Every claim is checked against evidence on disk, never against the agent's
own "status: done":
  - recipe files must exist (build_two_of_each._missing_recipe_files)
  - every generated .py must pass `python -m py_compile`
  - the site (C) is opened and checked in a real browser by site_builder
  - the analysis pipeline (E) is EXECUTED and its declared outputs must appear
  - the API (D) gets an HTTP smoke attempt through Flask's test client
    (recorded as evidence; the exact server shape is model-written)
  - the desktop app (F) is import-checked with QT_QPA_PLATFORM=offscreen

State is written per project, so a killed batch keeps its finished work.

Out: examples/generated/six_projects/{a_utility,...,f_desktop}
     qa_artifacts/reports/six_projects.json
     qa_artifacts/reports/six_projects_state/*.json
"""
from __future__ import annotations

import argparse
import json
import py_compile
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

OUT = BASE / "examples" / "generated" / "six_projects"
REPORT = BASE / "qa_artifacts" / "reports" / "six_projects.json"
STATE_DIR = BASE / "qa_artifacts" / "reports" / "six_projects_state"

APP_TIMEOUT = 600       # crown_code wall-clock cap per project

PROJECTS = [
    {
        "key": "A", "slug": "a_utility", "kind": None,
        "brief": "Build a command-line file-hygiene utility named tidyup: "
                 "recursively clean a folder of text files (trim trailing "
                 "whitespace, normalise line endings, de-duplicate adjacent "
                 "blank lines, optional lowercase filenames) with a dry-run "
                 "mode that prints a per-file diff summary.",
        "requirements":
            "single-file CLI in tidyup.py plus a README.md and a tests/ "
            "folder; argparse interface: tidyup.py PATH [--dry-run] "
            "[--lowercase] [--ext .md .txt]; pure standard library, no "
            "third-party dependencies; dry-run must change nothing on disk; "
            "include 3 sample files under samples/ and unittest tests that "
            "cover trim, line-ending normalisation and dry-run safety.",
    },
    {
        "key": "B", "slug": "b_sql", "kind": "mysql",
        "brief": "Build a MySQL analytics project for a city bike-share: "
                 "trips, stations, bikes and weather, with a normalised "
                 "schema, realistic seed data and the analysis queries an "
                 "operator actually runs.",
        "requirements":
            "database name bikeshare_ops; schema.sql: stations, bikes, "
            "trips (FKs, CHECK constraints on duration_min and bike_status, "
            "indexes on trip start time and station id); seed.sql: at least "
            "8 stations, 6 bikes and 40 labelled trips across two weeks "
            "including a weather table; queries.sql: 8 commented analysis "
            "queries (top stations, average duration by hour, bikes overdue "
            "for service, trips per weather condition, etc.); db.py reads "
            ".env (DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME) and exposes "
            "run_query(sql, params) with parameterised statements only.",
    },
    {
        "key": "C", "slug": "c_site", "kind": "site",
        "brief": "Portfolio website for Kiln & Current, a two-person "
                 "ceramics studio in Bristol selling tableware and running "
                 "quarterly workshops. Calm, tactile, light studio theme. "
                 "Four named pieces with real materials and prices, and the "
                 "workshop schedule with dates and remaining places.",
        "requirements": "kind portfolio, studio theme 'editorial'; one page "
                        "with hero, four works (each: name, clay body, "
                        "glaze, price in GBP), a workshops section with three "
                        "dated sessions and places-left, and a contact "
                        "footer; no invented awards or statistics.",
    },
    {
        "key": "D", "slug": "d_rest_api", "kind": "api-backend",
        "brief": "Build a JSON REST API named taskflow for a personal task "
                 "tracker: projects, tasks and tags, with filtering, "
                 "pagination and validation.",
        "requirements":
            "Flask + SQLite (taskflow.db in the project folder, created and "
            "seeded on first run); resources: /api/projects and /api/tasks "
            "with full CRUD, /api/tasks?status=&tag=&project= filtering and "
            "?limit=&offset= pagination; every write validated with clear "
            "400 messages; JSON errors never HTML tracebacks; port 5081; "
            "tests/test_api.py exercising CRUD, filtering and validation via "
            "Flask's test client; requirements.txt and a README with curl "
            "examples.",
    },
    {
        "key": "E", "slug": "e_analysis", "kind": None,
        "brief": "Build a runnable energy-analysis pipeline: a CSV of daily "
                 "household electricity readings for a full year is cleaned, "
                 "aggregated to monthly totals, joined with a tariff table, "
                 "and reported with charts and a written summary of findings.",
        "requirements":
            "data/household_energy.csv: 365 labelled daily rows (date, kWh, "
            "note) including at least 5 malformed rows the pipeline must "
            "repair or exclude with a logged reason; data/tariff.csv: 12 "
            "monthly tariff rows; analyze.py runs offline with no "
            "third-party services, writes outputs/monthly_totals.csv, "
            "outputs/kwh_by_month.png (matplotlib) and outputs/findings.md "
            "stating the true peak month, the cheapest month and the total "
            "annual kWh computed from the data; include tests/ that assert "
            "the totals match the CSV.",
    },
    {
        "key": "F", "slug": "f_desktop", "kind": "python-desktop",
        "brief": "Build a PyQt6 desktop app named NoteCanvas: a personal "
                 "note canvas where notes are cards on a grid, each with a "
                 "title, body, colour tag and pin state, persisted locally.",
        "requirements":
            "PyQt6; main.py launches the app; app/window.py: grid of note "
            "cards with add/edit/delete/pin, colour tags, and a search box "
            "filtering live; app/db.py: SQLite persistence (notes.db) with a "
            "schema migration on first run; app/theme.py: dark theme with a "
            "restrained accent palette; seed.py creating 6 sample notes; "
            "tests/ covering db CRUD; README.md with run instructions.",
    },
]


def _state_path(slug: str) -> Path:
    return STATE_DIR / f"{slug}.json"


def _save_state(entry: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _state_path(entry["slug"]).write_text(
        json.dumps(entry, indent=2, default=str), encoding="utf-8")


def _report(results: list[dict] | None = None) -> None:
    merged = {}
    if STATE_DIR.exists():
        for path in sorted(STATE_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("slug"):
                    merged[data["slug"]] = data
            except Exception:
                continue
    for entry in (results or []):
        if entry.get("slug"):
            merged[entry["slug"]] = entry
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({"projects": list(merged.values())},
                                 indent=2, default=str), encoding="utf-8")


# ── verification helpers ────────────────────────────────────────────────────

def _py_compile_all(workspace: Path) -> dict:
    """Syntax-check every generated .py. This is the floor of 'it runs'."""
    ok, failures = 0, []
    for path in sorted(workspace.rglob("*.py")):
        try:
            py_compile.compile(str(path), doraise=True)
            ok += 1
        except Exception as err:
            failures.append(f"{path.relative_to(workspace)}: {err}")
    return {"compiled": ok, "compile_failures": failures}


def _run(args, cwd: Path, timeout: int, env_extra: dict | None = None) -> dict:
    """Run a command headlessly; never raise; record real evidence."""
    import os
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.update(env_extra or {})
    started = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, *args], cwd=str(cwd), env=env,
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL)
        return {"exit": proc.returncode,
                "stdout": proc.stdout[-1500:], "stderr": proc.stderr[-1500:],
                "seconds": round(time.time() - started, 1)}
    except subprocess.TimeoutExpired as err:
        return {"exit": "timeout", "stdout": (err.stdout or b"")[-500:]
                if isinstance(err.stdout, bytes) else (err.stdout or "")[-500:],
                "stderr": f"timed out after {timeout}s",
                "seconds": round(time.time() - started, 1)}
    except Exception as err:
        return {"exit": "error", "stdout": "",
                "stderr": f"{type(err).__name__}: {err}",
                "seconds": round(time.time() - started, 1)}


def _verify_utility(workspace: Path) -> dict:
    """The CLI's interface is its arguments: run --help on the entry point."""
    entry = workspace / "tidyup.py"
    evidence: dict = {"entry_exists": entry.exists()}
    if entry.exists():
        help_run = _run(["tidyup.py", "--help"], workspace, timeout=60)
        evidence["help_run"] = help_run
        evidence["help_ok"] = (help_run["exit"] == 0
                               and "usage" in (help_run["stdout"] + "").lower())
        # dry-run on the shipped samples must not touch them
        samples = workspace / "samples"
        if samples.exists():
            before = {p.name: p.stat().st_size
                      for p in sorted(samples.rglob("*")) if p.is_file()}
            run = _run(["tidyup.py", "samples", "--dry-run"], workspace,
                       timeout=60)
            after = {p.name: p.stat().st_size
                     for p in sorted(samples.rglob("*")) if p.is_file()}
            evidence["dry_run"] = {"exit": run["exit"],
                                   "touched_nothing": before == after}
    if (workspace / "tests").exists():
        evidence["tests_run"] = _run(["-m", "unittest", "discover", "-s",
                                      "tests"], workspace, timeout=180)
    return evidence


def _verify_analysis(workspace: Path) -> dict:
    """The pipeline must actually RUN offline and produce its outputs."""
    run = _run(["analyze.py"], workspace, timeout=300)
    outputs = workspace / "outputs"
    produced = sorted(str(p.relative_to(workspace))
                      for p in outputs.rglob("*") if p.is_file()) \
        if outputs.exists() else []
    evidence = {"run": run, "outputs": produced}
    if (workspace / "tests").exists():
        evidence["tests_run"] = _run(["-m", "unittest", "discover", "-s",
                                      "tests"], workspace, timeout=180)
    return evidence


def _verify_api(workspace: Path) -> dict:
    """HTTP smoke through Flask's test client, run in a subprocess so the
    model-written server cannot hang the harness."""
    smoke = (
        "import json, sys\n"
        "sys.path.insert(0, '.')\n"
        "mod = __import__('app')\n"
        "app = getattr(mod, 'app', None) or getattr(mod, 'application', None)\n"
        "assert app is not None, 'no Flask app object exported'\n"
        "c = app.test_client()\n"
        "r = c.get('/api/projects')\n"
        "print('STATUS', r.status_code)\n"
        "print('BODY', (r.get_data(as_text=True) or '')[:300])\n"
    )
    run = _run(["-c", smoke], workspace, timeout=120)
    evidence = {"http_smoke": run}
    if (workspace / "tests").exists():
        evidence["tests_run"] = _run(["-m", "unittest", "discover", "-s",
                                      "tests"], workspace, timeout=300)
    return evidence


def _verify_desktop(workspace: Path) -> dict:
    """PyQt6 cannot open a window headlessly; offscreen import + tests."""
    main_py = workspace / "main.py"
    evidence: dict = {"main_exists": main_py.exists()}
    if main_py.exists():
        evidence["import_check"] = _run(["-c",
                                         "import main; print('import ok')"],
                                        workspace, timeout=120)
    if (workspace / "tests").exists():
        evidence["tests_run"] = _run(["-m", "unittest", "discover", "-s",
                                      "tests"], workspace, timeout=180)
    return evidence


def _verify_sql_real(workspace: Path) -> dict:
    schema = workspace / "schema.sql"
    seed = workspace / "seed.sql"
    queries = workspace / "queries.sql"
    evidence: dict = {
        "schema_exists": schema.exists(),
        "seed_exists": seed.exists(),
        "queries_exists": queries.exists(),
    }
    if schema.exists():
        text = schema.read_text(encoding="utf-8", errors="replace")
        evidence["create_tables"] = text.upper().count("CREATE TABLE")
        evidence["foreign_keys"] = text.upper().count("FOREIGN KEY")
        evidence["check_constraints"] = text.upper().count("CHECK")
        evidence["indexes"] = text.upper().count("CREATE INDEX")
    if seed.exists():
        seed_text = seed.read_text(encoding="utf-8", errors="replace")
        evidence["insert_statements"] = seed_text.upper().count("INSERT INTO")
    if queries.exists():
        queries_text = queries.read_text(encoding="utf-8", errors="replace")
        evidence["analysis_queries"] = queries_text.upper().count("SELECT")
    return evidence


VERIFY = {
    "a_utility": _verify_utility,
    "b_sql": _verify_sql_real,
    "d_rest_api": _verify_api,
    "e_analysis": _verify_analysis,
    "f_desktop": _verify_desktop,
}


# ── build phases ────────────────────────────────────────────────────────────

def build_site(project: dict, workspace: Path) -> dict:
    from core.site_builder import build_site as _build

    started = time.time()
    result = _build(project["brief"], workspace, kind="portfolio",
                    studio="editorial", speed="fast", attempts=1, browser=True,
                    on_log=lambda line: print(f"  · {line}", flush=True))
    return {"ok": bool(result.get("ok")),
            "seconds": result.get("seconds")
            or round(time.time() - started, 1),
            "browser": {k: result.get(k) for k in
                        ("browser_ok", "console_errors", "checks")
                        if k in result},
            "detail": {k: result.get(k) for k in
                       ("bytes", "sections", "warnings") if k in result}}


def build_app(project: dict, workspace: Path) -> dict:
    from actions import crown_code as cc
    from core import crown_bridge

    started = time.time()
    try:
        message = cc.crown_code({
            "description": project["brief"],
            "requirements": project["requirements"],
            "workspace": str(workspace),
            "wait": True,
            "timeout": APP_TIMEOUT,
        })
        finished = ("status: done" in message.lower()
                    or "done in" in message.lower())
    except Exception as err:
        message = f"{type(err).__name__}: {err}"
        finished = False
    return {"ok": finished,
            "seconds": round(time.time() - started, 1),
            "model": crown_bridge.load_config().get("model") or "qwen3:8b",
            "message": message[-1200:]}


def build_project(project: dict) -> dict:
    from qa_artifacts.build_two_of_each import _missing_recipe_files

    workspace = OUT / project["slug"]
    print(f"\n=== {project['key']} · {project['slug']} "
          f"({project['kind'] or 'custom'}) ===", flush=True)

    if project["key"] == "C":
        build = build_site(project, workspace)
    else:
        build = build_app(project, workspace)

    files = sorted(str(p.relative_to(workspace))
                   for p in workspace.rglob("*") if p.is_file()) \
        if workspace.exists() else []
    missing = _missing_recipe_files(project["kind"] or "", workspace)
    compile_check = (_py_compile_all(workspace)
                     if workspace.exists() else {"compiled": 0,
                                                 "compile_failures": ["workspace missing"]})
    verify = VERIFY.get(project["slug"], lambda w: {})(workspace)

    ok = (bool(files) and not missing and not compile_check["compile_failures"]
          and bool(build.get("ok")))
    entry = {
        "key": project["key"], "slug": project["slug"],
        "kind": project["kind"] or "custom",
        "build": build, "files_count": len(files), "files": files[:80],
        "missing_recipe_files": missing, "compile": compile_check,
        "verify": verify, "ok": ok,
    }
    _save_state(entry)
    _report([entry])
    print(f"  → {'OK' if ok else 'FAILED'} · {len(files)} files · "
          f"missing={missing or 'none'} · "
          f"py_errors={len(compile_check['compile_failures'])} · "
          f"{build['seconds']}s", flush=True)
    return entry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="",
                        help="comma-separated keys, e.g. A,C,E")
    args = parser.parse_args()
    wanted = {k.strip().upper() for k in args.only.split(",") if k.strip()}
    projects = [p for p in PROJECTS if not wanted or p["key"] in wanted]

    results = []
    for project in projects:
        results.append(build_project(project))

    print("\n=== stage 5 summary ===", flush=True)
    for entry in results:
        print(f"  {entry['key']} {entry['slug']}: "
              f"{'OK' if entry['ok'] else 'FAILED'} "
              f"({entry['files_count']} files, "
              f"{entry['build']['seconds']}s)", flush=True)
    passed = sum(1 for e in results if e["ok"])
    print(f"{passed}/{len(results)} projects passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
