"""
Plan executor (spec §10, §16, §18, §29).

Executes one step at a time with the loop:
    PLAN → ACT → OBSERVE → EVALUATE → (SUCCESS → next | FAIL → bounded retry
    | needs-confirmation → WAITING_FOR_USER)

Honours stop() between steps (never infinite loops), respects the SafetyLayer,
and reports WAITING_FOR_USER for actions that need the user's confirmation.
"""

from __future__ import annotations

import threading

from brain.log import (EVT_EVALUATION, EVT_RETRY, EVT_TOOL_EXECUTED,
                       EVT_TOOL_SELECTED, EVT_WAIT_USER)
from brain.safety import Decision, SafetyLevel
from brain.state import StepStatus


class Executor:
    def __init__(self, tool_registry, safety: "SafetyLayer",
                 evaluator, config, logger=None):
        self._registry = tool_registry
        self._safety   = safety
        self._evaluator = evaluator
        self._config   = config
        self._logger   = logger
        self._stop     = threading.Event()

    # ── control ──────────────────────────────────────────────────────────
    def stop(self) -> None:
        self._stop.set()

    def reset(self) -> None:
        self._stop.clear()

    def stopped(self) -> bool:
        return self._stop.is_set()

    # ── execution ────────────────────────────────────────────────────────
    def execute_step(self, step: dict, ui=None, speak=None,
                     approved: bool = False) -> dict:
        """
        Run one step; returns the updated step dict.

        approved=True skips the confirmation gate (the user already approved
        this exact step on a previous turn) but never bypasses a BLOCK.
        """
        tool = step.get("tool", "")
        args = step.get("arguments", {})

        if self.stopped():
            step["status"] = StepStatus.SKIPPED.value
            step["error"] = "Execution stopped by user."
            return step

        step["status"] = StepStatus.RUNNING.value
        step["attempts"] = step.get("attempts", 0) + 1
        if self._logger:
            self._logger.event(EVT_TOOL_SELECTED,
                               f"{tool} {args}")

        # ── permission gate ──────────────────────────────────────────────
        decision = self._safety.decision(tool, args, self._config)
        if decision == Decision.BLOCK:
            step["status"] = StepStatus.FAILED.value
            step["error"] = (f"'{tool}' is blocked by the safety layer "
                             "(blocked_tools config).")
            return step
        if decision == Decision.ASK and not approved:
            step["status"] = StepStatus.WAITING_FOR_USER.value
            step["result"] = None
            step["error"] = None
            if self._logger:
                self._logger.event(
                    EVT_WAIT_USER,
                    f"'{tool}' needs your confirmation: {args}")
            return step

        # ── run with bounded retries ─────────────────────────────────────
        max_retries = int(self._config.get("max_retries", 2))
        result = None
        while True:
            result = self._registry.execute(tool, args, ui, speak)
            if self._logger:
                self._logger.event(
                    EVT_TOOL_EXECUTED,
                    f"{tool} → {str(result.get('result'))[:120]}")
            evaluation = self._evaluator.evaluate(result)
            if self._logger:
                self._logger.event(
                    EVT_EVALUATION,
                    f"{tool} = {evaluation.status} ({evaluation.error_type})")
            step["observation"] = {
                "status": evaluation.status,
                "reason": evaluation.reason,
                "error_type": evaluation.error_type,
            }
            if evaluation.is_success():
                step["status"] = StepStatus.SUCCESS.value
                step["result"] = result.get("result")
                break
            # attempts was already incremented for THIS run; retries so far
            # are attempts - 1 (max_retries = number of allowed retries).
            # NEVER retry destructive (DANGEROUS) actions (spec §18).
            retryable = (
                self._evaluator.should_retry(evaluation,
                                             step["attempts"] - 1)
                and self._safety.permission_for(tool, args)
                != SafetyLevel.DANGEROUS)
            if retryable:
                step["attempts"] += 1
                if self._logger:
                    self._logger.event(
                        EVT_RETRY,
                        f"{tool} retrying ({step['attempts']}/{max_retries})")
                continue
            step["status"] = StepStatus.FAILED.value
            step["result"] = result.get("result")
            step["error"] = (evaluation.reason
                             or result.get("error")
                             or str(result.get("result"))[:200])
            if self._logger:
                self._logger.event(
                    EVT_TOOL_EXECUTED,
                    f"{tool} failed — session stays alive")
            break

        return step
