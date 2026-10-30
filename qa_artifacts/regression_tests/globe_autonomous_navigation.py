"""Can the agent open the globe and take it anywhere on its own?

This drives the same path a spoken or typed command takes (`globe.tools.globe`
from a worker thread) and then reads the **real Cesium camera** back out of the
page, so a "success" sentence with a camera that never moved cannot pass.

Two failure modes are covered explicitly:

* the open deadlock — `open()` used to take the same lock the GUI-side job
  needed, freezing the window for 240 s before reporting "the UI did not answer"
* silent no-op navigation — a location the page cannot geocode must be reported
  as a failure, and a successful one must leave the camera where it was asked

    python qa_artifacts/regression_tests/globe_autonomous_navigation.py
"""

from __future__ import annotations

import faulthandler
import json
import math
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

faulthandler.enable(all_threads=True)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CAMERA_JS = (
    "(function(){var v=window.__godsEyeView;"
    "if(!v||!v.viewer)return JSON.stringify(null);"
    "var c=v.viewer.camera.positionCartographic;"
    "return JSON.stringify({lat:c.latitude*180/Math.PI,"
    "lon:c.longitude*180/Math.PI,height:c.height});})()"
)

#: (label, kind, value, tolerance in degrees) — tolerance covers the geocoder's
#: choice of city/landmark centre, not the camera's accuracy.
TARGETS = [
    ("Tokyo",              "query", "Tokyo",                       0.6),
    ("Eiffel Tower",       "query", "Eiffel Tower, Paris",         0.6),
    ("Kanpur",             "query", "Kanpur, India",               0.6),
    ("Sydney Opera House", "query", "Sydney Opera House",          0.6),
    ("Reykjavik",          "query", "Reykjavik, Iceland",          0.6),
    ("Cape Town",          "query", "Cape Town, South Africa",     0.6),
    ("Null Island",        "coords", (0.0, 0.0),                   0.05),
    ("Antarctica",         "query", "Antarctica",                  2.5),
]

EXPECTED = {
    "Tokyo": (35.68, 139.69),
    "Eiffel Tower": (48.86, 2.29),
    "Kanpur": (26.45, 80.33),
    "Sydney Opera House": (-33.86, 151.21),
    "Reykjavik": (64.15, -21.94),
    "Cape Town": (-33.92, 18.42),
    "Null Island": (0.0, 0.0),
}


def main() -> int:
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    # `ui` imports QtWebEngine at module scope; importing it before the
    # QApplication exists is main.py's order and is what keeps WebEngine alive.
    import ui

    app = QApplication.instance() or QApplication(sys.argv)
    ui._ensure_gui_imports()
    window = ui.MainWindow("icon.png")
    window.show()

    results: list[tuple[str, bool, str]] = []

    def camera(timeout: float = 15.0):
        """Read the live camera position out of the page."""
        workspace = getattr(window, "_globe_ws", None)
        if workspace is None or workspace.view is None:
            return None
        box: dict = {}
        done = threading.Event()

        def scheduled():
            page = workspace.view.page()

            def got(value):
                box["v"] = value
                done.set()

            page.runJavaScript(CAMERA_JS, got)
            return True

        try:
            window.run_on_gui_thread(scheduled, timeout=timeout)
        except Exception:
            return None
        if not done.wait(timeout):
            return None
        try:
            return json.loads(box.get("v") or "null")
        except (TypeError, ValueError):
            return None

    def work() -> None:
        from globe import tools

        tools.register_ui(window)

        # 1. Open. The old deadlock made this report a 240 s UI timeout.
        t0 = time.perf_counter()
        opened = tools.globe({"action": "open"})
        opened_s = time.perf_counter() - t0
        opened_ok = ("failed" not in opened.lower()
                     and "did not answer" not in opened.lower())
        results.append((
            "open",
            opened_ok and opened_s < 45,
            f"{opened_s:.1f}s — {opened[:96]}",
        ))
        if not opened_ok:
            QTimer.singleShot(0, app.quit)
            return

        here = camera()
        results.append(("camera readable", isinstance(here, dict), str(here)))

        # 2. Fly everywhere, one place at a time, exactly as the agent would.
        for label, kind, value, tol in TARGETS:
            if kind == "query":
                spoken = tools.globe({"action": "navigate", "location": value})
            else:
                spoken = tools.globe({
                    "action": "navigate",
                    "latitude": value[0],
                    "longitude": value[1],
                })
            where = camera()
            ok = ("failed" not in spoken.lower()
                  and "cancelled" not in spoken.lower()
                  and isinstance(where, dict))
            detail = f"{spoken[:70]!r}"
            if ok and label in EXPECTED:
                want_lat, want_lon = EXPECTED[label]
                ok = (abs(where["lat"] - want_lat) <= tol
                      and abs(abs(where["lon"] - want_lon) - 0.0) <= 180)
                if abs(where["lon"] - want_lon) > tol:
                    # allow the ±360 wrap the geocoder can land on
                    ok = abs(abs(where["lon"] - want_lon) - 360.0) <= tol
                detail += (f" → camera {where['lat']:.2f},{where['lon']:.2f}"
                           f" (want {want_lat:.2f},{want_lon:.2f})")
            elif ok:
                detail += f" → camera {where['lat']:.2f},{where['lon']:.2f}"
            results.append((label, bool(ok), detail))

        QTimer.singleShot(0, app.quit)

    QTimer.singleShot(1500, lambda: threading.Thread(target=work,
                                                     daemon=True).start())
    QTimer.singleShot(420_000, app.quit)
    app.exec()

    print("=" * 74, flush=True)
    print("globe autonomous navigation", flush=True)
    print("=" * 74, flush=True)
    failures = 0
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:22s} {detail}", flush=True)
        failures += 0 if ok else 1
    print("=" * 74, flush=True)
    print(f"{len(results) - failures}/{len(results)} passed", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
