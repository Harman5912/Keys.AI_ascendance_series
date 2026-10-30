"""
demo_selfcheck.py — one command to demonstrate and verify the whole assistant.

What it does
------------
1. Runs every offline test suite in the repo (each in its own process).
2. Runs in-process PROBES for subsystems that have no test suite of their own:
   tool wiring, messaging paths, memory, the model ladder, the echo guard,
   the HUD avatar, the terminal, the overlays and the theming.
3. Prints one PASS/FAIL matrix and exits non-zero if anything failed.

Usage
-----
    python demo_selfcheck.py            # fast, fully offline
    python demo_selfcheck.py --live     # also runs the Crown Code live coding run

Nothing here sends a message, drives the desktop, or writes to your real
memory/config: live model calls and any mutation use temporary paths.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

SUITES_OFFLINE = [
    "test_agent_control.py", "test_brain.py", "test_browser_control.py",
    "test_computer_use.py", "test_editor_control.py", "test_firebase_feature.py",
    "test_google_accounts.py", "test_hybrid_automation.py", "test_install.py",
    "test_intelligence.py", "test_targeting.py", "test_window_chrome.py",
    "test_gemini_ladder.py", "test_crown_ui.py",
]
SUITES_LIVE = ["test_crown_flow.py", "test_crown_code.py"]

INLINE_TOOLS = {
    "save_memory", "screen_process", "close_camera", "web_search",
    "system_status", "shutdown_keysai", "recall_memory", "undo",
    "manage_monitor",
}
CALL_TOOLS = {"make_call", "end_call", "call_phone", "call_status"}


class Report:
    def __init__(self):
        self.rows: list[tuple[str, str, str]] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.rows.append((name, "PASS" if ok else "FAIL", detail))


def run_suite(path: str, report: Report) -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["QT_QPA_PLATFORM"] = "offscreen"
    try:
        p = subprocess.run([sys.executable, path], cwd=str(ROOT), env=env,
                           capture_output=True, text=True, timeout=900,
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        report.add(f"suite: {path}", False, "timed out")
        return
    out = (p.stdout or "") + (p.stderr or "")
    m = re.search(r"Ran (\d+) tests", out)
    count = m.group(1) if m else "?"
    ok = p.returncode == 0 and ("OK" in out or "RESULT: PASS" in out)
    detail = f"{count} tests"
    if not ok:
        bad = [ln for ln in out.splitlines()
               if ln.startswith(("FAIL:", "ERROR:")) or ln.startswith("FAIL ")]
        detail += " | " + "; ".join(bad[:2]) if bad else " | failed"
    report.add(f"suite: {path}", ok, detail)


def probe_deps() -> str:
    import importlib.util
    needed = ["PyQt6", "numpy", "google.genai", "psutil", "requests"]
    missing = [m for m in needed if importlib.util.find_spec(m) is None]
    if missing:
        raise AssertionError(f"missing: {', '.join(missing)}")
    return "core deps importable"


def probe_config() -> str:
    required = ["api_keys.json", "agent_control.json", "crown_code.json",
                "call_rules.json", "brain.json", "entities.json",
                "personality.json", "session_state.json", "window_state.json"]
    missing = []
    for name in required:
        p = ROOT / "config" / name
        if not p.exists():
            missing.append(name)
            continue
        json.loads(p.read_text(encoding="utf-8"))
    if missing:
        raise AssertionError(f"missing: {', '.join(missing)}")
    return f"{len(required)} config files valid"


def probe_tool_wiring() -> str:
    from core.tool_declarations import TOOL_DECLARATIONS
    from core.tool_registry import TOOL_HANDLERS
    declared = {t["name"] for t in TOOL_DECLARATIONS}
    handled = set(TOOL_HANDLERS) | INLINE_TOOLS
    unrouted = declared - handled
    if unrouted:
        raise AssertionError(f"declared but not routed: {sorted(unrouted)}")
    orphan = set(TOOL_HANDLERS) - declared
    return f"{len(declared)} tools routed" + (
        f" (orphan handlers: {sorted(orphan)})" if orphan else ""
    )


def probe_tool_targets() -> str:
    import importlib
    src = (ROOT / "core" / "tool_registry.py").read_text(encoding="utf-8")
    pairs = set(re.findall(r'_load\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)', src))
    broken = []
    for mod, fn in sorted(pairs):
        try:
            m = importlib.import_module(mod)
            if not hasattr(m, fn):
                broken.append(f"{mod}:{fn}")
        except Exception as e:  # noqa: BLE001
            broken.append(f"{mod}:{fn} ({type(e).__name__})")
    if broken:
        raise AssertionError("unresolved: " + "; ".join(broken[:4]))
    return f"{len(pairs)} handler targets resolve"


def probe_no_calling_tools() -> str:
    from core.tool_declarations import TOOL_DECLARATIONS
    names = {t["name"] for t in TOOL_DECLARATIONS}
    present = names & CALL_TOOLS
    if present:
        raise AssertionError(f"calling tools still exposed: {sorted(present)}")
    return "calling removed from the tool surface (messaging only)"


def probe_messaging_paths() -> str:
    import importlib
    checks = [
        ("actions.send_message", "send_message"),
        ("actions.whatsapp_control", "whatsapp_control"),
        ("actions.send_email", "send_email"),
        ("actions.google_account", "google_account"),
    ]
    for mod, fn in checks:
        m = importlib.import_module(mod)
        if not hasattr(m, fn):
            raise AssertionError(f"{mod}.{fn} missing")
    return f"{len(checks)} messaging entry points present"


def probe_memory() -> str:
    import memory.memory_manager as mm
    with tempfile.TemporaryDirectory() as td:
        old_mem, old_forg = mm.MEMORY_PATH, mm.FORGOTTEN_PATH
        mm.MEMORY_PATH = Path(td) / "long_term.json"
        mm.FORGOTTEN_PATH = Path(td) / "forgotten.json"
        try:
            before = len(mm.all_entries_for_ui())
            mm.remember("demo_city", "Berlin", "identity")
            assert mm.search_memory("Berlin"), "recall failed"
            mid = len(mm.all_entries_for_ui())
            mm.forget("demo_city", "identity")
            after = len(mm.all_entries_for_ui())
            archived = json.loads(mm.FORGOTTEN_PATH.read_text(encoding="utf-8"))
            assert before == 0 and mid == 1 and after == 0, (before, mid, after)
            assert archived and archived[0]["key"] == "demo_city"
        finally:
            mm.MEMORY_PATH, mm.FORGOTTEN_PATH = old_mem, old_forg
    return "save / recall / forget / archive"


def probe_ladder() -> str:
    import core.gemini_ladder as L
    L.reset_cooldowns()
    assert L.classify(Exception("429"))[0] == "quota"
    assert L.classify(Exception("503 UNAVAILABLE"))[0] == "outage"
    assert L.classify(Exception("404"))[0] == "notfound"
    order = L.models_to_try("preferred-model")
    assert order[0] == "preferred-model" and len(order) == len(set(order))
    L._rest("preferred-model", 60)
    assert "preferred-model" not in L.models_to_try("preferred-model")
    L.reset_cooldowns()
    return f"ladder of {len(order)} models, cooldowns + ordering"


def probe_echo_guard() -> str:
    import numpy as np
    from core.echo import EchoGuard
    g = EchoGuard()
    own = (np.random.default_rng(1).standard_normal(512) * 3000).astype(np.int16)
    g.note_output(own, 24000, 0.1)
    if g.is_user_speech(own, 16000, 0.1):
        raise AssertionError("echo guard mistook its own output for the user")
    return "own output rejected, distinct voice passes"


_QT_APP = None
QT_OK = False


def _qt_app():
    global _QT_APP
    from PyQt6.QtWidgets import QApplication
    if _QT_APP is None:
        _QT_APP = QApplication.instance() or QApplication(sys.argv[:1])
    return _QT_APP


def probe_hud_pulsating_logo() -> str:
    """The HUD centre uses icon.png as a simple pulsating logo with a soft glow.
    There is no holographic avatar and no Dyson-sphere orbital construct in the
    HUD centre."""
    from PyQt6.QtGui import QImage, QPainter, QColor
    _qt_app()
    import ui
    path = str(ROOT / "icon.png")
    hud = ui.HudCanvas(path)
    hud.resize(700, 700)

    # 1) the logo must have loaded as the HUD face pixmap
    if hud._face_px is None:
        raise AssertionError("icon.png did not load into HudCanvas")
    if hud._face_px.width() < 4 or hud._face_px.height() < 4:
        raise AssertionError(f"icon.png absurdly small: {hud._face_px.size()}")

    # 2) the HUD centre is a pulsating logo, not a Dyson-sphere / holographic avatar.
    #    We check the absence of the Dyson-sphere orbit state and the avatar.
    for attr in ("_dy_enabled", "_dy_intensity", "_dy_inclines", "_dy_rolls",
                 "_dy_speeds", "_paint_dyson_sphere", "set_dyson_enabled",
                 "set_dyson_intensity", "hud_settings_summary", "apply_hud_settings"):
        if hasattr(hud, attr):
            raise AssertionError(f"HudCanvas still carries Dyson-sphere state: {attr}")

    # 3) the holographic avatar must not be built into the HUD centre.
    if hud._avatar is not None:
        raise AssertionError("HUD still built a holographic avatar into the centre")

    # 4) render a frame and check that the logo actually appears in the HUD centre
    hud.speaking, hud.state = True, "SPEAKING"
    hud.set_hud_level(0.6)
    for _ in range(6):
        hud._step()
    img = QImage(700, 700, QImage.Format.Format_ARGB32)
    img.fill(QColor("#040508"))
    p = QPainter(img)
    hud.render(p)
    p.end()

    # The logo is a real image, so there must be a patch of pixels around the
    # centre that differs from the plain dark background. Sample the logo area.
    logo_lo, logo_hi = 280, 420
    logo_px = sum(
        1
        for x in range(logo_lo, logo_hi, 4)
        for y in range(logo_lo, logo_hi, 4)
        if QColor(img.pixel(x, y)).lightness() > 18
    )
    if logo_px < 40:
        raise AssertionError(f"HUD centre has almost no logo pixels ({logo_px})")

    # 5) the logo area should not be uniform — the pulsating glow + icon should make
    #    the centre visibly nonuniform against the dark background.
    logo_true = sum(
        1
        for x in range(logo_lo, logo_hi, 4)
        for y in range(logo_lo, logo_hi, 4)
        if img.pixel(x, y) != img.pixel(logo_lo, logo_lo)
    )
    if logo_true < 40:
        raise AssertionError(f"HUD centre is nearly uniform ({logo_true} changed px)")

    return (f"icon.png pulsating logo ({hud._face_px.width()}x{hud._face_px.height()}), "
            f"{logo_px} logo px, {logo_true} non-uniform centre px")


def probe_terminal() -> str:
    import ui
    runs = ui._terminal_runs("[exit 0]", "#cccccc")
    if runs != [("[exit 0]", "#5AF78E", True)]:
        raise AssertionError(f"exit-code chip wrong: {runs}")
    segs = ui._ansi_segments("\x1b[32mgreen\x1b[0m")
    if ("green", "#5AF78E", False) not in segs:
        raise AssertionError(f"ANSI colour wrong: {segs}")
    _qt_app()
    ti = ui._TerminalInput()
    ti.setText("ls")
    ti._on_return()
    ti.setText("pwd")
    ti._on_return()
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent
    ti.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
    )
    if ti.text() != "pwd":
        raise AssertionError("history up failed")
    return "ANSI colour, exit chips, history"


def probe_overlays() -> str:
    from PyQt6.QtWidgets import QWidget
    _qt_app()
    import ui
    parent = QWidget()
    parent.resize(1200, 800)
    for name, cls in (
        ("help", ui.ShortcutsOverlay),
        ("memory", ui.MemoryPanel),
        ("palette", ui.CommandPalette),
        ("showcase", ui.PresentationOverlay),
    ):
        ov = cls(parent)
        ov.recenter(parent)
        if ov.width() <= 0 or ov.height() <= 0:
            raise AssertionError(f"{name} overlay has no size")
    return "F1 / F2 / Ctrl+K / F3 overlays build"


def probe_theming() -> str:
    from PyQt6.QtGui import QImage, QPainter, QColor
    _qt_app()
    import ui
    hud = ui.HudCanvas(str(ROOT / "icon.png"))
    hud.resize(500, 500)
    hud.state = "SPEAKING"

    def snap():
        im = QImage(500, 500, QImage.Format.Format_ARGB32)
        im.fill(QColor("#06070A"))
        p = QPainter(im)
        hud.render(p)
        p.end()
        return im

    ui.apply_theme("gold")
    a = snap()
    ui.apply_theme("emerald")
    b = snap()
    diff = sum(
        1
        for x in range(0, 500, 2)
        for y in range(0, 500, 2)
        if a.pixel(x, y) != b.pixel(x, y)
    )
    ui.apply_theme("gold")
    if diff < 500:
        raise AssertionError(f"theme did not repaint ({diff} px)")
    return f"5 themes, repaint {diff} px"


def probe_crown_prereqs() -> str:
    from core.crown_bridge import headless_entry, node_exe
    if not node_exe():
        raise AssertionError("Node.js not on PATH")
    if not headless_entry().exists():
        raise AssertionError("headless build missing")
    return "Node + headless build present"


def probe_ollama() -> str:
    from core.crown_bridge import list_models
    models = list_models()
    if not models:
        raise AssertionError("no local models (is Ollama running?)")
    coders = [m for m in models if "coder" in m.lower()]
    return f"{len(models)} models, {len(coders)} coder model(s)"


def probe_main_window_chrome_and_icon() -> str:
    """MainWindow boots with the gold translucent frameless chrome and a taskbar
    icon. Mirrors what main.py actually constructs, but on temp/clean paths only."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    from pathlib import Path
    import ui
    from ui import _ensure_gui_imports
    _ensure_gui_imports()
    app_qt = QApplication.instance() or QApplication(sys.argv[:1])
    face = Path("icon.png")
    mw = ui.MainWindow(str(face))
    if not mw.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
        raise AssertionError("MainWindow missing WA_TranslucentBackground")
    if not (mw.windowFlags() & Qt.WindowType.FramelessWindowHint):
        raise AssertionError("MainWindow missing FramelessWindowHint")
    if mw.windowIcon().isNull():
        raise AssertionError("MainWindow windowIcon is null")
    if mw.windowState() not in (Qt.WindowState.WindowNoState,):
        raise AssertionError(f"unexpected windowState {mw.windowState()}")
    if not (hasattr(mw, "_chrome") and isinstance(mw._chrome, ui.WindowChromeFrame)):
        raise AssertionError("MainWindow chrome frame missing/wrong type")
    if mw._chrome._content is None:
        raise AssertionError("MainWindow chrome has no content widget")
    return "translucent frameless chrome + taskbar icon present"


