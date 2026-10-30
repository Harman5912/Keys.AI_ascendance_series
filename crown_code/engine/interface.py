"""
crown_code/engine/interface.py — Abstract AgentEngine contract.

Every engine implementation (legacy CrownBridge wrapper, v2 Python-native
engine, future cloud engine) must satisfy this interface.  The Crown Code
action layer (actions/crown_code.py) only talks to this interface, never to
a concrete engine directly.

This makes swapping engines a one-line change in the factory function at
the bottom of this file.
"""
from __future__ import annotations

import abc
from pathlib import Path
from typing import Optional

from crown_code.engine.events import EventBus


class AgentEngine(abc.ABC):
    """
    Abstract base for a Crown Code build engine.

    Lifecycle
    ---------
    1.  engine = factory(job_id, brief, workspace, bus, config)
    2.  engine.start()          # non-blocking; worker thread emits events
    3.  status = engine.status  # "queued" | "running" | "done" | "failed" | "cancelled"
    4.  engine.cancel()         # signal the worker to stop
    5.  engine.join(timeout)    # optional: wait for the worker to finish
    """

    # ── identity ──────────────────────────────────────────────────────────────

    @property
    @abc.abstractmethod
    def job_id(self) -> str:
        """Unique job identifier (hex string)."""

    @property
    @abc.abstractmethod
    def brief(self) -> str:
        """The original user request."""

    @property
    @abc.abstractmethod
    def workspace(self) -> Optional[Path]:
        """Project directory (may be None until planning resolves it)."""

    # ── lifecycle ─────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def start(self) -> None:
        """
        Launch the agent worker in a background thread.
        Must return immediately.  All progress is emitted via the EventBus.
        """

    @abc.abstractmethod
    def cancel(self) -> None:
        """
        Request cancellation.  The worker should stop at the next safe point
        and emit a DoneEvent(ok=False, summary="cancelled").
        """

    @abc.abstractmethod
    def join(self, timeout: float = 30.0) -> bool:
        """
        Block until the worker finishes or timeout expires.
        Returns True if the worker finished, False if it timed out.
        """

    # ── state ─────────────────────────────────────────────────────────────────

    @property
    @abc.abstractmethod
    def status(self) -> str:
        """One of: queued | running | done | failed | cancelled."""

    @property
    @abc.abstractmethod
    def result(self) -> dict:
        """
        The build result dict.  Keys are engine-dependent but always include:
          "ok"      : bool
          "summary" : str
          "files"   : list[str]
        """

    # ── checkpoints (optional override) ──────────────────────────────────────

    def save_checkpoint(self, label: str = "") -> str:
        """
        Save a snapshot of the current build state.
        Returns a checkpoint_id.  Engines that don't support checkpoints
        return an empty string.
        """
        return ""

    def restore_checkpoint(self, checkpoint_id: str) -> bool:
        """
        Restore a previously saved checkpoint.
        Returns True on success.
        """
        return False

    def list_checkpoints(self) -> list[dict]:
        """
        Return a list of available checkpoints:
          [{"id": str, "label": str, "ts": float}, ...]
        """
        return []


# ── factory ───────────────────────────────────────────────────────────────────

def make_engine(
    job_id: str,
    brief: str,
    workspace: Optional[str | Path],
    bus: EventBus,
    config: dict,
    *,
    engine_type: str = "",
) -> AgentEngine:
    """
    Return the correct AgentEngine implementation based on:
      1. engine_type argument (highest priority)
      2. CROWN_ENGINE env var
      3. config["engine"] key
      4. Default: "legacy"

    This is the ONLY place that knows which concrete class to instantiate.
    """
    import os
    kind = (
        engine_type
        or os.environ.get("CROWN_ENGINE", "")
        or config.get("engine", "")
        or "legacy"
    ).lower().strip()

    if kind == "v2":
        from crown_code.engine.v2_engine import V2Engine
        return V2Engine(job_id=job_id, brief=brief, workspace=workspace,
                        bus=bus, config=config)
    else:
        from crown_code.engine.legacy_engine import LegacyEngine
        return LegacyEngine(job_id=job_id, brief=brief, workspace=workspace,
                            bus=bus, config=config)
