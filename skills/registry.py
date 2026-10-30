"""SKILL REGISTRY — discovery, validation, state and execution for skills.

A skill is one Python module under ``skills/builtin/`` that declares::

    SKILL = {"name": "globe", "purpose": "...", "tools": ["globe"], ...}
    def run(parameters, ctx) -> str | dict      # optional but usual

plus, optionally, ``def verify() -> tuple[bool, str]`` — a cheap check that the
capability really works in this environment (used by ``python -m skills.inventory
--check``, never by ordinary execution).

The registry is the only place skills are discovered, enabled, disabled and
executed. It does not re-implement any capability: each skill's ``run`` delegates
to the tool that already exists, so a skill is a contract plus routing, not a
second implementation.

State lives in ``config/skills_state.json`` (enable/disable). Imported
manifests live in ``config/skills_declared.json`` and are *declarations only* —
they describe a capability with no code, and are reported as such.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import pkgutil
import threading
from dataclasses import dataclass, field
from pathlib import Path

from skills.manifest import SkillManifest
from skills.runner import SkillContext, SkillResult, execute

ROOT = Path(__file__).resolve().parents[1]
BUILTIN_PACKAGE = "skills.builtin"
STATE_PATH = ROOT / "config" / "skills_state.json"
DECLARED_PATH = ROOT / "config" / "skills_declared.json"
LOG_PATH = ROOT / "config" / "skills_log.jsonl"

_lock = threading.RLock()
_registry: "SkillRegistry | None" = None


@dataclass
class SkillEntry:
    manifest: SkillManifest
    run: object = None
    verify: object = None
    module: str = ""
    path: str = ""
    declared: bool = False
    enabled: bool = True
    source: str = "builtin"

    @property
    def implemented(self) -> bool:
        return callable(self.run)

    def as_dict(self) -> dict:
        return {
            "name": self.manifest.name,
            "version": self.manifest.version,
            "group": self.manifest.group,
            "purpose": self.manifest.purpose,
            "permission": self.manifest.permission,
            "tools": list(self.manifest.tools),
            "declared_inputs": self.manifest.input_schema(),
            "outputs": list(self.manifest.outputs),
            "requires": list(self.manifest.requires),
            "implemented": self.implemented,
            "enabled": self.enabled,
            "source": self.source,
            "module": self.module,
        }


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8")


class SkillRegistry:
    """Every skill the application knows about, and what state it is in."""

    def __init__(self, *, load: bool = True):
        self._entries: dict[str, SkillEntry] = {}
        self._disabled: set[str] = set()
        self.duplicates: list[dict] = []
        self.load_errors: list[str] = []
        if load:
            self.reload()

    # ── Discovery ─────────────────────────────────────────────────────────
    def reload(self) -> "SkillRegistry":
        with _lock:
            self._entries = {}
            self.duplicates = []
            self.load_errors = []
            self._disabled = set(
                (_read_json(STATE_PATH, {}) or {}).get("disabled") or [])
            self._load_builtin()
            self._load_declared()
            for entry in self._entries.values():
                entry.enabled = entry.manifest.name not in self._disabled
        return self

    def _register(self, entry: SkillEntry) -> None:
        existing = self._entries.get(entry.manifest.name)
        if existing is not None:
            self.duplicates.append({
                "name": entry.manifest.name,
                "kept": existing.module or existing.source,
                "ignored": entry.module or entry.source,
            })
            return
        self._entries[entry.manifest.name] = entry

    def _load_builtin(self) -> None:
        import skills.builtin as package

        for info in pkgutil.iter_modules(package.__path__):
            if info.name.startswith("_"):
                continue
            module_name = f"{BUILTIN_PACKAGE}.{info.name}"
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:                 # a broken skill must not
                self.load_errors.append(f"{module_name}: {exc}")   # stop the rest
                continue
            declared = getattr(module, "SKILL", None)
            if not isinstance(declared, dict):
                self.load_errors.append(f"{module_name}: no SKILL dict")
                continue
            manifest = SkillManifest.from_dict(declared)
            self._register(SkillEntry(
                manifest=manifest,
                run=getattr(module, "run", None),
                verify=getattr(module, "verify", None),
                module=module_name,
                path=str(getattr(module, "__file__", "")),
                source="builtin",
            ))

    def _load_declared(self) -> None:
        """Manifests installed from a JSON file — descriptions, not code."""
        for data in _read_json(DECLARED_PATH, []) or []:
            try:
                manifest = SkillManifest.from_dict(data)
            except Exception as exc:
                self.load_errors.append(f"declared skill: {exc}")
                continue
            self._register(SkillEntry(
                manifest=manifest,
                run=None,
                declared=True,
                source="declared",
            ))

    # ── Reading ───────────────────────────────────────────────────────────
    def all(self) -> list[SkillEntry]:
        return sorted(self._entries.values(), key=lambda e: e.manifest.name)

    def get(self, name: str) -> SkillEntry | None:
        return self._entries.get(str(name or "").strip().lower())

    def search(self, query: str) -> list[SkillEntry]:
        """Skills whose name, purpose, tags, triggers or capabilities match."""
        words = [w for w in str(query or "").lower().split() if w]
        if not words:
            return []
        scored: list[tuple[int, SkillEntry]] = []
        for entry in self._entries.values():
            m = entry.manifest
            haystack = " ".join([
                m.name, m.purpose, m.group, " ".join(m.tags),
                " ".join(m.capabilities), " ".join(m.triggers),
                " ".join(m.tools),
            ]).lower()
            score = sum(1 for w in words if w in haystack)
            if score:
                scored.append((score, entry))
        scored.sort(key=lambda pair: (-pair[0], pair[1].manifest.name))
        return [entry for _, entry in scored]

    def enabled(self) -> list[SkillEntry]:
        return [e for e in self.all() if e.enabled]

    def tools_for(self, tool: str) -> list[str]:
        return [e.manifest.name for e in self.all()
                if tool in e.manifest.tools]

    def validate(self, name: str | None = None) -> dict:
        """name -> problems. A skill with no implementation is a problem."""
        out: dict = {}
        targets = [self.get(name)] if name else self.all()
        for entry in targets:
            if entry is None:
                continue
            problems = list(entry.manifest.problems())
            if not entry.implemented:
                problems.append("declared only — there is no run() for it")
            out[entry.manifest.name] = problems
        return out

    # ── State ─────────────────────────────────────────────────────────────
    def set_enabled(self, name: str, enabled: bool) -> dict:
        entry = self.get(name)
        if entry is None:
            return {"ok": False, "error": f"No skill named '{name}'."}
        with _lock:
            if enabled:
                self._disabled.discard(entry.manifest.name)
            else:
                self._disabled.add(entry.manifest.name)
            entry.enabled = enabled
            _write_json(STATE_PATH, {"disabled": sorted(self._disabled)})
        return {"ok": True, "name": entry.manifest.name, "enabled": enabled}

    def install_declared(self, data: dict) -> dict:
        """Add a manifest from a file. Code import is never part of this."""
        manifest = SkillManifest.from_dict(data)
        problems = manifest.problems()
        if problems:
            return {"ok": False, "error": "; ".join(problems)}
        existing = self.get(manifest.name)
        if existing is not None:
            self.duplicates.append({
                "name": manifest.name,
                "kept": existing.module or existing.source,
                "ignored": "declared import",
            })
            return {"ok": False, "error": f"'{manifest.name}' already exists "
                                          "(duplicate detection refused it)"}
        declared = _read_json(DECLARED_PATH, []) or []
        declared.append(manifest.to_dict())
        _write_json(DECLARED_PATH, declared)
        self.reload()
        return {"ok": True, "name": manifest.name,
                "note": "declared only — it has no implementation yet"}

    def remove_declared(self, name: str) -> dict:
        entry = self.get(name)
        if entry is None or not entry.declared:
            return {"ok": False,
                    "error": "Only imported (declared) skills can be removed; "
                             "built-in skills are code in the repository."}
        declared = [d for d in (_read_json(DECLARED_PATH, []) or [])
                    if str(d.get("name")) != entry.manifest.name]
        _write_json(DECLARED_PATH, declared)
        self.reload()
        return {"ok": True, "name": entry.manifest.name}

    # ── Execution ─────────────────────────────────────────────────────────
    def execute(self, name: str, parameters: dict | None = None,
                ctx: SkillContext | None = None) -> SkillResult:
        ctx = ctx or SkillContext()
        entry = self.get(name)
        if entry is None:
            return SkillResult(skill=str(name), ok=False,
                               error=f"No skill named '{name}'.",
                               refused=True)
        result = execute(entry, dict(parameters or {}), ctx)
        self._log(result)
        return result

    def _log(self, result: SkillResult) -> None:
        record = {"at": __import__("time").time(), **result.as_dict()}
        record.pop("output", None)          # outputs can be long; keep the log light
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ── Presentation ──────────────────────────────────────────────────────
    def describe(self) -> str:
        """Prompt block: same shape the model already reads today."""
        lines = ["AVAILABLE SKILLS (route requests into the right skill):"]
        entries = self.enabled() or self.all()
        if not entries:
            return ""
        for entry in entries:
            m = entry.manifest
            note = "" if entry.implemented else " [declared only]"
            lines.append(f"- {m.name.title()}: {m.purpose}{note}")
            if m.capabilities:
                lines.append(f"    capabilities: {', '.join(m.capabilities[:5])}")
        return "\n".join(lines)

    def inventory(self, *, write: bool = False) -> dict:
        from skills.inventory import build

        return build(self, write=write)


def get_registry() -> SkillRegistry:
    """The process-wide registry."""
    global _registry
    with _lock:
        if _registry is None:
            _registry = SkillRegistry()
        return _registry


def reset_registry() -> None:
    """Testing hook: forget the cached registry."""
    global _registry
    with _lock:
        _registry = None


# ── Backwards-compatible prompt block ─────────────────────────────────────
def skills_block() -> str:
    """Prompt block injected by personality/__init__.py (never raises)."""
    try:
        return get_registry().describe()
    except Exception:
        return ""


def describe_skills() -> str:
    return skills_block()
