"""Regression tests for core.crown_jobs (background builds, progress, cancel).

Run:  python -m unittest qa_artifacts.regression_tests.test_crown_jobs -v
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from core import crown_jobs  # noqa: E402


class JobManagerTest(unittest.TestCase):
    def setUp(self):
        self.mgr = crown_jobs.JobManager()

    def _wait(self, job, timeout=5.0):
        job.thread.join(timeout)
        self.assertFalse(job.thread.is_alive(), "job thread did not finish")

    def test_job_reports_progress_then_done(self):
        def target(job):
            for i, phase in enumerate(("planning", "writing", "verifying")):
                job.update(phase=phase, progress=0.2 + 0.25 * i, log=f"{phase} step")
                time.sleep(0.02)
            return {"ok": True, "path": "out/index.html", "bytes": 4200,
                    "plan": {"sections": [{"heading": "Work"}]}}

        job = self.mgr.start("Build portfolio", target, kind="site", brief="portfolio")
        self.assertTrue(job.active)
        self._wait(job)
        self.assertEqual(job.status, "done")
        self.assertAlmostEqual(job.progress, 1.0)
        line = job.status_line()
        self.assertIn("done", line)
        self.assertIn("4200", line)
        text = self.mgr.status_text(verbose=True)
        self.assertIn("Work", text)
        self.assertIn("out/index.html", text)

    def test_failure_is_reported_with_reason(self):
        def target(job):
            raise RuntimeError("model unreachable")

        job = self.mgr.start("Build site", target, kind="site")
        self._wait(job)
        self.assertEqual(job.status, "failed")
        self.assertIn("model unreachable", job.status_line())

    def test_cancel_sets_flag_and_marks_cancelled(self):
        released = threading.Event()

        def target(job):
            while not job.cancelled:
                time.sleep(0.02)
            return {"ok": False, "error": "cancelled"}

        job = self.mgr.start("Long build", target, kind="code")
        time.sleep(0.05)
        msg = self.mgr.cancel(job.id)
        self.assertIn("Stopping", msg)
        self._wait(job)
        self.assertEqual(job.status, "cancelled")
        self.assertIn("cancelled", job.status_line())
        released.set()

    def test_status_text_when_idle(self):
        self.assertEqual(self.mgr.status_text(), "Nothing is building right now.")

    def test_get_prefers_active_job(self):
        quick = self.mgr.start("quick", lambda job: {"ok": True})
        self._wait(quick)
        slow = self.mgr.start("slow", lambda job: (time.sleep(0.2), {"ok": True})[1])
        self.assertEqual(self.mgr.get().id, slow.id)
        self._wait(slow)

    def test_eta_is_none_until_progress_exists(self):
        def target(job):
            time.sleep(0.05)
            return {"ok": True}

        job = self.mgr.start("x", target)
        self.assertIsNone(job.eta)
        self._wait(job)


if __name__ == "__main__":
    unittest.main()
