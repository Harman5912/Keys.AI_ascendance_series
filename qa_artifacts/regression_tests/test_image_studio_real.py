"""Live integration tests for AI Image Studio — real ComfyUI, real diffusion.

These are skipped unless a backend is actually available:

    KEYS_IMAGE_STUDIO_LIVE=1 python -m pytest \
        qa_artifacts/regression_tests/test_image_studio_real.py -v

They use the shipped service exactly as the UI does (settings → generate →
poll → fetch → save → history) and assert on the pixels on disk. Nothing is
simulated; when the backend is missing they report SKIP rather than PASS.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from core.image_studio import service as service_mod, settings  # noqa: E402

LIVE = os.environ.get("KEYS_IMAGE_STUDIO_LIVE") == "1"


def _service():
    return service_mod.ImageGenerationService()


def _live_status() -> dict:
    try:
        return _service().backend_status(force=True)
    except Exception:
        return {}


_STATUS = _live_status() if LIVE else {}
_READY = bool(_STATUS.get("reachable"))
_HAS_MODEL = False
if _READY:
    try:
        _HAS_MODEL = any(m.get("installed") for m in _service().list_models())
    except Exception:
        _HAS_MODEL = False

requires_backend = unittest.skipUnless(
    LIVE and _READY, "no live ComfyUI backend (set KEYS_IMAGE_STUDIO_LIVE=1)")
requires_model = unittest.skipUnless(
    LIVE and _READY and _HAS_MODEL, "no installed diffusion checkpoint")


def _wait(svc, job_id: str, timeout: float = 900.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = svc.get_job(job_id) or {}
        if job.get("status") in service_mod.TERMINAL:
            return job
        time.sleep(1.0)
    return svc.get_job(job_id) or {}


class TestLiveBackend(unittest.TestCase):
    """Test A — detection against the real install."""

    @requires_backend
    def test_detects_install_and_gpu(self):
        status = _service().backend_status(force=True)
        self.assertTrue(status["reachable"])
        self.assertTrue(status["installed"])
        self.assertTrue(Path(status["install_path"]).is_dir())
        device = status.get("device") or {}
        self.assertIn("vram_total_gb", device)
        print(f"\nbackend {status.get('comfy_version')} · {device.get('name')} "
              f"· {device.get('vram_total_gb')} GB")

    @requires_backend
    def test_models_report_real_files(self):
        models = _service().list_models(refresh=True)
        self.assertTrue(models)
        sd = next(m for m in models if m["id"] == "sd15")
        self.assertTrue(sd["files"][0]["present"], sd["files"])


class TestLiveGeneration(unittest.TestCase):
    """Test E — a real 512×512 image from a real checkpoint."""

    @requires_model
    def test_generates_and_saves_a_real_image(self):
        svc = _service()
        out_dir = svc.output_dir()
        before = {p.name for p in out_dir.glob("*")} if out_dir.is_dir() else set()
        job = svc.generate({
            "prompt": ("a silver knight in a crimson cape on a dark fantasy "
                       "battlefield, cinematic lighting"),
            "negative_prompt": "blurry, low quality, watermark, text",
            "model_id": "sd15", "width": 512, "height": 512, "steps": 20,
            "guidance_scale": 7.5, "seed": 424242,
        })
        done = _wait(svc, job["job_id"])
        self.assertEqual(done["status"], service_mod.COMPLETED, done.get("error"))
        path = Path(done["image_path"])
        self.assertTrue(path.is_file())
        self.assertIn(path.name, {p.name for p in out_dir.glob("*")} - before)
        with Image.open(path) as im:
            self.assertEqual(im.size, (512, 512))
            colours = len(im.convert("RGB").getcolors(maxcolors=1 << 20) or [])
        self.assertGreater(colours, 64, "image looks blank")
        record = next(r for r in svc.history() if r.get("job_id") == job["job_id"])
        self.assertEqual(record["status"], service_mod.COMPLETED)
        self.assertEqual(record["seed"], 424242)
        self.assertTrue(record["file_exists"])

    @requires_model
    def test_history_survives_a_new_service(self):
        svc = _service()
        job = svc.generate({"prompt": "a lone lighthouse at dusk",
                            "model_id": "sd15", "width": 512, "height": 512,
                            "steps": 8, "seed": 7})
        self.assertEqual(_wait(svc, job["job_id"])["status"],
                         service_mod.COMPLETED)
        fresh = service_mod.ImageGenerationService()
        records = fresh.history()
        match = next((r for r in records if r.get("job_id") == job["job_id"]),
                     None)
        self.assertIsNotNone(match, "record vanished across service instances")
        self.assertTrue(Path(match["image_path"]).is_file())


class TestLiveCancellation(unittest.TestCase):
    """Test J — cancellation against the real queue."""

    @requires_model
    def test_cancel_leaves_no_stuck_job(self):
        svc = _service()
        job = svc.generate({"prompt": "a very detailed castle, many steps",
                            "model_id": "sd15", "width": 512, "height": 512,
                            "steps": 100, "seed": 999})
        deadline = time.time() + 60
        while time.time() < deadline:
            cur = svc.get_job(job["job_id"]) or {}
            if cur.get("prompt_id"):
                break
            time.sleep(0.5)
        self.assertTrue((svc.get_job(job["job_id"]) or {}).get("prompt_id"))
        self.assertTrue(svc.cancel_job(job["job_id"])["ok"])
        done = _wait(svc, job["job_id"], timeout=120)
        self.assertEqual(done["status"], service_mod.CANCELLED, done)
        st = svc.backend_status(force=True)
        self.assertEqual(st.get("queue_running", 0), 0)


class TestLiveSettings(unittest.TestCase):
    def test_comfy_url_is_local_and_configurable(self):
        cfg = settings.load()
        self.assertNotEqual(settings.is_remote_endpoint(cfg["comfy_url"]), True)
        self.assertTrue(cfg["comfy_url"].startswith("http"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
