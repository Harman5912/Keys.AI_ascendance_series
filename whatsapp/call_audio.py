"""whatsapp/call_audio.py — REMOVED.

Calling features have been removed from Keys.ai. This module now provides
only stub functions so any legacy imports do not break.
"""

from __future__ import annotations

from typing import Iterator, Optional


def loopback_available() -> bool:
    return False


def find_cable_output(pa) -> Optional[dict]:
    return None


class CallAudioLink:
    """Stub — calling removed."""

    def __init__(self):
        self.loopback_ok = False
        self.cable_name: Optional[str] = None
        self.output_stream = None

    def open(self) -> None:
        pass

    def iter_loopback(self) -> Iterator[bytes]:
        return iter([])

    def close(self) -> None:
        pass
