"""Skill: the design system — tokens, contrast and layout guidance.

This one has no backing tool: it runs the repository's real design module. Its
whole point is that generated interfaces come from a contrast-checked token set
instead of invented colours.
"""

from __future__ import annotations

SKILL = {
    "name": "design-system",
    "purpose": "Produce a contrast-checked palette, type scale and layout "
               "guidance for an interface, or verify one.",
    "version": "1.0.0",
    "group": "interface",
    "capabilities": ["build tokens", "check contrast", "design brief",
                     "layout guidance"],
    "tools": [],
    "permission": "SAFE",
    "instructions": "Use action='tokens' with a seed for a colour set, "
                    "action='check' to run the module's own self-test first.",
    "triggers": ["design system", "colour palette", "contrast check",
                 "design brief", "make it accessible"],
    "inputs": {
        "action": {"type": "string",
                   "description": "tokens | check | brief (default: tokens)"},
        "seed": {"type": "string", "description": "Colour seed or mood word"},
        "kind": {"type": "string", "description": "web | dashboard | desktop"},
        "mood": {"type": "string", "description": "dark | light"},
    },
    "outputs": ["a token sheet, a design brief, or a pass/fail self-test"],
    "timeout": 30.0,
    "tags": ["design", "ui", "accessibility"],
}


def run(parameters: dict, ctx) -> dict:
    action = str(parameters.get("action") or "tokens").strip().lower()
    from core import design_system

    if action == "check":
        report = design_system.selftest()
        ok = bool(report.get("ok"))
        return {"ok": ok, "output": _summarise(report),
                "error": "" if ok else "the design self-test reported failures"}

    kind = design_system.normalise_kind(parameters.get("kind") or "web")
    seed = str(parameters.get("seed") or "keys").strip() or "keys"
    mood = str(parameters.get("mood") or "dark").strip() or "dark"

    if action == "brief":
        return {"ok": True,
                "output": design_system.design_brief(seed, kind=kind, mood=mood)}

    tokens = design_system.build_tokens(seed, kind=kind, mood=mood)
    brief = design_system.design_brief(seed, kind=kind, mood=mood)
    return {"ok": True, "output": f"{brief}\n\n{tokens.to_css()}"}


def _summarise(report: dict) -> str:
    lines = [f"design self-test: {'passed' if report.get('ok') else 'FAILED'}"]
    for key, value in report.items():
        if key == "ok":
            continue
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def verify() -> tuple[bool, str, str]:
    """Runs the module's real self-test over 96 token sets."""
    try:
        from core import design_system

        report = design_system.selftest()
        return (bool(report.get("ok")),
                f"self-test ok={report.get('ok')} over "
                f"{report.get('checked')} token sets", "functional")
    except Exception as exc:
        return False, f"design_system failed: {exc}", "functional"
