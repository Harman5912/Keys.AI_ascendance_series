"""Confirmation gate for high-impact actions.

Potentially consequential actions (sending a message, deleting files,
permanently changing files, submitting forms, purchasing, posting publicly,
sending email, destructive commands) pause for confirmation with:

    KEYS.AI IS READY TO PERFORM THIS ACTION
    [CONFIRM] [CANCEL] [TAKE CONTROL]

Harmless actions (opening an app, scrolling, searching, reading, navigating,
typing into a non-submitting field) never ask.

The gate itself is pure logic — the actual dialog lives in the control
overlay. `request()` blocks the calling (worker) thread until the user
answers or the timeout expires; if no dialog is attached it returns
"cancel" honestly instead of pretending.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

# actions / keywords that must pause for confirmation
HIGH_IMPACT_ACTIONS = {
    "send", "send_message", "send_email", "email", "post", "publish",
    "share", "submit", "purchase", "buy", "pay", "checkout", "order",
    "delete", "delete_file", "delete_folder", "remove", "uninstall",
    "overwrite", "replace_file", "move_file", "rename_file", "format",
    "wipe", "sign_out", "shutdown", "restart_pc", "destructive_command",
}

# keywords that make a free-text action description high impact
_HIGH_IMPACT_MARKERS = (
    "delete", "remove", "send", "submit", "purchase", "buy", "pay",
    "post", "publish", "share publicly", "email", "overwrite",
    "replace the file", "uninstall", "format", "wipe", "shut down",
    "place order", "checkout",
)

# explicitly harmless — never ask (kept for documentation + routing tests)
HARMLESS_ACTIONS = {
    "open", "scroll", "search", "read", "inspect", "find", "focus",
    "navigate", "switch_tab", "switch_window", "list", "copy", "paste",
    "select", "move_mouse", "press", "hotkey", "type", "wait", "verify",
}


def classify(action: str = "", description: str = "") -> str:
    """Return 'high' or 'low' impact for an action.

    Action names are matched against the known sets; free-text descriptions
    are scanned for high-impact markers. Unknown actions default to 'low'
    so harmless behaviour is never blocked by mistake.
    """
    a = (action or "").strip().lower().replace("-", "_").replace(" ", "_")
    if a in HIGH_IMPACT_ACTIONS:
        return "high"
    d = (description or "").lower()
    # a free-text description always wins — "click the send button" is high
    # even though the action name 'click' is harmless.
    if any(m in d for m in _HIGH_IMPACT_MARKERS):
        return "high"
    if a in HARMLESS_ACTIONS:
        return "low"
    return "low"


class ConfirmationGate:
    """Blocking confirmation with CONFIRM / CANCEL / TAKE CONTROL."""

    RESULT_CONFIRM = "confirm"
    RESULT_CANCEL = "cancel"
    RESULT_TAKEOVER = "takeover"
    RESULT_TIMEOUT = "timeout"

    def __init__(self, settings=None, bridge=None) -> None:
        self._settings = settings
        self._bridge = bridge
        self._event = threading.Event()
        self._result: Optional[str] = None
        self._prompt = ""
        self._timeout = 60.0

    def attach(self, bridge) -> None:
        """Attach a UI bridge (ControlOverlayBridge). Replace existing if set."""
        self._bridge = bridge

    def detach(self) -> None:
        self._bridge = None

    def needs_confirmation(self, action: str = "", description: str = "") -> bool:
        if self._settings is not None:
            from agent_control.settings import get_settings
            s = self._settings
            if not s.get("confirm_high_impact", True):
                return False
        return classify(action, description) == "high"

    def request(self, action: str = "", description: str = "",
                prompt: str = "", timeout: float = 60.0) -> str:
        """Block until the user answers. Returns one of the RESULT_* values.

        Honest fallbacks: no dialog attached → "cancel" (never pretend the
        action was approved); timeout → "timeout" (treated as cancel).
        """
        if self._bridge is None:
            return self.RESULT_CANCEL
        self._event.clear()
        self._result = None
        self._prompt = prompt or (
            f"Keys.ai is ready to perform this action "
            f"({action or 'high-impact action'}).")
        self._timeout = max(5.0, float(timeout))
        try:
            self._bridge.request_confirm(self._prompt, self._timeout, callback=self._resolve)
        except Exception:
            return self.RESULT_CANCEL
        waited = self._event.wait(self._timeout + 2.0)
        if not waited:
            return self.RESULT_TIMEOUT
        return self._result or self.RESULT_CANCEL

    def _resolve(self, result: str) -> None:
        """Called by the bridge when the user clicks a button."""
        self._result = result if result in (
            self.RESULT_CONFIRM, self.RESULT_CANCEL, self.RESULT_TAKEOVER) \
            else self.RESULT_CANCEL
        self._event.set()

    # convenience ---------------------------------------------------------
    def confirm_or_cancel(self, result: str) -> bool:
        return result in (self.RESULT_CONFIRM,)


_gate: Optional[ConfirmationGate] = None
_gate_lock = threading.Lock()


def get_gate(settings=None, bridge=None) -> ConfirmationGate:
    global _gate
    if _gate is None:
        with _gate_lock:
            if _gate is None:
                _gate = ConfirmationGate(settings, bridge)
    if bridge is not None:
        _gate.attach(bridge)
    if settings is not None and _gate._settings is None:
        _gate._settings = settings
    return _gate


def reset_gate() -> None:
    global _gate
    with _gate_lock:
        _gate = None
