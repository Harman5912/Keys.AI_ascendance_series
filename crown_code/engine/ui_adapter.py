"""
crown_code/engine/ui_adapter.py — Bridge between EventBus and Keys.AI Tkinter UI.

Subscribes to the EventBus of a running build job and forwards meaningful
events to the existing player (Keys.AI UI object) callbacks, preserving the
exact same interface the legacy CrownBridge already uses.

This means the UI never needs to know which engine is active — it always
receives the same set of method calls it expects.

Supported player methods (all optional — adapter checks before calling):
    terminal_output(text, stream, source)    — stream a line to the terminal
    creation_event(icon, label, url)         — update the creation panel event
    creation_preview(url)                    — show artifact in preview pane
    creation_progress(percent, phase, detail)— update progress bar
    creation_phase(phase)                    — set the current phase label
    speak(text)                              — text-to-speech narration
"""
from __future__ import annotations

import threading
from typing import Any, Optional

from crown_code.engine.events import (
    AnyEvent,
    CheckpointEvent,
    DoneEvent,
    ErrorEvent,
    EventBus,
    FileWriteEvent,
    ProgressEvent,
    ShellEvent,
    ThinkEvent,
    ToolCallEvent,
    ToolResultEvent,
)


def _call(player: Any, method: str, *args, **kwargs) -> Any:
    """Call player.method safely (ignores missing methods and exceptions)."""
    if player is None:
        return None
    fn = getattr(player, method, None)
    if fn is None:
        return None
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


class UIAdapter:
    """
    Subscribes to an EventBus and drives the Keys.AI player (UI) object.

    Usage
    -----
        adapter = UIAdapter(bus=bus, player=player)
        adapter.attach()      # starts listening
        ...                   # engine runs, events flow
        adapter.detach()      # stop listening (auto-called on DoneEvent)
    """

    def __init__(
        self,
        bus: EventBus,
        player: Any,
        *,
        speak_progress: bool = False,   # narrate progress updates via TTS
        speak_done: bool = True,        # narrate completion/failure via TTS
    ):
        self._bus = bus
        self._player = player
        self._speak_progress = speak_progress
        self._speak_done = speak_done
        self._unsub: Optional[callable] = None
        self._lock = threading.Lock()

    def attach(self) -> None:
        """Subscribe to the bus."""
        with self._lock:
            if self._unsub is not None:
                return  # already attached
            self._unsub = self._bus.subscribe(self._handle)

    def detach(self) -> None:
        """Unsubscribe from the bus."""
        with self._lock:
            unsub = self._unsub
            self._unsub = None
        if unsub:
            unsub()

    # ── event handler ────────────────────────────────────────────────────────

    def _handle(self, event: AnyEvent) -> None:
        p = self._player

        if isinstance(event, ProgressEvent):
            _call(p, "creation_progress",
                  event.percent, event.phase, event.message)
            _call(p, "creation_phase", event.phase)
            _call(p, "terminal_output",
                  f"[{event.phase}] {event.message}", "stdout", "agent")
            if self._speak_progress and event.message:
                _call(p, "speak", event.message)

        elif isinstance(event, ThinkEvent):
            if not event.streaming:
                _call(p, "terminal_output", event.text, "stdout", "think")

        elif isinstance(event, ToolCallEvent):
            _call(p, "terminal_output",
                  f"⚙ {event.name}({_fmt_params(event.params)})",
                  "stdout", "agent")
            _call(p, "creation_event", "⚙", f"Running {event.name}", "")

        elif isinstance(event, ToolResultEvent):
            icon = "✅" if event.ok else "❌"
            _call(p, "terminal_output",
                  f"{icon} {event.name}: {event.result[:200]}",
                  "stdout", "agent")

        elif isinstance(event, FileWriteEvent):
            _call(p, "terminal_output",
                  f"📄 wrote {event.path} ({event.size} bytes)",
                  "stdout", "agent")
            _call(p, "creation_event", "📄", f"Wrote {event.path}", "")

        elif isinstance(event, ShellEvent):
            icon = "✅" if event.exit_code == 0 else "❌"
            _call(p, "terminal_output",
                  f"{icon} $ {event.command}", "stdout", "agent")
            if event.stdout:
                for line in event.stdout.splitlines()[:10]:
                    _call(p, "terminal_output", f"  {line}", "stdout", "shell")
            if event.stderr and event.exit_code != 0:
                for line in event.stderr.splitlines()[:5]:
                    _call(p, "terminal_output", f"  ! {line}", "stderr", "shell")

        elif isinstance(event, ErrorEvent):
            _call(p, "terminal_output",
                  f"⚠ {event.message}", "stderr", "agent")
            if event.recoverable:
                _call(p, "creation_event", "⚠", "Recovering…", "")

        elif isinstance(event, CheckpointEvent):
            label = f"Checkpoint {event.action}: {event.checkpoint_id[:8]}"
            if event.label:
                label += f" — {event.label}"
            _call(p, "terminal_output", f"🔖 {label}", "stdout", "agent")

        elif isinstance(event, DoneEvent):
            if event.ok:
                _call(p, "terminal_output",
                      f"✅ Done — {event.summary}", "stdout", "agent")
                _call(p, "creation_event", "✅", event.summary or "Build complete", "")
                if self._speak_done:
                    _call(p, "speak",
                          event.summary or "Build complete, sir.")
            else:
                summary = event.summary or "Build failed."
                _call(p, "terminal_output", f"❌ {summary}", "stderr", "agent")
                _call(p, "creation_event", "❌", summary, "")
                if self._speak_done:
                    _call(p, "speak", summary)
            # auto-detach so we don't hold a reference after the job ends
            self.detach()


def _fmt_params(params: dict) -> str:
    """Compact single-line representation of tool params for terminal display."""
    if not params:
        return ""
    parts = []
    for k, v in list(params.items())[:4]:
        sv = str(v)
        if len(sv) > 40:
            sv = sv[:37] + "…"
        parts.append(f"{k}={sv!r}")
    suffix = ", …" if len(params) > 4 else ""
    return ", ".join(parts) + suffix
