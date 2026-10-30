"""
crown_code/engine/legacy_engine.py — Legacy CrownBridge wrapped in the AgentEngine interface.

This adapter makes the existing CrownBridge (headless.js subprocess) satisfy
the new AgentEngine contract so the action layer can use the same code path
regardless of which engine is active.  No behaviour is changed — it's a thin
shim that translates CrownBridge callbacks into EventBus emissions.
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from crown_code.engine.events import (
    EventBus,
    ProgressEvent,
    ThinkEvent,
    FileWriteEvent,
    ShellEvent,
    ErrorEvent,
    DoneEvent,
    CheckpointEvent,
)
from crown_code.engine.interface import AgentEngine
from crown_code.engine.checkpoints import CheckpointStore


class LegacyEngine(AgentEngine):
    """
    Wraps the original CrownBridge (Node.js headless.js subprocess) in the
    AgentEngine interface.  All the real work still happens in CrownBridge;
    this class:

    1. Translates on_event / on_file_written / on_done callbacks into
       typed EventBus emissions.
    2. Adds checkpoint save/restore via CheckpointStore (shadow-git).
    3. Exposes .status / .result / .cancel() / .join() consistently.
    """

    def __init__(
        self,
        *,
        job_id: str,
        brief: str,
        workspace: Optional[str | Path],
        bus: EventBus,
        config: dict,
    ):
        self._job_id = job_id
        self._brief = brief
        self._workspace = Path(workspace) if workspace else None
        self._bus = bus
        self._config = config

        self._status = "queued"
        self._result: dict = {}
        self._cancel_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # checkpoint support
        self._checkpoints = CheckpointStore(
            workspace=self._workspace,
            job_id=self._job_id,
        )

    # ── AgentEngine ───────────────────────────────────────────────────────────

    @property
    def job_id(self) -> str:
        return self._job_id

    @property
    def brief(self) -> str:
        return self._brief

    @property
    def workspace(self) -> Optional[Path]:
        return self._workspace

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def result(self) -> dict:
        with self._lock:
            return dict(self._result)

    def start(self) -> None:
        with self._lock:
            if self._status != "queued":
                return
            self._status = "running"

        self._thread = threading.Thread(
            target=self._run,
            name=f"legacy-engine-{self._job_id}",
            daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        self._cancel_event.set()

    def join(self, timeout: float = 30.0) -> bool:
        if self._thread is None:
            return True
        self._thread.join(timeout=timeout)
        return not self._thread.is_alive()

    # ── checkpoints ───────────────────────────────────────────────────────────

    def save_checkpoint(self, label: str = "") -> str:
        cp_id = self._checkpoints.save(label=label)
        if cp_id:
            self._bus.emit(CheckpointEvent(
                checkpoint_id=cp_id, action="saved", label=label
            ))
        return cp_id

    def restore_checkpoint(self, checkpoint_id: str) -> bool:
        ok = self._checkpoints.restore(checkpoint_id)
        if ok:
            self._bus.emit(CheckpointEvent(
                checkpoint_id=checkpoint_id, action="restored"
            ))
        return ok

    def list_checkpoints(self) -> list[dict]:
        return self._checkpoints.list()

    # ── internal run ──────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            from core.crown_bridge import CrownBridge, load_config
        except ImportError as exc:
            self._bus.emit(ErrorEvent(message=f"CrownBridge unavailable: {exc}"))
            self._finish(ok=False, summary=str(exc))
            return

        cfg = {**load_config(), **self._config}
        workspace_str = str(self._workspace) if self._workspace else ""

        bridge = CrownBridge(
            brief=self._brief,
            workspace=workspace_str,
            config=cfg,
            cancel_event=self._cancel_event,
        )

        # Wire CrownBridge callbacks → EventBus
        def _on_event(evt: dict) -> None:
            etype = evt.get("type", "")
            if etype == "progress":
                self._bus.emit(ProgressEvent(
                    phase=evt.get("phase", ""),
                    percent=float(evt.get("percent", 0)),
                    message=evt.get("message", ""),
                ))
            elif etype == "think":
                self._bus.emit(ThinkEvent(text=evt.get("text", "")))
            elif etype == "shell":
                self._bus.emit(ShellEvent(
                    command=evt.get("command", ""),
                    exit_code=int(evt.get("exit_code", 0)),
                    stdout=evt.get("stdout", ""),
                    stderr=evt.get("stderr", ""),
                ))
            elif etype == "error":
                self._bus.emit(ErrorEvent(message=evt.get("message", "")))
            elif etype == "file_write":
                self._bus.emit(FileWriteEvent(
                    path=evt.get("path", ""),
                    size=int(evt.get("size", 0)),
                ))

        def _on_done(result: dict) -> None:
            ok = bool(result.get("ok", result.get("success", True)))
            summary = result.get("summary", result.get("message", ""))
            files = result.get("files", [])
            self._finish(ok=ok, summary=summary, files=files, raw=result)

        try:
            bridge.run(on_event=_on_event, on_done=_on_done)
        except Exception as exc:
            if self._cancel_event.is_set():
                self._finish(ok=False, summary="cancelled")
            else:
                self._bus.emit(ErrorEvent(message=str(exc)))
                self._finish(ok=False, summary=str(exc))

    def _finish(
        self,
        *,
        ok: bool,
        summary: str = "",
        files: list[str] | None = None,
        raw: dict | None = None,
    ) -> None:
        with self._lock:
            cancelled = self._cancel_event.is_set()
            if cancelled and ok:
                ok = False
                summary = summary or "cancelled"
            self._status = "done" if ok else ("cancelled" if cancelled else "failed")
            self._result = {
                **(raw or {}),
                "ok": ok,
                "summary": summary,
                "files": files or [],
            }
        self._bus.emit(DoneEvent(ok=ok, summary=summary, files=files or []))
