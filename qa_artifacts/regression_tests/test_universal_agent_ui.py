"""Offscreen UI tests for the Project Agent overlay.

The overlay is driven the way a user drives it: type a request, press START,
wait on the poll timer, then check the pill, plan, artifact list and question
form. Workers are deterministic fakes so the test is about the interface, not
about a model or a browser.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from universal_agent import models  # noqa: E402
from universal_agent.service import ProjectAgentService  # noqa: E402
from universal_agent.studio_ui import ProjectAgentPanel  # noqa: E402


def _report(ctx):
    p = ctx.write_text("report.md", "# Report\n\n" + "Cited evidence. [1]\n" * 4)
    return {"ok": True, "summary": "research done",
            "artifacts": [ctx.artifact(p, "markdown", "report")],
            "evidence": [], "warnings": [], "error": "", "notes": []}


class TestProjectAgentPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ua_ui_"))
        self._patches = [
            mock.patch.object(models, "TASKS_DIR", self.tmp / "tasks"),
            mock.patch.object(models, "AUDIT_PATH", self.tmp / "audit.jsonl"),
        ]
        for p in self._patches:
            p.start()
        self.svc = ProjectAgentService(executors={"research": _report},
                                       use_model_planner=False,
                                       workspace_root=self.tmp / "ws")
        self.overlay = ProjectAgentPanel(service=self.svc)
        self.overlay.resize(1200, 720)
        self.overlay.show()

    def tearDown(self):
        self.overlay.shutdown()
        self.overlay.close()
        self.app.processEvents()
        time.sleep(0.15)
        for p in reversed(self._patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pump_until(self, predicate, timeout=20.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def test_start_to_completed_shows_plan_and_artifact(self):
        self.overlay.request.setPlainText("Research local LLM runtimes")
        self.overlay._start()
        self.assertTrue(self.pump_until(
            lambda: self.overlay._task_id
            and "COMPLETED" in self.overlay._pill.text(), timeout=25),
            self.overlay.action_label.text())
        self.assertGreaterEqual(self.overlay.plan_list.count(), 1)
        self.assertGreaterEqual(self.overlay.artifact_list.count(), 1)
        self.assertEqual(self.overlay.progress.value(), 100)
        # The action line states the verified outcome, not the worker's own claim.
        self.assertIn("verified", self.overlay.action_label.text())

    def test_questions_are_rendered_and_submittable(self):
        self.overlay.request.setPlainText("Build a portfolio website")
        self.overlay._start()
        self.assertTrue(self.pump_until(
            lambda: self.overlay._task_id
            and "WAITING FOR USER" in self.overlay._pill.text(), timeout=20),
            self.overlay.action_label.text())
        self.assertGreater(len(self.overlay._answer_widgets), 0)
        self.assertTrue(self.overlay.submit_answers.isEnabled())
        slot, widget = next(iter(self.overlay._answer_widgets.items()))
        if hasattr(widget, "setText"):
            widget.setText("a photographer")
        self.overlay._answer()
        self.assertTrue(self.pump_until(
            lambda: "WAITING FOR USER" not in self.overlay._pill.text(),
            timeout=20), self.overlay.action_label.text())

    def test_failure_is_visible_and_restartable(self):
        def broken(ctx):
            return {"ok": False, "summary": "down", "artifacts": [],
                    "evidence": [], "warnings": [], "error": "backend down",
                    "notes": []}

        self.svc._executors = {"research": broken}
        self.overlay.request.setPlainText("Research x")
        self.overlay._start()
        self.assertTrue(self.pump_until(
            lambda: self.overlay._task_id
            and "FAILED" in self.overlay._pill.text(), timeout=20),
            self.overlay.action_label.text())
        self.assertEqual(self.overlay.progress.value(), 0)
        self.assertTrue(self.overlay.start_btn.isEnabled())
        self.assertIn("backend down", self.overlay.action_label.text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