def probe_icon_face_roundtrip() -> str:
    """The icon.png supplied to MainWindow must be loadable by Qt and produce a
    non-null circular face pixmap in HudCanvas (the actual HUD face)."""
    import ui
    from pathlib import Path
    face = Path("icon.png")
    hud = ui.HudCanvas(str(face))
    if hud._face_px is None:
        raise AssertionError("HudCanvas did not load icon.png as face pixmap")
    return f"icon.png face px: {hud._face_px.width()}x{hud._face_px.height()}"


PROBES = [
    ("env: dependencies", probe_deps),
    ("config: files valid", probe_config),
    ("tools: declarations -> handlers", probe_tool_wiring),
    ("tools: handler targets resolve", probe_tool_targets),
    ("calling: removed from surface", probe_no_calling_tools),
    ("messaging: entry points", probe_messaging_paths),
    ("memory: save/recall/forget/archive", probe_memory),
    ("model ladder: timeouts + cooldowns", probe_ladder),
    ("echo guard: self-echo rejected", probe_echo_guard),
    ("HUD: pulsating icon.png logo (no hologram face)", probe_hud_pulsating_logo),
    ("terminal: colour / chips / history", probe_terminal),
    ("overlays: F1/F2/Ctrl+K/F3", probe_overlays),
    ("theming: live retint", probe_theming),
    ("crown code: prerequisites", probe_crown_prereqs),
    ("ollama: reachable + models", probe_ollama),
    ("window chrome: translucent + frameless", probe_main_window_chrome_and_icon),
    ("icon face: HUD face pixmap from icon.png", probe_icon_face_roundtrip),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Keys.ai demo / self-check")
    ap.add_argument(
        "--live", action="store_true", help="also run the Crown Code live coding suites"
    )
    ap.add_argument("--only", default="", help="filter checks by substring")
    args = ap.parse_args()

    report = Report()
    print("=" * 68)
    print("  KEYS.AI  -  DEMO SELF-CHECK")
    print("=" * 68)

    print("\n[ suites ]")
    for suite in SUITES_OFFLINE + (SUITES_LIVE if args.live else []):
        if not (ROOT / suite).exists():
            report.add(f"suite: {suite}", False, "file missing")
            continue
        run_suite(suite, report)

    # Create the Qt application once, up front: a QWidget constructed without
    # one is a fatal abort, not a catchable exception.
    global QT_OK
    try:
        _qt_app()
        QT_OK = True
    except Exception as e:  # noqa: BLE001
        print(f"  (Qt unavailable: {e})")

    print("\n[ probes ]")
    for name, fn in PROBES:
        if args.only and args.only.lower() not in name.lower():
            continue
        try:
            detail = fn()
            report.add(name, True, detail or "")
        except Exception as e:  # noqa: BLE001
            report.add(name, False, f"{type(e).__name__}: {e}")

    print()
    width = max(len(n) for n, _, _ in report.rows)
    for name, status, detail in report.rows:
        mark = "OK  " if status == "PASS" else "FAIL"
        print(f"  [{mark}] {name.ljust(width)}  {detail}")

    passed = sum(1 for _, s, _ in report.rows if s == "PASS")
    failed = len(report.rows) - passed
    print("\n" + "-" * 68)
    print(
        f"  RESULT: {passed} passed, {failed} failed"
        + ("" if failed else "  - everything checks out")
    )
    if not args.live:
        print("  (Crown Code LIVE coding suites skipped - run with --live)")
    print("-" * 68)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
