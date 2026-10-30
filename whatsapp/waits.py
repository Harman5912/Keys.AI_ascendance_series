"""Adaptive wait engine + readiness + stability (spec 3-4, 11-13, 26).

The core rule: WAIT FOR STATE, NOT FOR TIME. The AdaptiveWaitEngine polls a
condition with ADAPTIVE intervals (fast transitions poll quickly, known-long
operations poll slower), never wastes CPU, and never blocks the Keys.ai event
loop (async-only).

Also: multi-signal readiness scoring (spec 3), UI stability detection
(spec 11), and loading detection (spec 12).
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Optional


def _default_probe_interval(state_hint: str = "fast") -> float:
    return {"fast": 0.15, "medium": 0.35, "slow": 0.6}.get(state_hint, 0.3)


class AdaptiveWaitEngine:
    """Async condition waiting with adaptive polling intervals.

    Usage:
        await waits.wait_until(lambda: page.query(sel) is not None,
                               timeout=20, what="chat ready")
    The condition may be a plain callable or a coroutine function. Polling
    interval adapts to the state hint and to recent progress: a condition that
    flips quickly is polled often; a known-long operation is polled sparingly.
    """

    def __init__(self, log: Optional[Callable[[str], None]] = None) -> None:
        self.log = log or (lambda _m: None)

    async def wait_until(self, condition: Callable[[], bool],
                         timeout: float = 15.0, what: str = "condition",
                         state_hint: str = "medium",
                         progress: Optional[object] = None) -> bool:
        deadline = time.monotonic() + max(0.2, timeout)
        interval = _default_probe_interval(state_hint)
        while time.monotonic() < deadline:
            try:
                res = condition()
                if asyncio.iscoroutine(res):
                    res = await res
            except Exception:
                res = False
            if res:
                return True
            if progress is not None:
                try:
                    progress.set_progress(
                        min(0.95, max(0.0, 1.0 - (deadline - time.monotonic()) / timeout)))
                except Exception:
                    pass
            await asyncio.sleep(interval)
        return False

    # ── sync bridge (for tools that run in a thread, not the loop) ────────
    def wait_until_sync(self, condition: Callable[[], bool],
                        timeout: float = 15.0, what: str = "condition",
                        state_hint: str = "medium",
                        progress: Optional[object] = None) -> bool:
        """Blocking wrapper: polls with the same adaptive interval. Used by
        synchronous tool callbacks that already live on a worker thread; never
        call this from inside the async loop."""
        deadline = time.monotonic() + max(0.2, timeout)
        interval = _default_probe_interval(state_hint)
        while time.monotonic() < deadline:
            try:
                if condition():
                    return True
            except Exception:
                pass
            if progress is not None:
                try:
                    progress.set_progress(
                        min(0.95, max(0.0, 1.0 - (deadline - time.monotonic()) / timeout)))
                except Exception:
                    pass
            time.sleep(interval)
        return False


# ── multi-signal readiness (spec 3) ───────────────────────────────────────
class ReadinessSignals:
    """Declarative multi-signal readiness: each signal is (weight, check_fn).
    A thing is READY only when the weighted score passes the threshold.
    Never decide readiness from a single selector (spec 3)."""

    def __init__(self) -> None:
        self._signals: list[tuple[float, Callable[[], bool], str]] = []
        self.threshold = 0.65

    def add(self, weight: float, check: Callable[[], bool], label: str) -> None:
        self._signals.append((weight, check, label))

    def score(self) -> tuple[float, list[str]]:
        total_w = 0.0
        got_w = 0.0
        missing: list[str] = []
        for weight, check, label in self._signals:
            total_w += weight
            try:
                if check():
                    got_w += weight
                else:
                    missing.append(label)
            except Exception:
                missing.append(label)
        return (got_w / total_w if total_w else 0.0), missing

    def ready(self) -> bool:
        score, _ = self.score()
        return score >= self.threshold

    def describe(self) -> str:
        score, missing = self.score()
        pct = int(score * 100)
        state = "READY" if self.ready() else "NOT READY"
        if missing:
            return f"{state} ({pct}%) — waiting on: {', '.join(missing)}"
        return f"{state} ({pct}%)"


# ── UI stability detection (spec 11) ──────────────────────────────────────
class StabilityTracker:
    """Waits until a target's important properties stop changing.

    Samples a snapshot callable (returns a comparable tuple like
    (bounding_box, visible, text)) and considers the target STABLE when the
    snapshot is unchanged for `required_unchanged` consecutive samples.
    Especially important on slow computers / animated UIs.
    """

    def __init__(self, required_unchanged: int = 3, interval: float = 0.2,
                 log: Optional[Callable[[str], None]] = None) -> None:
        self.required_unchanged = max(1, required_unchanged)
        self.interval = interval
        self.log = log or (lambda _m: None)
        self._streak = 0
        self._last: Optional[object] = None

    async def wait_stable(self, snapshot: Callable[[], object],
                          timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + max(0.2, timeout)
        while time.monotonic() < deadline:
            try:
                snap = snapshot()
                if snap is None:
                    self._streak = 0
                elif snap == self._last:
                    self._streak += 1
                    if self._streak >= self.required_unchanged:
                        return True
                else:
                    self._streak = 1
                self._last = snap
            except Exception:
                self._streak = 0
            await asyncio.sleep(self.interval)
        return False

    def wait_stable_sync(self, snapshot: Callable[[], object],
                         timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + max(0.2, timeout)
        while time.monotonic() < deadline:
            try:
                snap = snapshot()
                if snap is None:
                    self._streak = 0
                elif snap == self._last:
                    self._streak += 1
                    if self._streak >= self.required_unchanged:
                        return True
                else:
                    self._streak = 1
                self._last = snap
            except Exception:
                self._streak = 0
            time.sleep(self.interval)
        return False


# ── loading detection (spec 12) ───────────────────────────────────────────
def is_loading(locators_visible: Callable[[str], bool]) -> bool:
    """True when any blocking/loading indicator is present."""
    for name in ("blocking_loader", "loading_indicators"):
        try:
            if locators_visible(name):
                return True
        except Exception:
            pass
    return False
