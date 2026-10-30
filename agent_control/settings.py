"""Agent Control settings — persisted to config/agent_control.json.

Holds the Keys.ai Agent Control Mode preferences:
    humour_level        OFF | LOW | MEDIUM | HIGH
    dark_humour         OFF/ON   (only ever situational, non-targeted)
    professional_mode   ON/OFF   (disables unnecessary jokes)
    retry_limit         max intelligent retries per failed action (0-10)
    confirm_high_impact gate potentially consequential actions (send/delete/...)
    overlay_enabled     show the animated gold control border + watermark
    max_wait_timeout    default state-based wait timeout (seconds)

Thread-safe. The AI can change these through the agent_settings tool and the
user through the UI — both write the same file, no provider restart needed.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

HUMOUR_LEVELS = ("OFF", "LOW", "MEDIUM", "HIGH")
VALID_KEYS = {
    "humour_level", "dark_humour", "professional_mode", "retry_limit",
    "confirm_high_impact", "overlay_enabled", "max_wait_timeout",
}

DEFAULTS: dict = {
    "humour_level": "MEDIUM",
    "dark_humour": False,
    "professional_mode": False,
    "retry_limit": 3,
    "confirm_high_impact": True,
    "overlay_enabled": True,
    "max_wait_timeout": 30.0,
}


def _config_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "config"
    return Path(__file__).resolve().parent.parent / "config"


class AgentControlSettings:
    """Thread-safe settings store with JSON persistence."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path else (_config_dir() / "agent_control.json")
        self._lock = threading.RLock()
        self._data: dict = dict(DEFAULTS)
        self._load()

    # ── persistence ────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            if self._path.exists():
                d = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    for k in VALID_KEYS:
                        if k in d:
                            self._data[k] = d[k]
        except Exception:
            pass  # corrupt file → keep defaults

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ── access ─────────────────────────────────────────────────────────
    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value) -> bool:
        """Validate + apply a setting. Returns True when applied."""
        key = str(key)
        if key not in VALID_KEYS:
            return False
        with self._lock:
            if key == "humour_level":
                value = str(value).upper()
                if value not in HUMOUR_LEVELS:
                    return False
            elif key in ("dark_humour", "professional_mode", "confirm_high_impact", "overlay_enabled"):
                value = bool(value)

            elif key == "retry_limit":
                try:
                    iv = int(value)
                except Exception:
                    return False
                if iv < 0 or iv > 10:
                    return False
                value = iv
            elif key == "max_wait_timeout":
                try:
                    value = max(3.0, min(300.0, float(value)))
                except Exception:
                    return False
            self._data[key] = value
        self.save()
        return True

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._data)

    def __repr__(self) -> str:
        return f"<AgentControlSettings {self.snapshot()}>"


_shared: Optional[AgentControlSettings] = None
_shared_lock = threading.Lock()


def get_settings(path: Optional[Path] = None) -> AgentControlSettings:
    """Shared singleton used by the engine, tools and UI."""
    global _shared
    if _shared is None:
        with _shared_lock:
            if _shared is None:
                _shared = AgentControlSettings(path)
    return _shared


def reset_settings() -> None:
    """For tests only — drop the singleton so a fresh one is created."""
    global _shared
    with _shared_lock:
        _shared = None


def settings_summary(settings: Optional[AgentControlSettings] = None) -> str:
    s = settings or get_settings()
    snap = s.snapshot()
    return (
        f"Humour: {snap['humour_level']} | Dark humour: "
        f"{'ON' if snap['dark_humour'] else 'OFF'} | Professional mode: "
        f"{'ON' if snap['professional_mode'] else 'OFF'} | Retry limit: "
        f"{snap['retry_limit']} | Confirm high-impact actions: "
        f"{'ON' if snap['confirm_high_impact'] else 'OFF'} | Overlay: "
        f"{'ON' if snap['overlay_enabled'] else 'OFF'}"
    )
