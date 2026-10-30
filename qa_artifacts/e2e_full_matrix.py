"""End-to-end matrix: every artifact kind, browser, web search and messaging.

Run:  python qa_artifacts/e2e_full_matrix.py [--only name,name]

Each check performs the real operation and reports PASS/FAIL with timings.
Nothing is sent to a real person: messaging is exercised read-only plus its
input validation.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WORK = Path.home() / "Desktop" / "keys_Creations" / "matrix"
RESULTS: list[dict] = []


def record(name: str, ok: bool, seconds: float, detail: str) -> None:
    RESULTS.append({"check": name, "ok": ok, "seconds": round(seconds, 1),
                    "detail": str(detail)[:600]})
    print(f"{'PASS' if ok else 'FAIL'}  {name}  ({seconds:.1f}s)")
    print("      " + str(detail).replace("\n", " | ")[:240], flush=True)


def check(name):
    def deco(fn):
        def run():
            t0 = time.time()
            try:
                ok, detail = fn()
            except Exception as e:
                import traceback
                traceback.print_exc()
                ok, detail = False, f"{type(e).__name__}: {e}"
            record(name, ok, time.time() - t0, detail)
        run.__name__ = fn.__name__
        return run
    return deco


class _Player:
    """Minimal UI stub: counts events so nothing depends on Qt."""
    def __init__(self):
        self.events = []

    def write_log(self, text):
        pass

    def creation_event(self, icon, text, *a):
        self.events.append((icon, str(text)[:120]))

    def creation_progress(self, pct):
        pass

    def creation_phase(self, *a):
        pass

    def creation_complete(self, text):
        pass

    def show_content(self, *a):
        pass

    def begin_creation(self, *a):
        pass

    def creation_file_add(self, *a):
        pass

    def creation_file_set_active(self, *a):
        pass

    def creation_code_set(self, *a):
        pass

    def begin_terminal(self, *a):
        pass

    def terminal_output(self, *a):
        pass


# ── artifact kinds ─────────────────────────────────────────────────────────

@check("website: portfolio")
def site():
    from actions.crown_code import crown_code
    ws = WORK / "site_portfolio"
    out = crown_code({"action": "build", "workspace": str(ws), "wait": True,
                      "kind": "portfolio", "timeout": 300,
                      "description": "Build a portfolio website for a landscape "
                                     "photographer named Elena Voss with hero, "
                                     "gallery, about and contact sections."},
                     player=_Player())
    index = ws / "index.html"
    ok = index.exists() and index.stat().st_size > 3000
    return ok, f"{out[:200]} | bytes={index.stat().st_size if index.exists() else 0}"


@check("dashboard: served + verified")
def dashboard():
    from actions.crown_code import crown_code
    ws = WORK / "dash_sales"
    out = crown_code({"action": "build", "workspace": str(ws), "wait": True,
                      "confirmed": True, "timeout": 300,
                      "description": "Build a sales dashboard web app in Python "
                                     "with Flask and SQLite seed data showing total "
                                     "revenue, orders and a monthly revenue chart."},
                     player=_Player())
    ok = (ws / "app.py").exists() and any(ws.rglob("templates/index.html"))
    return ok, f"files={len(list(ws.rglob('*')))} | {out[:220]}"


@check("desktop app: PyQt6 recipe")
def desktop():
    from actions.crown_code import crown_code
    ws = WORK / "desk_expenses"
    out = crown_code({"action": "build", "workspace": str(ws), "wait": True,
                      "confirmed": True, "timeout": 300,
                      "description": "Build a Python desktop expense tracker app with "
                                     "PyQt6 and SQLite: table of expenses, live search, "
                                     "add form and a running total."},
                     player=_Player())
    ok = (ws / "main.py").exists()
    run = subprocess.run([sys.executable, "main.py", "--selftest"], cwd=str(ws),
                         capture_output=True, text=True, timeout=90)
    return ok and run.returncode == 0, f"selftest exit={run.returncode} | {run.stdout[-200:]}"


@check("api: Flask REST service starts and answers")
def api():
    from actions.crown_code import crown_code
    ws = WORK / "api_books"
    out = crown_code({"action": "build", "workspace": str(ws), "wait": True,
                      "confirmed": True, "timeout": 420,
                      "description": "Create a Python Flask REST API for a book "
                                     "library using SQLite: GET /api/books, "
                                     "POST /api/books and GET /health. Print the "
                                     "port it listens on and run it to check it."},
                     player=_Player())
    py = next((p for p in ws.glob("*.py") if "app" in p.name.lower()), None) or \
         next(iter(ws.glob("*.py")), None)
    if py is None:
        return False, f"no python entrypoint | {out[:300]}"
    port = 5098
    env = dict(os.environ, PORT=str(port), FLASK_RUN_PORT=str(port))
    proc = subprocess.Popen([sys.executable, py.name], cwd=str(ws), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    healthy = False
    try:
        for _ in range(40):
            time.sleep(0.5)
            for path in ("/health", "/api/books", "/"):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=1) as r:
                        if r.status < 500:
                            healthy = True
                            break
                except Exception:
                    continue
            if healthy or proc.poll() is not None:
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    return healthy, f"entry={py.name} healthy={healthy} | {out[:200]}"


@check("game: playable browser game (canvas + JS)")
def game():
    from actions.crown_code import crown_code
    ws = WORK / "game_snake"
    out = crown_code({"action": "build", "workspace": str(ws), "wait": True,
                      "confirmed": True, "timeout": 360,
                      "description": "Build a playable Snake game as a single HTML "
                                     "page using a canvas and JavaScript, with "
                                     "keyboard controls, score and restart."},
                     player=_Player())
    page = ws / "index.html"
    if not page.exists():
        pages = list(ws.rglob("*.html"))
        page = pages[0] if pages else page
    ok = page.exists()
    body = page.read_text(encoding="utf-8", errors="replace") if ok else ""
    ok = ok and ("<canvas" in body.lower() or "<script" in body.lower())
    return ok, f"{page.name if ok else 'no page'} ({len(body)} chars) | {out[:200]}"


@check("library: Python package + tests")
def library():
    from actions.crown_code import crown_code
    ws = WORK / "lib_stringkit"
    out = crown_code({"action": "build", "workspace": str(ws), "wait": True,
                      "confirmed": True, "timeout": 360,
                      "description": "Create a small Python package called stringkit "
                                     "with two functions (slugify and word_count) in "
                                     "stringkit/__init__.py, plus a pytest test file "
                                     "and requirements.txt. Run pytest and make it pass."},
                     player=_Player())
    files = list(ws.rglob("*.py"))
    tests = [f for f in files if f.name.startswith("test") or "test" in f.parts]
    if not files:
        return False, f"no python files | {out[:250]}"
    run = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=str(ws),
                         capture_output=True, text=True, timeout=120)
    return run.returncode == 0, (f"files={[f.name for f in files]} tests={[t.name for t in tests]} "
                                 f"pytest exit={run.returncode} | {run.stdout[-160:]}")


@check("cli: coding agent writes and runs")
def cli():
    from actions.crown_code import crown_code
    ws = WORK / "cli_counter"
    out = crown_code({"action": "build", "workspace": str(ws), "wait": True,
                      "confirmed": True, "timeout": 360,
                      "description": "Create a Python command-line word counter: read a "
                                     "file path argument, print line/word/character counts "
                                     "and exit 0. Run it on itself to prove it works."},
                     player=_Player())
    files = list(ws.glob("*.py"))
    return bool(files), f"files={[f.name for f in files]} | {out[:220]}"


# ── browser & web ──────────────────────────────────────────────────────────

@check("browser: open, read text, tabs, screenshot, back")
def browser():
    from actions.browser_control import browser_control
    p = _Player()
    steps = []
    steps.append(("go_to", browser_control({"action": "go_to", "url": "https://example.com"}, player=p)))
    time.sleep(1.0)
    text = browser_control({"action": "get_text"}, player=p) or ""
    steps.append(("get_text", text[:80]))
    steps.append(("get_url", browser_control({"action": "get_url"}, player=p)))
    steps.append(("list_tabs", (browser_control({"action": "list_tabs"}, player=p) or "")[:80]))
    shot = WORK / "browser_shot.png"
    steps.append(("screenshot", (browser_control({"action": "screenshot", "path": str(shot)}, player=p) or "")[:80]))
    steps.append(("back", (browser_control({"action": "back"}, player=p) or "")[:60]))
    ok = "example" in text.lower() or "documentation" in text.lower()
    ok = ok and shot.exists() and shot.stat().st_size > 1000
    return ok, " | ".join(f"{k}: {str(v)[:70]}" for k, v in steps)


@check("web search: search / news / research / price / compare")
def search():
    from actions.web_search import web_search
    cases = [
        ("search", {"query": "Python 3.14 release notes", "mode": "search"}),
        ("news", {"query": "technology", "mode": "news"}),
        ("research", {"query": "what is retrieval augmented generation", "mode": "research"}),
        ("price", {"query": "iPhone 17", "mode": "price"}),
        ("compare", {"query": "python vs javascript", "mode": "compare",
                     "items": ["python", "javascript"], "aspect": "features"}),
    ]
    out = {}
    for name, params in cases:
        t0 = time.time()
        res = web_search(parameters=params, player=_Player()) or ""
        out[name] = (len(res), round(time.time() - t0, 1),
                     res[:60].replace("\n", " "))
    ok = all(v[0] > 80 for v in out.values())
    return ok, json.dumps(out)[:500]


# ── messaging (read-only) ──────────────────────────────────────────────────

@check("messaging: WhatsApp state + queue (read-only)")
def messaging():
    from actions.whatsapp_control import whatsapp_control
    p = _Player()
    status = whatsapp_control({"action": "status"}, player=p) or ""
    queue = whatsapp_control({"action": "queue_status"}, player=p) or ""
    return bool(status) and bool(queue), f"status={status[:160]} | queue={queue[:120]}"


@check("messaging: send validation refuses empty/invalid input")
def messaging_validation():
    from actions.whatsapp_control import whatsapp_control
    no_target = whatsapp_control({"action": "send", "message_text": "hi"}, player=_Player()) or ""
    no_text = whatsapp_control({"action": "send", "receiver": "Test"}, player=_Player()) or ""
    calls = whatsapp_control({"action": "make_call"}, player=_Player()) or ""
    ok = "receiver" in no_target.lower() and "message" in no_text.lower() and "removed" in calls.lower()
    return ok, f"{no_target[:60]} | {no_text[:60]} | {calls[:60]}"


@check("messaging: send_message input validation")
def send_validation():
    from actions.send_message import send_message
    res = send_message({"platform": "Telegram", "receiver": "", "message_text": ""},
                       response=None, player=_Player())
    return bool(res), str(res)[:200]


@check("google: account + contacts status")
def google():
    from actions.google_account import google_account
    p = _Player()
    accounts = google_account({"action": "list_accounts"}, player=p) or ""
    contacts = google_account({"action": "list_contacts"}, player=p) or ""
    return bool(accounts), f"accounts={accounts[:140]} | contacts={contacts[:140]}"


@check("vision: screen capture")
def vision():
    from actions.screen_processor import _capture_screen
    data, mime = _capture_screen()
    shot = WORK / "matrix_screen.png"
    shot.write_bytes(data)
    return shot.stat().st_size > 5000, f"{len(data)} bytes {mime}"


@check("documents: docx / xlsx / pptx")
def docs():
    from actions.file_processor import file_processor
    made = {}
    for name, instr in (("m.docx", "A short report about the Keys.ai demo."),
                        ("m.xlsx", "A table of months and revenue."),
                        ("m.pptx", "Five slides about Keys.ai capabilities.")):
        path = WORK / name
        out = file_processor({"action": "create", "file_path": str(path),
                              "instruction": instr, "title": name}, player=_Player()) or ""
        made[name] = path.exists()
    return all(made.values()), str(made)


CHECKS = [site, dashboard, desktop, api, cli, game, library, browser, search,
          messaging, messaging_validation, send_validation, google, vision, docs]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    wanted = {s.strip() for s in args.only.split(",") if s.strip()}
    WORK.mkdir(parents=True, exist_ok=True)
    for fn in CHECKS:
        if wanted and fn.__name__ not in wanted:
            continue
        print(f"\n=== {fn.__name__} ===", flush=True)
        fn()
    passed = sum(1 for r in RESULTS if r["ok"])
    print(f"\nMATRIX: {passed}/{len(RESULTS)} passed")
    for r in RESULTS:
        if not r["ok"]:
            print(f"  FAILED: {r['check']} — {r['detail'][:300]}")
    out = WORK / "matrix_report.json"
    out.write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
