"""whatsapp/calls.py — REMOVED.

Calling features have been removed from Keys.ai. This module now provides
only stub functions so any legacy imports do not break.
"""

from __future__ import annotations

from typing import Callable, Optional


class CallOperation:
    """Stub — calling removed."""

    STATES = ("NOT_STARTED",)

    def __init__(self, contact: str, call_type: str = "voice",
                 operation_id: Optional[str] = None) -> None:
        self.contact = contact
        self.call_type = call_type
        self.state = "NOT_STARTED"


class CallCoordinator:
    """Stub — calling removed."""

    def __init__(self, ready=None, driver=None, chat_opener=None,
                 waits=None, timing=None, log=None) -> None:
        pass

    def make_call(self, contact: str, call_type: str = "voice") -> dict:
        return {
            "success": False,
            "state": "CALL_FAILED",
            "contact": contact,
            "call_type": call_type,
            "detail": "Calling features have been removed. Keys.ai can only send messages.",
        }


async def whatsapp_make_call(contact: str, call_type: str = "voice",
                             log: Optional[Callable[[str], None]] = None) -> bool:
    return False


async def whatsapp_make_call_result(contact: str, call_type: str = "voice",
                                    log: Optional[Callable[[str], None]] = None) -> dict:
    return {
        "success": False,
        "state": "CALL_FAILED",
        "detail": "Calling features have been removed.",
    }


def make_call_sync(contact: str, call_type: str = "voice",
                   log: Optional[Callable[[str], None]] = None) -> dict:
    return {
        "success": False,
        "state": "CALL_FAILED",
        "detail": "Calling features have been removed.",
    }
