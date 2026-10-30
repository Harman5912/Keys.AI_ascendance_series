"""KEYS.AI CONTROL HISTORY — the agent activity log.

Every control action is recorded with:
    timestamp · application · action · detail · status

Statuses:
    ✓ SUCCESS   ● RUNNING   ⚠ WAITING   ✕ FAILED   ⏸ PAUSED

Privacy: sensitive content (API keys, passwords, tokens, auth headers,
message bodies) is scrubbed or truncated before it ever reaches a log or the
UI. Never store screenshots here — this is a text log only.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from typing import Optional

MAX_ENTRIES = 500

# ── status constants ──────────────────────────────────────────────────────
SUCCESS = "SUCCESS"
RUNNING = "RUNNING"
WAITING = "WAITING"
FAILED = "FAILED"
PAUSED = "PAUSED"
STOPPED = "STOPPED"

STATUS_ICON = {
    SUCCESS: "✓",
    RUNNING: "●",
    WAITING: "⚠",
    FAILED: "✕",
    PAUSED: "⏸",
    STOPPED: "■",
}

# ── privacy scrubbing ─────────────────────────────────────────────────────
# Two kinds of pattern: labelled ones (``token=XYZ``) keep their label and mask
# the value group; shape-only ones (a bare ``AIza…`` key) mask the whole match.
# The earlier implementation assumed every pattern had a second group and
# crashed with IndexError on the shape-only patterns — a log line containing a
# bare key took down the action that was trying to record it.
_SECRET_RE = [
    # An auth header carries a scheme (Bearer/Basic/…) before the secret; the
    # generic pattern below matched the scheme and left the token readable.
    re.compile(r"\b(authorization)\s*:\s*(?:[A-Za-z]+\s+)?(\S+)", re.I),
    re.compile(r"\b(api[_-]?key|password|passwd|secret|token|authorization|bearer)\s*[=:]\s*(\S+)", re.I),
    re.compile(r"\b(bearer)\s+([A-Za-z0-9._~+/=-]{12,})", re.I),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),          # google api key shape
    re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"),       # github token shapes
    re.compile(r"sk-[0-9A-Za-z_\-]{16,}"),           # openai/anthropic style
    re.compile(r"xox[abprs]-[0-9A-Za-z\-]{10,}"),    # slack
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # jwt
]


def _mask(match: "re.Match[str]") -> str:
    """Mask one secret match without ever raising."""
    text = match.group(0)
    try:
        if match.re.groups >= 2:
            value = match.group(2)
            if value:
                return text.replace(value, "***")
    except (IndexError, ValueError, re.error):
        pass
    # Shape-only match: keep a short, non-secret prefix (e.g. the "AIza"
    # vendor marker) so the line is still diagnosable.
    keep = 4 if len(text) > 10 else 0
    return text[:keep] + "***"


def scrub(text: str, max_len: int = 220) -> str:
    """Mask obvious secrets and cap length. Never logs raw typed message bodies.

    Redaction is best-effort: a malformed input must still produce a log line,
    so every failure path degrades to a truncated string rather than raising.
    """
    if not text:
        return ""
    try:
        out = str(text)
    except Exception:
        return "<unprintable>"
    try:
        for rx in _SECRET_RE:
            out = rx.sub(_mask, out)
        out = re.sub(r"\s+", " ", out).strip()
    except Exception:
        return "<redacted>"
    return out[:max_len]


class ControlHistory:
    """Thread-safe rolling action log."""

    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self._lock = threading.Lock()
        self._max = max(10, max_entries)
        self._entries: list[dict] = []
        self._listeners: list = []          # callbacks(entry: dict)
        self._next_id = 1

    # ── events ─────────────────────────────────────────────────────────
    def on_entry(self, listener) -> None:
        """Register a callback invoked (from the logging thread) per entry."""
        with self._lock:
            self._listeners.append(listener)

    def _notify(self, entry: dict) -> None:
        for cb in list(self._listeners):
            try:
                cb(entry)
            except Exception:
                pass

    # ── writing ────────────────────────────────────────────────────────
    def add(self, app: str = "", action: str = "", detail: str = "",
            status: str = RUNNING, ts: Optional[float] = None) -> dict:
        with self._lock:
            entry = {
                "id": self._next_id,
                "ts": ts if ts is not None else time.time(),
                "time": datetime.now().strftime("%H:%M:%S"),
                "app": scrub(app, 40),
                "action": scrub(action, 60),
                "detail": scrub(detail, 160),
                "status": status if status in STATUS_ICON else RUNNING,
            }
            self._next_id += 1
            self._entries.append(entry)
            if len(self._entries) > self._max:
                self._entries = self._entries[-self._max:]
            snapshot = dict(entry)
        self._notify(snapshot)
        return snapshot

    def update_status(self, entry, status: str) -> None:
        """Flip an entry's status (e.g. RUNNING → SUCCESS/FAILED).
        `entry` may be the dict returned by add(), or an entry id."""
        if status not in STATUS_ICON:
            return
        eid = entry.get("id") if isinstance(entry, dict) else entry
        with self._lock:
            for e in self._entries:
                if e.get("id") == eid:
                    e["status"] = status
                    snapshot = dict(e)
                    break
            else:
                return
        self._notify(snapshot)

    def clear(self) -> None:
        with self._lock:
            self._entries = []

    # ── reading ────────────────────────────────────────────────────────
    def recent(self, limit: int = 40) -> list[dict]:
        with self._lock:
            return list(self._entries[-max(1, limit):])

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def render(self, limit: int = 24) -> str:
        """Plain-text rendering (used by the AI tool + history panel)."""
        lines = []
        for e in self.recent(limit):
            icon = STATUS_ICON.get(e["status"], "●")
            app = f"[{e['app']}] " if e.get("app") else ""
            lines.append(f"{e['time']}  {icon}  {app}{e['action']}"
                         + (f" — {e['detail']}" if e.get("detail") else ""))
        return "\n".join(lines) if lines else "(control history is empty)"

    def render_html(self, limit: int = 30) -> str:
        """HTML lines for the main-window history panel."""
        cols = {
            SUCCESS: "#3DDC84", RUNNING: "#E5C368", WAITING: "#8FB8D8",
            FAILED: "#E5484D", PAUSED: "#A9B2C0", STOPPED: "#E5484D",
        }
        parts = []
        for e in self.recent(limit):
            icon = STATUS_ICON.get(e["status"], "●")
            col = cols.get(e["status"], "#E5C368")
            app = f"<span style='color:#8A6D2F'>{e['app']}</span> " if e.get("app") else ""
            parts.append(
                f"<span style='color:#6E7686'>{e['time']}</span> "
                f"<span style='color:{col}'>{icon}</span> {app}"
                f"{e['action']}"
                + (f" <span style='color:#7A8494'>— {e['detail']}</span>" if e.get("detail") else ""))
        return "<br>".join(parts) if parts else \
            "<span style='color:#4A5362'>(control history is empty)</span>"


_history: Optional[ControlHistory] = None
_history_lock = threading.Lock()


def get_history() -> ControlHistory:
    """Shared singleton control-history log."""
    global _history
    if _history is None:
        with _history_lock:
            if _history is None:
                _history = ControlHistory()
    return _history


def reset_history() -> None:
    global _history
    with _history_lock:
        _history = None
