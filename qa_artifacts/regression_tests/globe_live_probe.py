"""Live probe: does the real globe run inside Keys.AI's Chromium and move?

This is an end-to-end check against the running application, not a unit test.
It starts the real God's Eye View server, loads it in the same
``QWebEngineView`` the app uses, and then drives it exactly as the agent does —
through ``window.__godsEyeView.voiceCommands.runner``.

    python qa_artifacts/regression_tests/globe_live_probe.py

Checks, in order:
  1. the local server starts and serves the app
  2. the page publishes its command runner
  3. fly_to_location resolves a real place and the camera actually moves there
  4. adjust_camera_zoom changes the camera range
  5. zoom_to_globe returns to a full-Earth view
  6. the camera ends near the requested coordinates (not merely "no error")
  7. a second open reuses the same page instead of reloading it

Exit code 0 only when every check passes. Anything that fails prints why.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Cesium needs WebGL, and its camera animations advance on
# requestAnimationFrame — which Chromium only drives for a page that is actually
# being painted. So this probe opens a real window, exactly as Keys.AI does. In
# an offscreen/headless session nothing animates and every flight appears to
# hang, which is a property of the harness, not of the integration.
#
# The software rasteriser is requested as a fallback so the probe also works on
# a machine with no usable GPU; on real hardware the flag is simply unused.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--enable-unsafe-swiftshader")

KANPUR = (26.4499, 80.3319)

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        _failures.append(name)
    return ok


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def main() -> int:
    from PyQt6.QtWidgets import QApplication

    from globe import get_service
    from globe.workspace_ui import GlobeWorkspace

    app = QApplication.instance() or QApplication(sys.argv)
    service = get_service()

    # ── 1. Server ────────────────────────────────────────────────────────
    server = service.server.ensure(timeout=240)
    if not check("local server serves the app", bool(server.get("running")),
                 server.get("url") or server.get("error", "")):
        return 1

    # ── 2. Page hosted in QtWebEngine ────────────────────────────────────
    workspace = GlobeWorkspace()
    workspace.resize(1280, 800)
    workspace.show()
    app.processEvents()
    if not check("QtWebEngine view is available", workspace.available):
        return 1

    # The service reaches the page through the same accessor the app uses.
    service._workspace = lambda: workspace          # type: ignore[assignment]
    service._open_workspace = lambda url: (workspace.load(url), {"ok": True})[1]

    opened = service.open(timeout=180)
    if not check("globe page publishes its command runner", bool(opened.get("ok")),
                 str(opened.get("error", ""))):
        workspace.shutdown()
        return 1

    # ── 3. Navigation to a resolved place ────────────────────────────────
    opened_reuse = service.open(timeout=60)
    check("reopening reuses the live page", bool(opened_reuse.get("ok"))
          and service._page() is workspace.page())

    before = service._invoke("get_current_view_state", {})
    nav = service.navigate("Kanpur, Uttar Pradesh, India")
    if not check("navigate to Kanpur accepted", bool(nav.get("ok")),
                 str(nav.get("error", ""))):
        workspace.shutdown()
        return 1

    after = service._invoke("get_current_view_state", {})
    pos = _camera_position(after)
    if pos is None:
        check("camera position readable after navigation", False, str(after)[:300])
    else:
        km = _distance_km(pos, KANPUR)
        check("camera is actually near Kanpur", km < 250.0,
              f"{km:.0f} km from {KANPUR[0]}, {KANPUR[1]} (camera at "
              f"{pos[0]:.3f}, {pos[1]:.3f})")

    # ── 4. Zoom ──────────────────────────────────────────────────────────
    range_before = _camera_range(after)
    zoomed = service.zoom("in", "lot")
    time.sleep(1.2)
    after_zoom = service._invoke("get_current_view_state", {})
    range_after = _camera_range(after_zoom)
    check("zoom in reduced the camera range", bool(zoomed.get("ok"))
          and range_before and range_after and range_after < range_before,
          f"{range_before:.0f} m -> {range_after if range_after else 'n/a'}")

    # ── 5. Reset ─────────────────────────────────────────────────────────
    reset = service.reset()
    time.sleep(1.5)
    after_reset = service._invoke("get_current_view_state", {})
    reset_range = _camera_range(after_reset)
    check("reset returns to a full-Earth view", bool(reset.get("ok"))
          and reset_range is not None and reset_range > 5_000_000,
          f"range {reset_range:.0f} m" if reset_range else "range unreadable")

    # ── 6. Explicit coordinates are used as given ────────────────────────
    coords = service.navigate("", 48.8584, 2.2945)      # the Eiffel Tower
    time.sleep(1.2)
    pos2 = _camera_position(service._invoke("get_current_view_state", {}))
    if pos2 is not None:
        km2 = _distance_km(pos2, (48.8584, 2.2945))
        check("explicit coordinates are honoured", bool(coords.get("ok")) and km2 < 25.0,
              f"{km2:.1f} km from the Eiffel Tower")

    # ── 7. Layer control reports honestly ────────────────────────────────
    layer = service.layer("satellites", True)
    check("layer toggle answers", isinstance(layer.get("ok"), bool),
          f"ok={layer.get('ok')} {str(layer.get('error') or '')[:120]}")

    # ── 8. Unknown command never reaches the page ────────────────────────
    refused = service._invoke("run_arbitrary_js", {})
    check("unknown actions are refused", refused.get("ok") is False,
          str(refused.get("error", "")))

    # ── 9. The real tool path main.py dispatches ─────────────────────────
    # main.py calls TOOL_HANDLERS['globe'] -> globe.tools.globe. Exercise that
    # exact surface with a shim window so the wiring, not just the service, is
    # proven.
    class _Shim:
        def __init__(self, ws):
            self._globe_ws = ws
            self._win = self

        def run_on_gui_thread(self, fn, timeout=180.0):
            return fn()

        def _open_globe_workspace(self, url):
            ws.load(url)
            return {"ok": True, "url": url}

        def _show_hud_view(self):
            return None

    from globe import tools as globe_tools
    globe_tools.register_ui(_Shim(workspace))

    spoken = globe_tools.globe({"action": "navigate",
                                "location": "New Delhi, India"})
    check("tool path navigates and reports it", "flew to" in spoken.lower(), spoken)

    spoken = globe_tools.globe({"action": "zoom", "direction": "out",
                                "amount": "little"})
    check("tool path zooms out", "zoomed out" in spoken.lower(), spoken)

    spoken = globe_tools.globe({"action": "status"})
    check("tool path reports status", "running" in spoken.lower(), spoken)

    guarded = globe_tools.handle_utterance("open the globe")
    check("the utterance guard reaches the globe",
          guarded is not None and "globe" in guarded.lower(), str(guarded))

    untouched = globe_tools.handle_utterance("what is the capital of France")
    check("ordinary speech is left to the assistant", untouched is None,
          str(untouched))

    spoken = globe_tools.globe({"action": "close"})
    check("tool path closes the globe", "closed" in spoken.lower(), spoken)

    workspace.shutdown()
    print()
    if _failures:
        print(f"{len(_failures)} check(s) failed: {', '.join(_failures)}")
        return 1
    print("All live globe checks passed.")
    return 0


def _view_state(payload) -> dict:
    """The runner's view-state payload, wherever it nests the numbers.

    ``get_current_view_state`` returns the app's world packet, whose camera
    block is ``{latitude, longitude, heightM}`` (src/agent/worldPacket.js).
    """
    if not isinstance(payload, dict):
        return {}
    for key in ("result", "view", "state", "data"):
        inner = payload.get(key)
        if isinstance(inner, dict) and "camera" in inner:
            return inner
    return payload


def _camera_position(payload) -> tuple[float, float] | None:
    camera = _view_state(payload).get("camera")
    if isinstance(camera, dict):
        lat, lon = camera.get("latitude"), camera.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return (float(lat), float(lon))
    return None


def _camera_range(payload) -> float | None:
    """Camera height in metres — the app calls it ``heightM``."""
    camera = _view_state(payload).get("camera")
    if isinstance(camera, dict):
        value = camera.get("heightM")
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


if __name__ == "__main__":
    sys.exit(main())
