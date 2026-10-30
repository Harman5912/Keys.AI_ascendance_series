"""WhatsApp state machine (spec 2, 14-15).

The heart of the reliability subsystem: every operation is a STATE
TRANSITION, never a timed sequence. We never claim "WhatsApp is ready"
because 5 seconds passed — we claim it because the state machine reached
READY through verified transitions.

Also houses the ProgressMonitor: observable progress for long operations and
STALL DETECTION (time passing but state not changing).
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Optional


class WhatsAppState(str, Enum):
    """All states the subsystem can be in (spec 2)."""

    STARTING = "STARTING"
    BROWSER_LAUNCHING = "BROWSER_LAUNCHING"
    PAGE_LOADING = "PAGE_LOADING"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    QR_REQUIRED = "QR_REQUIRED"
    SYNCING = "SYNCING"
    READY = "READY"
    CHAT_OPENING = "CHAT_OPENING"
    CHAT_READY = "CHAT_READY"
    COMPOSER_READY = "COMPOSER_READY"
    SENDING = "SENDING"
    SEND_VERIFICATION = "SEND_VERIFICATION"
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"
    RECONNECTING = "RECONNECTING"
    UI_STALLED = "UI_STALLED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    BROWSER_CRASHED = "BROWSER_CRASHED"
    UNKNOWN = "UNKNOWN"

    # ── helpers ───────────────────────────────────────────────────────────
    @property
    def is_ready(self) -> bool:
        return self in (WhatsAppState.READY, WhatsAppState.CHAT_READY,
                        WhatsAppState.COMPOSER_READY)

    @property
    def is_failure(self) -> bool:
        return self in (WhatsAppState.BROWSER_CRASHED, WhatsAppState.UNKNOWN,
                        WhatsAppState.SESSION_EXPIRED)

    @property
    def is_transient(self) -> bool:
        """States that need a wait, not a failure report."""
        return self in (WhatsAppState.SYNCING, WhatsAppState.CHAT_OPENING,
                        WhatsAppState.PAGE_LOADING, WhatsAppState.SENDING,
                        WhatsAppState.SEND_VERIFICATION,
                        WhatsAppState.RECONNECTING, WhatsAppState.QR_REQUIRED)


class StateMachine:
    """Tracks the current state, when it changed, and enforces transitions."""

    def __init__(self, initial: WhatsAppState = WhatsAppState.STARTING) -> None:
        self._state = initial
        self._changed_at = time.monotonic()
        self._history: list[tuple[str, float]] = [(self._state.value, self._changed_at)]

    @property
    def state(self) -> WhatsAppState:
        return self._state

    @property
    def elapsed_in_state(self) -> float:
        return time.monotonic() - self._changed_at

    def transition(self, new: WhatsAppState) -> WhatsAppState:
        """Move to a new state; records history. Same-state calls are no-ops
        so repeated observations don't reset the stall clock."""
        if new != self._state:
            self._state = new
            self._changed_at = time.monotonic()
            self._history.append((new.value, self._changed_at))
            if len(self._history) > 200:
                self._history = self._history[-100:]
        return self._state

    def stalled(self, threshold: float) -> bool:
        """Time is passing but the state has not changed."""
        return self.elapsed_in_state >= threshold

    def describe(self) -> str:
        return f"{self._state.value} (for {self.elapsed_in_state:.1f}s)"

    def history(self, limit: int = 8) -> list[str]:
        return [f"{s}" for s, _ in self._history[-limit:]]


class ProgressMonitor:
    """Spec 15: every long operation shows progress and can detect stalls.

    Tracks operation lifecycle (operation_started / last_progress / state /
    last_state_change). If now - last_progress > stall_threshold, the caller
    should invoke recovery instead of waiting forever.
    """

    def __init__(self, operation: str, stall_threshold: float = 20.0) -> None:
        self.operation = operation
        self.started_at = time.monotonic()
        self.last_progress_at = self.started_at
        self.progress: float = 0.0          # 0..1
        self.current_state: str = operation.upper()
        self.last_state_change = self.started_at
        self.stall_threshold = stall_threshold

    def set_progress(self, fraction: float, state: Optional[str] = None) -> None:
        self.progress = max(0.0, min(1.0, float(fraction)))
        self.last_progress_at = time.monotonic()
        if state:
            self.current_state = state
            self.last_state_change = self.last_progress_at

    def note(self, state: str) -> None:
        """A state change is itself progress (state machine advanced)."""
        self.set_progress(self.progress, state)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def stalled(self) -> bool:
        return (time.monotonic() - self.last_progress_at) >= self.stall_threshold

    def bar(self, width: int = 12) -> str:
        filled = int(round(self.progress * width))
        return "[" + "█" * filled + "░" * (width - filled) + "]"

    def describe(self) -> str:
        return (f"{self.operation}: {self.bar()} {int(self.progress*100)}% "
                f"state={self.current_state} "
                f"({self.elapsed:.1f}s)")


def now() -> float:
    return time.monotonic()
