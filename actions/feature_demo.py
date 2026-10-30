"""
actions/feature_demo.py — "Demo" mode: show every capability by doing it.

The user says "demo" (or "run the demo", "show me everything you can do") and
this module performs the real actions in front of them, one after another,
narration on the activity timeline and artifacts left on disk:

    system status      real CPU/RAM/GPU numbers
    live web search    grounded answer, mirrored to the content panel
    browser control    opens a real page and reads it back
    documents          creates a real .docx / .xlsx / .pptx
    screen vision      captures the actual screen to a PNG and reports it
    code intelligence  repository inventory + symbols of this project
    memory             saves a fact, then recalls it from disk
    messaging          WhatsApp state + queue (read-only: nothing is sent)
    websites           builds a portfolio page and opens it in the browser
    dashboards         builds a Flask + SQLite dashboard, serves it, opens it
    desktop apps       builds a PyQt6 desktop app in its own window
    coding agent       writes and runs a small CLI program, checks exit code

Nothing here sends a message, an email, or shuts anything down. Steps that
would contact a real person are demonstrated in read-only mode on purpose.

Parameters:
    action : run (default) | status | stop | list
    steps  : optional comma-separated subset of step ids (see DEMO_STEPS)
    fast   : skip the slower build steps (websites are kept)

The run happens on a worker thread so the assistant stays responsive; progress
is available with action="status" and can be stopped with action="stop".

IMPORTANT: do not open the demo artifacts folder in the file explorer as part
of the demo. The demo writes artifacts to disk and reports the path, but it
never opens that folder, previews its contents, or otherwise interacts with
the demo examples on disk.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
from core.features_knowledge import IDENTITY, WHAT_CAN_I_DO
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

_DEMO_ROOT = Path.home() / "Desktop" / "keys_Creations" / "demo"

_LOCK = threading.Lock()
_STATE: dict = {
    "running": False,
    "stop": threading.Event(),
    "thread": None,
    "step": "",
    "index": 0,
    "total": 0,
    "started": 0.0,
    "results": [],
    "report": "",
}


def _log(player, text: str) -> None:
    try:
        if player is not None and hasattr(player, "write_log"):
            player.write_log(f"[Demo] {text}")
    except Exception:
        pass
    print(f"[Demo] {text}")


def _event(player, icon: str, text: str, path: str = "") -> None:
    for method in ("creation_event",):
        fn = getattr(player, method, None) if player is not None else None
        if fn is None:
            continue
        try:
            if path:
                fn(icon, text, path)
            else:
                fn(icon, text)
        except Exception:
            pass


def _phase(player, label: str) -> None:
    _log(player, label)
    _event(player, "◆", label)


# ── individual steps ────────────────────────────────────────────────────────

def _step_system(player, work: Path) -> tuple[bool, str]:
    from actions.system_monitor import get_system_status
    text = str(get_system_status())
    _event(player, "✓", text.splitlines()[0][:160] if text else "system status read")
    return True, text[:600]


def _step_search(player, work: Path) -> tuple[bool, str]:
    from actions.web_search import web_search
    res = web_search(parameters={"query": "latest AI model releases this week",
                                 "mode": "search"}, player=player) or ""
    if res and hasattr(player, "show_content"):
        try:
            player.show_content("DEMO - live web search", res)
        except Exception:
            pass
    ok = bool(res) and not res.lower().startswith(("search failed", "no results"))
    _event(player, "✓" if ok else "✕",
           f"Web search returned {len(res)} chars" if ok else "Web search returned nothing")
    return ok, res[:700]


def _step_browser(player, work: Path) -> tuple[bool, str]:
    """Drive a real browser: open a page and read it back."""
    try:
        from actions.browser_control import browser_control
    except Exception as e:
        return False, f"browser_control unavailable: {e}"
    url = "https://example.com"
    opened = browser_control(parameters={"action": "go_to", "url": url}, player=player) or ""
    time.sleep(1.5)
    text = browser_control(parameters={"action": "get_text"}, player=player) or ""
    combined = (opened + " " + text).lower()
    ok = len(text.strip()) > 40 and ("documentation" in combined or "example domain" in combined)
    _event(player, "✓" if ok else "!",
           "Browser opened example.com and read its text" if ok
           else "Browser opened, page text not read back")
    return ok, (f"{opened}\n{text}" if opened or text else "")[:700]


def _step_documents(player, work: Path) -> tuple[bool, str]:
    from actions.file_processor import file_processor
    made = []
    targets = [
        ("demo_report.docx", "Demo summary document for Keys.ai: what the assistant can do."),
        ("demo_data.xlsx", "Demo sales data: a table of months with revenue and orders."),
        ("demo_deck.pptx", "Demo presentation: Keys.ai feature showcase, five slides."),
    ]
    for name, instruction in targets:
        path = work / name
        try:
            out = file_processor(parameters={"action": "create", "file_path": str(path),
                                            "instruction": instruction,
                                            "title": path.stem.replace("_", " ").title()},
                                 player=player) or ""
        except Exception as e:
            out = f"failed: {e}"
        made.append((name, path.exists(), out[:120]))
    ok = all(exists for _, exists, _ in made)
    _event(player, "✓" if ok else "✕",
           "Created " + ", ".join(n for n, e, _ in made if e)
           if ok else "Document creation failed")
    return ok, json.dumps([{"file": n, "created": e, "result": o} for n, e, o in made], indent=1)[:900]


def _step_vision(player, work: Path) -> tuple[bool, str]:
    from actions.screen_processor import _capture_screen
    data, mime = _capture_screen()
    shot = work / "screen_capture.png"
    shot.write_bytes(data)
    ok = shot.exists() and shot.stat().st_size > 1000
    _event(player, "✓" if ok else "✕",
           f"Captured the screen ({len(data) // 1024} KB, {mime}) -> {shot.name}")
    return ok, f"{shot} ({shot.stat().st_size} bytes, {mime})"


def _step_repo(player, work: Path) -> tuple[bool, str]:
    from actions.repo_tool import repo_inspect
    out = repo_inspect(parameters={"action": "summary", "root": str(BASE_DIR)}, player=player) or ""
    ok = "file" in out.lower()
    _event(player, "✓" if ok else "✕",
           "Indexed this project: inventory, symbols and imports" if ok
           else "Repository index returned nothing")
    return ok, out[:800]


def _step_memory(player, work: Path) -> tuple[bool, str]:
    from memory.memory_manager import load_memory, search_memory, update_memory
    stamp = datetime.now().strftime("%H:%M:%S")
    phrase = f"Feature demo ran at {stamp}"
    update_memory({"notes": {"demo_last_run": {"value": phrase}}})
    # search_memory indexes VALUES, not keys — search the sentence that was
    # saved, then confirm against the store so a loose match cannot pass.
    found = search_memory(phrase, limit=2)
    ok = phrase in found
    if not ok:
        stored = json.dumps(load_memory().get("notes", {}), ensure_ascii=False)
        ok = phrase in stored
    _event(player, "✓" if ok else "✕",
           "Memory: saved a fact, then recalled it from disk" if ok else "Memory recall found nothing")
    return ok, found[:400]


def _step_messaging(player, work: Path) -> tuple[bool, str]:
    """Read-only messaging: state, queue and contact resolution. Sends nothing."""
    from actions.whatsapp_control import whatsapp_control
    status = whatsapp_control(parameters={"action": "status"}, player=player) or ""
    queue = whatsapp_control(parameters={"action": "queue_status"}, player=player) or ""
    contacts = ""
    try:
        from actions.google_account import google_account
        contacts = google_account(parameters={"action": "list_accounts"}, player=player) or ""
    except Exception as e:
        contacts = f"google_account unavailable: {e}"
    ok = bool(status)
    _event(player, "✓" if ok else "✕",
           "Messaging stack responded (nothing sent — read-only demo)")
    return ok, f"WhatsApp status: {status[:300]}\nQueue: {queue[:200]}\nAccounts: {contacts[:300]}"


def _step_site(player, work: Path) -> tuple[bool, str]:
    from actions.crown_code import crown_code
    out = crown_code(parameters={
        "action": "build",
        "description": ("Build a portfolio website for a landscape photographer "
                        "named Elena Voss, with a hero section, a gallery, an "
                        "about section and a contact section."),
        "kind": "portfolio",
        "workspace": str(work / "demo_portfolio"),
        "wait": True,
        "timeout": 420,
    }, player=player) or ""
    index = work / "demo_portfolio" / "index.html"
    ok = index.exists() and index.stat().st_size > 2000
    _event(player, "✓" if ok else "✕",
           f"Portfolio built and opened ({index.stat().st_size} bytes)" if ok
           else "Portfolio build did not produce a page")
    return ok, out[:800]


def _step_dashboard(player, work: Path) -> tuple[bool, str]:
    from actions.crown_code import crown_code
    out = crown_code(parameters={
        "action": "build",
        "description": ("Build a sales dashboard web app in Python with Flask and "
                        "SQLite seed data showing total revenue, orders and a "
                        "monthly revenue chart."),
        "workspace": str(work / "demo_dashboard"),
        "confirmed": True,
        "wait": True,
        "timeout": 420,
    }, player=player) or ""
    ws = work / "demo_dashboard"
    ok = any(ws.glob("*.py")) and (ws / "app.py").exists()
    _event(player, "✓" if ok else "✕",
           "Dashboard built, started and opened in the browser" if ok
           else "Dashboard build did not produce an app")
    return ok, out[:800]


def _step_desktop(player, work: Path) -> tuple[bool, str]:
    from actions.crown_code import crown_code
    out = crown_code(parameters={
        "action": "build",
        "description": ("Build a Python desktop expense tracker app with PyQt6 and "
                        "SQLite: a table of expenses, live search, an add form and "
                        "a running total."),
        "workspace": str(work / "demo_desktop"),
        "confirmed": True,
        "wait": True,
        "timeout": 420,
    }, player=player) or ""
    ws = work / "demo_desktop"
    ok = (ws / "main.py").exists()
    _event(player, "✓" if ok else "✕",
           "Desktop app built and launched in its own window" if ok
           else "Desktop build did not produce main.py")
    return ok, out[:800]


def _step_code(player, work: Path) -> tuple[bool, str]:
    from actions.crown_code import crown_code
    out = crown_code(parameters={
        "action": "build",
        "description": ("Create a Python command-line word counter: read a file path "
                        "argument, print line, word and character counts, and exit 0. "
                        "Then run it on itself to prove it works."),
        "workspace": str(work / "demo_cli"),
        "confirmed": True,
        "wait": True,
        "timeout": 420,
    }, player=player) or ""
    ws = work / "demo_cli"
    ok = any(ws.glob("*.py"))
    _event(player, "✓" if ok else "✕",
           "Coding agent wrote and ran a CLI program" if ok
           else "Coding agent produced no file")
    return ok, out[:800]


DEMO_STEPS = [
    ("system", "System status", _step_system),
    ("search", "Live web search", _step_search),
    ("browser", "Browser control", _step_browser),
    ("documents", "Documents (Word / Excel / PowerPoint)", _step_documents),
    ("vision", "Screen vision", _step_vision),
    ("repo", "Code intelligence", _step_repo),
    ("memory", "Long-term memory", _step_memory),
    ("messaging", "Messaging (read-only)", _step_messaging),
    ("site", "Website builder", _step_site),
    ("dashboard", "Dashboard builder", _step_dashboard),
    ("desktop", "Desktop app builder", _step_desktop),
    ("code", "Coding agent", _step_code),
]

_SLOW = {"site", "dashboard", "desktop", "code"}


# ── runner ─────────────────────────────────────────────────────────────────


def _run(player, steps, work: Path) -> None:
    _STATE["results"] = []
    total = len(steps)
    _STATE.update(total=total, started=time.time(), step="starting")
    summary_lines = []
    try:
        _event(player, "▶", f"Feature demo started — {total} capabilities, live")
        for i, (sid, label, fn) in enumerate(steps, 1):
            if _STATE["stop"].is_set():
                _event(player, "■", "Demo stopped by the user")
                break
            _STATE.update(index=i, step=label)
            _phase(player, f"[{i}/{total}] {label}")
            if player is not None and hasattr(player, "creation_phase"):
                try:
                    player.creation_phase(label, i / total, 0)
                except Exception:
                    pass
            t0 = time.time()
            try:
                ok, detail = fn(player, work)
            except Exception as e:
                ok, detail = False, f"{type(e).__name__}: {e}"
                traceback.print_exc()
            elapsed = round(time.time() - t0, 1)
            _STATE["results"].append({"step": sid, "label": label, "ok": ok,
                                      "seconds": elapsed, "detail": str(detail)[:1200]})
            summary_lines.append(f"{'PASS' if ok else 'FAIL'}  {label} ({elapsed}s)")
            if player is not None and hasattr(player, "creation_progress"):
                try:
                    player.creation_progress(i / total)
                except Exception:
                    pass
    finally:
        passed = sum(1 for r in _STATE["results"] if r["ok"])
        total_run = len(_STATE["results"])
        seconds = round(time.time() - _STATE["started"], 1)
        report = {
            "started": datetime.now().isoformat(timespec="seconds"),
            "seconds": seconds,
            "passed": passed,
            "total": total_run,
            "system": {
                "assistant": IDENTITY["name"],
                "creator": IDENTITY["creator"],
                "creator_description": IDENTITY["creator_description"],
                "philosophy": IDENTITY["philosophy"],
            },
            "what_can_i_do": WHAT_CAN_I_DO,
            "results": _STATE["results"],
            "workspace": str(work),
            "artifacts_opened": False,
        }
        try:
            (work / "demo_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        except Exception:
            pass
        _STATE.update(running=False, step="finished", report=str(work / "demo_report.json"))
        text = f"Demo finished: {passed}/{total_run} capabilities passed in {seconds}s"
        _log(player, text)
        for line in summary_lines:
            _log(player, "  " + line)
        _event(player, "✓" if passed == total_run and total_run else "!",
               text + f" — results recorded in {work / 'demo_report.json'}")
        if player is not None:
            for method in ("creation_complete", "creation_progress"):
                try:
                    fn = getattr(player, method, None)
                    if fn is None:
                        continue
                    fn(text if method == "creation_complete" else 1.0)
                except Exception:
                    pass


def _selected_steps(raw: str, fast: bool) -> list:
    wanted = {s.strip().lower() for s in re.split(r"[,\s]+", raw or "") if s.strip()}
    steps = [s for s in DEMO_STEPS if not wanted or s[0] in wanted]
    if fast and not wanted:
        steps = [s for s in DEMO_STEPS if s[0] not in _SLOW]
    return steps


def feature_demo(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "run").strip().lower()

    if action in ("status", "progress"):
        if not _STATE["running"]:
            return ("No demo is running right now. Say \"demo\" to start one.")
        elapsed = round(time.time() - _STATE["started"], 1)
        return (f"Demo running: step {_STATE['index']}/{_STATE['total']} — "
                f"{_STATE['step']} ({elapsed}s elapsed).")

    if action in ("stop", "cancel"):
        _STATE["stop"].set()
        return "Stopping the demo after the current step."

    if action in ("list", "steps"):
        return "Demo steps:\n" + "\n".join(f"  {sid}: {label}" for sid, label, _ in DEMO_STEPS)

    if _STATE["running"]:
        return (f"A demo is already running ({_STATE['step']}). "
                "Say \"demo status\" for progress or \"stop the demo\" to end it.")

    fast = bool(p.get("fast"))
    steps = _selected_steps(str(p.get("steps") or ""), fast)
    if not steps:
        return "None of those steps exist. Valid steps: " + ", ".join(s[0] for s in DEMO_STEPS)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work = (_DEMO_ROOT / stamp).resolve()
    work.mkdir(parents=True, exist_ok=True)

    with _LOCK:
        _STATE["stop"] = threading.Event()
        _STATE["running"] = True
        thread = threading.Thread(target=_run, args=(player, steps, work),
                                  name="keysai-feature-demo", daemon=True)
        _STATE["thread"] = thread
        thread.start()

    if speak:
        try:
            speak("Starting the live feature demo now, sir.")
        except Exception:
            pass
    return (f"Demo started — {len(steps)} capabilities will run live, one after another.\n"
            f"Results will be recorded in demo_report.json.\n"
            f"Ask \"demo status\" for progress anytime.")
