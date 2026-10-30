"""Agent-facing tool: let the model see, choose and run skills.

Registered in ``core/tool_registry.py`` as ``skills`` and declared in
``core/tool_declarations.py``, so it is reachable exactly like every other tool.

The model may not approve its own consequential action: ``run`` refuses a
MODERATE or DANGEROUS skill unless the caller passes ``approved=true``, which the
engine sets only from an actual user answer.
"""

from __future__ import annotations

import json


def _restraint() -> str:
    return ("Use at most the skills the request actually needs. One skill that "
            "does the job is better than three that nearly do.")


def skills(parameters: dict | None = None, ui=None, speak=None) -> str:
    """Handle one ``skills`` tool call. Returns the sentence to show/speak."""
    parameters = dict(parameters or {})
    action = str(parameters.get("action") or "list").strip().lower()

    from skills.registry import get_registry
    from skills.runner import SkillContext

    registry = get_registry()

    if action in ("list", "all"):
        from skills.inventory import evidence, status_of

        proven = evidence()
        lines = ["Skills:"]
        for entry in registry.all():
            status, _ = status_of(entry, proven)
            if not entry.enabled:
                status += " (disabled)"
            lines.append(f"- {entry.manifest.name} [{status}]: "
                         f"{entry.manifest.purpose}")
        return "\n".join(lines)

    if action in ("inspect", "describe"):
        name = str(parameters.get("name") or "").strip().lower()
        entry = registry.get(name)
        if entry is None:
            return f"No skill named '{name}'."
        return json.dumps(entry.as_dict(), indent=2, ensure_ascii=False)

    if action == "search":
        query = str(parameters.get("query") or "").strip()
        hits = registry.search(query)
        if not hits:
            return f"No skill matches '{query}'."
        return "\n".join(f"- {e.manifest.name}: {e.manifest.purpose}"
                         for e in hits)

    if action in ("select", "plan"):
        from skills.orchestrator import plan

        request = str(parameters.get("request") or parameters.get("query")
                      or "").strip()
        result = plan(registry, request)
        if result.clarification:
            return result.clarification
        lines = [f"For '{request}' these are the relevant skills:"]
        for candidate in result.candidates:
            approval = " (needs the user's approval)" if candidate.needs_approval else ""
            lines.append(f"- {candidate.name}{approval}: {candidate.reason}")
        lines.append(_restraint())
        return "\n".join(lines)

    if action in ("run", "execute"):
        name = str(parameters.get("name") or "").strip().lower()
        if not name:
            return "Which skill should I run?"
        extra = parameters.get("parameters") or parameters.get("inputs") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except ValueError:
                return "The skill parameters must be a JSON object."
        if not isinstance(extra, dict):
            return "The skill parameters must be a JSON object."
        ctx = SkillContext(ui=ui, speak=speak,
                           approved=bool(parameters.get("approved")))
        result = registry.execute(name, extra, ctx)
        if result.refused:
            return f"Not run: {result.error}"
        if not result.ok:
            return f"{name} failed: {result.error}"
        return result.output or f"{name} finished."

    if action in ("enable", "disable"):
        name = str(parameters.get("name") or "").strip().lower()
        result = registry.set_enabled(name, action == "enable")
        return (f"'{result['name']}' is now "
                f"{'enabled' if result.get('enabled') else 'disabled'}."
                if result.get("ok") else f"Cannot {action}: {result.get('error')}")

    if action in ("status", "inventory", "diagnose"):
        inventory = registry.inventory()
        counts = inventory["counts"]
        totals = inventory["totals"]
        lines = [f"{totals['available']} of {totals['registered']} skills are "
                 f"usable; {totals['planned']} catalogued capabilities are still "
                 "missing.",
                 "status: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))]
        if inventory["load_errors"]:
            lines.append("load errors: " + "; ".join(inventory["load_errors"]))
        return "\n".join(lines)

    return (f"Unknown skills action '{action}'. Use list, search, inspect, "
            "select, run, enable, disable or status.")
