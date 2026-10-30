"""
test_crown_ui.py — offscreen smoke test for the embedded Crown Code terminal.

Confirms the terminal panel exists inside Keys.AI's live-creation workspace and
that streaming output, clearing, the running indicator, and the user-command /
stop signals all work — without needing the full app or a display.

Run:  python test_crown_ui.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main() -> int:
    failures: list[str] = []

    try:
        from PyQt6.QtWidgets import QApplication
        import ui as keys_ui
    except Exception as e:
        print(f"SKIP: cannot import the Keys.AI UI ({e})")
        return 2

    app = QApplication.instance() or QApplication(sys.argv)

    try:
        ws = keys_ui.CreationWorkspace()
    except Exception as e:
        print(f"FAIL: CreationWorkspace() raised: {e}")
        return 1

    # 1. Terminal widget present
    if not hasattr(ws, "_term_view") or not hasattr(ws, "_term_input"):
        print("FAIL: terminal widgets missing from CreationWorkspace")
        return 1
    print("PASS: terminal panel exists inside the creation workspace")

    # 2. Streaming output appears
    ws.terminal_write("hello ", "stdout")
    ws.terminal_write("error-line\n", "stderr")
    ws.terminal_write("[exit 0]\n", "meta")
    text = ws._term_view.toPlainText()
    if "hello" in text and "error-line" in text and "[exit 0]" in text:
        print("PASS: stdout/stderr/meta stream into the terminal")
    else:
        failures.append(f"terminal text wrong: {text!r}")

    # 3. Clear
    ws.terminal_clear()
    if ws._term_view.toPlainText() == "":
        print("PASS: terminal clear works")
    else:
        failures.append("terminal clear did not empty the view")

    # 4. Running indicator
    ws.set_terminal_running(True, "running")
    if ws._term_run_lbl.text() == "running":
        print("PASS: running-state indicator updates")
    else:
        failures.append("running indicator not updated")

    # 5. User command + stop signals
    seen: list[str] = []
    stops: list[int] = []
    ws.terminalCommandSubmitted.connect(lambda c: seen.append(c))
    ws.stopRequested.connect(lambda: stops.append(1))
    ws._term_input.setText("echo hi")
    ws._submit_terminal_cmd()
    if seen == ["echo hi"]:
        print("PASS: typing a command emits terminalCommandSubmitted")
    else:
        failures.append(f"command signal wrong: {seen}")
    ws._term_stop_btn.click()
    if stops:
        print("PASS: Stop button emits stopRequested")
    else:
        failures.append("stop signal not emitted")

    # 6. begin()/reset() lifecycle does not raise
    try:
        ws.begin("code", "demo", str(BASE_DIR))
        ws.reset()
        print("PASS: begin()/reset() lifecycle works")
    except Exception as e:
        failures.append(f"lifecycle error: {e}")

    # 7. Build-phase chip: phase, percent and ETA are visible at a glance
    try:
        ws.begin("code", "portfolio_lena", str(BASE_DIR))
        ws.set_phase("writing", 0.42, 90)
        chip = ws._phase_lbl.text()
        if "WRITING" in chip and "42%" in chip and "ETA" in chip:
            print(f"PASS: phase chip shows phase/percent/ETA ({chip!r})")
        else:
            failures.append(f"phase chip wrong: {chip!r}")
        ws.set_progress(0.55)
        if "55%" in ws._phase_lbl.text():
            print("PASS: progress updates the phase chip")
        else:
            failures.append(f"progress did not reach the chip: {ws._phase_lbl.text()!r}")
        ws.creation_event_for_test = None
        ws.add_event("→", "Writing index.html — 42% of the file")
        ws.complete("Built index.html (20949 bytes)")
        if "DONE" in ws._phase_lbl.text():
            print("PASS: completion marks the chip DONE")
        else:
            failures.append(f"chip not marked done: {ws._phase_lbl.text()!r}")

        shots = BASE_DIR / "qa_artifacts" / "screenshots"
        shots.mkdir(parents=True, exist_ok=True)
        ws.resize(1200, 340)
        ws.show()
        app.processEvents()
        png = shots / "creation_workspace_build.png"
        ws.grab().save(str(png))
        if png.exists() and png.stat().st_size > 5000:
            print(f"PASS: workspace screenshot written ({png.stat().st_size} bytes)")
        else:
            failures.append("workspace screenshot was not written")
        ws.reset()
    except Exception as e:
        failures.append(f"phase-chip check error: {e}")

    print("-" * 60)
    if failures:
        print(f"RESULT: FAIL ({len(failures)})")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: PASS — embedded terminal UI works")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
