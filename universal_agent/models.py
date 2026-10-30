"""Task state for the Universal Project Agent.

A task is a plain dict with a stable id and an explicit status, persisted as
one JSON file per task. That keeps it inspectable, resumable after a restart
and independent of the chat transcript — the failure mode this exists to avoid
is "the last model message is the only record of what was done".

Status transitions are validated. A model claiming success cannot move a task
to COMPLETED on its own: only the service does that, and only after the
artifact validators passed.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from enum import Enum
from pathlib import Path

from universal_agent import security


class Status(str, Enum):
    INTAKE = "INTAKE"
    PLANNING = "PLANNING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    VALIDATING = "VALIDATING"
    REPAIRING = "REPAIRING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL = {Status.COMPLETED, Status.FAILED, Status.CANCELLED}

TRANSITIONS: dict[Status, set[Status]] = {
    Status.INTAKE: {Status.WAITING_FOR_USER, Status.READY, Status.PLANNING,
                    Status.FAILED, Status.CANCELLED},
    Status.WAITING_FOR_USER: {Status.PLANNING, Status.READY, Status.FAILED,
                              Status.CANCELLED},
    Status.PLANNING: {Status.READY, Status.RUNNING, Status.FAILED,
                      Status.CANCELLED, Status.WAITING_FOR_USER},
    Status.READY: {Status.RUNNING, Status.PLANNING, Status.CANCELLED,
                   Status.FAILED, Status.WAITING_FOR_USER},
    Status.RUNNING: {Status.VALIDATING, Status.WAITING_FOR_APPROVAL,
                     Status.REPAIRING, Status.COMPLETED, Status.FAILED,
                     Status.CANCELLED, Status.READY},
    Status.WAITING_FOR_APPROVAL: {Status.RUNNING, Status.VALIDATING,
                                  Status.CANCELLED, Status.FAILED},
    Status.VALIDATING: {Status.COMPLETED, Status.REPAIRING, Status.FAILED,
                        Status.CANCELLED},
    Status.REPAIRING: {Status.RUNNING, Status.VALIDATING, Status.COMPLETED,
                       Status.FAILED, Status.CANCELLED},
    Status.COMPLETED: set(),
    Status.FAILED: {Status.READY, Status.CANCELLED},
    Status.CANCELLED: set(),
}


class StateError(RuntimeError):
    pass


def can_transition(old: str, new: str) -> bool:
    try:
        return Status(new) in TRANSITIONS[Status(old)]
    except Exception:
        return False


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


TASKS_DIR = _base_dir() / "config" / "universal_agent" / "tasks"
AUDIT_PATH = _base_dir() / "config" / "universal_agent" / "audit.jsonl"
MAX_EVENTS = 300


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def new_task(request: str, intent: str, workspace: str = "",
             task_id: str | None = None) -> dict:
    return {
        "id": task_id or uuid.uuid4().hex[:12],
        "request": str(request or "").strip(),
        "created_at": _now(),
        "updated_at": _now(),
        "status": Status.INTAKE.value,
        "intent": intent,
        "workspace": str(workspace or ""),
        "questions": [],
        "answers": {},
        "assumptions": [],
        "brief": {},
        "plan": [],
        "current_step": 0,
        "artifacts": [],
        "evidence": [],
        "events": [],
        "approval": None,
        "error": "",
        "warnings": [],
        "attempts": {},
        "result": {},
    }


def add_event(task: dict, kind: str, text: str, **extra) -> dict:
    event = {"ts": _now(), "type": str(kind), "text": security.redact_secrets(text)[:1000]}
    event.update(extra)
    task.setdefault("events", []).append(event)
    task["events"] = task["events"][-MAX_EVENTS:]
    task["updated_at"] = event["ts"]
    return event


def set_status(task: dict, status: str | Status, reason: str = "") -> None:
    new = status.value if isinstance(status, Status) else str(status)
    old = str(task.get("status"))
    if new == old:
        return
    if not can_transition(old, new):
        raise StateError(f"Illegal task transition {old} → {new}")
    task["status"] = new
    add_event(task, "status", f"{old} → {new}" + (f" ({reason})" if reason else ""))


# ── persistence ────────────────────────────────────────────────────────────
_LOCK = threading.RLock()


def _path(task_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(task_id))[:40]
    if not safe:
        raise StateError("Invalid task id")
    return TASKS_DIR / f"{safe}.json"


def save(task: dict) -> dict:
    with _LOCK:
        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        path = _path(task["id"])
        tmp = path.with_name(path.name + f".tmp{os.getpid()}")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(task, fh, indent=2, ensure_ascii=False)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except Exception:
                    pass
            os.replace(tmp, path)
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
    return task


def load(task_id: str) -> dict | None:
    with _LOCK:
        path = _path(task_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except Exception:
            return None
    return data if isinstance(data, dict) else None


def delete(task_id: str) -> bool:
    with _LOCK:
        try:
            _path(task_id).unlink()
            return True
        except FileNotFoundError:
            return False


def list_tasks(limit: int = 50) -> list[dict]:
    with _LOCK:
        if not TASKS_DIR.is_dir():
            return []
        records = []
        for path in TASKS_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("id"):
                    records.append(data)
            except Exception:
                continue
    records.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    return records[:max(1, int(limit))]


def audit(entry: dict) -> None:
    """Append an audit record. Failure is never fatal to a task."""
    with _LOCK:
        try:
            AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(AUDIT_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass


def read_audit(limit: int = 200) -> list[dict]:
    try:
        lines = AUDIT_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
    except Exception:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def recoverable(task: dict) -> bool:
    """A task that was mid-flight when the process died can be resumed."""
    return str(task.get("status")) in {
        Status.RUNNING.value, Status.PLANNING.value,
        Status.VALIDATING.value, Status.REPAIRING.value,
        Status.WAITING_FOR_APPROVAL.value, Status.READY.value,
    }


__all__ = [
    "Status", "TERMINAL", "TRANSITIONS", "StateError", "can_transition",
    "new_task", "add_event", "set_status", "save", "load", "delete",
    "list_tasks", "audit", "read_audit", "recoverable", "TASKS_DIR",
    "AUDIT_PATH",
]
