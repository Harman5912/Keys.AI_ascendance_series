"""
crown_code/engine/events.py — Typed event bus for Crown Code v2.

Every meaningful state change inside the agent loop is emitted as a typed
Event.  The UI adapter listens and forwards events to the Tkinter layer
without knowing anything about agent internals.  Tests can subscribe to the
bus to verify behaviour without running a real model.

Design principles:
  - Zero dependencies on Tkinter / Qt / any UI toolkit.
  - Thread-safe: subscribers are called from the worker thread that emits.
  - No lost events: a ring buffer (maxlen=500) lets latecomers replay history.
  - Lightweight: importing this module costs nothing; the bus is a singleton.

Event taxonomy
--------------
PlanEvent       — the agent wrote / updated its todo list
ToolCallEvent   — the agent is about to run a tool
ToolResultEvent — a tool finished (ok or error)
FileWriteEvent  — a file was created or overwritten
FileReadEvent   — a file was read
ShellEvent      — a shell command ran
ThinkEvent      — the agent's reasoning narration (streaming)
ProgressEvent   — build progress (phase, percent, message)
CheckpointEvent — a checkpoint was saved or restored
ErrorEvent      — a recoverable error occurred
DoneEvent       — the build finished (ok=True) or failed (ok=False)
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

# ── event types ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PlanEvent:
    todos: list[str]
    done: list[str] = field(default_factory=list)
    ts: float = field(default_factory=time.time)
    kind: str = "plan"

@dataclass(frozen=True)
class ToolCallEvent:
    name: str
    params: dict
    call_id: str = ""
    ts: float = field(default_factory=time.time)
    kind: str = "tool_call"

@dataclass(frozen=True)
class ToolResultEvent:
    name: str
    result: str
    ok: bool
    call_id: str = ""
    ts: float = field(default_factory=time.time)
    kind: str = "tool_result"

@dataclass(frozen=True)
class FileWriteEvent:
    path: str
    size: int = 0
    ts: float = field(default_factory=time.time)
    kind: str = "file_write"

@dataclass(frozen=True)
class FileReadEvent:
    path: str
    ts: float = field(default_factory=time.time)
    kind: str = "file_read"

@dataclass(frozen=True)
class ShellEvent:
    command: str
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    ts: float = field(default_factory=time.time)
    kind: str = "shell"

@dataclass(frozen=True)
class ThinkEvent:
    text: str
    streaming: bool = False
    ts: float = field(default_factory=time.time)
    kind: str = "think"

@dataclass(frozen=True)
class ProgressEvent:
    phase: str
    percent: float          # 0.0–1.0
    message: str = ""
    ts: float = field(default_factory=time.time)
    kind: str = "progress"

@dataclass(frozen=True)
class CheckpointEvent:
    checkpoint_id: str
    action: str             # "saved" | "restored" | "deleted"
    label: str = ""
    ts: float = field(default_factory=time.time)
    kind: str = "checkpoint"

@dataclass(frozen=True)
class ErrorEvent:
    message: str
    recoverable: bool = True
    ts: float = field(default_factory=time.time)
    kind: str = "error"

@dataclass(frozen=True)
class DoneEvent:
    ok: bool
    summary: str = ""
    files: list[str] = field(default_factory=list)
    ts: float = field(default_factory=time.time)
    kind: str = "done"

# Union type for type hints
AnyEvent = (
    PlanEvent | ToolCallEvent | ToolResultEvent | FileWriteEvent |
    FileReadEvent | ShellEvent | ThinkEvent | ProgressEvent |
    CheckpointEvent | ErrorEvent | DoneEvent
)

# ── event bus ─────────────────────────────────────────────────────────────────

class EventBus:
    """
    Thread-safe pub/sub event bus with a replay buffer.

    Usage
    -----
        bus = EventBus()

        # subscribe
        unsub = bus.subscribe(lambda e: print(e))

        # emit (from any thread)
        bus.emit(ProgressEvent("planning", 0.1, "Analysing brief"))

        # replay history for a late subscriber
        for e in bus.history():
            ...

        # unsubscribe when done
        unsub()
    """

    def __init__(self, maxhistory: int = 500):
        self._subs: list[Callable] = []
        self._history: deque = deque(maxlen=maxhistory)
        self._lock = threading.Lock()

    def subscribe(self, fn: Callable[[Any], None]) -> Callable:
        """Register a subscriber. Returns an unsubscribe callable."""
        with self._lock:
            self._subs.append(fn)
        def _unsub():
            with self._lock:
                try:
                    self._subs.remove(fn)
                except ValueError:
                    pass
        return _unsub

    def emit(self, event: Any) -> None:
        """Emit an event to all subscribers (called from worker thread)."""
        with self._lock:
            self._history.append(event)
            subs = list(self._subs)
        for fn in subs:
            try:
                fn(event)
            except Exception:
                pass  # never let a subscriber crash the agent loop

    def history(self) -> list:
        """Return a snapshot of the event history (newest last)."""
        with self._lock:
            return list(self._history)

    def clear(self) -> None:
        with self._lock:
            self._history.clear()
            self._subs.clear()


# Module-level singleton for convenience
_default_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_bus() -> EventBus:
    """Return (or create) the module-level default EventBus."""
    global _default_bus
    with _bus_lock:
        if _default_bus is None:
            _default_bus = EventBus()
        return _default_bus


def reset_bus() -> EventBus:
    """Replace the module-level bus with a fresh one (useful in tests)."""
    global _default_bus
    with _bus_lock:
        _default_bus = EventBus()
        return _default_bus
