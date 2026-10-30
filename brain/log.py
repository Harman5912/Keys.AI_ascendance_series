"""
Structured, high-level event logging for the Smart Brain.

Only SAFE high-level status is emitted — never internal chain-of-thought.
Sink defaults to print; the host app can supply ui.write_log so brain events
appear in the on-screen log. Format: [HH:MM:SS] TAG message
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime
from typing import Callable

# Canonical high-level events (spec §30)
EVT_USER_REQUEST   = "USER_REQUEST"
EVT_INTENT         = "INTENT_DETECTED"
EVT_MEMORY         = "MEMORY_RETRIEVED"
EVT_MEMORY_SAVED   = "MEMORY_SAVED"
EVT_PLAN           = "PLAN_CREATED"
EVT_ROUTE          = "ROUTED"
EVT_TOOL_SELECTED  = "TOOL_SELECTED"
EVT_TOOL_EXECUTED  = "TOOL_EXECUTED"
EVT_OBSERVATION    = "OBSERVATION"
EVT_EVALUATION     = "EVALUATION"
EVT_RETRY          = "RETRY"
EVT_RECOVER        = "RECOVERED"
EVT_WAIT_USER      = "WAITING_FOR_USER"
EVT_TASK_COMPLETE  = "TASK_COMPLETE"
EVT_TASK_FAILED    = "TASK_FAILED"
EVT_STOPPED        = "STOPPED"
EVT_PAUSED         = "PAUSED"
EVT_RESUMED        = "RESUMED"
EVT_FALLBACK       = "FALLBACK"


class BrainLogger:
    def __init__(self, level: str = "info",
                 sink: Callable[[str], None] | None = None):
        self._level = (level or "info").lower()
        self._sink  = sink
        self._lock  = threading.Lock()

    @property
    def sink(self):
        return self._sink

    @sink.setter
    def sink(self, fn):
        self._sink = fn

    def _write(self, tag: str, msg: str) -> None:
        ts   = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {tag} {msg}"
        try:
            if self._sink is not None:
                self._sink(line)
            else:
                print(line, flush=True)
        except Exception:
            try:
                print(line, flush=True)
            except Exception:
                pass

    def event(self, tag: str, msg: str) -> None:
        self._write(tag, msg)

    def info(self, msg: str) -> None:
        if self._level in ("info", "debug"):
            self._write("INFO", msg)

    def warn(self, msg: str) -> None:
        self._write("WARN", msg)

    def error(self, msg: str) -> None:
        self._write("ERROR", msg)

    def debug(self, msg: str) -> None:
        if self._level == "debug":
            self._write("DEBUG", msg)
