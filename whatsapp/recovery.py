"""Recovery & retry (spec 16-18, 41). Self-healing without restarting Keys.ai:
recover the SMALLEST failed component first, escalate only when the previous
level fails. Never restart the browser for a button that took 2s longer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional


LEVELS = [
    "wait",                 # 0: short wait, re-check
    "recheck_dom",          # 1: re-check DOM/UI state
    "reacquire_page",       # 2: reacquire the WhatsApp page
    "reconnect_session",    # 3: reconnect WhatsApp session
    "reload_page",          # 4: reload WhatsApp page
    "restart_context",      # 5: restart browser context
    "restart_browser",      # 6: restart the browser
    "ask_user",             # 7: request user intervention
]


class RecoveryLadder:
    """Bounded, escalating recovery. Climb one level at a time; a level only
    runs when the previous one failed. Stops at max_depth (fail safely,
    spec 33) and never loops infinitely.

    Handlers: dict mapping level name -> callable(attempt_context) -> bool.
    Attempts call the SAME operation again with a fresh budget; escalations
    run progressively stronger repairs.
    """

    def __init__(self, handlers: dict, max_depth: int = 4,
                 log: Optional[Callable[[str], None]] = None) -> None:
        self.handlers = handlers
        self.max_depth = max(max_depth, 1)
        self.log = log or (lambda _m: None)
        self.history: list[str] = []

    def recover(self, attempt: int = 1) -> tuple[bool, str]:
        """Run recovery for one failed attempt. Returns (recovered, detail)."""
        depth = min(self.max_depth, len(LEVELS))
        for i in range(depth):
            level = LEVELS[i]
            handler = self.handlers.get(level)
            if handler is None:
                continue
            try:
                ok = bool(handler(attempt))
            except Exception as e:
                ok = False
                self.log(f"[WA] recovery {level} raised: {e}")
            self.history.append(level)
            if ok:
                return True, level
        return False, "_exhausted"

    def describe(self) -> str:
        return " -> ".join(self.history[-8:]) or "(no recovery yet)"


def bounded_retry(operation: Callable[[int], bool], budget,
                  ladder: Optional[RecoveryLadder] = None,
                  log: Optional[Callable[[str], None]] = None) -> tuple[bool, dict]:
    """Spec 16-17: bounded retries with escalating recovery, then fail safely.

    - Attempts never repeat identically: between attempts we run the next
      recovery level (wait -> recheck -> reacquire -> ...).
    - Stops after budget.max_retries attempts (never infinite).
    - Returns (ok, info) where info carries attempt count and recovery trail.
    """
    log = log or (lambda _m: None)
    info: dict = {"attempts": 0, "recovery": [], "detail": ""}
    for attempt in range(1, max(1, budget.max_retries) + 1):
        info["attempts"] = attempt
        try:
            if operation(attempt):
                info["detail"] = f"ok on attempt {attempt}"
                return True, info
        except Exception as e:
            log(f"[WA] attempt {attempt} raised: {e}")
        if attempt < budget.max_retries:
            delay = budget.next_retry_delay(attempt)
            time.sleep(delay)
            if ladder is not None:
                ok, level = ladder.recover(attempt)
                info["recovery"].append(f"{level}" if ok else f"x{level}")
                log(f"[WA] recovery[{level}] -> {'recovered' if ok else 'continue escalating'}")
    info["detail"] = "failed after " + str(info["attempts"]) + " attempts"
    return False, info
