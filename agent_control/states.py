"""Agent Control task state machine.

    IDLE → UNDERSTANDING → INSPECTING → PLANNING → CONTROL_ACTIVE →
    EXECUTING → VERIFYING → (CONTINUE | RECOVER→INSPECTING) → COMPLETED →
    CONTROL_RELEASED → IDLE

Plus always-available:  PAUSED · USER_TAKEOVER · FAILED · STOPPED

Clean transitions only — invalid moves are refused (a UI/stop can force any
transition via force=True, which is what makes ESC/STOP take priority).
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

IDLE = "IDLE"
UNDERSTANDING = "UNDERSTANDING"
INSPECTING = "INSPECTING"
PLANNING = "PLANNING"
CONTROL_ACTIVE = "CONTROL_ACTIVE"
EXECUTING = "EXECUTING"
VERIFYING = "VERIFYING"
CONTINUE = "CONTINUE"
RECOVER = "RECOVER"
COMPLETED = "COMPLETED"
CONTROL_RELEASED = "CONTROL_RELEASED"
PAUSED = "PAUSED"
USER_TAKEOVER = "USER_TAKEOVER"
FAILED = "FAILED"
STOPPED = "STOPPED"

ALL_STATES = (
    IDLE, UNDERSTANDING, INSPECTING, PLANNING, CONTROL_ACTIVE, EXECUTING,
    VERIFYING, CONTINUE, RECOVER, COMPLETED, CONTROL_RELEASED, PAUSED,
    USER_TAKEOVER, FAILED, STOPPED,
)

# allowed transitions: current → {next states}
_TRANSITIONS: dict[str, set[str]] = {
    IDLE: {UNDERSTANDING, INSPECTING, CONTROL_ACTIVE, PLANNING, EXECUTING,
           FAILED, STOPPED, CONTROL_RELEASED},
    UNDERSTANDING: {INSPECTING, PLANNING, CONTROL_ACTIVE, EXECUTING, FAILED,
                    STOPPED, PAUSED, USER_TAKEOVER, IDLE},
    INSPECTING: {PLANNING, CONTROL_ACTIVE, EXECUTING, UNDERSTANDING, RECOVER,
                 FAILED, STOPPED, PAUSED, USER_TAKEOVER, IDLE},
    PLANNING: {CONTROL_ACTIVE, EXECUTING, INSPECTING, FAILED, STOPPED,
               PAUSED, USER_TAKEOVER, IDLE},
    CONTROL_ACTIVE: {EXECUTING, VERIFYING, INSPECTING, PAUSED, USER_TAKEOVER,
                     STOPPED, COMPLETED, CONTROL_RELEASED, FAILED},
    EXECUTING: {VERIFYING, EXECUTING, PAUSED, USER_TAKEOVER, STOPPED, FAILED,
                RECOVER, CONTROL_ACTIVE, CONTINUE, CONTROL_RELEASED},
    VERIFYING: {CONTINUE, RECOVER, EXECUTING, COMPLETED, FAILED, PAUSED,
                USER_TAKEOVER, STOPPED, CONTROL_RELEASED},
    CONTINUE: {EXECUTING, VERIFYING, COMPLETED, CONTROL_RELEASED, STOPPED,
               PAUSED, USER_TAKEOVER},
    RECOVER: {INSPECTING, EXECUTING, FAILED, STOPPED, PAUSED, USER_TAKEOVER,
              CONTROL_RELEASED},
    COMPLETED: {CONTROL_RELEASED, IDLE, STOPPED},
    CONTROL_RELEASED: {IDLE, CONTROL_ACTIVE, EXECUTING, STOPPED},
    PAUSED: {EXECUTING, USER_TAKEOVER, STOPPED, CONTROL_RELEASED, FAILED,
             CONTROL_ACTIVE},
    USER_TAKEOVER: {PAUSED, EXECUTING, STOPPED, CONTROL_RELEASED, CONTROL_ACTIVE},
    FAILED: {INSPECTING, RECOVER, EXECUTING, CONTROL_RELEASED, IDLE, STOPPED,
             PAUSED},
    STOPPED: {IDLE, CONTROL_RELEASED, CONTROL_ACTIVE, EXECUTING},
}

# map machine state → human status line + colour role for the UI/overlay pill
_STATUS_UI: dict[str, tuple[str, str]] = {
    UNDERSTANDING:  ("ANALYZING", "gold"),
    INSPECTING:     ("ANALYZING", "gold"),
    PLANNING:       ("ANALYZING", "gold"),
    CONTROL_ACTIVE: ("CONTROL ACTIVE", "gold"),
    EXECUTING:      ("EXECUTING", "gold"),
    VERIFYING:      ("VERIFYING", "cyan"),
    CONTINUE:       ("CONTINUING", "gold"),
    RECOVER:        ("RECOVERING", "amber"),
    COMPLETED:      ("COMPLETED", "green"),
    CONTROL_RELEASED: ("CONTROL RELEASED", "green"),
    PAUSED:         ("PAUSED", "blue"),
    USER_TAKEOVER:  ("USER CONTROL", "blue"),
    FAILED:         ("ACTION FAILED", "red"),
    STOPPED:        ("STOPPED", "red"),
    IDLE:           ("CONTROL RELEASED", "muted"),
}

# allowed states while idle — the pill reads as released
IDLE_UI = ("CONTROL RELEASED", "muted")


def ui_status(state: str) -> tuple[str, str]:
    """(status text, colour role) for the pill on the overlay / main UI."""
    if state in (IDLE, CONTROL_RELEASED):
        return _STATUS_UI.get(CONTROL_RELEASED, IDLE_UI)
    return _STATUS_UI.get(state, IDLE_UI)


class ControlStateMachine:
    """Thread-safe state machine. Every transition is validated."""

    def __init__(self, initial: str = IDLE) -> None:
        self._lock = threading.RLock()
        self._state = initial if initial in ALL_STATES else IDLE
        self._listeners: list[Callable[[str, str], None]] = []

    # ── events ─────────────────────────────────────────────────────────
    def on_transition(self, listener: Callable[[str, str], None]) -> None:
        """Register a (old_state, new_state) callback."""
        with self._lock:
            self._listeners.append(listener)

    def _emit(self, old: str, new: str) -> None:
        for cb in list(self._listeners):
            try:
                cb(old, new)
            except Exception:
                pass

    # ── transitions ────────────────────────────────────────────────────
    def transition(self, new: str, force: bool = False) -> bool:
        new = str(new).upper()
        if new not in ALL_STATES:
            return False
        with self._lock:
            old = self._state
            if old == new:
                return True
            allowed = _TRANSITIONS.get(old, set())
            if not force and new not in allowed:
                return False
            self._state = new
        self._emit(old, new)
        return True

    def force(self, new: str) -> bool:
        """Unconditional transition (emergency stop / takeover)."""
        return self.transition(new, force=True)

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def is_active(self) -> bool:
        """True while the agent holds control and is (or can be) working."""
        with self._lock:
            return self._state in (
                CONTROL_ACTIVE, EXECUTING, VERIFYING, CONTINUE, RECOVER,
                UNDERSTANDING, INSPECTING, PLANNING, PAUSED, USER_TAKEOVER,
            )

    def is_running(self) -> bool:
        with self._lock:
            return self._state in (CONTROL_ACTIVE, EXECUTING, VERIFYING,
                                   CONTINUE, RECOVER, UNDERSTANDING,
                                   INSPECTING, PLANNING)

    def ui(self) -> tuple[str, str]:
        return ui_status(self.state)

    def __repr__(self) -> str:
        return f"<ControlStateMachine {self.state}>"


_machine: Optional[ControlStateMachine] = None
_machine_lock = threading.Lock()


def get_machine() -> ControlStateMachine:
    """Shared singleton state machine."""
    global _machine
    if _machine is None:
        with _machine_lock:
            if _machine is None:
                _machine = ControlStateMachine()
    return _machine


def reset_machine() -> None:
    global _machine
    with _machine_lock:
        _machine = None
