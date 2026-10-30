"""A build is only done when the workspace's own check agrees.

Regression: a real run wrote sample.txt, test_wordcount.py and README.md, ran
`python wordcount.py sample.txt` twice (both failed — wordcount.py was never
written), and the job still finished as `done` with writes=3. The user was told
a project was built that did not contain its main file.

The rule locked down here: if the last shell command the agent ran exited
non-zero and was never re-run successfully, the build is a failure, however many
files were written before that.

Run: python -m unittest qa_artifacts.regression_tests.test_crown_build_verification -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from actions import crown_code as cc  # noqa: E402
from core import crown_jobs  # noqa: E402


class ScriptedBridge:
    """Emits a fixed event stream, then reports whatever the model claimed."""

    def __init__(self, events, claimed=None, **kwargs):
        self.events = events
        self.claimed = claimed if claimed is not None else {"ok": True, "summary": "built"}
        self.kwargs = kwargs
        self.stopped = 0

    def start(self, task):
        emit = self.kwargs.get("on_event") or (lambda ev: None)
        for ev in self.events:
            emit(ev)
        return True, "started"

    def wait(self, timeout=None):
        return dict(self.claimed)

    def stop(self):
        self.stopped += 1


def run_bridge(events, claimed=None):
    job = crown_jobs.BuildJob(kind="code", brief="build it", workspace="", model="m")
    factory = lambda **kw: ScriptedBridge(events, claimed, **kw)  # noqa: E731
    with mock.patch.object(cc, "CrownBridge", side_effect=factory):
        return job, cc._run_bridge(job, "build it", Path("."), "m", "ollama",
                                   "safe", 30, None, max_iterations=3)


WRITE = {"type": "tool_start", "tool": "write_file", "input": {"path": "app.py"}}
WRITE_OK = {"type": "tool_end", "isError": False, "output": "Created app.py"}
TERM = {"type": "tool_start", "tool": "terminal", "input": {"command": "python app.py"}}
TERM_OK = {"type": "tool_end", "isError": False, "output": "ran"}


class FailingLastCommandTest(unittest.TestCase):
    def test_failing_last_command_is_not_a_done_build(self):
        job, result = run_bridge([
            WRITE, WRITE_OK,
            {"type": "terminal_output", "chunk": "Traceback ...\n", "stream": "stderr"},
            TERM, {"type": "terminal_exit", "exitCode": 1},
            {"type": "tool_end", "isError": True, "output": "can't open file 'app.py'"},
        ])
        self.assertFalse(result["ok"], "a failed last command must not be reported as done")
        self.assertIn("failing command", result.get("error", "").lower())
        self.assertIn("unverified", result.get("error", "").lower())

    def test_repaired_command_passes(self):
        _, result = run_bridge([
            WRITE, WRITE_OK,
            TERM, {"type": "terminal_exit", "exitCode": 1},
            {"type": "tool_end", "isError": True, "output": "missing file"},
            WRITE, WRITE_OK,                       # the agent fixes it
            TERM, {"type": "terminal_exit", "exitCode": 0},
            TERM_OK,
        ])
        self.assertTrue(result["ok"], result)

    def test_zero_exit_command_passes(self):
        _, result = run_bridge([WRITE, WRITE_OK, TERM,
                                {"type": "terminal_exit", "exitCode": 0}, TERM_OK])
        self.assertTrue(result["ok"], result)

    def test_run_without_commands_is_unaffected(self):
        _, result = run_bridge([WRITE, WRITE_OK])
        self.assertTrue(result["ok"], result)


class ExistingGuardsStillHold(unittest.TestCase):
    def test_no_writes_is_still_a_failure_even_with_a_passing_command(self):
        _, result = run_bridge([
            {"type": "tool_start", "tool": "read_file", "input": {"path": "x"}},
            {"type": "tool_end", "isError": False, "output": "contents"},
            TERM, {"type": "terminal_exit", "exitCode": 0}, TERM_OK,
        ])
        self.assertFalse(result["ok"])
        self.assertIn("without writing any file", result.get("error", ""))

    def test_model_claiming_failure_is_respected(self):
        _, result = run_bridge([WRITE, WRITE_OK],
                               claimed={"ok": False, "summary": "gave up"})
        self.assertFalse(result["ok"])
        self.assertIn("gave up", result.get("error", ""))


if __name__ == "__main__":
    unittest.main()
