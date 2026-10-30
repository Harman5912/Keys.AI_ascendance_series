"""Diagnose *where* the globe makes the window stop responding.

The previous probe only proved a stall existed. This one separates the phases so
the cause is named rather than guessed:

    open            agent asks for the globe (server is already up)
    navigate        fly to a location
    idle_visible    globe on screen, nothing asked of it
    back_to_hud     user pressed BACK; HUD is on screen, page still alive
    frames          how many rAF ticks the page serves per second

Three outcomes are distinguishable:

* a gap with the main thread parked in a Python frame  -> our code blocks
* a gap with every Python frame idle                    -> Chromium/compositor
* idle_visible or back_to_hud stalling                  -> the page keeps
                                                           rendering when it
                                                           should not

Stacks for the worst stall are written to QA_STALL_FILE.

    python qa_artifacts/regression_tests/globe_stall_diagnose.py
"""

from __future__ import annotations

import faulthandler
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# A native fault inside Chromium kills the interpreter with no Python
# traceback at all (exit 127, empty log). faulthandler prints every thread's
# Python frames the moment that happens, which is the only way to tell which
# call was on the stack.
faulthandler.enable(all_threads=True)

# Do not force software rendering here: the point is to measure the environment
# the user actually runs, not a special one.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--enable-unsafe-swiftshader")

HEARTBEAT_MS = 50
STALL_MS = 1200
QA_DIR = ROOT / "qa_artifacts"
STALL_FILE = QA_DIR / "globe_stall_stacks.txt"
REPORT_FILE = QA_DIR / "globe_stall_report.txt"

_lines: list[str] = []


def say(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def main() -> int:
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    import ui

    ui._ensure_gui_imports()
    window = ui.MainWindow("icon.png")
    window.show()

    start = time.perf_counter()
    phase = {"name": "startup"}
    gaps: list[tuple[float, float, str]] = []      # (gap_s, at_s, phase)
    last = [start]
    dumped = {"done": False}

    def tick() -> None:
        now = time.perf_counter()
        gap = now - last[0]
        last[0] = now
        gaps.append((gap, now - start, phase["name"]))
        if gap * 1000 > STALL_MS and not dumped["done"]:
            dumped["done"] = True
            try:
                with open(STALL_FILE, "w", encoding="utf-8") as handle:
                    handle.write(f"stall {gap:.2f}s during phase={phase['name']}\n")
                    faulthandler.dump_traceback(file=handle, all_threads=True)
            except OSError:
                pass

    beat = QTimer()
    beat.setInterval(HEARTBEAT_MS)
    beat.timeout.connect(tick)
    beat.start()

    def js(script: str, timeout: float = 6.0):
        """Run JS on the globe page, waiting with a nested loop (GUI thread)."""
        from globe import tools as globe_tools

        service = globe_tools._service()
        workspace = getattr(window, "_globe_ws", None)
        if workspace is None or workspace.view is None:
            return None
        loop = QEventLoop()
        box: dict = {}

        def done(value):
            box["v"] = value
            loop.quit()

        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(int(timeout * 1000))
        workspace.view.page().runJavaScript(script, done)
        loop.exec()
        timer.stop()
        return box.get("v")

    result: dict = {}

    def work() -> None:
        from globe import tools

        tools.register_ui(window)

        phase["name"] = "open"
        t0 = time.perf_counter()
        result["open"] = tools.globe({"action": "open"})
        result["open_s"] = round(time.perf_counter() - t0, 1)

        # Frames per second the page actually serves while it is on screen and
        # nothing is being asked of it. 60/s means Cesium never parked.
        QTimer.singleShot(0, lambda: js(
            "window.__qz=0;(function l(){window.__qz++;"
            "requestAnimationFrame(l);})();1", 3.0))

        phase["name"] = "navigate"
        t0 = time.perf_counter()
        result["nav"] = tools.globe({"action": "navigate",
                                     "location": "Kanpur, India"})
        result["nav_s"] = round(time.perf_counter() - t0, 1)

        phase["name"] = "idle_visible"
        time.sleep(20)

        frames = {}
        def grab():
            frames["count"] = js("window.__qz || 0", 4.0)
        QTimer.singleShot(0, grab)
        time.sleep(6)
        result["frames"] = frames.get("count")

        phase["name"] = "back_to_hud"
        QTimer.singleShot(0, window._show_hud_view)
        time.sleep(25)

        phase["name"] = "done"
        QTimer.singleShot(0, app.quit)

    QTimer.singleShot(2000, lambda: threading.Thread(target=work, daemon=True).start())
    QTimer.singleShot(240_000, app.quit)
    app.exec()

    total = time.perf_counter() - start
    say("=" * 66)
    say(f"globe stall diagnosis — {total:.1f}s total, heartbeat {HEARTBEAT_MS}ms")
    say("=" * 66)
    for key in ("open", "navigate"):
        if key in result:
            say(f"{key:10s} {result.get(key + '_s', 0):5.1f}s  {str(result[key])[:90]}")

    by_phase: dict[str, list[float]] = {}
    for gap, _at, name in gaps:
        by_phase.setdefault(name, []).append(gap)
    say("")
    say(f"{'phase':14s} {'ticks':>6s} {'worst':>8s} {'>1.2s':>6s}")
    for name, values in by_phase.items():
        worst = max(values) if values else 0.0
        stalls = sum(1 for v in values if v * 1000 > STALL_MS)
        say(f"{name:14s} {len(values):6d} {worst:7.2f}s {stalls:6d}")
    say("")
    say(f"page frames counted while idle+visible: {result.get('frames')!r}")
    say("  (~1 means Cesium parked; ~120+ means it rendered continuously)")
    if STALL_FILE.exists():
        say(f"stacks for worst stall: {STALL_FILE}")
    else:
        say("no stall above threshold; no stacks written")

    try:
        REPORT_FILE.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    except OSError:
        pass

    stalls = [g for g in by_phase.get("idle_visible", []) + by_phase.get("back_to_hud", [])]
    return 1 if any(g * 1000 > STALL_MS for g in stalls) else 0


if __name__ == "__main__":
    raise SystemExit(main())
