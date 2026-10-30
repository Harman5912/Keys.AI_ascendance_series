"""Skill manifests — the schema every skill declares, and its validation.

A manifest is data: purpose, inputs, outputs, the tools that back it, the
permission it needs and how it is verified. It is deliberately strict — a
manifest that does not validate is reported as BLOCKED instead of being loaded
on trust.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,48}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
PERMISSIONS = ("SAFE", "MODERATE", "DANGEROUS")
INPUT_TYPES = ("string", "integer", "number", "boolean", "array", "object")

#: Fields a skill may declare. Anything else in the dict is ignored, so a
#: manifest can carry extra notes without breaking the loader.
KNOWN_FIELDS = frozenset({
    "name", "purpose", "version", "group", "capabilities", "tools",
    "permission", "instructions", "triggers", "inputs", "outputs", "requires",
    "timeout", "retries", "tags", "parallel_safe",
})


@dataclass(frozen=True)
class SkillManifest:
    name: str
    purpose: str
    version: str = "1.0.0"
    group: str = "misc"
    capabilities: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    permission: str = "SAFE"
    instructions: str = ""
    triggers: tuple[str, ...] = ()
    inputs: dict = field(default_factory=dict)
    outputs: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    timeout: float = 90.0
    retries: int = 0
    tags: tuple[str, ...] = ()
    parallel_safe: bool = False

    # ── Construction ──────────────────────────────────────────────────────
    @classmethod
    def from_dict(cls, data: dict, *, source: str = "") -> "SkillManifest":
        data = dict(data or {})
        unknown = set(data) - KNOWN_FIELDS
        for key in unknown:
            data.pop(key, None)
        for key in ("capabilities", "tools", "triggers", "outputs",
                    "requires", "tags"):
            if key in data:
                data[key] = tuple(str(v) for v in (data[key] or ()))
        return cls(**{k: v for k, v in data.items() if k in KNOWN_FIELDS})

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "version": self.version,
            "group": self.group,
            "capabilities": list(self.capabilities),
            "tools": list(self.tools),
            "permission": self.permission,
            "instructions": self.instructions,
            "triggers": list(self.triggers),
            "inputs": dict(self.inputs),
            "outputs": list(self.outputs),
            "requires": list(self.requires),
            "timeout": self.timeout,
            "retries": self.retries,
            "tags": list(self.tags),
            "parallel_safe": self.parallel_safe,
        }

    def with_changes(self, **changes) -> "SkillManifest":
        return replace(self, **changes)

    # ── Validation ────────────────────────────────────────────────────────
    def problems(self) -> list[str]:
        """Every reason this manifest cannot be trusted, as plain sentences."""
        out: list[str] = []
        if not NAME_RE.match(self.name or ""):
            out.append(f"name {self.name!r} must be lower-case words separated "
                       "by dashes (a-z, 0-9, 2-49 chars)")
        if not str(self.purpose or "").strip():
            out.append("purpose is empty — a skill must say what it is for")
        if not VERSION_RE.match(self.version or ""):
            out.append(f"version {self.version!r} is not MAJOR.MINOR.PATCH")
        if self.permission not in PERMISSIONS:
            out.append(f"permission {self.permission!r} is not one of "
                       f"{', '.join(PERMISSIONS)}")
        if float(self.timeout) <= 0:
            out.append("timeout must be greater than zero")
        if int(self.retries) < 0:
            out.append("retries cannot be negative")
        for key, spec in (self.inputs or {}).items():
            if not isinstance(spec, dict):
                out.append(f"input {key!r} must be a dict describing the value")
                continue
            kind = str(spec.get("type") or "string")
            if kind not in INPUT_TYPES:
                out.append(f"input {key!r} has unknown type {kind!r}")
        return out

    def input_schema(self) -> dict:
        """The declared inputs, normalised to {type, required, description}."""
        out: dict = {}
        for key, spec in (self.inputs or {}).items():
            spec = dict(spec or {})
            out[key] = {
                "type": str(spec.get("type") or "string"),
                "required": bool(spec.get("required", False)),
                "description": str(spec.get("description") or ""),
            }
        return out
