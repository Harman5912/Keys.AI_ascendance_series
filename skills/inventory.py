"""Skill inventory — what exists, what works, and what is only planned.

Two outputs, from one source of truth:

* ``config/skills_inventory.json`` — machine-readable, for tooling.
* ``docs/SKILL_CATALOG.md`` — readable, with the status of every capability.

Statuses are evidence-based, never optimistic:

    PLANNED     named in the target catalog, no implementation
    BLOCKED     implementation exists but cannot be trusted (manifest invalid,
                dependency missing, module failed to import)
    REGISTERED  implemented and valid, but never executed by a test
    TESTED      a test executed it and recorded the evidence here
    VERIFIED    a live check ran in this environment and recorded the evidence

Evidence is written by the thing that ran: tests call :func:`record` after they
have executed the skill, and ``python -m skills.inventory --check`` runs each
skill's own ``verify()``. Nothing infers "verified" from a file existing.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "config" / "skills_evidence.json"
INVENTORY_PATH = ROOT / "config" / "skills_inventory.json"
REPORT_PATH = ROOT / "docs" / "SKILL_CATALOG.md"

STAGES = ("TESTED", "VERIFIED")
STATUS_ORDER = ("VERIFIED", "TESTED", "REGISTERED", "BLOCKED", "PLANNED")


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def evidence() -> dict:
    return _read(EVIDENCE_PATH, {}) or {}


def record(name: str, stage: str, note: str = "") -> dict:
    """Record that *something actually ran*. Returns the evidence entry."""
    stage = str(stage).upper()
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {', '.join(STAGES)}")
    data = evidence()
    entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": str(note)}
    data.setdefault(str(name), {})[stage] = entry
    _write(EVIDENCE_PATH, data)
    return entry


def status_of(entry, evidence_map: dict) -> tuple[str, list[str]]:
    """(status, reasons). Reasons explain BLOCKED or incompleteness."""
    from skills.runner import _dependencies_missing

    problems = list(entry.manifest.problems())
    missing = _dependencies_missing(entry.manifest)
    if missing:
        problems.append("missing dependency: " + ", ".join(missing))
    if problems:
        return "BLOCKED", problems

    if not entry.implemented:
        return "PLANNED", ["declared only — no run() implementation"]

    proven = evidence_map.get(entry.manifest.name) or {}
    if "VERIFIED" in proven:
        return "VERIFIED", [f"verified {proven['VERIFIED']['at']}"]
    if "TESTED" in proven:
        return "TESTED", [f"tested {proven['TESTED']['at']}"]
    return "REGISTERED", ["implemented, no recorded test run yet"]


def build(registry=None, *, write: bool = False) -> dict:
    """The whole inventory as a dict. Writes both files when asked."""
    from skills.catalog import TARGET_CATALOG, all_names
    from skills.registry import get_registry

    registry = registry or get_registry()
    proven = evidence()
    skills: dict = {}
    available: list[str] = []
    covered: set[str] = set()

    for entry in registry.all():
        status, reasons = status_of(entry, proven)
        name = entry.manifest.name
        skills[name] = {
            "status": status,
            "enabled": bool(entry.enabled),
            "available": bool(entry.enabled and status not in ("BLOCKED",
                                                               "PLANNED")),
            "group": entry.manifest.group,
            "version": entry.manifest.version,
            "purpose": entry.manifest.purpose,
            "permission": entry.manifest.permission,
            "tools": list(entry.manifest.tools),
            "inputs": entry.manifest.input_schema(),
            "implemented": entry.implemented,
            "module": entry.module,
            "source": entry.source,
            "reasons": reasons,
            "evidence": proven.get(name, {}),
        }
        if skills[name]["available"]:
            available.append(name)
        covered.add(name)
        covered.update(entry.manifest.tags)
        covered.update(entry.manifest.tools)

    planned = []
    for group, names in TARGET_CATALOG.items():
        for name in names:
            if name in covered:
                continue
            planned.append({"name": name, "group": group,
                            "status": "PLANNED",
                            "reason": "no skill claims this capability yet"})

    counts: dict = {}
    for item in list(skills.values()) + planned:
        counts[item["status"]] = counts.get(item["status"], 0) + 1

    inventory = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "counts": counts,
        "totals": {
            "registered": len(skills),
            "available": len(available),
            "disabled": sum(1 for s in skills.values() if not s["enabled"]),
            "planned": counts.get("PLANNED", 0),
            "target_catalog": len(all_names()),
        },
        "duplicates": list(getattr(registry, "duplicates", [])),
        "load_errors": list(getattr(registry, "load_errors", [])),
        "skills": skills,
        "planned": planned,
    }
    if write:
        _write(INVENTORY_PATH, inventory)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(render_markdown(inventory), encoding="utf-8")
    return inventory


def render_markdown(inventory: dict) -> str:
    counts = inventory.get("counts") or {}
    totals = inventory.get("totals") or {}
    lines = [
        "# Skill catalog",
        "",
        f"Generated {inventory.get('generated_at')} by "
        "`python -m skills.inventory --write`.",
        "",
        "Statuses come from evidence, not from a file existing: **REGISTERED** "
        "means implemented and valid, **TESTED** means a test executed it, "
        "**VERIFIED** means a live check ran here.",
        "",
        "| Status | Count |",
        "|---|---|",
    ]
    for status in STATUS_ORDER:
        lines.append(f"| {status} | {counts.get(status, 0)} |")
    lines += [
        "",
        f"{totals.get('available', 0)} of {totals.get('registered', 0)} "
        f"registered skills are enabled and usable; "
        f"{counts.get('PLANNED', 0)} capabilities from the target catalog are "
        "still unclaimed.",
        "",
        "## Implemented skills",
        "",
        "| Skill | Status | Permission | Enabled | Tools | Purpose |",
        "|---|---|---|---|---|---|",
    ]
    skills = inventory.get("skills") or {}
    for name in sorted(skills, key=lambda n: (STATUS_ORDER.index(
            skills[n]["status"]) if skills[n]["status"] in STATUS_ORDER else 99, n)):
        item = skills[name]
        tools = ", ".join(item["tools"]) or "—"
        lines.append(
            f"| `{name}` | {item['status']} | {item['permission']} | "
            f"{'yes' if item['enabled'] else 'no'} | {tools} | "
            f"{item['purpose']} |")

    blocked = [n for n, i in skills.items() if i["status"] == "BLOCKED"]
    if blocked:
        lines += ["", "## Blocked", ""]
        for name in blocked:
            lines.append(f"- `{name}` — {'; '.join(skills[name]['reasons'])}")

    lines += ["", "## Still planned", "",
              "Named in the target catalog with no implementation yet. These "
              "are gaps, not features.", ""]
    by_group: dict = {}
    for item in inventory.get("planned") or []:
        by_group.setdefault(item["group"], []).append(item["name"])
    for group in sorted(by_group):
        lines.append(f"- **{group}** — {', '.join(sorted(by_group[group]))}")

    duplicates = inventory.get("duplicates") or []
    errors = inventory.get("load_errors") or []
    if duplicates or errors:
        lines += ["", "## Load problems", ""]
        for item in duplicates:
            lines.append(f"- duplicate `{item['name']}`: kept "
                         f"{item['kept']}, ignored {item['ignored']}")
        for error in errors:
            lines.append(f"- {error}")
    return "\n".join(lines) + "\n"


def verify_skill(entry) -> tuple[bool, str, str]:
    """Run a skill's own check. Returns (ok, detail, stage).

    A check that only proves wiring records TESTED; a check that exercises the
    real work records VERIFIED. ``verify()`` may return ``(ok, detail)`` —
    wiring — or ``(ok, detail, "functional")``.
    """
    verifier = getattr(entry, "verify", None)
    if not callable(verifier):
        return False, "no verify() declared, so nothing was checked", "TESTED"
    try:
        value = verifier()
    except Exception as exc:
        return False, f"verify() raised {type(exc).__name__}: {exc}", "TESTED"
    if not isinstance(value, tuple) or len(value) < 2:
        return False, f"verify() returned {value!r}", "TESTED"
    ok, detail = bool(value[0]), str(value[1])
    level = str(value[2]) if len(value) > 2 else "wiring"
    if ok and level == "functional":
        return True, detail, "VERIFIED"
    return ok, detail, "TESTED"


def clear_stage(name: str, stage: str) -> None:
    """Drop one stage of evidence — used when a weaker check supersedes it."""
    data = evidence()
    entry = data.get(str(name)) or {}
    if entry.pop(str(stage).upper(), None) is not None:
        _write(EVIDENCE_PATH, data)


def check_all(registry=None) -> list[tuple[str, bool, str]]:
    """Run each skill's own check and record the honest stage.

    A check that only proves wiring clears any older VERIFIED claim: evidence
    must describe the check that actually ran just now, not a better one that
    ran once.
    """
    from skills.registry import get_registry

    registry = registry or get_registry()
    results: list[tuple[str, bool, str]] = []
    for entry in registry.all():
        ok, detail, stage = verify_skill(entry)
        if ok:
            if stage == "TESTED":
                clear_stage(entry.manifest.name, "VERIFIED")
            record(entry.manifest.name, stage, detail)
        results.append((entry.manifest.name, ok, f"{detail} [{stage}]"))
    return results


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from skills.registry import get_registry

    registry = get_registry()
    if "--check" in argv:
        results = check_all(registry)
        for name, ok, detail in results:
            print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        print()
    inventory = build(registry, write=("--write" in argv or "--check" not in argv))
    if "--json" in argv:
        print(json.dumps(inventory, indent=2, ensure_ascii=False))
    else:
        counts = inventory["counts"]
        print("skills: " + ", ".join(f"{k}={counts[k]}"
                                     for k in STATUS_ORDER if k in counts))
        print(f"inventory written to {INVENTORY_PATH.relative_to(ROOT)} and "
              f"{REPORT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
