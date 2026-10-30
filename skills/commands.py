"""Text commands for skills: ``/help`` and ``/skills …``.

Called from ``main.py`` before anything is sent to the model, so these work the
moment the window is up — no session required.

Consequential commands are deliberate about consent:

* ``/skills disable`` changes what the assistant can do, so it is allowed but
  reported clearly.
* ``/skills remove`` destroys an imported manifest and requires ``--yes``.
* ``/skills import`` accepts **JSON manifests only**. Importing Python code from
  a file or a downloaded package is not performed here at all — that would be
  remote code execution with extra steps.
"""

from __future__ import annotations

import json
from pathlib import Path

HELP = """\
/skills                     list every skill and its status
/skills search <query>      find skills by name, purpose or trigger
/skills inspect <name>      manifest, inputs, tools, permission and state
/skills run <name> [k=v ...] run a skill now (asks first if it is not SAFE)
/skills enable <name>       allow a skill to run
/skills disable <name>      stop a skill from running
/skills validate <name>     report manifest or dependency problems
/skills test <name>         run that skill's own live check
/skills diagnose            inventory counts, duplicates and load errors
/skills list-tools <name>   the registered tools a skill uses
/skills history             the last skill executions
/skills export <name>       print the skill's manifest as JSON
/skills import <path>       install a JSON manifest (never code)
/skills remove <name> --yes delete an imported manifest
/skills create <name>       declare a new capability (no code yet)
/skills plan <request>      which skills would handle this request
/help                       this list
"""


def is_command(text: str) -> bool:
    stripped = str(text or "").strip()
    return stripped.startswith("/")


def handle(text: str, ctx=None) -> str | None:
    """Answer a command. None when the text is not one."""
    stripped = str(text or "").strip()
    if not stripped.startswith("/"):
        return None
    parts = stripped.split()
    head = parts[0].lower()
    if head in ("/help", "/?"):
        return HELP.strip()
    if head != "/skills":
        return f"Unknown command {parts[0]}. Type /help for the list."

    from skills.registry import get_registry
    from skills.runner import SkillContext

    registry = get_registry()
    args = parts[1:]
    sub = args[0].lower() if args else "list"
    rest = args[1:]

    if sub == "list":
        return _list(registry)
    if sub == "search":
        return _search(registry, " ".join(rest))
    if sub == "inspect":
        return _inspect(registry, _arg(rest))
    if sub in ("enable", "disable"):
        result = registry.set_enabled(_arg(rest), sub == "enable")
        if not result.get("ok"):
            return f"Cannot {sub}: {result.get('error')}"
        return (f"Skill '{result['name']}' is now "
                f"{'enabled' if result['enabled'] else 'disabled'}.")
    if sub == "validate":
        name = _arg(rest)
        problems = registry.validate(name or None)
        if name:
            items = {name: problems.get(name, ["no such skill"])}
        else:
            items = problems
        broken = {k: v for k, v in items.items() if v}
        if not broken:
            return f"All {len(items)} skill(s) validate cleanly."
        lines = [f"{len(broken)} skill(s) have problems:"]
        for key, values in sorted(broken.items()):
            lines.append(f"- {key}: " + "; ".join(values))
        return "\n".join(lines)
    if sub == "test":
        from skills.inventory import record, verify_skill

        name = _arg(rest)
        entry = registry.get(name)
        if entry is None:
            return f"No skill named '{name}'."
        if not callable(entry.verify):
            return f"'{name}' has no live check declared."
        ok, detail, stage = verify_skill(entry)
        if ok:
            record(entry.manifest.name, stage, detail)
        return (f"{'PASS' if ok else 'FAIL'} — {entry.manifest.name}: {detail} "
                f"[{stage}]")
    if sub in ("diagnose", "diagnostics"):
        return _diagnose(registry)
    if sub in ("list-tools", "tools"):
        entry = registry.get(_arg(rest))
        if entry is None:
            return f"No skill named '{_arg(rest)}'."
        if not entry.manifest.tools:
            return f"'{entry.manifest.name}' uses no registered tools."
        from skills.builtin._delegate import tool_callable

        lines = [f"Tools for '{entry.manifest.name}':"]
        for tool in entry.manifest.tools:
            wired = "registered" if tool_callable(tool) else "MISSING"
            lines.append(f"  {tool} — {wired}")
        return "\n".join(lines)
    if sub == "history":
        return _history()
    if sub == "export":
        entry = registry.get(_arg(rest))
        if entry is None:
            return f"No skill named '{_arg(rest)}'."
        return json.dumps(entry.manifest.to_dict(), indent=2, ensure_ascii=False)
    if sub == "import":
        return _import(registry, _arg(rest))
    if sub == "remove":
        name = _arg(rest)
        if "--yes" not in rest:
            return (f"Removing '{name}' cannot be undone. Repeat as "
                    f"/skills remove {name} --yes to confirm.")
        result = registry.remove_declared(name)
        return (f"Removed imported skill '{result['name']}'."
                if result.get("ok") else f"Cannot remove: {result.get('error')}")
    if sub == "create":
        return _create(registry, _arg(rest), " ".join(rest[1:]))
    if sub == "install":
        return ("Installing a skill from outside this repository is not enabled: "
                "it would mean running code nobody inspected. Add a module under "
                "skills/builtin/ (see docs/SKILLS.md) or import a JSON manifest "
                "with /skills import.")
    if sub == "update":
        name = _arg(rest)
        entry = registry.get(name)
        if entry is None:
            return f"No skill named '{name}'."
        return (f"'{name}' is at version {entry.manifest.version}; it is built "
                "from this repository, so updating means changing its module.")
    if sub in ("run", "execute"):
        return _run(registry, rest, ctx)
    if sub == "plan":
        return _plan(registry, " ".join(rest))
    return f"Unknown /skills subcommand '{sub}'. Type /help for the list."


