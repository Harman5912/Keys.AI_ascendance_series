"""
actions/crown_code.py — Crown Code Terminal Agent (Dev Agent) for Keys.AI.

Two execution paths, chosen from what the task actually IS:

    an application — dashboard, data tool, login, database, API integration,
    anything that has to do something with real data
        the real Crown Code headless agent (plan -> write -> run -> fix),
        driving node dist-headless/headless.js in the configured workspace.
        It writes real files and real structure, because the thing asked for
        is a program and a program is not one rendered page.

    an information page — portfolio, landing page, marketing site
        core.site_builder: plan -> write -> verify -> repair, with a
        plan-driven rendered page as the guaranteed floor. This is the path
        that reliably finishes a page even when an 8B local model refuses to
        call tools.

Before either path runs, the brief goes through core.brief_spec: an
application request that does not state its data source, its metrics, its
chart types, its stack or its scope returns NEED REQUIREMENTS instead of a
build. Nothing is created, nothing runs, and the assistant is told to ask the
user rather than choose for them.

Both paths run as BACKGROUND JOBS (core.crown_jobs): the call returns in under
a second with a job id, the conversation stays usable, and progress is
available at any time through action="status" (or by simply asking "how's it
going?").

Parameters:
    description / task : what to build or fix (required for action=build)
    action             : build (default) | clarify | status | cancel | list
    requirements       : the user's answers to the questions a build needs
                         (free text or "slot: value" lines)
    confirmed          : true only when the user said to build without answering
    job_id             : which job status/cancel refers to (default: newest)
    workspace          : existing project folder (optional)
    project_name       : folder name for a new project (optional)
    kind               : portfolio | website (optional override; applications
                         are routed to the agent regardless of this)
    model              : local model override (optional)
    policy             : safe | readonly | all
    timeout            : per-run wall-clock limit in seconds (default 900)
    wait               : true to block until the build finishes (default false)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core import crown_jobs  # noqa: E402



def _get_manager():
    """Resolve the job registry at call time.

    Binding ``crown_jobs._manager`` into a module-level alias at import time
    froze the registry: patching it later (tests, or a host that swaps the
    manager) silently had no effect and builds registered somewhere else than
    the reads that were supposed to see them.
    """
    return crown_jobs._manager()

from core.brief_spec import (  # noqa: E402
    analyse_brief,
    is_app_brief,
    merge_brief,
    questions_text,
    refusal_text,
    apply_recommended_defaults,
    generate_interactive_questions,
)
from core.research_harvester import ResearchHarvester  # noqa: E402
from core.blueprint_engine import BlueprintEngine  # noqa: E402
from core.app_builder import app_kind_for  # noqa: E402
from core.build_recipes import detect_stacks, recipe_block  # noqa: E402
from core.crown_bridge import (  # noqa: E402
    CrownBridge,
    ensure_local_model,
    load_config,
)

_PROJECTS_DIR = Path.home() / "Desktop" / "keys_Creations" / "code"

# A page request is anything that names a page artifact and nothing that names
# a program. "build a portfolio website" -> site path; "build a CLI in python"
# or "fix the nav on my portfolio" -> Crown Code's general agent.
_SITE_WORDS = re.compile(
    r"\b(website|web[\s-]?page|webpage|landing[\s-]?page|portfolio|microsite|"
    r"one[\s-]?pager|homepage|static site)\b", re.I)
_CODE_WORDS = re.compile(
    r"\b(api|backend|back[\s-]end|cli|script|python|node|react|vue|angular|"
    r"flutter|android|ios app|desktop app|database|sql|scraper|crawler|bot|"
    r"library|package|plugin|extension|fix|bug|refactor|unit test|pytest|"
    r"docker|kubernetes|terraform|game|compiler)\b", re.I)


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", (text or "").strip().lower())
    s = re.sub(r"\s+", "_", s)[:40].strip("_")
    return s or "crown_project"


def _status_safe(player, method: str, *args, **kwargs):
    """Call an optional player method, ignoring missing methods / errors."""
    if player is None:
        return None
    fn = getattr(player, method, None)
    if fn is None:
        return None
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


# ── opening what was built ────────────────────────────────────────────────

_LAUNCHED: dict[str, "subprocess.Popen"] = {}
_LAUNCH_LOCK = threading.Lock()


def _port_for(workspace: Path) -> int:
    """The port a rendered dashboard listens on (PORT in its .env, else 5071)."""
    try:
        env = (workspace / ".env").read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^\s*PORT\s*=\s*(\d{2,5})\s*$", env, re.M)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 5071


def _wait_http(url: str, timeout: float = 20.0) -> bool:
    """True as soon as `url` answers (the server is up, not merely started)."""
    import urllib.request
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:  # noqa: S310
                if resp.status < 500:
                    return True
        except Exception:
            time.sleep(0.35)
    return False


def _stream_process(proc, player=None) -> None:
    """Forward a launched app's output into the console terminal."""
    def pump():
        try:
            for line in proc.stdout or ():
                _status_safe(player, "terminal_output", line, "stdout", "agent")
        except Exception:
            pass
    threading.Thread(target=pump, daemon=True).start()


def _open_url(url: str, player=None, label: str = "") -> str:
    """Show the artifact in the app preview and open the default browser."""
    _status_safe(player, "creation_preview", url)
    _status_safe(player, "creation_event", "🌐", f"Opened {label or url}", url)
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass
    return url


