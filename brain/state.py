"""
Task state model (spec §10, §28).

Every active task has a TaskState: user request, intent, plan, current step,
tool results, errors and status — so tasks can pause, resume and be inspected.

A plan is an ordered list of step dicts:
    {
        "id": "1",
        "description": "...",
        "tool": "open_app",
        "arguments": {"app_name": "Chrome"},
        "status": "PENDING",          # PENDING|RUNNING|SUCCESS|FAILED|SKIPPED|WAITING_FOR_USER
        "result": None,
        "error": None,
    }
"""

from __future__ import annotations

import time
import uuid
from enum import Enum


class StepStatus(str, Enum):
    PENDING          = "PENDING"
    RUNNING          = "RUNNING"
    SUCCESS          = "SUCCESS"
    FAILED           = "FAILED"
    SKIPPED          = "SKIPPED"
    WAITING_FOR_USER = "WAITING_FOR_USER"


class BrainStatus(str, Enum):
    IDLE            = "IDLE"
    UNDERSTANDING   = "UNDERSTANDING"
    PLANNING        = "PLANNING"
    EXECUTING       = "EXECUTING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    COMPLETED       = "COMPLETED"
    FAILED          = "FAILED"
    STOPPED         = "STOPPED"
    PAUSED          = "PAUSED"


def new_step(description: str, tool: str, arguments: dict | None = None,
             step_id: str | None = None) -> dict:
    return {
        "id": step_id or str(uuid.uuid4())[:8],
        "description": description or "",
        "tool": tool,
        "arguments": arguments or {},
        "status": StepStatus.PENDING.value,
        "result": None,
        "error": None,
        "attempts": 0,
    }


def new_plan(user_request: str, intent: str = "", summary: str = "") -> dict:
    return {
        "user_request": user_request,
        "intent": intent,
        "summary": summary or "",
        "steps": [],
        "created_at": time.time(),
    }


class TaskState:
    def __init__(self, user_request: str, intent: str = "",
                 plan: dict | None = None):
        self.task_id        = uuid.uuid4().hex[:12]
        self.user_request   = user_request
        self.intent         = intent
        self.plan           = plan or new_plan(user_request, intent)
        self.current_index  = 0
        self.observations   = []          # list[str]
        self.tool_results   = []          # list[dict]
        self.errors         = []          # list[dict]
        self.status         = "PENDING"   # PENDING|RUNNING|WAITING_FOR_USER|...
        self.created_at     = time.time()
        self.updated_at     = self.created_at

    # ── step access ──────────────────────────────────────────────────────
    def steps(self) -> list[dict]:
        return self.plan.get("steps", [])

    def step(self, index: int | None = None) -> dict | None:
        steps = self.steps()
        if not steps:
            return None
        idx = self.current_index if index is None else index
        if 0 <= idx < len(steps):
            return steps[idx]
        return None

    def remaining(self) -> list[dict]:
        return self.steps()[self.current_index:]

    def advance(self) -> None:
        self.current_index += 1
        self.updated_at = time.time()

    def mark_current(self, status: str, result=None, error=None) -> None:
        step = self.step()
        if step is None:
            return
        step["status"] = status
        if result is not None:
            step["result"] = result
            self.tool_results.append({
                "step_id": step["id"], "tool": step.get("tool"),
                "result": result,
            })
        if error is not None:
            step["error"] = error
            self.errors.append({
                "step_id": step["id"], "tool": step.get("tool"), "error": error,
            })
        self.updated_at = time.time()

    def add_observation(self, text: str) -> None:
        self.observations.append(text)
        self.updated_at = time.time()

    # ── serialization ────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "user_request": self.user_request,
            "intent": self.intent,
            "plan": self.plan,
            "current_index": self.current_index,
            "observations": self.observations,
            "tool_results": self.tool_results,
            "errors": self.errors,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskState":
        state = cls(data.get("user_request", ""), data.get("intent", ""),
                    data.get("plan"))
        state.task_id       = data.get("task_id", state.task_id)
        state.current_index = data.get("current_index", 0)
        state.observations  = data.get("observations", [])
        state.tool_results  = data.get("tool_results", [])
        state.errors        = data.get("errors", [])
        state.status        = data.get("status", state.status)
        return state
