"""Skill execution — validation, permission gate, timeout, retries, tracing.

Nothing here knows about any particular skill. The registry hands over an entry
(manifest + callable) and this module decides whether it may run and what the
structured result is.

The permission gate is layered on purpose:

* the manifest says what the skill is worth (SAFE / MODERATE / DANGEROUS);
* ``brain.safety.SafetyLayer`` escalates by argument — a ``SAFE`` file skill
  asked to *delete* becomes DANGEROUS without the manifest changing — so the
  same action-keyword rules the rest of Keys.AI obeys apply here;
* a MODERATE or DANGEROUS skill only runs when the caller passes
  ``approve=True``, which the UI sets from the user's own answer.
"""

from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field


class SkillRefused(Exception):
    """The skill existed but policy did not let it run."""


class SkillTimeout(Exception):
    """The skill did not finish inside its declared timeout."""


@dataclass
class SkillContext:
    """What a skill is allowed to touch while it runs."""

    ui: object = None
    speak: object = None
    approved: bool = False
    cancelled: threading.Event = field(default_factory=threading.Event)
    notes: list[str] = field(default_factory=list)

    def log(self, message: str) -> None:
        self.notes.append(str(message))
        sink = getattr(self.ui, "write_log", None)
        if callable(sink):
            try:
                sink(str(message))
            except Exception:
                pass

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled.is_set()


@dataclass
class SkillResult:
    skill: str
    ok: bool
    output: str = ""
    error: str = ""
    attempts: int = 0
    seconds: float = 0.0
    refused: bool = False
    trace: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "skill": self.skill, "ok": self.ok, "output": self.output,
            "error": self.error, "attempts": self.attempts,
            "seconds": round(self.seconds, 3), "refused": self.refused,
            "trace": list(self.trace),
        }


def _coerce(value, kind: str):
    """Check one value against a declared input type. Returns (ok, value)."""
    if kind == "string":
        return isinstance(value, str), value
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool), value
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool), value
    if kind == "boolean":
        return isinstance(value, bool), value
    if kind == "array":
        return isinstance(value, (list, tuple)), list(value)
    if kind == "object":
        return isinstance(value, dict), value
    return True, value


def validate_inputs(manifest, parameters: dict) -> tuple[dict, list[str]]:
    """Normalise arguments against the manifest. Returns (args, problems)."""
    parameters = dict(parameters or {})
    problems: list[str] = []
    cleaned: dict = {}
    for key, spec in manifest.input_schema().items():
        if key not in parameters:
            if spec["required"]:
                problems.append(f"missing required input '{key}'")
            continue
        ok, value = _coerce(parameters[key], spec["type"])
        if not ok:
            problems.append(f"input '{key}' must be {spec['type']}")
            continue
        cleaned[key] = value
    for key, value in parameters.items():
        if key not in cleaned and key not in manifest.input_schema():
            cleaned[key] = value            # extra arguments are allowed
    return cleaned, problems


def check_permission(manifest, parameters: dict, approved: bool) -> tuple[bool, str]:
    """(allowed, reason). Escalates by argument, like the rest of Keys.ai."""
    try:
        from brain.safety import SafetyLayer

        layer = SafetyLayer({"permissions": {manifest.permission: [manifest.name]}})
        level = layer.permission_for(manifest.name, parameters).value
    except Exception:
        level = manifest.permission
    if level == "SAFE":
        return True, ""
    if approved:
        return True, ""
    return False, (f"'{manifest.name}' is {level} and needs confirmation. "
                   "Ask the user, then run it again with approval.")


def _dependencies_missing(manifest) -> list[str]:
    import importlib.util

    missing = []
    for name in manifest.requires:
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except (ImportError, ValueError):
            missing.append(name)
    return missing


def execute(entry, parameters: dict, ctx: SkillContext | None = None,
            *, safety_override: bool = False) -> SkillResult:
    """Run one registry entry and report exactly what happened."""
    ctx = ctx or SkillContext()
    manifest = entry.manifest
    result = SkillResult(skill=manifest.name, ok=False)

    def stop(error: str, *, refused: bool = False) -> SkillResult:
        result.error = error
        result.refused = refused
        result.trace.append({"event": "refused" if refused else "failed",
                             "error": error})
        return result

    problems = manifest.problems()
    if problems:
        return stop("; ".join(problems))

    missing = _dependencies_missing(manifest)
    if missing:
        return stop("missing dependency: " + ", ".join(missing))

    if not entry.enabled:
        return stop("this skill is disabled", refused=True)

    if entry.run is None:
        return stop("this skill is declared but has no implementation",
                    refused=True)

    args, arg_problems = validate_inputs(manifest, parameters)
    if arg_problems:
        return stop("; ".join(arg_problems), refused=True)

    if not safety_override:
        allowed, reason = check_permission(manifest, args, ctx.approved)
        if not allowed:
            return stop(reason, refused=True)

    attempts_allowed = max(0, int(manifest.retries)) + 1
    started = time.perf_counter()
    for attempt in range(1, attempts_allowed + 1):
        if ctx.is_cancelled:
            return stop("cancelled before it ran")
        result.attempts = attempt
        box: dict = {}

        def _call():
            try:
                box["value"] = entry.run(args, ctx)
            except BaseException as exc:                 # reported, not raised
                box["error"] = exc
                box["traceback"] = traceback.format_exc()

        worker = threading.Thread(target=_call, name=f"skill-{manifest.name}",
                                  daemon=True)
        worker.start()
        worker.join(timeout=float(manifest.timeout))
        if worker.is_alive():
            result.trace.append({"event": "timeout", "attempt": attempt,
                                 "timeout": manifest.timeout})
            return stop(f"'{manifest.name}' did not finish within "
                        f"{int(manifest.timeout)}s")
        if "error" in box:
            result.trace.append({"event": "exception", "attempt": attempt,
                                 "error": str(box["error"])})
            if attempt < attempts_allowed:
                time.sleep(0.2 * attempt)
                continue
            return stop(f"{type(box['error']).__name__}: {box['error']}")

        value = box.get("value")
        if isinstance(value, dict) and value.get("ok") is False:
            error = str(value.get("error") or "the skill reported a failure")
            result.trace.append({"event": "failure", "attempt": attempt,
                                 "error": error})
            if value.get("retryable") and attempt < attempts_allowed:
                time.sleep(0.2 * attempt)
                continue
            result.error = error
            return result

        result.ok = True
        result.output = _as_text(value)
        result.trace.append({"event": "ok", "attempt": attempt})
        result.seconds = time.perf_counter() - started
        return result

    return stop("no attempt was made")


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("output", "result", "text", "message"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner
        import json

        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)