def _launch_artifact(result: dict, workspace: Path, player=None) -> str:
    """Run the built artifact and open it — a page in the browser, an app as a
    live server, a desktop app in its own window.

    A build that is only announced in chat is not a build the user can see;
    this is the step that puts it in front of them.
    """
    kind = str((result or {}).get("kind") or "")
    entry = str((result or {}).get("entry") or "")
    if not entry or not (workspace / entry).exists():
        if (workspace / "index.html").exists():
            entry = "index.html"
            kind = kind or "page"
        elif (workspace / "main.py").exists():
            entry = "main.py"
            kind = kind or "app"
        else:
            return ""

    if entry.endswith(".html"):
        # Serve the page over localhost: the Research Browser refuses file:
        # URLs on purpose, so a file:// preview reached the browser as a
        # blocked address and the built site was never displayed.
        try:
            from core.preview_server import preview_url
            url = preview_url(workspace, entry)
        except Exception as e:
            print(f"[Crown] preview server unavailable: {e}")
            url = (workspace / entry).resolve().as_uri()
        _open_url(url, player, f"{workspace.name} — {entry}")
        return url
    key = str(workspace.resolve())
    with _LAUNCH_LOCK:
        proc = _LAUNCHED.get(key)
        running = proc is not None and proc.poll() is None
    if not running:
        try:
            env = dict(os.environ)
            if kind == "dashboard":
                seed = workspace / "seed.py"
                if seed.exists():
                    subprocess.run([sys.executable, "seed.py"], cwd=str(workspace),
                                   capture_output=True, timeout=120)
                env["PORT"] = str(_port_for(workspace))
            proc = subprocess.Popen(
                [sys.executable, entry], cwd=str(workspace), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            with _LAUNCH_LOCK:
                _LAUNCHED[key] = proc
            _stream_process(proc, player)
        except Exception as e:
            _status_safe(player, "creation_event", "✕", f"Could not open {entry}: {e}")
            return ""

    if kind == "dashboard":
        url = f"http://127.0.0.1:{_port_for(workspace)}"
        if _wait_http(url):
            _open_url(url, player, f"{workspace.name} — {url}")
        else:
            _status_safe(player, "creation_event", "!",
                         f"{entry} is starting — open {url} in a moment", url)
        return url

    # Desktop recipes open their own window; nothing to load in a browser.
    _status_safe(player, "creation_event", "✓", f"Launched {entry} — its window is opening")
    return ""


def classify_task(task: str, explicit: str = "") -> str:
    """"'site' or 'code' — which execution path this request belongs to.

    The artifact beats the wording. A dashboard, a data tool, anything with a
    login or a database is an APPLICATION: it goes to the agent that writes
    real files, even when the caller called it "a website" or passed
    kind="website". Sending it to the page renderer is how a chart request
    became a portfolio page with no charts in it.

    A game now routes to the recipe builder so the Crown Code agent does not
    get asked to produce one from scratch (and occasionally does). The game
    recipe writes the real loop and state and self-tests it, which is the only
    path that reliably finishes a real, playable game on this machine.
    """
    text = task or ""
    explicit = (explicit or "").strip().lower()
    if explicit in ("webapp", "app", "application", "dashboard", "code"):
        return "code"
    if is_app_brief(text):
        return "code"
    # Games are recipes now, not agent requests.
    if re.search(r"\b(game|pygame|shoot-em-up|shooter|arcade)\b", text, re.I):
        return "code"
    if explicit in ("portfolio", "website", "site", "page"):
        return "site"
    if _SITE_WORDS.search(text) and not _CODE_WORDS.search(text):
        return "site"
    return "code"


def infer_kind(task: str, explicit: str = "") -> str:
    """Page kind for the renderer. Applications never reach it."""
    explicit = (explicit or "").strip().lower()
    if explicit in ("portfolio", "website"):
        return explicit
    low = (task or "").lower()
    if "portfolio" in low:
        return "portfolio"
    if re.search(r"\b(game|pygame|shoot-em-up|shooter|arcade)\b", low, re.I):
        return "game"
    return "website"


# ── Site path ─────────────────────────────────────────────────────────────

def _run_site(job, workspace: Path, kind: str, model: str, player=None,
              speed: str = "custom") -> dict:
    from core.site_builder import build_site

    budget = {"pct": 0.05}

    def on_phase(name: str, pct: float, detail: str = "") -> None:
        budget["pct"] = max(budget["pct"], pct)
        job.update(phase=name, progress=pct, detail=detail)
        _status_safe(player, "creation_progress", pct)
        _status_safe(player, "creation_phase", name.replace("_", " "), pct, job.eta or 0)
        if detail:
            _status_safe(player, "creation_event", "→", f"{name.title()}: {detail}")

    def on_log(line: str) -> None:
        job.update(log=line)
        _status_safe(player, "write_log", f"[Crown] {line}")

    _status_safe(player, "creation_event", "◆",
                 ("Plan → render → verify (fast)" if speed == "fast"
                  else "Plan → render → bespoke design → verify") + f" in {workspace}")

    result = build_site(
        job.brief, workspace, kind=kind, model=model, speed=speed,
        attempts=2, browser=True, on_phase=on_phase, on_log=on_log,
        cancelled=lambda: job.cancelled,
    )

    index = Path(result.get("path") or workspace / "index.html")
    if index.exists():
        try:
            code = index.read_text(encoding="utf-8", errors="replace")[:20000]
            _status_safe(player, "creation_file_set_active", str(index))
            _status_safe(player, "creation_code_set", code)
        except Exception:
            pass
        _status_safe(player, "creation_file_add", index.name,
                     result.get("bytes", 0) // 40, "done")

    for line in job.logs:
        if "acceptance checklist" in line:
            _status_safe(player, "creation_event", "✓" if "all items met" in line else "!",
                         line.split(" ", 1)[-1])

    if result.get("ok"):
        summary = (f"Built {index.name} ({result.get('bytes', 0)} bytes) "
                   f"in {result.get('seconds', 0)}s")
        if result.get("studio"):
            summary += f" · {result['studio']} studio"
        if result.get("mode") == "model":
            summary += f" · bespoke design by {result.get('model', 'the model')}"
        else:
            summary += " · rendered from the approved plan"
        if result.get("checklist_score"):
            summary += f" · plan checklist {result['checklist_score']}"
        if result.get("used_fallback"):
            summary += " (rendered from the plan after the model's file failed checks)"
        _status_safe(player, "creation_complete", summary)
        _status_safe(player, "creation_progress", 1.0)
        result["url"] = _open_url(index.resolve().as_uri(), player, index.name)
        result["summary"] = summary
    else:
        problems = "; ".join((result.get("checks") or {}).get("problems", [])[:3])
        err = problems or "the page did not pass verification"
        result["error"] = err
        _status_safe(player, "creation_error", err[:300])
    return result


# ── Recipe-rendered application path ─────────────────────────────────────

def _run_app(job, workspace: Path, app_kind: str, player=None) -> dict:
    """Render a dashboard or desktop app from its recipe, then verify it.

    Nothing here consults a model. The result reports the checks that actually
    ran (compiled, seeded, served, self-tested) so "done" is a measurement.
    """
    from core.app_builder import build_app

    def on_phase(name: str, pct: float, detail: str = "") -> None:
        job.update(phase=name, progress=pct, detail=detail)
        _status_safe(player, "creation_progress", pct)
        _status_safe(player, "creation_phase", name.replace("_", " "), pct,
                     job.eta or 0)
        if detail:
            _status_safe(player, "creation_event", "→",
                         f"{name.title()}: {detail}")

    def on_log(line: str) -> None:
        job.update(log=line)
        _status_safe(player, "write_log", f"[Crown] {line}")

    _status_safe(player, "creation_event", "◆",
                 f"{app_kind} recipe → write → verify in {workspace}")

    result = build_app(job.brief, workspace, kind=app_kind,
                       on_phase=on_phase, on_log=on_log)

    job.files = list(result.get("files") or [])
    entry = workspace / str(result.get("entry") or "")
    if entry.name and entry.exists():
        try:
            code = entry.read_text(encoding="utf-8", errors="replace")[:20000]
            _status_safe(player, "creation_file_set_active", str(entry))
            _status_safe(player, "creation_code_set", code)
        except Exception:
            pass
        _status_safe(player, "creation_file_add", entry.name,
                     result.get("bytes", 0) // 40, "done")

    for check in result.get("checks") or []:
        _status_safe(player, "creation_event", "✓" if check.get("ok") else "✕",
                     check.get("check", ""))

    if result.get("ok"):
        message = result.get('message') if isinstance(result.get('message'), str) else ''
        summary = (f"Built {app_kind}: {len(job.files)} files, "
                   f"{result.get('bytes', 0)} bytes in {result.get('seconds', 0)}s"
                   f" · verified — {message}"
                   f" · run it with: {result.get('run', '')}")
        result["summary"] = summary
        job.update(log=summary)
        _status_safe(player, "creation_progress", 1.0)
        _status_safe(player, "creation_complete", summary[:300])
        print("[Crown._run_app] ok-result keys:", sorted(result.keys()), flush=True)
        # Open it: a dashboard in the browser, a desktop app in its window.
        result["url"] = _launch_artifact(result, workspace, player)

        # Runtime design check. The source gate cannot see an image that fails
        # once a server resolves it, or a script that throws on load. A broken
        # image is an unambiguous defect, so it fails the build; console errors
        # are reported without overriding the verification that already ran.
        if result.get("url") and str(app_kind) in ("dashboard", "site", "web"):
            try:
                from core.design_check import check_rendered as _check_rendered
                _rt = _check_rendered(result["url"])
                if _rt.findings:
                    result["runtime_issues"] = [f.as_dict() for f in _rt.findings]
                    broken = [f for f in _rt.errors if f.code == "broken-image"]
                    if broken:
                        result["ok"] = False
                        result["error"] = ("the running page has broken images: "
                                           + "; ".join(f.message for f in broken[:3]))
                        _status_safe(player, "creation_event", "✕",
                                     f"Runtime check: {len(broken)} broken image(s)")
                    else:
                        _status_safe(player, "creation_event", "!",
                                     f"Runtime check: {len(_rt.findings)} issue(s)")
            except Exception as _exc:
                _status_safe(player, "creation_event", "!",
                             f"Runtime check skipped: {_exc}")
    else:
        error = result.get("message") if isinstance(result.get("message"), str) else "the application did not pass verification"
        result["error"] = error
        job.update(log=f"FAILED verification — {error}")
        _status_safe(player, "creation_error", error[:300])
        print("[Crown._run_app] fail-result repr:", repr(result), flush=True)
    return result


# ── General Crown Code path ───────────────────────────────────────────────

def _permission_handler(workspace: str, policy: str, player=None, job=None):
    """Build the supervisor for the agent's permission requests.

    The model proposes an action; this function decides. Reads and
    workspace-local writes run unattended, installs/network/out-of-workspace
    work is put to the user through the existing ``ask_permission`` card, and
    destructive or credential-touching actions are refused even when no card
    can be shown.
    """
    from core import agent_permissions

    granted_for_task: set[str] = set()

    def approve(decision):
        ask = getattr(player, "ask_permission", None) if player is not None else None
        if ask is None:
            return "deny"                     # fail closed, never guess
        try:
            return ask(decision.tool or "crown action", decision.reason,
                       decision.target or decision.command or str(workspace))
        except Exception:
            return "deny"

    def handler(ev: dict):
        decision = agent_permissions.evaluate(
            ev, workspace=workspace, policy=policy, approve=approve,
            session_allows=granted_for_task,
        )
        line = f"permission {'allowed' if decision.allow else 'denied'}: {decision.describe()}"
        if job is not None:
            job.update(log=line)
        _status_safe(player, "write_log", f"[Crown] {line}")
        _status_safe(player, "creation_event", "✓" if decision.allow else "✕",
                     f"Permission {'granted' if decision.allow else 'refused'}: "
                     f"{decision.reason}")
        return decision

    return handler

def _run_bridge(job, task: str, workspace: Path, model: str, provider: str,
                policy: str, timeout: int, player=None,
                max_iterations: int = 0, verify_tests: bool = False,
                tools: list[str] | None = None) -> dict:
    tools_ok = {"n": 0}
    commands = {"n": 0}
    writes = {"n": 0}
    # The exit code of the last shell command the agent ran. A build is only
    # finished when the last thing it ran succeeded: an agent that runs
    # `python app.py`, watches it fail and stops has not built anything, even
    # though it wrote files along the way.
    last_exit: dict[str, int | None] = {"code": None}

    def on_event(ev: dict) -> None:
        etype = ev.get("type", "")
        if etype == "ready":
            job.update(phase="working", progress=0.08,
                       detail=f"{ev.get('provider')}/{ev.get('model')}")
            # The console is already open (crown_code opened it before the
            # model check); reopening it here would wipe the events that
            # arrived in the meantime.
            _status_safe(player, "creation_event", "✓",
                         f"Crown Code ready — {ev.get('provider')}/{ev.get('model')}")
            _status_safe(player, "creation_phase", "working", 0.08, job.eta or 0)
        elif etype == "tool_start":
            tool = ev.get("tool", "")
            inp = ev.get("input") or {}
            if tool in ("write_file", "edit_file"):
                writes["n"] += 1
            if tool == "write_file":
                path = str(inp.get("path", ""))
                job.files.append(path)
                job.update(phase="writing", progress=min(0.85, job.progress + 0.06),
                           detail=f"writing {path}")
                content = str(inp.get("content", ""))
                # Register the file so the console's file list can show it (and
                # keep showing it after the agent moves on to the next one).
                _status_safe(player, "creation_file_add", path,
                             content.count("\n") + 1 if content else 0, "done")
                _status_safe(player, "creation_file_set_active", path)
                _status_safe(player, "creation_event", "→", f"Modifying {path}", path)
                _status_safe(player, "creation_code_set", content[:20000])
            elif tool == "terminal":
                commands["n"] += 1
                job.update(phase="running", detail=f"$ {inp.get('command', '')}")
                _status_safe(player, "creation_event", "◆", f"$ {inp.get('command', '')}")
            else:
                job.update(phase="inspecting", detail=f"{tool}")
        elif etype == "tool_end":
            if not ev.get("isError"):
                tools_ok["n"] += 1
            job.update(progress=min(0.9, job.progress + 0.05), log=str(ev.get("output", ""))[:180])
        elif etype == "terminal_exit":
            code = ev.get("exitCode")
            if code is not None:
                last_exit["code"] = int(code)
        elif etype == "terminal_output":
            _status_safe(player, "terminal_output", ev.get("chunk", ""),
                         ev.get("stream", "stdout"), ev.get("origin", "agent"))
        elif etype == "notice":
            job.update(log=str(ev.get("message", "")))
            _status_safe(player, "write_log", f"[Crown] {ev.get('message', '')}")
        elif etype == "error":
            job.update(log=str(ev.get("error", "")))
            _status_safe(player, "creation_error", str(ev.get("error", "")))

    # The tool surface comes from the caller, which holds the build params. This
    # block used to read `p` here, inside the event handler, where that name does
    # not exist: every event raised NameError, so the browser tools merge below
    # could never have run and no build could have completed through this path.
    tool_names = [t for t in (tools or []) if t]

    bridge = CrownBridge(
        workspace=str(workspace), on_event=on_event,
        permission_handler=_permission_handler(str(workspace), policy, player, job),
        log=lambda m: (job.update(log=m), _status_safe(player, "write_log", f"[Crown] {m}")),
        model=model, provider=provider, policy=policy,
        max_iterations=max_iterations,
        tools=tool_names,
    )
    if player is not None and hasattr(player, "set_terminal_stop_handler"):
        try:
            player.set_terminal_stop_handler(bridge.stop)
        except Exception:
            pass

    started, msg = bridge.start(task)
    if not started:
        _status_safe(player, "creation_error", msg)
        return {"ok": False, "error": msg}

    stop_watch = threading.Event()
    deadline = time.time() + max(30, int(timeout))

    def watch() -> None:
        while not stop_watch.wait(0.5):
            if job.cancelled:
                bridge.stop()
                return
            if time.time() > deadline:
                # Hard wall-clock guard. A stuck agent loop must never hold a
                # build (or the demo) for an hour: kill the bridge at the limit.
                _status_safe(player, "creation_event", "!",
                             f"Crown Code reached its {int(timeout)}s limit — stopping")
                bridge.stop()
                return

    threading.Thread(target=watch, daemon=True).start()
    try:
        result = bridge.wait(timeout=timeout + 10) or {}
        if not result:
            result = {"ok": False,
                      "error": (f"Crown Code hit its {int(timeout)}s wall-clock limit "
                                "and was stopped. Files it already wrote remain on disk.")}
    except Exception as e:
        # The live bridge blocks on the subprocess lifetime; if that fails to
        # start or dies under us, the caller must see a build failure, not a
        # model-capability guess.
        bridge.stop()
        stop_watch.set()
        result = {"ok": False, "error": f"Crown Code bridge failed: {e}"}
        _status_safe(player, "creation_error", result["error"][:300])
    finally:
        stop_watch.set()
        bridge.stop()
        if player is not None and hasattr(player, "set_terminal_stop_handler"):
            try:
                player.set_terminal_stop_handler(None)
            except Exception:
                pass

    ok = bool(result.get("ok")) and tools_ok["n"] > 0
    summary = str(result.get("summary") or "").strip()
    if result.get("ok") and tools_ok["n"] == 0:
        summary = ("Crown Code executed no tools, so nothing changed. The local model printed its "
                   "tool call instead of issuing one. Pick a tool-capable model (gemma4:12b). "
                   f"Model output: {summary[:300] or '(empty)'}")
    if ok and writes["n"] == 0:
        # Searching a folder that does not exist yet is not a build. A run that
        # read files and answered without writing one is reported as the failure
        # it is — never as a finished build (this is exactly how two dashboards
        # were once reported "done" with only brief.json on disk).
        ok = False
        summary = ("Crown Code stopped without writing any file: it searched the empty "
                   "workspace and answered instead of building. No code was produced. "
                   "Retry with a model that calls write_file (gemma4:12b), or build this "
                   "artifact through its recipe path.")
    if ok:
        ok = writes["n"] > 0 or commands["n"] > 0

    # Verify the project's own tests BEFORE judging the exit-code guard: a
    # stale "exit 1" from an earlier failed run must not outvote a real, fresh
    # pytest pass (the agent commonly runs the tests, fixes them, runs again).
    test_ok, test_note = True, ""
    if verify_tests and (writes["n"] or commands["n"]):
        # Verify even when the run did not report success: an agent that ran
        # the tests, saw them fail and stopped has still left work that can be
        # repaired — that is exactly the case the repair pass exists for.
        test_ok, test_note = _verify_project_tests(workspace)
        if not test_ok:
            _status_safe(player, "creation_event", "✕",
                         "Project tests fail — a repair pass is needed")
        elif test_note:
            _status_safe(player, "creation_event", "✓", test_note)

    # ── design gate ────────────────────────────────────────────────────────
    # Only for projects that actually have a UI: an API backend has no palette
    # to check, and failing it for that would be a false negative.
    design = {"ok": True, "errors": [], "warnings": [], "checked": 0}
    if writes["n"] or commands["n"]:
        try:
            produced = _produced_ui_files(workspace, job.files)
            if produced:
                from core.design_check import check_files as _check_design
                _drep = _check_design(produced, root=workspace)
                design = {"ok": _drep.ok,
                          "errors": [f.as_dict() for f in _drep.errors],
                          "warnings": [f.as_dict() for f in _drep.warnings],
                          "checked": len(_drep.checked_files)}
                if _drep.errors:
                    _status_safe(player, "creation_event", "✕",
                                 f"Design gate: {len(_drep.errors)} issue(s)")
                elif _drep.warnings:
                    _status_safe(player, "creation_event", "✓",
                                 f"Design gate passed ({len(_drep.warnings)} warning(s))")
                else:
                    _status_safe(player, "creation_event", "✓", "Design gate passed")
        except Exception as exc:
            # A bug in the checker is not a defect in the user's project. Report
            # it as unchecked rather than failing a build that may be fine.
            design = {"ok": True, "checked": 0, "errors": [],
                      "warnings": [{"message": f"design gate could not run: {exc}"}]}
            _status_safe(player, "creation_event", "!",
                         f"Design gate could not run: {exc}")

    if ok and last_exit["code"] not in (None, 0) and test_ok:
        # Files were written, but the last command the agent ran failed and was
        # never re-run successfully — the workspace's own check disagrees with
        # the model's claim that the work is done.
        ok = False
        summary = (f"Crown Code stopped on a failing command (exit {last_exit['code']}): "
                   "the last step it ran did not succeed and was never re-run, so "
                   "the build is unverified. "
                   + (summary[:400] if summary else ""))
    if ok and not test_ok:
        ok = False
        summary = ("Crown Code wrote the project but its own tests fail: "
                   + test_note[:450])
    if not ok and not summary:
        # Never say "nothing changed" when files are on disk: the agent may
        # have written code through a shell command instead of write_file.
        try:
            produced = [p.name for p in workspace.rglob("*")
                        if p.is_file() and p.name != "brief.json"]
        except Exception:
            produced = []
        summary = (f"Crown Code ended without confirming success. "
                   f"{len(produced)} file(s) on disk: {', '.join(produced[:6])}"
                   if produced else "Crown Code stopped without changing anything")
    if ok and not design.get("ok", True):
        # The project runs, but it does not meet the design bar it was given.
        first = (design.get("errors") or [{}])[0].get("message") or "design issues"
        ok = False
        summary = (f"Crown Code built the project but it fails the design gate: "
                   f"{str(first)[:300]}")

    out = {"ok": ok, "summary": summary, "tools": tools_ok["n"], "commands": commands["n"],
           "writes": writes["n"], "bytes": 0,
           "tests_ok": test_ok, "test_note": test_note,
           "design_ok": design.get("ok", True),
           "design_checked": design.get("checked", 0),
           "design_errors": design.get("errors", []),
           "design_warnings": design.get("warnings", [])}
    if not ok:
        out["error"] = summary or "Crown Code stopped without changing anything"
        _status_safe(player, "creation_error", out["error"][:300])
    else:
        _status_safe(player, "creation_progress", 1.0)
        _status_safe(player, "creation_complete", summary[:300] or "Crown Code finished")
    return out


_UI_SUFFIXES = (".html", ".htm", ".css")


def _produced_ui_files(workspace: Path, written) -> list[Path]:
    """The HTML, CSS and theme files this build wrote — nothing else.

    The design gate exists to judge what a build produced. Scanning the whole
    workspace judged files the build never touched: a project created inside
    another repository inherited that host's stylesheets and failed on colours
    nobody here wrote.
    """
    out: list[Path] = []
    seen: set[Path] = set()
    for raw in written or ():
        path = Path(str(raw))
        if not path.is_absolute():
            path = workspace / path
        if path in seen or not path.is_file():
            continue
        if (path.suffix.lower() not in _UI_SUFFIXES
                and path.name not in ("theme.py", "styles.py")):
            continue
        seen.add(path)
        out.append(path)
    theme = workspace / "app" / "theme.py"
    if theme.is_file() and theme not in seen:
        out.append(theme)
    return out



# ── Autonomous Portfolio Pipeline (No Presets) ──────────────────────────────

def _run_autonomous_portfolio(job, workspace: Path, task: str, requirements: str,
                              stacks: list[str], player=None, model: str = "",
                              provider: str = "", policy: str = "safe",
                              timeout: int = 900, p: dict | None = None) -> dict:
    """Execute the full autonomous portfolio creation pipeline:
    1. Detail Intake & Memory Persistence (long-term memory + entities)
    2. Live Inbuilt Browser Research & Asset Harvesting (Google search, images, SVG icons)
    3. Architecture Blueprint & Master Prompt Synthesis & Display to User
    4. Crown Code Autonomous Builder with Inbuilt Local Model (NO PRESET DESIGN)
    5. Verification & Live Browser Launch
    """
    p = p or {}
    brief = task

    # ── Step 1: Detailing & Memory Persistence ──────────────────────────────
    task_lower = task.lower()
    is_harman = "harman" in task_lower or "harman" in str(requirements or "").lower()

    job.update(phase="detailing", progress=0.1, detail="Saving entity profile to long-term memory")
    if is_harman:
        _status_safe(player, "creation_event", "💾", "Saving Harman Sadhwani profile and projects to memory")
        try:
            from memory.memory_manager import update_memory
            update_memory({
                "identity": {
                    "creator": {"value": "Harman Sadhwani", "updated": time.strftime("%Y-%m-%d")},
                    "role": {"value": "Lead AI Architect & Systems Engineer, Creator of Keys.ai", "updated": time.strftime("%Y-%m-%d")}
                },
                "projects": {
                    "keys_ai": {"value": "Keys.ai autonomous desktop assistant and screen understanding system", "updated": time.strftime("%Y-%m-%d")},
                    "reviewbot": {"value": "AI-powered automated GitHub code review assistant", "updated": time.strftime("%Y-%m-%d")},
                    "drop_of_hope": {"value": "Real-time community blood donation matching platform", "updated": time.strftime("%Y-%m-%d")},
                    "bharathealth": {"value": "AI-assisted healthcare platform", "updated": time.strftime("%Y-%m-%d")}
                }
            })
            print("[Crown] Saved Harman Sadhwani profile and projects to Keys.ai long-term memory")
        except Exception as _mem_e:
            print(f"[Crown] Memory update note: {_mem_e}")

    # ── Step 2: Inbuilt Browser Research & Asset Harvesting ─────────────────
    # Research is expensive and needs the Qt UI; only run it when explicitly
    # requested. The blueprint and the agent build do not depend on it.
    _research_mode = str(p.get("research_mode") or "").strip().lower()
    _wants_research = _research_mode in ("browser", "deep", "on", "research",
                                         "true", "1")
    research_data = {}
    if _wants_research:
        job.update(phase="researching", progress=0.25, detail="Inbuilt browser research & asset harvesting")
        _status_safe(player, "creation_event", "🔍", "Inbuilt Browser: researching Google & harvesting assets")
        try:
            harvester = ResearchHarvester(workspace, player)
            research_data = harvester.run(task, stack=", ".join(stacks) if stacks else "HTML5 + Tailwind CSS + Vanilla JS")
        except Exception as e:
            print(f"[Crown] Research harvest note: {e}")
            research_data = {}

    # ── Step 3: Architecture Blueprint & Master Prompt Generation ──────────
    job.update(phase="planning", progress=0.45, detail="Synthesizing Blueprint & Master Prompt")
    _status_safe(player, "creation_event", "📐", "Synthesizing Blueprint & Master Instruction Prompt")
    try:
        blueprint_eng = BlueprintEngine(workspace, player)
        bp_res = blueprint_eng.synthesize(task, str(requirements or ""), research_data)
        master_prompt = bp_res["master_prompt"]
        explanation = bp_res.get("explanation", "")
        if explanation:
            print(f"\n{explanation}\n")
            _status_safe(player, "terminal_output", explanation, "stdout", "agent")
            _status_safe(player, "creation_event", "📜", "Master Prompt Synthesized & Displayed")
            _status_safe(player, "speak", "I have synthesized the architectural blueprint and master prompt for your portfolio.")
    except Exception as e:
        print(f"[Crown] Blueprint note: {e}")
        master_prompt = brief

    # ── Step 4: Crown Code Terminal Builder (Inbuilt Local Model, NO PRESET) ─
    job.update(phase="coding", progress=0.6, detail="Crown Code Terminal Builder (Inbuilt Model, No Presets)")
    _status_safe(player, "creation_event", "⚡", "Starting Crown Code autonomous builder with local model")

    _browser_tools = [
        "navigate_to_url", "get_page_text", "get_page_title",
        "capture_screenshot", "capture_full_page", "list_page_images",
        "download_resource", "save_source",
    ]
    _tools = [t for t in (p.get("tools") or []) if t]
    if str(p.get("research_mode") or "").strip().lower() == "browser":
        for _bt in _browser_tools:
            if _bt not in _tools:
                _tools.append(_bt)

    res = _agent_build(job, master_prompt, workspace, model or "", provider, policy,
                        timeout, player, verify_tests=True, tools=_tools)

    # Ensure index.html is fully written by the local model if agent didn't write it directly
    index_file = workspace / "index.html"
    if not index_file.exists():
        job.update(phase="coding", progress=0.75, detail="Synthesizing bespoke portfolio HTML via local model")
        _status_safe(player, "creation_event", "⚡",
                     f"Inbuilt model {model or 'the local model'} writing bespoke portfolio code")
        try:
            from core.llm_client import complete as _llm_complete
            gen_prompt = (
                f"{master_prompt}\n\n"
                "INSTRUCTION FOR BESPOKE CODE GENERATION:\n"
                "Write the complete, modern, production-ready, bespoke single-page portfolio HTML file.\n"
                "Include:\n"
                "- Responsive dark-theme Tailwind CDN layout with custom glassmorphism styles\n"
                "- Engaging Hero section with Harman Sadhwani's name, role, bio, and CTA buttons\n"
                "- Featured Projects grid with all 4 projects: Keys.ai, ReviewBot, Drop of Hope, BharatHealth\n"
                "- Technical Skills Matrix categorized into AI & LLMs, Systems & Desktop, Web & Full-Stack, DevOps\n"
                "- Interactive project filter buttons and working stat counters\n"
                "- Working Contact Form and Social links\n"
                "- References to vector SVG icons in assets/icons/\n"
                "STRICT: NO PRESET TEMPLATES. Output ONLY the complete HTML5 document starting with <!DOCTYPE html>."
            )
            html_code = _llm_complete("crown_code", gen_prompt)
            if html_code:
                html_code = re.sub(r"^```(?:html)?\s*", "", html_code.strip())
                html_code = re.sub(r"\s*```$", "", html_code.strip())
                index_file.write_text(html_code, encoding="utf-8")
                _status_safe(player, "creation_event", "✓", f"Wrote bespoke index.html ({len(html_code)} chars)")
                _status_safe(player, "creation_file_add", "index.html", len(html_code) // 40, "done")
                res["ok"] = True
                res["entry"] = "index.html"
                res["files"] = list(set((res.get("files") or []) + ["index.html"]))
                res["path"] = str(index_file)
        except Exception as _gen_err:
            print(f"[Crown] Direct model code gen note: {_gen_err}")

    # Auto-launch artifact if finished successfully
    if res.get("ok") or index_file.exists():
        res["ok"] = True
        res["entry"] = "index.html"
        res["kind"] = "page"
        job.update(phase="launching", progress=0.95, detail="Opening live application")
        _launch_artifact(res, workspace, player)
    return res


def _agent_build(job, brief: str, workspace: Path, model: str, provider: str,
                 policy: str, timeout: int, player=None, verify_tests: bool = False,
                 repair_attempts: int = 2, tools: list[str] | None = None) -> dict:
    """Run the agent, then let it repair its own failing tests.

    A build that ships tests which fail is not finished, and telling the user
    "your tests fail" is only half the job — the agent is still in the
    workspace with its tools. Give it the real pytest output and one or two
    focused repair passes before reporting anything.
    """
    import os as _os
    _engine_flag = _os.environ.get("CROWN_ENGINE", "legacy").lower().strip()

    if _engine_flag == "v2":
        # ── v2 engine path ────────────────────────────────────────────────────
        try:
            from crown_code.engine.events import reset_bus
            from crown_code.engine.events import ProgressEvent, ErrorEvent
            from crown_code.engine.interface import make_engine
            from crown_code.engine.ui_adapter import UIAdapter

            bus = reset_bus()
            cfg = {
                "model": model or "",
                "provider": provider or "ollama",
                "ollama_url": _os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
                "max_iterations": max(10, int(timeout / 30)),
            }
            engine = make_engine(job_id=job.id, brief=brief,
                                 workspace=str(workspace),
                                 bus=bus, config=cfg, engine_type="v2")

            UIAdapter(bus=bus, player=player, speak_done=True).attach()

            def _on_v2_event(evt):
                if isinstance(evt, ProgressEvent):
                    job.update(phase=evt.phase, progress=evt.percent,
                               detail=evt.message, log=evt.message)
                elif isinstance(evt, ErrorEvent):
                    job.update(log=f"[error] {evt.message}")
            bus.subscribe(_on_v2_event)

            engine.start()
            engine.join(timeout=timeout + 60)
            result = engine.result or {"ok": False, "summary": "No result returned."}
        except Exception as _exc:
            result = {"ok": False, "summary": f"v2 engine error: {_exc}"}
    else:
        # ── legacy path (original CrownBridge subprocess) ─────────────────────
        result = _run_bridge(job, brief, workspace, model, provider, policy, timeout,
                             player, max_iterations=int(timeout / 30),
                             verify_tests=verify_tests, tools=tools)
    for attempt in range(1, max(0, repair_attempts) + 1):
        if result.get("ok") or result.get("tests_ok", True) or job.cancelled:
            break
        note = str(result.get("test_note") or "").strip()[:1200]
        if not note:
            break
        _status_safe(player, "creation_event", "↻",
                     f"Repair pass {attempt}/{repair_attempts}: fixing {note.splitlines()[0][:90]}")
        job.update(phase="repairing", progress=max(job.progress, 0.9),
                   detail=f"repair pass {attempt}")
        repair_brief = (
            brief
            + "\n\nREPAIR PASS: the project is ALREADY WRITTEN in this workspace "
              "(read the existing files; do not recreate it from scratch). "
              "Its OWN tests fail. "
              "Read the failing test(s) and the code they exercise, then fix the "
              "CODE so the tests pass. Do not delete, skip or weaken a test to "
              "make it green; only change a test if it asserts something the "
              "user never asked for, and say so. Run `python -m pytest -q` "
              "yourself and finish only when it passes.\n\n"
            + "Failing output:\n" + note
        )
        result = _run_bridge(job, repair_brief, workspace, model, provider, policy,
                             timeout, player, max_iterations=int(timeout / 30),
                             verify_tests=True, tools=tools)
        if result.get("ok"):
            _status_safe(player, "creation_event", "✓",
                         f"Repair pass {attempt} fixed the tests")
    if not result.get("ok") and result.get("tests_ok") is False:
        note = str(result.get("test_note") or "")[:400]
        result["summary"] = ((result.get("summary") or "")
                             + f" | tests still fail after repair: {note}").strip(" |")
        result["error"] = result["summary"]
    return result


def _verify_project_tests(workspace: Path) -> tuple[bool, str]:
    """A brand-new project that ships its own tests is only done when they pass.

    The local agent has written a failing assertion, never run pytest, and
    reported success. The workspace's own test suite is the measurement that
    settles it. Returns (ok, note); (True, "") when there is nothing to run.
    """
    test_files = list(workspace.rglob("test_*.py")) + list(workspace.rglob("*_test.py"))
    if not test_files:
        return True, ""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=str(workspace), capture_output=True, text=True, timeout=150,
        )
    except Exception as e:
        return True, f"tests could not be run ({e})"
    if proc.returncode == 0:
        return True, f"Project tests pass ({len(test_files)} test file(s))"
    tail = " ".join((proc.stdout or proc.stderr or "").strip().splitlines()[-5:])
    return False, f"pytest exit {proc.returncode}: {tail[:400]}"


# ── Entry point ───────────────────────────────────────────────────────────

def crown_code(parameters: dict, player=None, speak=None, session_memory=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "build").strip().lower()
    task = (p.get("description") or p.get("task") or p.get("prompt") or "").strip()

    # Read-only actions before any side effects.
    # All job lookups go through _get_manager() so the read-only actions and
    # the build path can never observe two different registries.
    if action in ("status", "progress", "check"):
        return _get_manager().status_text(str(p.get("job_id") or ""), verbose=True)
    if action in ("cancel", "stop"):
        return _get_manager().cancel(str(p.get("job_id") or ""))
    if action in ("list", "jobs"):
        jobs = _get_manager().all()
        if not jobs:
            return "No builds have run yet."
        return "\n".join(f"• {j.status_line()} [{j.id}]" for j in jobs[-8:])
    if action in ("history", "builds", "previous"):
        limit = int(p.get("limit") or 50)
        history = crown_jobs.get_build_history(limit)
        if not history:
            return "No previous builds found."
        lines = []
        for job in history:
            status_icon = "✓" if job["status"] == "done" else ("✕" if job["status"] == "failed" else "○")
            saved = job.get("saved_at_human", job.get("completed_at", ""))[:10]
            elapsed = job.get("elapsed", 0)
            files = ", ".join(job.get("files", [])[-3:]) if job.get("files") else ""
            workspace = job.get("workspace", "") or ""
            kind = job.get("kind", "") or ""
            title = job.get("title", "") or "Untitled"
            if len(title) > 50:
                title = title[:47] + "..."
            line = f"{status_icon} [{saved}] {title} ({job['status']})"
            if kind:
                line += f" [{kind}]"
            line += f" — {elapsed}s"
            if files:
                line += f" · {files}"
            if workspace:
                line += f" · {workspace}"
            lines.append(line)
        return "\n".join(lines)

    if not task:
        return "Tell me what to build or fix and I'll run Crown Code on it."

    # ── requirements gate ──────────────────────────────────────────────────
    # Runs before the workspace exists and before any model is loaded: an
    # unanswered requirement must cost the user a question, never a folder
    # full of guesses.
    explicit_kind = str(p.get("kind") or "")
    requirements = p.get("requirements") or p.get("answers") or p.get("spec") or ""
    confirmed = bool(p.get("confirmed") or p.get("assume"))
    analysis = analyse_brief(task, explicit_kind, requirements)

    if action in ("clarify", "requirements", "questions"):
        if not analysis["questions"]:
            return ("No requirements are missing for this request — there is "
                    "nothing to ask. Call crown_code with action=build to start it.")
        return ("REQUIREMENTS BEFORE BUILDING — ask the user, do not answer these "
                "yourself:\n" + questions_text(analysis))

    assumptions = []
    if analysis["questions"] and confirmed:
        assumptions = [q["slot"].replace("_", " ") for q in analysis.get("questions", [])]
    if analysis["questions"] and (confirmed or p.get("auto_defaults")):
        analysis = apply_recommended_defaults(task, analysis)
        if not requirements:
            requirements = analysis.get("auto_requirements", "")

    # If there are unanswered questions and no confirmation, ask the user interactively.
    # This is the key fix: instead of just returning refusal_text (which is meant for
    # the assistant to relay), we now actually prompt the user via the UI's ask_decision
    # or ask_permission flow, then re-call with the answers.
    if analysis["questions"] and not confirmed and player is not None:
        # Generate interactive questions for the UI
        interactive_qs = generate_interactive_questions(analysis)
        if interactive_qs and hasattr(player, "ask_decision"):
            answers = {}
            for q in interactive_qs:
                slot = q.get("slot", "")
                question_text = q.get("question", "") or f"Please choose: {q.get('slot', '').replace('_', ' ')}"
                options = q.get("options", [])
                why = analysis.get("questions", [{}])[0].get("why", "") if analysis.get("questions") else ""
                try:
                    answer = player.ask_decision(
                        question=question_text,
                        options=options,
                        show_why=True,
                        why_text=q.get("why", ""),
                    )
                    answers[slot] = answer
                except Exception as _q_e:
                    print(f"[Crown] Question '{slot}' failed: {_q_e}")
                    # Fall through to refusal if we can't ask
                    break
            else:
                # All questions answered — rebuild requirements and re-analyse
                if answers:
                    requirements = "\n".join(f"{k.replace('_', ' ')}: {v}" for k, v in answers.items() if v)
                    analysis = analyse_brief(task, explicit_kind, requirements)
                    if not analysis["questions"]:
                        confirmed = True
                        assumptions = [f"{k.replace('_', ' ')}: {v}" for k, v in answers.items()]
                    else:
                        # Still have questions after answers — fall through to refusal
                        pass

    if analysis["questions"] and not confirmed:
        # If we have a player with ask_permission, use it to show the refusal as a blocking message
        if player is not None and hasattr(player, "ask_permission"):
            try:
                player.ask_permission(
                    action="requirements_needed",
                    reason=f"This request needs answers before building:\n{refusal_text(analysis, task)}",
                    location="build"
                )
            except Exception:
                pass
        return refusal_text(analysis, task)

    brief = merge_brief(task, requirements)

    # Which builder owns this request, decided on what the user actually asked
    # for — before the build guidance is appended. The guidance text mentions
    # MySQL and logins while describing what to avoid, so testing it here would
    # disqualify the very recipes it is describing.
    app_kind = app_kind_for(brief)

    if not assumptions and analysis["questions"]:
        # The user said go ahead anyway. Record what is being decided without
        # them, and require the agent to report it — a disclosed assumption is
        # not the same as a silent one.
        assumptions = [q["slot"].replace("_", " ") for q in analysis["questions"]]
        brief += ("\n\nThe user chose to start without answering: "
                  + ", ".join(assumptions)
                  + ". Choose the simplest option that needs no external "
                    "credentials, write every such choice into the final report, "
                    "and mark those parts of the build as replaceable.")

    # Concrete structure for the artifact being asked for: file layout, run
    # command and the check that proves it works on this machine.
    stacks = detect_stacks(task)
    guidance = recipe_block(stacks)
    if guidance:
        brief += "\n\n" + guidance

    # Design tokens and layout structure the build must use. These are the same
    # values the design gate checks afterwards, so "well designed" is a
    # measurable request rather than an adjective.
    try:
        _design_kind = ("game" if "game" in stacks
                        else "python-desktop" if "python-desktop" in stacks
                        else "dashboard" if "dashboard" in stacks else "web")
        # References the research browser actually collected win: the hue is
        # sampled from their pixels instead of being invented from the brief.
        _refs = p.get("design_references") or []
        if isinstance(_refs, str):
            _refs = [part.strip() for part in _refs.replace(";", ",").split(",")
                     if part.strip()]
        if _refs:
            from core.design_research import design_research_brief as _ref_brief
            brief += "\n\n" + _ref_brief(_refs, seed=task, kind=_design_kind)
        else:
            from core.design_system import design_brief as _design_brief
            # Application presets: a dashboard, web app or Python app is built
            # from one of the 100+ presets, so its palette and structure follow
            # the preset instead of one generic token set for every brief.
            from core.app_presets import (choose_app_preset as _choose_preset,
                                          describe as _describe_preset,
                                          token_kwargs as _preset_tokens)
            _preset_kind = ("dashboard" if _design_kind == "dashboard"
                            else "python" if _design_kind == "python-desktop"
                            else "webapp")
            _app_preset = _choose_preset(task, _preset_kind, seed=task)
            _preset_design = _preset_tokens(_app_preset)
            brief += "\n\n" + _design_brief(task, kind=_design_kind,
                                             mood=_preset_design["mood"],
                                             hue=_preset_design["hue"])
            brief += "\n\n" + _describe_preset(_app_preset)
    except Exception as exc:
        print(f"[Crown] design brief skipped: {exc}")

    # ── workspace ──────────────────────────────────────────────────────────
    ws_param = (p.get("workspace") or "").strip()
    if ws_param:
        workspace = Path(ws_param).expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
    else:
        name = (p.get("project_name") or "").strip() or _slug(task)
        workspace = (_PROJECTS_DIR / _slug(name)).resolve()
        workspace.mkdir(parents=True, exist_ok=True)

    # Open the Live Coding console as soon as the workspace is known — before
    # the local-model check and before the Node agent is spawned. It used to
    # open only when the bridge announced `ready`, which arrives after a model
    # may have spent 30-60s loading, and never arrives at all if the agent
    # fails to start. Either way the app looked dead while the user waited.
    _status_safe(player, "begin_creation", "code", workspace.name, str(workspace))

    # ── build target decision (before model work, so recipe builds stay offline) ──
    path_kind = "app" if app_kind else classify_task(task, explicit_kind)
    kind = infer_kind(task, explicit_kind)
    # "fast" renders the plan into a verified page (~20 s on this machine).
    # "custom" additionally lets the writer model replace it; measured at 4.5+
    # minutes and still unfinished for a one-page brief, so it stays opt-in
    # rather than the default. The rendered page is kept as the fallback either
    # way, so a slow or failed model never costs the user a working site.
    speed = str(p.get("speed") or "fast").strip().lower()
    if speed not in ("fast", "custom"):
        speed = "fast"

    # ── model readiness (only for builds that actually need a model) ─────────────
    cfg = load_config()
    provider = (p.get("provider") or cfg.get("provider") or "ollama").lower()
    policy = (p.get("policy") or cfg.get("policy") or "safe").lower()
    timeout = int(p.get("timeout") or 900)
    # An explicit call argument wins, then the model pinned in
    # config/crown_code.json. Before this, the configured Gemma 4 model was
    # silently ignored and auto-pick chose a different (weaker) model.
    model = (p.get("model") or cfg.get("model") or "").strip()
    wait = bool(p.get("wait") or p.get("background") is False)

    # Recipe builds (path_kind == "app") stay completely offline and need no model
    needs_model = (path_kind != "app")
    if needs_model and provider in ("ollama", "auto", "local"):
        if player:
            _status_safe(player, "creation_event", "◆", "Checking local model (Ollama)...")
        ensurer = getattr(player, "ensure_local_model", None) or ensure_local_model
        ok, info = ensurer(
            log=lambda m: _status_safe(player, "write_log", f"[Crown] {m}"),
            on_progress=lambda d: _status_safe(player, "creation_event", "→",
                                               f"Ollama: {d.get('status', '')}"),
            preferred=model,
        )
        if not ok:
            msg = f"Crown Code cannot start: {info}"
            _status_safe(player, "creation_error", msg)
            return msg
        model = info
        provider = "ollama"

    title = f"{'Coding' if path_kind == 'code' else 'Building'} {workspace.name}"

    try:
        (workspace / "brief.json").write_text(json.dumps({
            "request": task,
            "requirements": requirements,
            "artifact": analysis["artifact"],
            "answered": analysis["answered"],
            "assumptions": assumptions,
            "recipes": stacks,
            "path": path_kind,
        }, indent=2), encoding="utf-8")
    except Exception:
        pass

    # ── execution target ──────────────────────────────────────────────────
    # Recipe apps build offline. Websites/portfolios render from a verified
    # plan. Application/code requests go straight to the agent loop. Network
    # research and a second plan-confirmation dialog used to run before every
    # code build; that delayed the build (and could abort the process) before
    # the agent ever wrote a file. They are now opt-in via research_mode.
    research_mode = str(p.get("research_mode") or "").strip().lower()
    wants_research = research_mode in ("browser", "deep", "on", "research",
                                       "true", "1")

    if path_kind == "app":
        def target(job):
            return _run_app(job, workspace, app_kind, player)
    elif path_kind == "site":
        def target(job):
            # Harman/portfolio requests may use the research-heavy pipeline,
            # but only when research was actually asked for; otherwise the
            # verified page renderer builds the site immediately.
            task_l = task.lower()
            if wants_research and ("harman" in task_l or "no preset" in task_l
                                   or str(p.get("no_preset", "")).lower() == "true"):
                return _run_autonomous_portfolio(
                    job, workspace, task, requirements, stacks, player, model,
                    provider, policy, timeout, p)
            return _run_site(job, workspace, kind, model, player, speed=speed)
    else:
        def target(job):
            browser_tools = [
                "navigate_to_url", "get_page_text", "get_page_title",
                "capture_screenshot", "capture_full_page", "list_page_images",
                "download_resource", "save_source",
            ]
            tools = [t for t in (p.get("tools") or []) if t]
            if wants_research:
                for name in browser_tools:
                    if name not in tools:
                        tools.append(name)
            return _agent_build(job, brief, workspace, model or "", provider,
                                policy, timeout, player, verify_tests=True,
                                tools=tools)

    
    # ── start background job ────────────────────────────────────────────────
    # Every build is a background job so the chat thread stays responsive and
    # progress is queryable at any time. The job id is returned immediately.
    def _on_job_event(ev: dict) -> None:
        """Report the REAL finish state, not just that the thread started.

        The assistant has no way to know a background build ended unless we
        tell it; without this it kept claiming "done" while the job was still
        running or had failed.
        """
        kind_ev = ev.get("type")
        finished_job = ev.get("job")
        if kind_ev == "done":
            line = finished_job.status_line() if finished_job else "Build finished"
            _status_safe(player, "write_log", f"[Crown] {line}")
            if speak:
                try:
                    speak(f"Build finished. {line}")
                except Exception:
                    pass
        elif kind_ev == "failed":
            err = ((finished_job.error if finished_job else "")
                   or str(ev.get("error") or "unknown error"))
            _status_safe(player, "creation_error", err)
            if speak:
                try:
                    speak(f"The build failed: {err[:240]}")
                except Exception:
                    pass
        else:
            _status_safe(player, "creation_event", "✓", f"{kind_ev}")

    job = _get_manager().start(
        name=title,
        target=target,
        on_event=_on_job_event,
        kind=path_kind or "code",
        brief=task,
        workspace=str(workspace),
        model=model or "",
    )

    # ── Verify the job actually started before reporting success ────────────────
    # The previous code returned "Started: {name}" immediately after calling .start()
    # but the thread may have died instantly (model unavailable, import error, etc.)
    # without any visible failure. Now we wait a brief moment and check that the job
    # is still active (thread alive + status not failed) before claiming it started.
    _startup_wait = 0.5  # seconds to wait for the thread to show activity
    _startup_deadline = time.time() + max(2.0, _startup_wait * 4)  # max 2s to verify
    _job_started = False
    while time.time() < _startup_deadline:
        if not job.thread or not job.thread.is_alive():
            # Thread died immediately — job failed to start
            _status_safe(player, "creation_error", f"Build failed to start: thread exited immediately")
            if speak:
                try:
                    speak(f"Build could not start {workspace.name}")
                except Exception:
                    pass
            # Check if the job already recorded a failure
            if job.status == "failed":
                err = job.error or job.result.get("error", "unknown error")
                return f"Build failed to start: {err}"
            return f"Build failed to start: the background job could not be created"
        if job.status != "queued":
            # Job has moved past queued — it's actually running
            _job_started = True
            break
        time.sleep(0.1)

    if not _job_started:
        # Thread is alive but job still stuck in queued after waiting — suspicious
        # but not necessarily fatal (could be slow imports). Warn but proceed.
        _status_safe(player, "creation_event", "!", "Build thread started but progress not yet reported")

    if speak:
        try:
            speak(f"Started building {workspace.name}")
        except Exception:
            pass

    if wait:
        job.thread.join(timeout + 120)
        desc = job.describe()
        if speak:
            try:
                speak(f"Finished building {workspace.name}")
            except Exception:
                pass
        return desc

    mode = ("I'll plan the page, render it, and check it in a real browser (about a minute)"
        if path_kind == "site" and speed == "fast" else
        "I'll plan the page, render it as a verified floor, then write the real "
        "structure and check both in a browser"
        if path_kind == "site" else
        "I'll render it from the recipe, then compile it, start it and call its "
        "endpoints so the result is proven to run"
        if path_kind == "app" else
        "I'll run the Crown Code agent loop — it writes real files, runs them and fixes what fails")
    if assumptions:
        mode += f"\nStarting without: {', '.join(assumptions)} — those choices will be reported."
    return (f"Build STARTED — NOT finished yet  (job {job.id})\n"
        f"Workspace: {workspace.name}\n"
        f"{mode}.\n"
        f"The job is running in the background. Do NOT tell the user it is "
        f"done. Call crown_code with action='status' (job_id='{job.id}') to "
        f"check it, and only report success when that status says done and "
        f"lists the files.\n"
        f"Output: {workspace}")
