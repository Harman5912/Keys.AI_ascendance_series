"""Capture what the app actually looks like, as PNG files.

There is no way to reason about "the window looks wrong" without seeing it.
This starts the real window, optionally opens the globe, and writes PNGs that
can be opened and inspected.

    python qa_artifacts/regression_tests/screen_capture.py
    python qa_artifacts/regression_tests/screen_capture.py --globe

Writes qa_artifacts/screens/hud.png, globe.png and a one-line summary of what
each shot contains (size, centre view, visible widgets).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "qa_artifacts" / "screens"


def main() -> int:
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    import ui                                        # WebEngine import order

    app = QApplication.instance() or QApplication(sys.argv)
    ui._ensure_gui_imports()
    window = ui.MainWindow("icon.png")
    window.resize(1280, 800)
    window.show()
    OUT.mkdir(parents=True, exist_ok=True)

    def shot(name: str) -> None:
        path = OUT / f"{name}.png"
        pixmap = window.grab()
        pixmap.save(str(path), "PNG")
        centre = window._center_stack.currentWidget()
        print(f"{name:8s} {pixmap.width()}x{pixmap.height()} "
              f"centre={type(centre).__name__} -> {path}", flush=True)

    def run() -> None:
        shot("hud")
        if "--globe" in sys.argv:
            from globe import tools

            tools.register_ui(window)
            print(tools.globe({"action": "open"})[:120], flush=True)
            QTimer.singleShot(6000, after_globe)
        else:
            app.quit()

    def after_globe() -> None:
        shot("globe")
        from globe import tools
        print(tools.globe({"action": "navigate",
                           "location": "Eiffel Tower, Paris"})[:120], flush=True)
        QTimer.singleShot(5000, after_fly)

    def after_fly() -> None:
        shot("globe_paris")
        app.quit()

    QTimer.singleShot(2500, run)
    QTimer.singleShot(90_000, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