# ── Pieces ────────────────────────────────────────────────────────────────
def _arg(rest: list[str]) -> str:
    for item in rest:
        if not item.startswith("--"):
            return item.strip().lower()
    return ""


def _list(registry) -> str:
    from skills.inventory import status_of, evidence

    proven = evidence()
    lines = ["SKILLS"]
    for entry in registry.all():
        status, _ = status_of(entry, proven)
        flag = "" if entry.enabled else " (disabled)"
        lines.append(f"  {entry.manifest.name:<18} {status:<10}{flag}  "
                     f"{entry.manifest.purpose[:70]}")
    if not registry.all():
        lines.append("  none registered")
    return "\n".join(lines)


def _search(registry, query: str) -> str:
    if not query.strip():
        return "What should I search the skills for?"
    hits = registry.search(query)
    if not hits:
        return f"No skill matches '{query}'."
    lines = [f"Skills matching '{query}':"]
    for entry in hits:
        lines.append(f"  {entry.manifest.name} — {entry.manifest.purpose[:70]}")
    return "\n".join(lines)


def _inspect(registry, name: str) -> str:
    entry = registry.get(name)
    if entry is None:
        return f"No skill named '{name}'. Try /skills search <query>."
    m = entry.manifest
    lines = [
        f"{m.name}  v{m.version}  [{m.permission}]"
        f"{'' if entry.enabled else '  (disabled)'}",
        f"purpose: {m.purpose}",
        f"group: {m.group}",
        f"tools: {', '.join(m.tools) or '—'}",
    ]
    if m.inputs:
        lines.append("inputs:")
        for key, spec in m.input_schema().items():
            required = " (required)" if spec["required"] else ""
            lines.append(f"  {key}: {spec['type']}{required} — "
                         f"{spec['description'] or 'no description'}")
    if m.outputs:
        lines.append("outputs: " + ", ".join(m.outputs))
    if m.instructions:
        lines.append(f"use it: {m.instructions}")
    if m.requires:
        lines.append("requires: " + ", ".join(m.requires))
    lines.append(f"timeout: {int(m.timeout)}s, retries: {m.retries}")
    lines.append("implemented" if entry.implemented else
                 "declared only — no implementation")
    return "\n".join(lines)


