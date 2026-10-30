"""
core/app_checks.py — evidence that a generated application actually runs.

Why this exists
---------------
A build was reported "finished" because its recipe files existed on disk. That
is the weakest possible level of evidence: a dashboard can have `app.py`,
`db.py` and a template and still fail on line one — pointing at a MySQL server
that is not running, importing a module that is not installed, or returning an
HTML error page where the front end expects JSON. Both dashboards in the last
batch had "no missing files" and neither could be started.

So verification is graded, and each level says only what it measured:

    exists      the file is on disk
    compiles    python -m py_compile accepted every module
    executes    a process was started and exited with the expected status
    serves      an HTTP request returned 200 with the JSON shape promised

`verify_workspace()` runs the levels that apply to the files that are present
and returns every check with its real command and real output. Nothing here
returns True because a check was skipped: a skipped level is reported as
skipped, and `ok` is False when a level that ran failed.

Everything is a subprocess with an argument list (never a shell string), a
timeout, and the child is killed afterwards — including the HTTP server, which
is started on a free port so a verification can never collide with a running
build or leave a server behind.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PY = sys.executable or "python"

# Every subprocess in this module is bounded. A build that hangs must cost
# seconds, not the whole session.
DEFAULT_TIMEOUT = 120


# ── process helpers ───────────────────────────────────────────────────────

def _run(cmd: list[str], cwd: Path, timeout: int = DEFAULT_TIMEOUT,
         env: dict | None = None) -> dict:
    """Run one command with an argument list. Never raises for a bad exit."""
    started = time.time()
    full_env = os.environ.copy()
    full_env.setdefault("PYTHONIOENCODING", "utf-8")
    full_env.setdefault("PYTHONUNBUFFERED", "1")
    if env:
        full_env.update(env)
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), env=full_env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace",
        )
        return {
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
            "seconds": round(time.time() - started, 2),
            "command": " ".join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False, "code": None, "stdout": "", "stderr": "",
            "seconds": round(time.time() - started, 2),
            "command": " ".join(cmd),
            "error": f"timed out after {timeout}s",
        }
    except OSError as err:
        return {
            "ok": False, "code": None, "stdout": "", "stderr": "",
            "seconds": round(time.time() - started, 2),
            "command": " ".join(cmd), "error": f"{type(err).__name__}: {err}",
        }


def _python_files(workspace: Path) -> list[Path]:
    return sorted(p for p in workspace.rglob("*.py")
                  if "__pycache__" not in p.parts)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _tail(text: str, limit: int = 600) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def _check(name: str, ok: bool, detail: str = "", level: str = "",
           command: str = "") -> dict:
    return {"check": name, "level": level, "ok": bool(ok),
            "detail": _tail(detail), "command": command}


# ── level: compiles ───────────────────────────────────────────────────────

def check_compiles(workspace: Path) -> dict:
    """`python -m py_compile` over every module in the project."""
    files = _python_files(workspace)
    if not files:
        return _check("compiles", False, "no Python files found", "compiles")
    rel = [str(p.relative_to(workspace)) for p in files]
    result = _run([PY, "-m", "py_compile", *rel], workspace, timeout=90)
    detail = result["stdout"] or result["stderr"] or "all modules compiled"
    return _check(f"compiles ({len(rel)} files)", result["ok"], detail,
                  "compiles", result["command"])


# ── level: executes ───────────────────────────────────────────────────────

def check_selftest(workspace: Path, entry: str = "main.py",
                   flag: str = "--selftest", expect: str = "OK",
                   timeout: int = 90) -> dict:
    """Run a program's own headless self-test.

    GUIs are started offscreen so this needs no display, no mouse and no user.
    """
    if not (workspace / entry).exists():
        return _check("executes (--selftest)", False, f"{entry} is missing",
                      "executes")
    env = {"QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(workspace)}
    result = _run([PY, entry, flag], workspace, timeout=timeout, env=env)
    combined = (result["stdout"] + "\n" + result["stderr"]).strip()
    ok = result["ok"] and expect in result["stdout"]
    if result["ok"] and not ok:
        combined += f"\n(expected {expect!r} on stdout)"
    return _check(f"executes (python {entry} {flag})", ok, combined,
                  "executes", result["command"])


def check_script(workspace: Path, script: str, timeout: int = 120) -> dict:
    """Run a setup script (a seeder) and require exit status 0."""
    if not (workspace / script).exists():
        return _check(f"executes ({script})", False, f"{script} is missing",
                      "executes")
    result = _run([PY, script], workspace, timeout=timeout)
    detail = result["stdout"] or result["stderr"] or "exited 0"
    return _check(f"executes (python {script})", result["ok"], detail,
                  "executes", result["command"])


# ── level: serves ─────────────────────────────────────────────────────────

def _get_json(url: str, timeout: float = 10.0) -> tuple[bool, str, object]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = getattr(resp, "status", 200)
        try:
            return status == 200, body, json.loads(body)
        except json.JSONDecodeError:
            return False, body, None
    except urllib.error.HTTPError as err:
        return False, f"HTTP {err.code}", None
    except Exception as err:                        # refused, reset, timeout
        return False, f"{type(err).__name__}: {err}", None


def browser_probe(expect: tuple[str, ...] = ("#kpis .kpi", "svg"),
                  screenshot: Path | None = None, seconds: int = 25):
    """A callback that loads the page in Chromium and checks it rendered.

    The API can answer perfectly while the page shows nothing — a broken
    script, a selector typo, a console error. This is the level that catches
    that, and it is why it is optional: it needs a browser, and a build should
    not depend on one.
    """

    def probe(base_url: str) -> tuple[bool, str]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as err:                  # browser not installed
            return False, f"playwright unavailable: {err}"
        errors: list[str] = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                try:
                    page = browser.new_page(viewport={"width": 1280,
                                                      "height": 900})
                    page.on("console", lambda msg: errors.append(msg.text)
                            if msg.type == "error" else None)
                    page.on("pageerror", lambda exc: errors.append(str(exc)))
                    page.goto(base_url, wait_until="networkidle",
                              timeout=seconds * 1000)
                    page.wait_for_selector(expect[0], timeout=seconds * 1000)
                    counts = {sel: page.locator(sel).count()
                              for sel in expect}
                    if screenshot is not None:
                        screenshot.parent.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(screenshot), full_page=True)
                finally:
                    browser.close()
        except Exception as err:
            return False, f"{type(err).__name__}: {err}"[:500]
        detail = ", ".join(f"{sel}={n}" for sel, n in counts.items())
        if errors:
            return False, f"{detail}; console errors: {errors[:3]}"
        return True, detail

    return probe


def check_http_endpoints(workspace: Path, entry: str = "app.py",
                         endpoints: tuple[str, ...] = ("/api/health",),
                         ready_seconds: float = 25.0,
                         required_keys: dict | None = None,
                         nonempty_keys: dict | None = None,
                         db_path: str = "",
                         page_probe=None) -> list[dict]:
    """Start the server, call each endpoint, require JSON, then shut it down.

    A server that starts but answers with an HTML traceback is a failure, so
    the response body is parsed rather than just fetched. `nonempty_keys`
    asserts that a list in the response actually contains rows — a 200 with an
    empty array is a server that never reached its database.

    `db_path` is only set when the caller wants the app pointed at a specific
    file; leaving it empty lets the app open its own default, which is the same
    file the seeder wrote.
    """
    checks: list[dict] = []
    if not (workspace / entry).exists():
        return [_check("serves (HTTP)", False, f"{entry} is missing", "serves")]

    port = _free_port()
    env = os.environ.copy()
    env.update({
        "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": str(workspace),
        "PORT": str(port), "APP_PORT": str(port), "FLASK_RUN_PORT": str(port),
    })
    if db_path:
        env["DB_PATH"] = db_path
    log_path = workspace / "_server.log"
    try:
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            proc = subprocess.Popen(  # noqa: S603 - argument list, no shell
                [PY, entry], cwd=str(workspace), env=env,
                stdout=log, stderr=subprocess.STDOUT, text=True,
            )
    except OSError as err:
        return [_check("serves (HTTP)", False,
                       f"could not start {entry}: {err}", "serves")]

    base = f"http://127.0.0.1:{port}"
    started = time.time()
    up = False
    try:
        while time.time() - started < ready_seconds:
            if proc.poll() is not None:
                break
            ok, _, _ = _get_json(base + "/api/health", timeout=2.0)
            if ok:
                up = True
                break
            time.sleep(0.25)

        if not up:
            server_log = ""
            try:
                server_log = log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
            checks.append(_check(
                "serves (HTTP)", False,
                "server did not answer /api/health: " + _tail(server_log, 700),
                "serves"))
            return checks

        for endpoint in endpoints:
            ok, body, payload = _get_json(base + endpoint)
            detail = _tail(body, 400)
            if ok and isinstance(payload, dict) and required_keys \
                    and endpoint in required_keys:
                missing = [k for k in required_keys[endpoint]
                           if k not in payload]
                if missing:
                    ok = False
                    detail = f"missing keys {missing} — {detail}"
            if ok and isinstance(payload, dict) and nonempty_keys \
                    and endpoint in nonempty_keys:
                for key in nonempty_keys[endpoint]:
                    value = payload.get(key)
                    if not isinstance(value, list) or not value:
                        ok = False
                        detail = (f"{key} is empty — the app served JSON but "
                                  f"read no rows ({detail[:200]})")
                        break
            checks.append(_check(f"serves GET {endpoint}", ok, detail, "serves"))

        if page_probe is not None:
            ok, detail = page_probe(base)
            checks.append(_check("renders in Chromium", ok, detail, "renders"))
        return checks
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            log_path.unlink()
        except OSError:
            pass


# ── public entry point ────────────────────────────────────────────────────

def verify_workspace(workspace: Path | str, kind: str = "",
                     entry: str = "", endpoints: tuple[str, ...] | None = None,
                     required_keys: dict | None = None,
                     nonempty_keys: dict | None = None,
                     seed: str = "", db_path: str = "",
                     browser: bool = False, screenshot: Path | None = None) -> dict:
    """Run every level of verification that applies to this workspace.

    Returns {"ok", "checks", "levels", "counts", "message"}. `ok` is True only
    when at least one check ran and every check that ran passed.
    """
    workspace = Path(workspace)
    checks: list[dict] = []
    if not workspace.exists():
        return {"ok": False, "checks": [], "levels": [], "counts": {},
                "message": f"workspace {workspace} does not exist"}

    checks.append(check_compiles(workspace))

    if seed:
        checks.append(check_script(workspace, seed))

    if entry and not (workspace / entry).exists():
        # A missing entry point is a failure, not a skipped check: reporting
        # "ok" because nothing ran is the mistake this module exists to stop.
        checks.append(_check(f"executes ({entry})", False,
                             f"{entry} is missing", "executes"))
    elif entry:
        # A PyQt6 launcher is verified by its own offscreen self-test; a web
        # server is verified by asking it for JSON.
        is_web = bool(endpoints)
        if is_web:
            checks.extend(check_http_endpoints(
                workspace, entry=entry, endpoints=endpoints,
                required_keys=required_keys, nonempty_keys=nonempty_keys,
                db_path=db_path,
                page_probe=(browser_probe(screenshot=screenshot)
                            if browser else None)))
        elif "argparse" in (workspace / entry).read_text(
                encoding="utf-8", errors="replace"):
            checks.append(check_selftest(workspace, entry=entry))

    levels: list[str] = []
    for check in checks:
        if check["level"] and check["level"] not in levels:
            levels.append(check["level"])
    failed = [c for c in checks if not c["ok"]]
    counts: dict[str, int] = {}
    for check in checks:
        counts[check["level"]] = counts.get(check["level"], 0) + 1
    ok = bool(checks) and not failed
    if ok:
        message = (f"{len(checks)} checks passed "
                   f"({', '.join(f'{v} {k}' for k, v in counts.items())})")
    elif not checks:
        message = "nothing could be verified"
    else:
        message = "failed: " + "; ".join(
            f"{c['check']} — {c['detail'][:200]}" for c in failed)
    return {"ok": ok, "checks": checks, "levels": levels,
            "counts": counts, "message": message}
