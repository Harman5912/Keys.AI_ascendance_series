"""Offscreen UI test for AI Image Studio.

Drives the real overlay against the fake ComfyUI backend: builds the widget,
presses Generate, pumps the Qt event loop while the job runs on its worker
thread, and asserts the preview, progress bar and history list update. This is
the interface half of the generation test — it proves the UI stays responsive
and shows the actual saved file, not that a diffusion model produced it.
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

from core.image_studio import service as service_mod, settings, store  # noqa: E402
from core.image_studio.studio_ui import ImageStudioPanel  # noqa: E402
from qa_artifacts.regression_tests.test_image_studio import FakeComfy  # noqa: E402


class TestStudioOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        # mkdtemp (not TemporaryDirectory): on Windows a just-closed JSON file
        # can still be held for a moment, and a failed cleanup must not turn a
        # passing UI test into an error.
        self.tmp_path = Path(tempfile.mkdtemp(prefix="keysai_imgui_"))
        self.fake = FakeComfy().start()
        self.cfg = {
            **settings.DEFAULTS,
            "comfy_url": self.fake.url,
            "comfy_path": str(self.tmp_path / "ComfyUI"),
            "output_dir": str(self.tmp_path / "out"),
            "model_id": "sd15",
        }
        self._patches = [
            mock.patch.object(settings, "load", lambda: dict(self.cfg)),
            mock.patch.object(settings, "save", lambda patch: {**self.cfg, **patch}),
            mock.patch.object(store, "HISTORY_PATH", self.tmp_path / "history.json"),
        ]
        for p in self._patches:
            p.start()
        self.svc = service_mod.ImageGenerationService()
        self.overlay = ImageStudioPanel(service=self.svc)
        self.overlay.resize(1200, 720)
        self.overlay.show()

    def tearDown(self):
        self.overlay.shutdown()
        self.overlay.close()
        self.fake.stop()
        self.app.processEvents()
        time.sleep(0.2)
        for p in reversed(self._patches):
            p.stop()
        shutil.rmtree(self.tmp_path, ignore_errors=True)

    def _pump(self, seconds: float = 0.2):
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()
            time.sleep(0.02)

    def _pump_until(self, predicate, timeout: float = 20.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def test_overlay_reaches_ready_state(self):
        self.assertTrue(self._pump_until(lambda: self.overlay.model_combo.count() > 0))
        self.assertTrue(self._pump_until(
            lambda: "READY" in self.overlay._state_pill.text()))
        self.assertEqual(self.overlay.model_combo.currentData(), "sd15")

    def test_generate_button_produces_a_visible_image(self):
        self.assertTrue(self._pump_until(lambda: self.overlay.model_combo.count() > 0))
        self._pump_until(lambda: "READY" in self.overlay._state_pill.text())
        self.overlay.prompt.setPlainText("silver knight, red cape")
        self.overlay._generate()
        self.assertTrue(self._pump_until(
            lambda: not self.overlay._active_job
            and "COMPLETED" in self.overlay._state_pill.text(), timeout=25),
            self.overlay.status_label.text())
        self.assertIsNotNone(self.overlay.preview_label.pixmap())
        self.assertFalse(self.overlay.preview_label.pixmap().isNull())
        self.assertEqual(self.overlay.progress.value(), 100)
        self.assertTrue(self.overlay._preview_path)
        self.assertTrue(Path(self.overlay._preview_path).is_file())
        self.assertIn("Saved", self.overlay.status_label.text())
        self.assertTrue(self._pump_until(
            lambda: self.overlay.history_list.count() >= 1))
        self.assertTrue(self.overlay.save_btn.isEnabled())

    def test_generation_failure_never_leaves_a_spinner(self):
        self.assertTrue(self._pump_until(lambda: self.overlay.model_combo.count() > 0))
        self.fake.checkpoints = []
        self.svc.invalidate_health()
        self.overlay.refresh_all(force=True)
        self._pump(0.6)
        self.overlay.prompt.setPlainText("a lighthouse")
        self.overlay._generate()
        self.assertTrue(self._pump_until(
            lambda: not self.overlay._active_job
            and "FAILED" in self.overlay._state_pill.text(), timeout=25),
            self.overlay.status_label.text())
        self.assertEqual(self.overlay.progress.value(), 0)
        self.assertTrue(self.overlay.generate_btn.isEnabled())
        self.assertIn("not installed", self.overlay.status_label.text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
