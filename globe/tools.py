"""globe.tools — the agent-facing face of the globe integration.

``main.py`` dispatches every registry tool as ``(parameters, ui, speak)``, so
this module is the single place both the text assistant and the voice assistant
reach the globe through. There is deliberately **no launcher button** and no
second microphone: an utterance ("Keys, open the globe", "take me to Kanpur")
reaches here either as a model tool call or as a deterministic utterance match.

Success is only reported when the running app actually accepted the action. A
refusal, a timeout, or a missing checkout comes back as a plain failure sentence
— never as "done".
"""

from __future__ import annotations

import json

_registered_ui = None


def register_ui(window) -> None:
    """Remember the main window so the service can reach the Qt thread."""
    global _registered_ui
    _registered_ui = window
    try:
        from globe import get_service
        get_service().attach(window)
    except Exception:
        pass


def _service():
    from globe import get_service
    service = get_service()
    if _registered_ui is not None:
        service.attach(_registered_ui)
    return service


def _coord(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _describe_result(result: dict) -> str:
    """A truthful one-paragraph outcome for the user."""
    if not result.get("ok"):
        message = str(result.get("error") or "The globe could not do that.")
        hints = result.get("hints") or []
        if hints:
            message = f"{message} {hints[0]}"
        return f"Globe: {message}"

    action = str(result.get("action") or "")
    payload = result.get("result")

    if action.endswith("NAVIGATE_TO_LOCATION") or action == "NAVIGATE_TO_LOCATION":
        # The app's own label is on the envelope itself (``_from_runner`` copies
        # its keys up), so look there as well as under ``result``.
        target = (_target_from(payload) or _target_from(result)
                  or result.get("target") or "")
        return (f"The globe flew to {target}." if target
                else "The globe moved to the requested location.")
    if action == "ZOOM_IN":
        return "Zoomed in on the globe."
    if action == "ZOOM_OUT":
        return "Zoomed out on the globe."
    if action == "RESET_GLOBE":
        return "Reset the globe to the full Earth view."
    if action == "TOGGLE_DATA_LAYER":
        state = "on" if result.get("enabled", True) else "off"
        return f"Turned the {result.get('layer', 'requested')} layer {state}."
    if action == "CLOSE_GLOBE":
        return "Closed the globe."
    if action == "OPEN_GLOBE":
        return f"The globe is open at {result.get('url', 'the local server')}."
    if action == "GET_GLOBE_STATUS":
        server = result.get("server") or {}
        state = "running" if server.get("running") else "not running"
        return f"The globe server is {state} on port {server.get('port') or '—'}."
    return "The globe completed the request."


def _target_from(payload) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("label", "name", "place", "query", "title"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def globe(parameters: dict | None = None, ui=None, speak=None) -> str:
    """Handle one ``globe`` tool call. Returns the sentence to say."""
    parameters = parameters or {}
    service = _service()
    action = str(parameters.get("action") or "open").strip().lower()

    if ui is not None:
        try:
            service.attach(getattr(ui, "_win", ui))
        except Exception:
            pass

    try:
        if action in ("open", "show", "launch", "start"):
            result = service.open()
            location = str(parameters.get("location") or "").strip()
            if result.get("ok") and location:
                result = service.navigate(location)
                result.setdefault("action", "NAVIGATE_TO_LOCATION")

        elif action in ("close", "hide", "back", "dismiss"):
            result = service.close()

        elif action in ("navigate", "go", "fly", "goto"):
            lat = _coord(parameters.get("latitude"))
            lon = _coord(parameters.get("longitude"))
            location = str(parameters.get("location") or parameters.get("query") or "").strip()
            result = service.navigate(location, lat, lon)

        elif action in ("search", "find"):
            result = service.search(
                str(parameters.get("query") or parameters.get("location") or ""))

        elif action in ("zoom", "zoom_in", "zoom_out"):
            direction = str(parameters.get("direction") or "").strip().lower()
            if not direction:
                direction = "out" if action == "zoom_out" else "in"
            amount = str(parameters.get("amount") or "medium").strip().lower()
            result = service.zoom(direction, amount)

        elif action in ("reset", "home", "earth", "globe_view"):
            result = service.reset()

        elif action in ("layer", "toggle_layer"):
            result = service.layer(
                str(parameters.get("layer") or ""),
                bool(parameters.get("enabled", True)),
            )

        elif action in ("status", "state"):
            result = service.status()

        else:
            result = {
                "ok": False,
                "error": f"Unknown globe action '{action}'.",
            }
    except Exception as exc:                       # never crash the tool loop
        result = {"ok": False, "error": f"The globe failed: {exc}"}

    if not result.get("ok") and speak is not None:
        # One short spoken line on failure; the detail stays in the log.
        try:
            speak("The globe could not do that.")
        except Exception:
            pass
    return _describe_result(result)


def handle_utterance(text: str, ui=None, speak=None) -> str | None:
    """Run a globe request that arrived as raw user text.

    Returns None when the text is not an explicit globe request, so the normal
    assistant path continues untouched.
    """
    service = _service()
    if ui is not None:
        try:
            service.attach(getattr(ui, "_win", ui))
        except Exception:
            pass
    try:
        result = service.handle_text(text)
    except Exception:
        return None
    if result is None:
        return None
    if result.get("ok") and speak is not None:
        try:
            speak(result.get("said") or "Opening the globe.")
        except Exception:
            pass
    return _describe_result(result)


def status_json() -> str:
    """Diagnostics used by the audit/health checks."""
    return json.dumps(_service().status(), indent=2)
