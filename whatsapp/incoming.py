"""whatsapp/incoming.py — REMOVED.

Calling features have been removed from Keys.ai. This module now provides
only stub functions so any legacy imports do not break.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional


class IncomingCallWatcher:
    """Stub — calling removed."""

    def __init__(self, log=None):
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def set_callback(self, fn=None) -> None:
        pass

    def snapshot(self) -> dict:
        return {"state": "disabled", "incoming": {}, "handling": {}}

    def status_text(self) -> str:
        return "Calling features are disabled. Keys.ai can only send messages."


_watcher: Optional[IncomingCallWatcher] = None
_watcher_lock = threading.Lock()


def get_watcher(log=None) -> IncomingCallWatcher:
    """Module-level singleton — returns a disabled watcher."""
    global _watcher
    if _watcher is None:
        with _watcher_lock:
            if _watcher is None:
                _watcher = IncomingCallWatcher(log=log)
    return _watcher
