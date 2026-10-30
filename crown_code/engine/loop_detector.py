"""
crown_code/engine/loop_detector.py — Agent-loop infinite-loop / stall detector.

The loop detector watches the sequence of tool calls the agent makes and fires
if it detects any of:

  REPEAT   — the same tool + same params appeared N times in a row
  SPIN     — no file was written in the last K tool calls
  STALL    — no event arrived for more than T seconds

On detection, the engine is signalled to cancel and the EventBus receives an
ErrorEvent with recoverable=False so the UI can show a human-readable message.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from crown_code.engine.events import ErrorEvent, EventBus, ToolCallEvent, FileWriteEvent


@dataclass
class LoopConfig:
    repeat_limit: int = 3           # identical (name, params-hash) in a row
    spin_limit: int = 12            # tool calls without any file write
    stall_seconds: float = 120.0    # seconds without any event


class LoopDetector:
    """
    Attach to an EventBus; cancels the build if looping is detected.

    Usage
    -----
        detector = LoopDetector(bus, cancel_fn, config=LoopConfig())
        detector.start()
        ...
        detector.stop()
    """

    def __init__(
        self,
        bus: EventBus,
        cancel_fn: callable,
        config: LoopConfig | None = None,
    ):
        self._bus = bus
        self._cancel = cancel_fn
        self._cfg = config or LoopConfig()

        # state
        self._last_event_ts = time.monotonic()
        self._tool_calls: deque[str] = deque(maxlen=self._cfg.spin_limit + 5)
        self._repeat_counter = 0
        self._last_key = ""
        self._calls_since_write = 0
        self._fired = False
        self._lock = threading.Lock()

        # stall monitor thread
        self._stop_event = threading.Event()
        self._monitor: threading.Thread | None = None
        self._unsub = None

    def start(self) -> None:
        self._unsub = self._bus.subscribe(self._handle)
        self._monitor = threading.Thread(
            target=self._stall_monitor, daemon=True,
            name="loop-detector-stall"
        )
        self._monitor.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._unsub:
            self._unsub()
            self._unsub = None

    # ── event handler ────────────────────────────────────────────────────────

    def _handle(self, event: Any) -> None:
        with self._lock:
            self._last_event_ts = time.monotonic()

        if isinstance(event, FileWriteEvent):
            with self._lock:
                self._calls_since_write = 0

        elif isinstance(event, ToolCallEvent):
            key = f"{event.name}:{hash(str(sorted(event.params.items())))}"
            with self._lock:
                self._tool_calls.append(key)
                self._calls_since_write += 1

                # REPEAT check
                if key == self._last_key:
                    self._repeat_counter += 1
                else:
                    self._repeat_counter = 1
                    self._last_key = key

                repeat = self._repeat_counter >= self._cfg.repeat_limit
                spin = self._calls_since_write >= self._cfg.spin_limit

            if repeat and not self._fired:
                self._fire(
                    f"Loop detected: tool '{event.name}' called "
                    f"{self._cfg.repeat_limit}× in a row with identical params."
                )
            elif spin and not self._fired:
                self._fire(
                    f"Spin detected: {self._cfg.spin_limit} tool calls "
                    "with no file written — possible infinite loop."
                )

    def _stall_monitor(self) -> None:
        while not self._stop_event.wait(timeout=10.0):
            with self._lock:
                idle = time.monotonic() - self._last_event_ts
                fired = self._fired
            if not fired and idle > self._cfg.stall_seconds:
                self._fire(
                    f"Stall detected: no agent activity for "
                    f"{idle:.0f}s (limit {self._cfg.stall_seconds:.0f}s)."
                )

    def _fire(self, message: str) -> None:
        with self._lock:
            if self._fired:
                return
            self._fired = True
        self._bus.emit(ErrorEvent(message=message, recoverable=False))
        self._cancel()
        self.stop()
