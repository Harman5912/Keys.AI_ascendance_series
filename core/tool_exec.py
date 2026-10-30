"""
Shared tool-execution envelope for Keys.ai.

Both the voice path (main.py _execute_tool) and the brain path
(brain/tools.py ToolRegistry.execute) need the same failure contract:

- tool outcomes should be representable as a structured envelope, not just
  "string or exception";
- tool failures should be classifiable so the caller can decide whether a
  retry, a fallback, or a plain error message is the right next move;
- the app session must never be ended by a tool failure that the caller did
  not explicitly authorize.

This module is the small normalization layer between "some tool returned a
string or raised" and "the caller received a reasoned outcome". It does not
replace the existing registries; it just gives both paths a shared vocabulary
for success / soft failure / hard failure.
"""

from __future__ import annotations

import traceback as _traceback
from dataclasses import dataclass
from typing import Any, Callable


class ToolError(Exception):
    """A tool outcome that should be treated as a failure, not a success string.

    Existing handlers already return human-friendly error text. This exception
    is for the cases where the dispatch layer itself wants to distinguish
    "the tool intentionally rejected this" from "something in the caller went
    wrong and we should still keep the session alive".
    """
    def __init__(self, message: str, *, kind: str = "TOOL_ERROR", detail: Any = None):
        super().__init__(message)
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True)
class ToolOutcome:
    """Normalized result of one tool invocation.

    This is the shared vocabulary both paths should eventually pass around:
    - success: the tool did its job and returned usable text;
    - soft_fail: the tool ran, but the result looks like a failure worth
      retrying or falling back from;
    - hard_fail: the tool did not produce a usable result.
    """
    name: str
    status: str                      # "success" | "soft_fail" | "hard_fail"
    result: str                     # user-facing text, if any
    error: str | None               # normalized error, if any
    kind: str                      # error classifier, when applicable
    silent: bool = False            # save_memory-style outcomes that should not speak
    shutdown_requested: bool = False

    @classmethod
    def success(cls, name: str, result: str, *, silent: bool = False) -> "ToolOutcome":
        return cls(name, "success", result or "", None, "OK", silent=silent)

    @classmethod
    def soft_fail(cls, name: str, result: str, *, kind: str = "UNKNOWN") -> "ToolOutcome":
        return cls(name, "soft_fail", result or "", None, kind)

    @classmethod
    def hard_fail(cls, name: str, error: str, *, kind: str = "TOOL_ERROR") -> "ToolOutcome":
        return cls(name, "hard_fail", "", error, kind)

    @classmethod
    def from_callable(
        cls,
        name: str,
        fn: Callable[[], str],
        *,
        silent_on_done: bool = False,
    ) -> "ToolOutcome":
        """Run a tool call through the envelope contract.

        This is the helper the voice path should use when it wants tool
        failures to remain *visible and classified* instead of turning into
        either a raw exception escape or a vague "Done." / "failed: ..." string
        that the caller cannot reliably act on.

        It is deliberately narrow: it wraps one synchronous callable that
        returns a user-facing string. Async tool paths still do their own
        awaiting; this is for the pieces that are easiest to normalize near
        the dispatch layer.
        """
        try:
            value = fn()
        except ToolError as exc:
            return cls.hard_fail(name, str(exc), kind=exc.kind)
        except Exception as exc:
            # Any unexpected failure is still just a tool failure from the
            # session's point of view. The app must not treat this as a signal
            # to shut down.
            return cls.hard_fail(name, f"{type(exc).__name__}: {exc}", kind="TOOL_ERROR")
        if value is None:
            value = ""
        text = str(value).strip()
        if text.lower().startswith("done") and not text[4:].strip():
            if silent_on_done:
                return cls.success(name, "", silent=True)
            return cls.success(name, "Done.")
        return cls.success(name, text)

    @property
    def ok(self) -> bool:
        return self.status == "success"

    def is_retryable(self) -> bool:
        return self.status == "soft_fail"


def classify_tool_error(text: str) -> str:
    """Best-effort classifier for tool-result text.

    Mirrors the shape the brain evaluator already uses, so the voice path can
    describe failures in similar terms without importing the brain module.
    """
    low = text.lower()
    if "timeout" in low or "timed out" in low:
        return "TIMEOUT"
    if ("connection" in low or "network" in low or "offline" in low
            or "getaddrinfo" in low or "ssl" in low or "refused" in low):
        return "NETWORK_ERROR"
    if any(k in low for k in ("unauthorized", "auth", "token", "permission", "api key")):
        return "AUTH_ERROR"
    if any(k in low for k in ("invalid", "argument", "parameter")):
        return "INVALID_ARGUMENT"
    return "TOOL_ERROR"
