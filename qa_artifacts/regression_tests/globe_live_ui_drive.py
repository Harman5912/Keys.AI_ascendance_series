"""Drive the real Keys.AI window: type globe commands and watch them happen.

Runs the actual application window, types into the actual command bar, and lets
the real globe service open God's Eye View and fly it. A 50 ms heartbeat records
whether the window froze at any point, so "it lagged" becomes a number rather
than an impression.

    python qa_artifacts/regression_tests/globe_live_ui_drive.py [seconds_to_stay]

The window is left open for the requested time (default 300 s) so the run can be
watched; pass 0 to close as soon as the last command is done.
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

LOG_PATH = ROOT / "qa_artifacts" / "globe_ui_run.log"
COMMANDS = [
    "open the globe",
    "take me to Kanpur",
    "fly to Paris",
    "toggle the satellites layer",
    "zoom out",
    "reset the globe",
    "close the globe",
]


def main() -> int:
    stay = float(sys.argv[1]) if len(sys.argv) > 1 else 300.0
    log_file = open(LOG_PATH, "w", encoding="utf-8", buffering=1)

    def log(text: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {text}"
        print(line, flush=True)
        log_file.write(line + "\n")

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    import ui

    ui._ensure_gui_imports()
    window = ui.MainWindow("icon.png")
    window.show()

    # ── Text routing, exactly as main.py wires it ────────────────────────
    # KeysAIUI._send hands the text to this callback on a plain thread; the
    # globe guard answers deterministically instead of waiting for the model.
    def on_text(text: str) -> None:
        from globe.intents import try_parse

        if try_parse(text) is None:
            log(f"(not a globe request, left to the assistant): {text}")
            return
        from globe.tools import handle_utterance

        log(f"-> {text}")
        started = time.perf_counter()
        reply = handle_utterance(text, window, None)
        log(f"<- {reply}  [{time.perf_counter() - started:.1f}s]")

    window.on_text_command = on_text

    # ── Heartbeat: is the window still painting? ─────────────────────────
    gaps: list[tuple[float, float]] = []
    t0 = time.perf_counter()
    last = [t0]

    def tick() -> None:
        now = time.perf_counter()
        gaps.append((now - last[0], now - t0))
        last[0] = now

    beat = QTimer()
    beat.setInterval(50)
    beat.timeout.connect(tick)
    beat.start()

    queue = list(COMMANDS)

    def next_command() -> None:
        if not queue:
            log("all commands issued")
            if stay > 0:
                log(f"window stays open for {stay:.0f}s so it can be watched")
                QTimer.singleShot(int(stay * 1000), app.quit)
            else:
                window.close()
                app.quit()
            return
        text = queue.pop(0)
        window._input.setText(text)      # what typing looks like
        window._send()                   # what Enter looks like
        QTimer.singleShot(9000, next_command)

    QTimer.singleShot(2500, next_command)
    QTimer.singleShot(int((len(COMMANDS) * 9 + stay + 60) * 1000), app.quit)
    app.exec()

    beat.stop()
    worst = max(gaps, default=(0.0, 0.0))
    stalls = sorted([g for g in gaps if g[0] > 0.5], reverse=True)[:6]
    log(f"window alive {time.perf_counter() - t0:.0f}s, {len(gaps)} heartbeats")
    log(f"worst GUI stall: {worst[0] * 1000:.0f} ms at t={worst[1]:.1f}s")
    for gap, at in stalls:
        log(f"  stall {gap * 1000:6.0f} ms at t={at:6.1f}s")
    if not stalls:
        log("no stall over 500 ms — the window kept responding")
    log_file.close()
    return 0 if not stalls else 1


if __name__ == "__main__":
    raise SystemExit(main())