def _diagnose(registry) -> str:
    from skills.inventory import build

    inventory = build(registry)
    counts = inventory["counts"]
    lines = ["SKILL DIAGNOSTICS",
             "counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
             f"available: {inventory['totals']['available']} of "
             f"{inventory['totals']['registered']}"]
    if inventory["duplicates"]:
        lines.append("duplicates:")
        for item in inventory["duplicates"]:
            lines.append(f"  {item['name']}: kept {item['kept']}, "
                         f"ignored {item['ignored']}")
    if inventory["load_errors"]:
        lines.append("load errors:")
        lines += [f"  {error}" for error in inventory["load_errors"]]
    broken = {n: i["reasons"] for n, i in inventory["skills"].items()
              if i["status"] == "BLOCKED"}
    if broken:
        lines.append("blocked:")
        for name, reasons in broken.items():
            lines.append(f"  {name}: {'; '.join(reasons)}")
    return "\n".join(lines)


def _history(limit: int = 12) -> str:
    from skills.registry import LOG_PATH

    try:
        rows = LOG_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return "No skill has been run yet."
    if not rows:
        return "No skill has been run yet."
    lines = ["RECENT SKILL RUNS"]
    for row in rows:
        try:
            data = json.loads(row)
        except ValueError:
            continue
        state = "ok" if data.get("ok") else "failed"
        lines.append(f"  {data.get('skill')}: {state} "
                     f"({data.get('attempts')} attempt(s)) "
                     f"{data.get('error', '')[:60]}")
    return "\n".join(lines)


def _import(registry, path: str) -> str:
    if not path:
        return "Usage: /skills import <path-to-manifest.json>"
    file = Path(path)
    if file.suffix.lower() != ".json":
        return ("Only JSON manifests can be imported — never code. A .py file "
                "would be executed on import, so it is refused.")
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except OSError as exc:
        return f"Cannot read {path}: {exc}"
    except ValueError as exc:
        return f"{path} is not valid JSON: {exc}"
    if isinstance(data, list):
        return "Import one manifest at a time (a JSON object, not a list)."
    result = registry.install_declared(data)
    return (f"Imported '{result['name']}' ({result['note']})."
            if result.get("ok") else f"Cannot import: {result.get('error')}")


def _create(registry, name: str, purpose: str) -> str:
    if not name:
        return "Usage: /skills create <name> <purpose>"
    if registry.get(name) is not None:
        return f"'{name}' already exists — refusing to create a duplicate."
    manifest = {
        "name": name,
        "purpose": purpose or f"{name} (purpose not given yet)",
        "version": "0.1.0",
        "group": "custom",
        "permission": "MODERATE",
        "instructions": "Declared only: describe what it should do, then add a "
                        "module under skills/builtin/ with run(parameters, ctx).",
        "tags": [name],
    }
    result = registry.install_declared(manifest)
    if not result.get("ok"):
        return f"Cannot create: {result.get('error')}"
    return (f"Declared '{name}'. It has no implementation yet, so it is reported "
            "as PLANNED until a module with run() exists.")


def _run(registry, rest: list[str], ctx) -> str:
    from skills.runner import SkillContext

    if not rest:
        return "Usage: /skills run <name> [key=value ...]"
    name = rest[0].strip().lower()
    parameters: dict = {}
    for token in rest[1:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        parameters[key.strip()] = _coerce_value(value.strip())
    entry = registry.get(name)
    if entry is None:
        return f"No skill named '{name}'."
    approved = "--yes" in rest or bool(getattr(ctx, "approved", False))
    runtime = ctx if ctx is not None else SkillContext()
    runtime.approved = approved
    result = registry.execute(name, parameters, runtime)
    if result.refused:
        return f"Not run: {result.error}"
    if not result.ok:
        return f"{name} failed: {result.error}"
    return result.output or f"{name} finished."


def _coerce_value(value: str):
    lowered = value.lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _plan(registry, request: str) -> str:
    from skills.orchestrator import plan

    result = plan(registry, request)
    if result.clarification:
        return result.clarification
    lines = [f"For '{request}' I would use:"]
    for candidate in result.candidates:
        approval = " (will ask first)" if candidate.needs_approval else ""
        lines.append(f"  {candidate.name}{approval} — {candidate.reason}")
    return "\n".join(lines)
