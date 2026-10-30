#!/usr/bin/env python3
"""install.py — one-command bootstrap for Keys.ai (pre-configures new users).

What it does, in order:

  1.  Ensures Python >= 3.10.
  2.  Creates a virtualenv (``.venv``) — the project's consistent runtime.
  3.  Installs ``requirements.txt`` with ``uv`` when available (fast, modern
      dependency management), falling back to the venv's pip.
  4.  Installs Playwright Chromium (needed for WhatsApp Web + dashboard).
  5.  Installs optional Windows extras for the call receptionist
      (``pyaudiowpatch`` = WASAPI loopback so it can HEAR callers) and prints
      the VB-CABLE guidance so callers can hear replies.
  6.  Scaffolds missing config files (create-if-missing, never overwrites):
      api_keys.json template, call_rules.json defaults, agent_control.json,
      brain.json / personality.json / entities.json / session_state.json /
      window_state.json as {} and the certs/ directory — so a brand-new user
      gets a working layout immediately.
  7.  Runs a ``doctor`` self-check and prints next steps.

Flags:
    --no-venv        install into the current interpreter instead of .venv
    --skip-deps      don't (re)install Python dependencies
    --skip-playwright  don't (re)install Playwright browsers
    --skip-scaffold  don't touch the config directory
    --doctor         only run the self-check; make no changes
    --test           after install, run the unit test suite
    --quiet          reduce output

Config-management notes: scaffolding follows the "ensure state" pattern used
by tools like Ansible/Salt — each file is only created when missing, existing
user data is never touched, and every JSON template parses as valid JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
VENV_DIR = BASE / ".venv"
MIN_PYTHON = (3, 10)
OS_NAME = platform.system().lower()  # windows | linux | darwin

# ── output helpers (safe on any Windows codepage) ─────────────────────────
_OK = "[OK]"
_WARN = "[!]"
_ERR = "[x]"
_STEP = ">>>"


def say(msg: str = "") -> None:
    try:
        print(msg)
    except Exception:
        pass


def step(num: int, title: str) -> None:
    say(f"\n{_STEP} Step {num}/7 — {title}")


def fail(msg: str) -> None:
    say(f"{_ERR} {msg}")
    sys.exit(1)


def run(cmd: list, cwd: Path = BASE, check: bool = True) -> subprocess.CompletedProcess:
    say("    $ " + " ".join(cmd))
    try:
        return subprocess.run(cmd, cwd=str(cwd), check=check)
    except FileNotFoundError:
        if check:
            fail(f"command not found: {cmd[0]}")
        return subprocess.CompletedProcess(cmd, 1, b"", b"command not found")


def venv_python() -> Path:
    exe = "Scripts/python.exe" if OS_NAME == "windows" else "bin/python"
    return VENV_DIR / exe


def system_python() -> str:
    return sys.executable


# ── 1. Python check ───────────────────────────────────────────────────────
def check_python() -> None:
    v = sys.version_info
    say(f"    Python {v.major}.{v.minor}.{v.micro} ({sys.executable})")
    if (v.major, v.minor) < MIN_PYTHON:
        fail(f"Python {'.'.join(map(str, MIN_PYTHON))}+ required — "
             f"install a newer Python from python.org first.")


# ── 2. Virtualenv ─────────────────────────────────────────────────────────
def ensure_venv(use_uv: bool) -> Path:
    if VENV_DIR.exists() and venv_python().exists():
        say("    .venv already exists — reusing it.")
        return venv_python()
    say(f"    creating .venv ...")
    if use_uv:
        run(["uv", "venv", str(VENV_DIR)])
    else:
        run([system_python(), "-m", "venv", str(VENV_DIR)])
    if not venv_python().exists():
        fail("virtualenv creation failed.")
    return venv_python()


# ── 3. Dependencies ───────────────────────────────────────────────────────
def install_deps(py: Path, use_uv: bool, quiet: bool) -> None:
    req = BASE / "requirements.txt"
    if not req.exists():
        say(f"    requirements.txt missing — skipping dependency install.")
        return
    env = dict(os.environ)
    if use_uv:
        say("    installing requirements with uv (fast dependency manager) ...")
        cmd = ["uv", "pip", "install", "--python", str(py)]
        if quiet:
            cmd.append("--quiet")
        cmd += ["-r", str(req)]
        r = run(cmd, check=False)
        if r.returncode == 0:
            return
        say(f"{_WARN} uv install failed (code {r.returncode}) — falling back to pip.")
    say("    installing requirements with pip ...")
    cmd = [str(py), "-m", "pip", "install", "--upgrade", "pip"]
    run(cmd, check=False)
    cmd = [str(py), "-m", "pip", "install"]
    if quiet:
        cmd.append("--quiet")
    cmd += ["-r", str(req)]
    run(cmd)


# ── 4. Playwright browsers ────────────────────────────────────────────────
def install_playwright(py: Path) -> None:
    say("    installing Playwright Chromium ...")
    cmd = [str(py), "-m", "playwright", "install", "chromium"]
    if OS_NAME == "linux":
        # system browser deps on Linux need the --with-deps flag (may need sudo)
        say(f"{_WARN} Linux: if the install above needs system libraries, run:\n"
            f"        sudo {str(py)} -m playwright install --with-deps chromium")
    run(cmd, check=False)


# ── 5. Receptionist audio extras ──────────────────────────────────────────
def install_audio_extras(py: Path) -> None:
    if OS_NAME != "windows":
        say("    (audio extras are Windows-only — skipped)")
        return
    say("    installing pyaudiowpatch (lets the agent HEAR WhatsApp callers) ...")
    run([str(py), "-m", "pip", "install", "pyaudiowpatch"], check=False)
    say(f"{_WARN} To let callers HEAR the agent's replies, install VB-CABLE once:\n"
        f"        https://vb-audio.com/Cable/  (free)\n"
        f"    then set WhatsApp's microphone to 'CABLE Output'.")


# ── 6. Config scaffolding (create-if-missing only) ────────────────────────
API_KEYS_TEMPLATE = {
    "gemini_api_key": "",
    "llm_provider": "gemini",
    "llm_model": "",
    "llm_url": "",
    "os_system": "windows",
    "camera_index": 0,
    "google_oauth_client_id": "",
    "google_oauth_client_secret": "",
    "firebase_api_key": "",
    "firebase_project_id": "",
}

AGENT_CONTROL_TEMPLATE = {
    "humour_level": "MEDIUM",
    "dark_humour": False,
    "professional_mode": True,
    "retry_limit": 3,
    "confirm_high_impact": True,
    "overlay_enabled": True,
    "max_wait_timeout": 30.0,
}

# Matches the live config/call_rules.json shape (call handling is currently
# disabled in the app, but the file must still exist and be well-formed so the
# settings reader never has to special-case its absence).
CALL_RULES_TEMPLATE = {
    "enabled": False,
    "auto_answer": False,
    "answer_after_ring_s": 0,
    "watch_web": False,
    "watch_desktop_app": False,
    "greeting": "",
    "unknown_reply": "",
    "rules": [],
}

_EMPTY_JSON_FILES = (
    "brain.json", "entities.json", "personality.json",
    "session_state.json", "window_state.json",
)


def scaffold_configs(base: Path) -> list:
    """Create missing configs. Returns list of created paths. Never overwrites."""
    created = []
    cfg = base / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "certs").mkdir(exist_ok=True)

    def _write(name: str, payload) -> bool:
        p = cfg / name
        if p.exists():
            return False
        p.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                     encoding="utf-8")
        created.append(str(p.relative_to(base)))
        return True

    # api_keys.json — empty template → the app shows its setup overlay
    _ak_payload = dict(API_KEYS_TEMPLATE)
    _ak_payload["os_system"] = OS_NAME
    if _write("api_keys.json", _ak_payload):
        say(f"    created config/api_keys.json (template — add your Gemini key)")

    if _write("agent_control.json", AGENT_CONTROL_TEMPLATE):
        say("    created config/agent_control.json (defaults)")
    if _write("call_rules.json", CALL_RULES_TEMPLATE):
        say("    created config/call_rules.json (defaults)")
    for name in _EMPTY_JSON_FILES:
        if _write(name, {}):
            say(f"    created config/{name} (empty defaults)")
    return created


# ── 7. Doctor ─────────────────────────────────────────────────────────────
CRITICAL_IMPORTS = (
    "PyQt6", "google.genai", "playwright", "sounddevice", "numpy",
    "requests", "bs4", "duckduckgo_search", "psutil", "mss",
    "PIL", "fastapi", "cv2", "pyautogui",
)


def _browser_cache_dir() -> Path:
    """Where Playwright keeps its browser binaries (per-user, OS-specific)."""
    home = Path.home()
    if OS_NAME == "windows":
        return Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "ms-playwright"
    if OS_NAME == "darwin":
        return home / "Library" / "Caches" / "ms-playwright"
    return Path(os.environ.get("XDG_CACHE_HOME", home / ".cache")) / "ms-playwright"


def browsers_present() -> bool:
    """True when a chromium build is present in the shared browser cache."""
    cache = _browser_cache_dir()
    if not cache.is_dir():
        return False
    try:
        return any(p.name.startswith("chromium") for p in cache.iterdir())
    except Exception:
        return False


def doctor(base: Path, quiet: bool = False, venv_dir: Path = VENV_DIR) -> int:
    """Report environment health. Returns 0 = healthy, 1 = needs action."""
    say(f"\n{_STEP} Doctor self-check")
    issues = 0
    py = venv_dir / ("Scripts/python.exe" if OS_NAME == "windows" else "bin/python")
    py = py if py.exists() else None

    # python
    say(f"    Python {sys.version_info.major}.{sys.version_info.minor} "
        f"(system: {sys.executable})")
    if not py:
        say(f"{_WARN} no .venv found — run install.py first.")
        issues += 1
    else:
        say(f"    virtualenv: {py}")
        # critical imports inside the venv
        code = ("import importlib.util;"
                "mods='PyQt6 google.genai playwright sounddevice numpy requests "
                "bs4 duckduckgo_search psutil mss PIL fastapi cv2 pyautogui'.split();"
                "missing=[m for m in mods if importlib.util.find_spec(m) is None];"
                "print('MISSING:' + ','.join(missing) if missing else 'ALL_OK')")
        r = run([str(py), "-c", code], check=False)
        out = (r.stdout or b"").decode("utf-8", "replace").strip()
        if "MISSING:" in out:
            say(f"{_WARN} missing packages in .venv: {out.split(':', 1)[1]}")
            issues += 1
        else:
            say(f"{_OK} critical packages import cleanly in .venv")

        # playwright browsers — verify the shared cache directly (a broken
        # venv can otherwise make --list report false negatives)
        if browsers_present():
            say(f"{_OK} Playwright Chromium installed (cache: {_browser_cache_dir()})")
        else:
            r = run([str(py), "-m", "playwright", "install", "--list"], check=False)
            out = (r.stdout or b"").decode("utf-8", "replace")
            if "chromium" in out.lower():
                say(f"{_OK} Playwright Chromium installed")
            else:
                say(f"{_WARN} Playwright Chromium not installed — run: "
                    f"{str(py)} -m playwright install chromium")
                issues += 1

        # venv health (a missing pyvenv.cfg makes the venv unusable)
        if py is not None and not (venv_dir / "pyvenv.cfg").exists():
            say(f"{_WARN} {venv_dir} looks broken (missing pyvenv.cfg) — "
                f"recreate it with: python -m venv --clear {venv_dir}")
            issues += 1

        # receptionist extras
        r = run([str(py), "-c", "import pyaudiowpatch;print('ok')"], check=False)
        if r.returncode == 0:
            say(f"{_OK} pyaudiowpatch installed (receptionist can HEAR callers)")
        else:
            say(f"{_WARN} pyaudiowpatch not installed — receptionist hearing "
                f"disabled (pip install pyaudiowpatch)")
            issues += 1

    # configs
    cfg = base / "config"
    say("    config:")
    for name in ("api_keys.json", "agent_control.json"):
        p = cfg / name
        if p.exists():
            say(f"      {_OK} config/{name}")
        else:
            say(f"      {_WARN} config/{name} missing — will be scaffolded on install")
            issues += 1

    # next steps
    ak = cfg / "api_keys.json"
    if ak.exists():
        try:
            has_key = bool(json.loads(ak.read_text(encoding="utf-8")).get("gemini_api_key"))
        except Exception:
            has_key = False
        if has_key:
            say(f"    {_OK} Gemini API key present")
        elif not quiet:
            say("    - Launch the app and enter your Gemini API key "
                "(aai.google.dev) — the setup overlay will guide you.")
    if not quiet:
        say("    - For WhatsApp messaging: sign in to the WhatsApp desktop app.\n"
            "    - For Google-verified contacts: follow FIREBASE_SETUP.md "
            "and say 'sign in with Google'.")
    say(f"\n{'All checks healthy.' if issues == 0 else f'{issues} item(s) need attention.'}")
    return 0 if issues == 0 else 1


# ── tests ─────────────────────────────────────────────────────────────────
def run_tests(py: Path) -> None:
    say(f"\n{_STEP} Running the test suite (unittest) ...")
    r = run([str(py), "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"],
            check=False)
    if r.returncode != 0:
        say(f"{_ERR} tests failed (code {r.returncode})")
        sys.exit(r.returncode)
    say(f"{_OK} tests passed")


# ── main ──────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Keys.ai bootstrap installer")
    ap.add_argument("--no-venv", action="store_true",
                    help="install into the current interpreter (no .venv)")
    ap.add_argument("--skip-deps", action="store_true")
    ap.add_argument("--skip-playwright", action="store_true")
    ap.add_argument("--skip-scaffold", action="store_true")
    ap.add_argument("--doctor", action="store_true",
                    help="only run the self-check; make no changes")
    ap.add_argument("--test", action="store_true", help="run tests after install")
    ap.add_argument("--quiet", action="store_true")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.doctor:
        return doctor(BASE, quiet=args.quiet)

    say("=" * 62)
    say("  Keys.ai bootstrap installer")
    say("=" * 62)
    check_python()

    use_uv = shutil.which("uv") is not None
    if use_uv:
        say(f"{_OK} uv found — using it as the dependency manager")

    py = Path(system_python()) if args.no_venv else None
    if py is None:
        step(2, "Virtualenv")
        py = ensure_venv(use_uv)

    if not args.skip_deps:
        step(3, "Dependencies")
        install_deps(py, use_uv, args.quiet)
    if not args.skip_playwright:
        step(4, "Playwright browsers")
        install_playwright(py)
    step(5, "Receptionist audio extras")
    install_audio_extras(py)
    if not args.skip_scaffold:
        step(6, "Config scaffolding (create-if-missing)")
        scaffold_configs(BASE)
    step(7, "Self-check")
    doctor(BASE, quiet=args.quiet)

    if args.test:
        run_tests(py)

    say("\nDone. Run the app with:")
    if args.no_venv:
        say("    python main.py")
    else:
        say("    " + str(venv_python()) + " main.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
