"""Skill: the globe (God's Eye View) — open it, fly it, control its layers.

Verified live in this repository (``qa_artifacts/regression_tests/
globe_live_probe.py``); this module only declares the contract and routes to the
``globe`` tool so there is one implementation, not two.
"""

from __future__ import annotations

from skills.builtin._delegate import run_tool, tool_ready

SKILL = {
    "name": "globe",
    "purpose": "Open God's Eye View and fly the 3D Earth to places, zoom, and "
               "switch data layers.",
    "version": "1.0.0",
    "group": "research",
    "capabilities": ["open the globe", "fly to a location", "zoom",
                     "toggle data layers", "close the globe"],
    "tools": ["globe"],
    "permission": "SAFE",
    "instructions": "Use action='open' to show it, 'navigate' with a location "
                    "or latitude/longitude to move, 'layer' to switch data on.",
    "triggers": ["open the globe", "show me the earth", "take me to kanpur",
                 "fly to paris", "zoom out on the globe", "close the globe"],
    "inputs": {
        "action": {"type": "string", "required": True,
                   "description": "open | close | navigate | search | zoom | "
                                  "reset | layer | status"},
        "location": {"type": "string",
                     "description": "Place name for navigate"},
        "latitude": {"type": "number"},
        "longitude": {"type": "number"},
        "query": {"type": "string", "description": "Search text"},
        "direction": {"type": "string", "description": "in | out"},
        "amount": {"type": "string", "description": "little | medium | lot"},
        "layer": {"type": "string", "description": "Layer id, e.g. satellites"},
        "enabled": {"type": "boolean"},
    },
    "outputs": ["a spoken sentence describing what actually happened"],
    "timeout": 180.0,
    "tags": ["globe", "earth", "map", "3d"],
}


def run(parameters: dict, ctx) -> dict:
    return run_tool("globe", parameters, ctx)


def verify() -> tuple[bool, str, str]:
    """Wiring plus a real parse — enough to call this functional.

    The globe itself was verified live against the running application in
    ``qa_artifacts/regression_tests/globe_live_probe.py``; what this check adds
    is that the skill still routes to it.
    """
    ready, detail = tool_ready("globe")
    if not ready:
        return False, detail, "wiring"
    try:
        from globe.intents import try_parse

        command = try_parse("open the globe")
        if command is None:
            return (False, "the globe intent parser did not recognise "
                           "'open the globe'", "functional")
        return (True, f"routing works (parsed as {command.action})",
                "functional")
    except Exception as exc:
        return False, f"globe intents unavailable: {exc}", "functional"
