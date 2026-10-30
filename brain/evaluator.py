"""
Observation → evaluation → recovery (spec §17, §18, §19).

After a tool executes we never blindly assume success. The evaluator looks at
the returned text for known failure markers, decides success / soft-fail /
hard-fail, and decides whether a bounded retry makes sense.

Errors are also categorized (TOOL_ERROR, NETWORK_ERROR, TIMEOUT, ...) so the
brain can pick the right recovery without ever looping forever.
"""

from __future__ import annotations

import re

# Failure markers in tool result text (lowercase match)
FAIL_MARKERS = [
    "failed", "failure", "error", "exception", "traceback", "unable to",
    "could not", "cannot", "not found", "no such", "timed out", "timeout",
    "invalid", "unknown tool", "does not exist", "denied", "refused",
    "connection error", "network error", "crashed", "❌", "⚠️ failed",
    "hata", "başarısız", "bulunamadı", "yapılamadı",
]

NETWORK_MARKERS = [
    "timed out", "timeout", "connection", "network", "getaddrinfo",
    "ssl", "refused", "offline", "internet",
]

TIMEOUT_MARKERS = ["timed out", "timeout"]


class Evaluation:
    def __init__(self, status: str, reason: str = "", error_type: str = ""):
        self.status     = status      # success | soft_fail | hard_fail
        self.reason     = reason
        self.error_type = error_type  # TOOL_ERROR | NETWORK_ERROR | TIMEOUT | ...

    def is_success(self) -> bool:
        return self.status == "success"

    def is_retryable(self) -> bool:
        return self.status in ("soft_fail",) and self.error_type in (
            "TOOL_ERROR", "NETWORK_ERROR", "TIMEOUT", "UNKNOWN")


class Evaluator:
    def __init__(self, max_retries: int = 2):
        self.max_retries = max_retries

    def evaluate(self, result: dict | None) -> Evaluation:
        """Evaluate a ToolRegistry.execute() dict."""
        if result is None:
            return Evaluation("soft_fail", "no result returned", "UNKNOWN")

        if not result.get("ok"):
            err = str(result.get("error", ""))
            etype = self._categorize(err)
            return Evaluation("hard_fail", err or "tool crashed", etype)

        text = str(result.get("result", ""))
        low  = text.lower()
        if not text.strip():
            return Evaluation("soft_fail", "empty result — needs verification",
                              "TOOL_ERROR")

        for marker in FAIL_MARKERS:
            if marker in low:
                etype = self._categorize(text)
                if etype in ("TIMEOUT", "NETWORK_ERROR"):
                    return Evaluation("soft_fail", f"failure marker: {marker}",
                                      etype)
                return Evaluation("soft_fail", f"failure marker: {marker}",
                                  "TOOL_ERROR")
        return Evaluation("success", "ok")

    def should_retry(self, evaluation: Evaluation, attempts: int) -> bool:
        if not evaluation.is_retryable():
            return False
        return attempts < self.max_retries

    def _categorize(self, text: str) -> str:
        low = text.lower()
        if any(m in low for m in TIMEOUT_MARKERS):
            return "TIMEOUT"
        if any(m in low for m in NETWORK_MARKERS):
            return "NETWORK_ERROR"
        if any(k in low for k in ("api key", "unauthorized", "auth", "token",
                                  "permission")):
            return "AUTH_ERROR"
        if any(k in low for k in ("invalid", "argument", "parameter")):
            return "INVALID_ARGUMENT"
        return "TOOL_ERROR"
