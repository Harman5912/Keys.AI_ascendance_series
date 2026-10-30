"""Observability & performance telemetry (spec §44–45).

Every computer-use action is traced through its phases — target discovery,
planning, action, verification — and the trace can be rendered as the spec's
single-line debug record:

    TARGET: Send button   METHOD: UIA   VISION: No
    ACTION: Invoke        LATENCY: 18 ms   VERIFICATION: bubble detected

Debug mode is opt-in (config flag) and OFF in production, so the overhead is
zero unless a developer enables it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional


class ActionTrace:
    """Per-action telemetry record."""

    def __init__(self, target: str = "") -> None:
        self.target = target
        self.method: str = ""
        self.action: str = ""
        self.vision: bool = False
        self.verification: str = ""
        self.phases: dict[str, float] = {}
        self._t0 = time.perf_counter()

    def mark(self, phase: str) -> None:
        """Record a phase completion timestamp (phase -> elapsed ms)."""
        self.phases[phase] = round((time.perf_counter() - self._t0) * 1000, 1)

    def total_ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000, 1)

    def debug_line(self) -> str:
        """The spec §44 single-line record."""
        lat = self.phases.get("action", self.total_ms())
        return (
            f"TARGET: {self.target or '—'} | METHOD: {self.method or '—'}"
            f" | VISION: {'Yes' if self.vision else 'No'}"
            f" | ACTION: {self.action or '—'}"
            f" | LATENCY: {lat:.0f} ms"
            f" | VERIFICATION: {self.verification or '—'}"
        )

    def as_dict(self) -> dict:
        return {
            "target": self.target,
            "method": self.method,
            "action": self.action,
            "vision": self.vision,
            "verification": self.verification,
            "phases_ms": self.phases,
            "total_ms": self.total_ms(),
        }


class Telemetry:
    """Shared telemetry hub. `enabled` gates everything so production costs
    nothing. Recent traces are kept in a small ring buffer for debugging."""

    def __init__(self, enabled: bool = False, ring_size: int = 64) -> None:
        self.enabled = enabled
        self.ring: list[ActionTrace] = []
        self._ring_size = max(1, ring_size)

    def begin(self, target: str = "") -> ActionTrace:
        tr = ActionTrace(target)
        if self.enabled:
            self.ring.append(tr)
            if len(self.ring) > self._ring_size:
                self.ring.pop(0)
        return tr

    def dump(self, limit: int = 20) -> str:
        if not self.enabled:
            return "(telemetry disabled)"
        lines = [t.debug_line() for t in self.ring[-limit:]]
        return "\n".join(lines) if lines else "(no actions traced yet)"

    @staticmethod
    def config_from_file(path: Optional[Path] = None) -> bool:
        """Read the debug flag from config/api_keys.json ('debug_automation': true)."""
        try:
            p = path or Path(__file__).resolve().parent.parent / "config" / "api_keys.json"
            return bool(json.loads(p.read_text(encoding="utf-8")).get("debug_automation", False))
        except Exception:
            return False


# Shared singleton — lazily configured, cheap when off.
_telemetry: Optional[Telemetry] = None


def get_telemetry() -> Telemetry:
    global _telemetry
    if _telemetry is None:
        _telemetry = Telemetry(enabled=Telemetry.config_from_file())
    return _telemetry
