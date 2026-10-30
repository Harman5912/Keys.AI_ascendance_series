"""Adaptive environment model (spec 5-6, 30-33).

Combines machine-speed profiling, network-health estimation and latency
learning into ONE AdaptiveTiming model that computes operation budgets:

    timeout = baseline + env_factor + recent_latency_factor + safety_margin

with hard caps per operation. Different operations have different bottlenecks
(launch ≠ chat-open ≠ send), so we never multiply one global timeout by a
single factor (spec 30).

All measurements are lightweight rolling samples — no expensive hardware
polling, no ML model (spec 31).
"""

from __future__ import annotations

import time
from collections import deque
from typing import Optional


# ── machine speed (spec 5) ────────────────────────────────────────────────
class MachineProfile:
    """Rolling, self-correcting estimate of this machine's UI speed.

    Uses observed UI-transition latency (not raw CPU%, which is noisy and
    machine-specific): recent chat-open / launch durations feed a rolling
    average. A machine is never permanently classified as slow — the profile
    re-learns from recent samples (spec 5).
    """

    def __init__(self, window: int = 10) -> None:
        self._samples: deque[float] = deque(maxlen=window)
        self._baseline_ms = 500.0          # assumed NORMAL until evidence

    def observe(self, transition_ms: float) -> None:
        if transition_ms > 0:
            self._samples.append(float(transition_ms))
            self._baseline_ms = sum(self._samples) / len(self._samples)

    @property
    def label(self) -> str:
        if not self._samples:
            return "NORMAL"
        if self._baseline_ms < 300:
            return "FAST"
        if self._baseline_ms > 1500:
            return "SLOW"
        return "NORMAL"

    @property
    def baseline_ms(self) -> float:
        return self._baseline_ms

    def ui_factor(self) -> float:
        """Multiplier for UI-transition waits (longer on slow machines)."""
        if not self._samples:
            return 1.0
        return max(0.5, min(2.5, self._baseline_ms / 500.0))


# ── network health (spec 6) ───────────────────────────────────────────────
class NetworkHealth:
    """Lightweight network estimate from observed latencies + failures."""

    LEVELS = ("EXCELLENT", "GOOD", "DEGRADED", "POOR", "OFFLINE")

    def __init__(self, window: int = 12) -> None:
        self._latencies: deque[float] = deque(maxlen=window)
        self._failures = 0
        self._recent_failures = 0
        self._last = time.monotonic()
        self._offline = False

    def observe_latency(self, ms: float) -> None:
        if ms > 0:
            self._latencies.append(float(ms))

    def observe_failure(self) -> None:
        self._failures += 1
        self._recent_failures += 1

    def observe_success(self) -> None:
        self._recent_failures = 0
        self._offline = False

    def mark_offline(self) -> None:
        self._offline = True

    @property
    def label(self) -> str:
        if self._offline:
            return "OFFLINE"
        if self._recent_failures >= 3:
            return "POOR"
        if not self._latencies:
            return "GOOD"
        avg = sum(self._latencies) / len(self._latencies)
        if avg < 150:
            return "EXCELLENT"
        if avg < 500:
            return "GOOD"
        if avg < 1500:
            return "DEGRADED"
        return "POOR"

    def factor(self) -> float:
        """Network multiplier for network-bound waits."""
        return {"EXCELLENT": 0.8, "GOOD": 1.0, "DEGRADED": 1.8,
                "POOR": 3.0, "OFFLINE": 5.0}[self.label]

    def healthy(self) -> bool:
        return not self._offline and self._recent_failures < 3


# ── latency learning (spec 31) ────────────────────────────────────────────
class LatencyLearner:
    """Rolling EMA per operation -> expected duration. No ML, just EMA."""

    def __init__(self, alpha: float = 0.4) -> None:
        self._ema: dict[str, float] = {}
        self._count: dict[str, int] = {}
        self._alpha = alpha

    def record(self, operation: str, seconds: float) -> None:
        op = operation.lower()
        if seconds <= 0:
            return
        prev = self._ema.get(op)
        if prev is None:
            self._ema[op] = seconds
        else:
            self._ema[op] = self._alpha * seconds + (1 - self._alpha) * prev
        self._count[op] = self._count.get(op, 0) + 1

    def expected(self, operation: str, default: float = 3.0) -> float:
        return self._ema.get(operation.lower(), default)

    def samples(self, operation: str) -> int:
        return self._count.get(operation.lower(), 0)


# ── operation budgets (spec 7, 32-33) ────────────────────────────────────
class OperationBudget:
    """Per-operation timeout + retry + recovery caps (fail safely)."""

    def __init__(self, baseline: float, ui_factor: float = 1.0,
                 network_factor: float = 1.0, latency_expected: Optional[float] = None,
                 safety: float = 2.0, cap: float = 120.0,
                 max_retries: int = 3, max_recovery_depth: int = 4) -> None:
        self.baseline = baseline
        self.ui_factor = ui_factor
        self.network_factor = network_factor
        self.latency_expected = latency_expected
        self.safety = safety
        self.cap = cap
        self.max_retries = max_retries
        self.max_recovery_depth = max_recovery_depth

    @property
    def timeout(self) -> float:
        """timeout = baseline + env factor + recent latency factor + margin."""
        t = (self.baseline
             + (self.ui_factor - 1.0) * 2.0 * self.baseline
             + (self.network_factor - 1.0) * self.baseline
             + (self.latency_expected or 0.0)
             + self.safety)
        return min(self.cap, max(0.5, t))

    def next_retry_delay(self, attempt: int) -> float:
        """Escalating short backoff: 0.4s, 1.0s, 2.5s — never huge."""
        return min(4.0, 0.4 * (2.5 ** max(0, attempt - 1)))

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (f"OperationBudget(timeout={self.timeout:.1f}s, "
                f"retries={self.max_retries}, depth={self.max_recovery_depth})")


# ── combined adaptive model (spec 30) ────────────────────────────────────
class AdaptiveTiming:
    """One place that turns machine + network + learning into budgets."""

    def __init__(self, machine: Optional[MachineProfile] = None,
                 network: Optional[NetworkHealth] = None,
                 learner: Optional[LatencyLearner] = None) -> None:
        self.machine = machine or MachineProfile()
        self.network = network or NetworkHealth()
        self.learner = learner or LatencyLearner()

    def budget(self, operation: str, baseline: float,
               safety: float = 2.0, cap: float = 120.0,
               max_retries: int = 3, max_recovery_depth: int = 4) -> OperationBudget:
        """Build a budget for one operation using the adaptive model."""
        return OperationBudget(
            baseline=baseline,
            ui_factor=self.machine.ui_factor(),
            network_factor=self.network.factor(),
            latency_expected=self.learner.expected(operation, default=0.0),
            safety=safety, cap=cap,
            max_retries=max_retries, max_recovery_depth=max_recovery_depth,
        )

    def record(self, operation: str, seconds: float) -> None:
        """Feed real measurements back into the learner."""
        self.learner.record(operation, seconds)
        self.machine.observe(seconds * 1000.0)

    def summary(self) -> str:
        return (f"MACHINE: {self.machine.label} | NETWORK: {self.network.label}")


def make_timing() -> AdaptiveTiming:
    return AdaptiveTiming()
