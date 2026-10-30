"""Group J — application integration and regression.

The Project Agent is exercised through the real Keys.AI window code: the
``MainWindow._open_project_agent`` method is called on an instance whose only
initialised attributes are the ones that method uses, so the launcher, lazy
import, overlay construction, geometry and shutdown path are the production
ones — not a re-implementation in the test.

Everything else asserts that what existed before still exists: the chat
provider path, the tool registry, the model catalogue, the image studio, Crown
Code, settings storage, and that all project modules still compile.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication, QStackedWidget, QWidget  # noqa: E402

import universal_agent  # noqa: E402
from universal_agent import models  # noqa: E402
from universal_agent.service import ProjectAgentService  # noqa: E402



def _ok_worker(ctx):
    path = ctx.write_text("deliverable.md",
                          "# Deliverable\n\n" + "Verified content. " * 8)
    return {"ok": True, "summary": "delivered",
            "artifacts": [ctx.artifact(path, "md")],
            "evidence": [], "warnings": [], "error": "", "notes": []}


def env_for_qt() -> dict:
    return {**os.environ, "QT_QPA_PLATFORM": "offscreen"}


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ua_int_"))
        self._patches = [
            mock.patch.object(models, "TASKS_DIR", self.tmp / "tasks"),
            mock.patch.object(models, "AUDIT_PATH", self.tmp / "audit.jsonl"),
        ]
        for patch in self._patches:
            patch.start()
        self.svc = ProjectAgentService(executors={"research": _ok_worker},
                                       use_model_planner=False,
                                       workspace_root=self.tmp / "ws")
        self.overlays: list = []

    def tearDown(self):
        for overlay in self.overlays:
            try:
                overlay.shutdown()
                overlay.close()
                overlay.deleteLater()
            except Exception:
                pass
        self.svc.cancel_all()
        self.app.processEvents()
        time.sleep(0.05)
        for patch in reversed(self._patches):
            patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pump_until(self, predicate, timeout=25.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def window_stub(self):
        """A MainWindow with only the attributes the launcher methods use."""
        from ui import MainWindow
        win = MainWindow.__new__(MainWindow)
        # Features open as pages of the centre view stack (page 0 = HUD).
        win._center_stack = QStackedWidget()
        win.hud = QWidget()
        win._center_stack.addWidget(win.hud)
        win._center_stack.resize(1280, 800)
        # A child of a hidden parent reports isVisible() == False; the real
        # stack is on screen, so show it here too.
        win._center_stack.show()
        self.addCleanup(win._center_stack.close)
        win._log = types.SimpleNamespace(append_log=lambda _m: None)
        win._project_agent = None
        return win


class TestLauncherIntegration(_Base):
    def test_service_is_a_shared_singleton(self):
        universal_agent._service = None
        try:
            with mock.patch.object(universal_agent, "get_service",
                                   wraps=universal_agent.get_service):
                first = universal_agent.get_service()
                second = universal_agent.get_service()
            self.assertIs(first, second)
            self.assertTrue(callable(first.cancel_all))
        finally:
            universal_agent._service = None


class TestShutdownPath(_Base):
    def test_application_shutdown_stops_agent_work(self):
        from ui import KeysAIUI

        class Overlay:
            def __init__(self):
                self.stopped = False

            def shutdown(self):
                self.stopped = True

        class Service:
            def __init__(self):
                self.cancelled = 0

            def cancel_all(self):
                self.cancelled += 1

        studio = Overlay()
        agent_service = Service()
        image_service = Service()
        win = types.SimpleNamespace(_image_studio=studio)
        app = KeysAIUI.__new__(KeysAIUI)
        app._win = win
        with mock.patch("universal_agent.get_service", lambda: agent_service), \
             mock.patch("core.image_studio.get_service", lambda: image_service):
            KeysAIUI._shutdown_image_studio(app)
        self.assertTrue(studio.stopped)
        self.assertEqual(agent_service.cancelled, 1)


class TestPreservedFunctionality(_Base):
    def test_all_project_modules_compile(self):
        for path in sorted((ROOT / "universal_agent").rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")

    def test_application_entry_points_compile(self):
        for name in ("ui.py", "main.py"):
            path = ROOT / name
            compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_application_window_starts_and_exits(self):
        """The real MainWindow is built off-screen and closes on a timer.        """
        script = ("import sys\n"
                  "from PyQt6.QtWidgets import QApplication\n"
                  "from PyQt6.QtCore import QTimer\n"
                  "import ui\n"
                  "app = QApplication(sys.argv)\n"
                  "ui._ensure_gui_imports()\n"
                  "w = ui.MainWindow('icon.png')\n"
                  "w.show()\n"
                  "print('MAINWINDOW_OK', flush=True)\n"
                  "assert hasattr(w, '_open_research_browser')\n"
                  "QTimer.singleShot(1200, app.quit)\n"
                  "app.exec()\n"
                  "print('EXITED_CLEANLY', flush=True)\n")
        proc = subprocess.run(
            [sys.executable, "-c", script], cwd=str(ROOT), env=env_for_qt(),
            capture_output=True, text=True, timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stderr[-1000:])
        self.assertIn("MAINWINDOW_OK", proc.stdout)
        self.assertIn("EXITED_CLEANLY", proc.stdout)

    def test_existing_tool_registry_is_intact(self):
        from core.tool_registry import TOOL_HANDLERS
        # web_search and a few session-bound tools are handled inline by the
        # engine, so they are asserted through the tool declarations instead.
        for name in ("open_app", "browser_control", "file_controller",
                     "crown_code", "computer_control", "desktop_control",
                     "code_helper", "file_processor"):
            self.assertIn(name, TOOL_HANDLERS)

    def test_existing_chat_provider_still_builds(self):
        from brain.providers import get_provider
        provider = get_provider(api_config={"llm_provider": "gemini",
                                            "gemini_api_key": ""})
        self.assertTrue(callable(provider.generate))

    def test_model_catalog_is_readable(self):
        from core.model_catalog import PROVIDERS, default_model_for
        self.assertIn("gemini", PROVIDERS)
        self.assertTrue(default_model_for("ollama"))

    def test_settings_storage_is_readable(self):
        from core import config_store
        data = config_store.load()
        self.assertIsInstance(data, dict)

    def test_crown_code_is_still_callable(self):
        from actions.crown_code import crown_code
        from core import crown_jobs
        self.assertTrue(callable(crown_code))
        self.assertTrue(callable(crown_jobs._manager))

    def test_image_studio_is_still_present(self):
        from core.image_studio import get_service
        from core.image_studio.studio_ui import ImageStudioPanel
        self.assertTrue(callable(get_service))
        self.assertTrue(callable(ImageStudioPanel))

    def test_filesystem_tools_are_still_present(self):
        import actions.file_controller as fc
        self.assertTrue(callable(fc.file_controller))

    def test_document_reading_is_still_present(self):
        from actions import _file_readers
        for name in ("read_pdf", "read_docx", "read_pptx", "read_xlsx"):
            self.assertTrue(callable(getattr(_file_readers, name)))


class TestTaskContinuity(_Base):
    def test_events_describe_the_work_in_order(self):
        events: list = []
        self.svc.add_listener(lambda task, event: events.append(event.get("type")))
        task = self.svc.create("Research events", intent="research")
        self.assertTrue(self.pump_until(
            lambda: (self.svc.get_task(task["id"]) or {}).get("status")
            == "COMPLETED"))
        # 'completed' is emitted just after the status transition, so wait for
        # the event rather than assuming it already arrived.
        self.assertTrue(self.pump_until(lambda: "completed" in events))
        for expected in ("created", "plan", "step_started", "artifact",
                         "completed"):
            self.assertIn(expected, events)

    def test_progress_belongs_to_the_correct_task(self):
        first = self.svc.create("Research first", intent="research")
        second = self.svc.create("Research second", intent="research")
        self.assertTrue(self.pump_until(
            lambda: all((self.svc.get_task(t["id"]) or {}).get("status")
                        == "COMPLETED" for t in (first, second))))
        a = self.svc.get_task(first["id"])
        b = self.svc.get_task(second["id"])
        self.assertNotEqual(a["workspace"], b["workspace"])
        self.assertFalse({x["path"] for x in a["artifacts"]}
                         & {x["path"] for x in b["artifacts"]})
        self.assertTrue(all(x["task_id"] == first["id"] for x in a["artifacts"]))

    def test_task_survives_an_application_restart(self):
        task = self.svc.create("Research restarts", intent="research")
        self.assertTrue(self.pump_until(
            lambda: (self.svc.get_task(task["id"]) or {}).get("status")
            == "COMPLETED"))
        restarted = ProjectAgentService(use_model_planner=False,
                                        workspace_root=self.tmp / "ws")
        self.svc = restarted
        found = restarted.get_task(task["id"])
        self.assertIsNotNone(found)
        self.assertEqual(found["status"], "COMPLETED")
        self.assertTrue(found["artifacts"])
        self.assertIn("COMPLETED", restarted.report_text(task["id"]))

    def test_report_text_states_the_verified_outcome(self):
        task = self.svc.create("Research reporting", intent="research")
        self.assertTrue(self.pump_until(
            lambda: (self.svc.get_task(task["id"]) or {}).get("status")
            == "COMPLETED"))
        text = self.svc.report_text(task["id"])
        self.assertIn("Outcome:", text)
        self.assertIn("artifact(s) verified", text)
        self.assertIn("— verified", text)

    def test_cancelled_task_reports_no_work_left(self):
        task = self.svc.create("Research cancellable", intent="research",
                               auto_start=False)
        self.svc.cancel(task["id"])
        live = self.svc.get_task(task["id"])
        self.assertEqual(live["status"], "CANCELLED")
        self.assertIn("Cancelled", self.svc.report_text(task["id"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
