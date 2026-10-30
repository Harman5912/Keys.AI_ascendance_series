"""Shared helper: a skill runs the tool that already exists.

Every builtin skill is a contract — manifest plus argument mapping — over a tool
that is already registered in ``core.tool_registry``. Nothing is re-implemented
here, so a fix to the tool fixes the skill too.
"""

from __future__ import annotations


def tool_callable(name: str):
    """The registered handler for `name`, or None."""
    try:
        from core.tool_registry import TOOL_HANDLERS
    except Exception:
        return None
    handler = TOOL_HANDLERS.get(name)
    return handler if callable(handler) else None


def run_tool(name: str, parameters: dict, ctx) -> dict:
    """Call a registered tool on behalf of a skill."""
    handler = tool_callable(name)
    if handler is None:
        return {"ok": False, "error": f"the '{name}' tool is not registered"}
    try:
        output = handler(dict(parameters or {}),
                         getattr(ctx, "ui", None),
                         getattr(ctx, "speak", None))
    except Exception as exc:                      # reported to the caller
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if isinstance(output, dict):
        return output
    return {"ok": True, "output": "" if output is None else str(output)}


def tool_ready(name: str) -> tuple[bool, str]:
    """Verification helper: the tool this skill claims is really wired."""
    return (tool_callable(name) is not None,
            "handler is registered" if tool_callable(name) else
            f"no handler registered for '{name}'")
