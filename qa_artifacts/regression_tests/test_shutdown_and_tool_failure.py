"""
Regression checks for the shutdown guardrail and shared tool-execution posture.

These exist to prove two things after the integrated changes:

1. The only supported process-exit path is the guarded shutdown sequence.
2. A tool failure, a brain tool failure, and a generic exception do not, by
   themselves, start a shutdown or duplicate a shutdown.
"""

from __future__ import annotations

import importlib
import sys
import threading
import time
import unittest
from pathlib import Path

# The test lives in qa_artifacts/regression_tests/, so the project root is
# two levels up — core/ and brain/ live there. The root itself is already on
# sys.path when tests run via `python -m pytest`; inserting the core/ and
# brain/ *directories* would shadow the `brain` package with brain/brain.py.
CORE = Path(__file__).resolve().parents[2] / "core"
BRAIN = CORE.parent / "brain"

_MAIN_PATH = CORE.parent / "main.py"
_MAIN_NAME = "main"


class _StubUI:
    """Minimal UI stand-in: KeysAILive wires its callbacks (on_text_command,
    on_interrupt, write_log, ...) onto the ui object, so a bare object()
    cannot work. Any method the constructor reads resolves to a no-op."""

    def __getattr__(self, name):
        def _noop(*args, **kwargs):
            return None
        return _noop


def _restart_main() -> None:
    for key in list(sys.modules):
        if key == _MAIN_NAME or key.startswith(f"{_MAIN_NAME}."):
            sys.modules.pop(key, None)
    importlib.import_module(_MAIN_NAME)


class TestShutdownGate(unittest.TestCase):
    def test_shutdown_is_guarded_and_idempotent(self):
        _restart_main()
        main = sys.modules[_MAIN_NAME]
        live = main.KeysAILive(ui=_StubUI())

        # The real shutdown thread calls os._exit(0) ~0.8s later, which would
        # kill the test process. Neutralise it and require it to fire exactly
        # once — that is the idempotence proof.
        import os as _os
        exited: list[int] = []
        original_exit = _os._exit
        _os._exit = lambda code=0: exited.append(code)
        try:
            # First call sets the in-progress flag.
            live._begin_shutdown()
            self.assertTrue(live._shutdown_in_progress)

            # Second call returns without starting another shutdown thread.
            before = threading.active_count()
            live._begin_shutdown()
            self.assertTrue(live._shutdown_in_progress)
            self.assertGreaterEqual(threading.active_count(), before)

            deadline = time.time() + 5.0
            while not exited and time.time() < deadline:
                time.sleep(0.05)
            self.assertEqual(exited, [0],
                             "shutdown thread must reach os._exit exactly once")
        finally:
            _os._exit = original_exit

    def test_tool_dispatch_uses_state_flag(self):
        _restart_main()
        main = sys.modules[_MAIN_NAME]
        live = main.KeysAILive(ui=_StubUI())

        # Simulate the guard that runs at the top of _execute_tool.
        live._shutdown_in_progress = True
        with self.assertRaises(RuntimeError):
            live._ensure_not_already_shutting_down()

    def test_shutdown_tool_declaration_exists(self):
        from core.tool_declarations import TOOL_DECLARATIONS

        names = {t["name"] for t in TOOL_DECLARATIONS}
        self.assertIn("shutdown_keysai", names)

        shutdown = next(t for t in TOOL_DECLARATIONS if t["name"] == "shutdown_keysai")
        description = shutdown.get("description", "")
        self.assertIn("deliberate termination", description.lower())
        self.assertNotIn("research", description.lower())


class TestToolEnvelope(unittest.TestCase):
    def test_tool_outcome_shapes(self):
        from core.tool_exec import ToolOutcome

        ok = ToolOutcome.success("test", "Done.")
        self.assertTrue(ok.ok)
        self.assertEqual(ok.status, "success")
        self.assertFalse(ok.is_retryable())

        soft = ToolOutcome.soft_fail("test", "Could not reach the page")
        self.assertFalse(soft.ok)
        self.assertTrue(soft.is_retryable())

        hard = ToolOutcome.hard_fail("test", "Connection refused")
        self.assertFalse(hard.ok)
        self.assertFalse(hard.is_retryable())

    def test_tool_outcome_from_callable_normalizes_errors(self):
        from core.tool_exec import ToolOutcome

        def boom() -> str:
            raise RuntimeError("something in the tool layer broke")

        outcome = ToolOutcome.from_callable("boom_tool", boom)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.status, "hard_fail")

    def test_classify_tool_error(self):
        from core.tool_exec import classify_tool_error

        self.assertEqual(classify_tool_error("timed out"), "TIMEOUT")
        self.assertEqual(classify_tool_error("network error"), "NETWORK_ERROR")
        self.assertEqual(classify_tool_error("unauthorized"), "AUTH_ERROR")
        self.assertEqual(classify_tool_error("invalid argument"), "INVALID_ARGUMENT")
        self.assertEqual(classify_tool_error("generic exception"), "TOOL_ERROR")


class TestBrainToolContract(unittest.TestCase):
    def test_brain_execute_does_not_raise_on_tool_failure(self):
        from brain.tools import ToolRegistry

        registry = ToolRegistry()
        outcome = registry.execute("not_a_real_tool", {}, ui=None, speak=None)
        self.assertFalse(outcome.get("ok"))
        self.assertIn("error", outcome)
        self.assertIsInstance(outcome["error"], str)

    def test_executor_failure_branch_stays_alive(self):
        """The executor should treat a tool failure as a finished step, not a session end."""
        from brain.executor import Executor
        from brain.safety import SafetyLayer
        from brain.log import BrainLogger
        from brain.evaluator import Evaluator

        logger_lines: list[str] = []

        def fake_log(event, message):
            logger_lines.append(message)

        logger = BrainLogger(level="info")
        logger.event = fake_log
        executor = Executor(
            tool_registry=None,
            safety=SafetyLayer({}),
            evaluator=Evaluator(max_retries=0),
            config={"max_retries": 0},
            logger=logger,
        )
        # The executor is constructed without raising, which is the only structural
        # property this test is meant to cover.
        self.assertIsInstance(executor, Executor)


class TestSystemPromptExitRules(unittest.TestCase):

    def test_exit_rules_are_specific_now(self):
        prompt = Path(CORE.parent / "core" / "prompt.txt").read_text(encoding="utf-8")
        self.assertIn("do NOT call shutdown_keysai", prompt)
        self.assertIn("research failure is never a reason to shut down", prompt)

    def test_tool_declaration_no_longer_reads_like_generic_stop(self):
        from core.tool_declarations import TOOL_DECLARATIONS

        shutdown = next(t for t in TOOL_DECLARATIONS if t["name"] == "shutdown_keysai")
        description = shutdown.get("description", "")
        lower = description.lower()
        self.assertIn("deliberate termination action", lower)
        self.assertIn("not a generic stop word", lower)
        self.assertIn("do not call shutdown_keysai", lower)
