"""Probe: does the window stay responsive while the globe opens?

The report from the desktop was "asked it to open the globe, the entire app
lagged and stopped responding". This measures that claim instead of guessing at
it: a 50 ms heartbeat runs on the Qt GUI thread while the globe is opened from a
worker thread (exactly how ``main.py`` dispatches the tool), and every gap
longer than a few frames is reported with the phase that was running.

    python qa_artifacts/regression_tests/globe_responsiveness_probe.py

Exit code 0 only when no phase stalls the GUI thread.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--enable-unsafe-swiftshader")

HEARTBEAT_MS = 50
STALL_MS = 750          # half a second of silence is where Windows paints "Not responding"


def main() -> int:
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    import ui

    ui._ensure_gui_imports()
    window = ui.MainWindow("icon.png")
    window.show()

    gaps: list[tuple[float, float]] = []
    phase = {"name": "startup"}
    marks: list[tuple[float, str]] = []
    start = time.perf_counter()
    last = [start]

    def tick() -> None:
        now = time.perf_counter()
        gaps.append((now - last[0], now - start))
        last[0] = now

    beat = QTimer()
    beat.setInterval(HEARTBEAT_MS)
    beat.timeout.connect(tick)
    beat.start()

    result: dict = {}

    def work() -> None:
        from globe import tools

        tools.register_ui(window)
        marks.append((time.perf_counter() - start, "globe.open called"))
        phase["name"] = "globe.open"
        t0 = time.perf_counter()
        spoken = tools.globe({"action": "open"})
        marks.append((time.perf_counter() - start, f"globe.open returned ({spoken[:90]})"))
        result["open"] = spoken
        result["open_s"] = round(time.perf_counter() - t0, 1)

        phase["name"] = "globe.navigate"
        marks.append((time.perf_counter() - start, "globe.navigate called"))
        t0 = time.perf_counter()
        spoken = tools.globe({"action": "navigate", "location": "Kanpur, India"})
        marks.append((time.perf_counter() - start, f"globe.navigate returned ({spoken[:90]})"))
        result["navigate"] = spoken
        result["navigate_s"] = round(time.perf_counter() - t0, 1)
        phase["name"] = "idle"
        QTimer.singleShot(0, app.quit)

    QTimer.singleShot(1500, lambda: threading.Thread(target=work, daemon=True).start())
    QTimer.singleShot(200_000, app.quit)
    app.exec()

    total = time.perf_counter() - start
    worst = max(gaps, default=(0.0, 0.0))
    stalls = [(g, t) for g, t in gaps if g * 1000 > STALL_MS]

    print()
    print(f"window alive for {total:.1f}s, {len(gaps)} heartbeats")
    print(f"worst GUI stall: {worst[0] * 1000:.0f} ms at t={worst[1]:.1f}s")
    if stalls:
        print(f"{len(stalls)} stall(s) over {STALL_MS} ms — the window would look frozen:")
        for gap, at in sorted(stalls, reverse=True)[:8]:
            print(f"  {gap * 1000:6.0f} ms at t={at:6.1f}s")
    else:
        print("no stall over the threshold — the window kept painting throughout")
    print()
    for at, what in marks:
        print(f"  t={at:6.1f}s  {what}")
    print()
    for key in ("open", "navigate"):
        if key in result:
            print(f"{key} ({result.get(key + '_s')}s): {result[key]}")

    try:
        window.close()
    except Exception:
        pass
    return 1 if stalls else 0


if __name__ == "__main__":
    raise SystemExit(main())
