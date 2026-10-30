"""Regression tests for AI Image Studio.

These exercise the real service against a local HTTP server that implements
ComfyUI's documented API contract (/system_stats, /object_info, /prompt,
/queue, /history, /view, /interrupt). That proves the integration path —
submit, poll, fetch, validate, save, history, cancel, failure handling —
without requiring a GPU, ComfyUI, or a 4 GB checkpoint download.

What these tests do NOT prove: that a real diffusion model produces a good
image. That needs ComfyUI + weights on the target machine and is reported
separately.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from core.image_studio import (  # noqa: E402
    installer, registry, service as service_mod, settings, store, validation,
    workflows,
)

PNG_BYTES = b""


def _png() -> bytes:
    global PNG_BYTES
    if not PNG_BYTES:
        buf = io.BytesIO()
        Image.new("RGB", (64, 48), (200, 40, 40)).save(buf, format="PNG")
        PNG_BYTES = buf.getvalue()
    return PNG_BYTES


class FakeComfy:
    """Minimal but faithful ComfyUI API for tests."""

    def __init__(self, checkpoints=("v1-5-pruned-emaonly.safetensors",),
                 slow=False):
        self.checkpoints = list(checkpoints)
        self.slow = slow
        self.jobs: dict[str, dict] = {}
        self.counter = 0
        self.interrupted = 0
        self.prompt_bodies: list[dict] = []
        self.lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):   # silence test output
                pass

            def _json(self, obj, code=200):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                path = urlparse(self.path).path
                if path == "/system_stats":
                    return self._json({
                        "system": {"comfyui_version": "0.3.0-test",
                                   "python_version": "3.12"},
                        "devices": [{"name": "Fake GPU", "type": "cuda",
                                     "vram_total": 6 * 10**9,
                                     "vram_free": 5 * 10**9}],
                    })
                if path.startswith("/object_info/"):
                    node = path.rsplit("/", 1)[-1]
                    fields = {"CheckpointLoaderSimple": ("ckpt_name", fake.checkpoints),
                              "UNETLoader": ("unet_name", []),
                              "CLIPLoader": ("clip_name", []),
                              "VAELoader": ("vae_name", [])}
                    if node in fields:
                        key, names = fields[node]
                        return self._json({node: {"input": {"required":
                                                           {key: [names]}}}})
                    return self._json({})
                if path == "/queue":
                    with fake.lock:
                        running = [[0, pid, {}, {}, []]
                                   for pid, j in fake.jobs.items()
                                   if not j["done"] and not j["cancelled"]]
                    return self._json({"queue_running": running,
                                       "queue_pending": []})
                if path.startswith("/history/"):
                    pid = path.rsplit("/", 1)[-1]
                    with fake.lock:
                        job = fake.jobs.get(pid)
                        if not job or not job["done"]:
                            return self._json({})
                        return self._json({pid: {
                            "outputs": {"8": {"images": [
                                {"filename": "keysai_test.png",
                                 "subfolder": "KeysAI", "type": "output"}]}},
                            "status": {"status_str": "success",
                                       "completed": True, "messages": []},
                        }})
                if path == "/view":
                    data = _png()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return None
                return self._json({"error": "not found"}, 404)

            def do_POST(self):  # noqa: N802
                path = urlparse(self.path).path
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                if path == "/prompt":
                    payload = json.loads(body or b"{}")
                    fake.prompt_bodies.append(payload)
                    with fake.lock:
                        fake.counter += 1
                        pid = f"pid{fake.counter}"
                        fake.jobs[pid] = {"done": not fake.slow,
                                          "cancelled": False,
                                          "polls": 0}
                    return self._json({"prompt_id": pid, "number": 1,
                                       "node_errors": {}})
                if path == "/interrupt":
                    fake.interrupted += 1
                    return self._json({})
                if path == "/queue":
                    payload = json.loads(body or b"{}")
                    for pid in payload.get("delete") or []:
                        with fake.lock:
                            job = fake.jobs.get(pid)
                            if job:
                                job["cancelled"] = True
                    return self._json({})
                if path == "/upload/image":
                    return self._json({"name": "uploaded.png",
                                       "subfolder": "", "type": "input"})
                return self._json({"error": "not found"}, 404)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass

    def complete_all(self):
        with self.lock:
            for job in self.jobs.values():
                job["done"] = True


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.out_dir = self.tmp_path / "out"
        self.cfg = {
            **settings.DEFAULTS,
            "comfy_url": "http://127.0.0.1:1",
            "comfy_path": str(self.tmp_path / "ComfyUI"),
            "output_dir": str(self.out_dir),
            "model_id": "sd15",
        }
        self._patches = [
            mock.patch.object(settings, "load", lambda: dict(self.cfg)),
            mock.patch.object(settings, "save", lambda patch: {
                **self.cfg, **patch}),
            mock.patch.object(store, "HISTORY_PATH",
                              self.tmp_path / "history.json"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self.tmp.cleanup()

    def _wait(self, svc, job_id, timeout=20.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = svc.get_job(job_id)
            if job and job["status"] in service_mod.TERMINAL:
                return job
            time.sleep(0.1)
        self.fail(f"job {job_id} did not finish in {timeout}s: "
                  f"{svc.get_job(job_id)}")


class TestRegistry(_Base):
    def test_vision_models_are_not_generators(self):
        generators = {m["capability"] for m in registry.generator_models()}
        self.assertNotIn(registry.VISION, generators)
        for vis in registry.vision_models():
            self.assertEqual(vis["capability"], registry.VISION)
            self.assertIsNone(registry.get_model(vis["id"]))

    def test_sd15_is_the_supported_default(self):
        self.assertEqual(registry.default_model_id(), "sd15")
        sd = registry.get_model("sd15")
        self.assertEqual(sd["status"], "supported")
        self.assertLessEqual(sd["min_vram_gb"], 6.0)
        self.assertTrue(sd["files"][0]["sha256"])

    def test_heavy_models_declare_their_limits(self):
        self.assertEqual(registry.get_model("sdxl")["status"], "warn")
        self.assertFalse(registry.fits_vram("flux2-klein-4b", 6.0))
        self.assertTrue(registry.fits_vram("sd15", 6.0))


class TestValidation(_Base):
    def test_empty_prompt(self):
        with self.assertRaises(validation.ValidationError) as ctx:
            validation.validate_request({"prompt": "   ", "model_id": "sd15"})
        self.assertIn("prompt", str(ctx.exception).lower())

    def test_long_prompt(self):
        with self.assertRaises(validation.ValidationError):
            validation.validate_request({"prompt": "x" * 2100,
                                         "model_id": "sd15"})

    def test_bad_dimensions_and_steps(self):
        base = {"prompt": "a cat", "model_id": "sd15"}
        for patch in ({"width": 100}, {"width": 513}, {"height": 4096},
                      {"steps": 0}, {"steps": 500},
                      {"guidance_scale": 99}, {"output_format": "gif"},
                      {"batch_size": 9}):
            with self.subTest(patch=patch):
                with self.assertRaises(validation.ValidationError):
                    validation.validate_request({**base, **patch})

    def test_seed_is_randomised_when_negative(self):
        req = validation.validate_request({"prompt": "a cat",
                                           "model_id": "sd15", "seed": -1})
        self.assertGreaterEqual(req["seed"], 0)

    def test_negative_prompt_dropped_when_unsupported(self):
        req = validation.validate_request({
            "prompt": "a cat", "model_id": "z-image-turbo",
            "negative_prompt": "ugly", "width": 1024, "height": 1024})
        self.assertEqual(req["negative_prompt"], "")

    def test_safe_output_names_never_overwrite(self):
        first = validation.unique_output_path(self.out_dir, "job123", "png")
        Path(first).write_bytes(_png())
        second = validation.unique_output_path(self.out_dir, "job123", "png")
        self.assertNotEqual(first, second)
        self.assertFalse(second.exists())


class TestWorkflows(_Base):
    def test_graph_uses_core_nodes_only(self):
        model = registry.get_model("sd15")
        req = validation.validate_request({"prompt": "knight", "model_id": "sd15"})
        graph = workflows.build_graph(model, req, job_id="abc",
                                      checkpoint="v1-5-pruned-emaonly.safetensors")
        classes = {n["class_type"] for n in graph.values()}
        self.assertEqual(classes, {
            "CheckpointLoaderSimple", "CLIPTextEncode", "EmptyLatentImage",
            "KSampler", "VAEDecode", "SaveImage"})
        self.assertEqual(graph["6"]["inputs"]["seed"], req["seed"])
        self.assertEqual(graph["4"]["inputs"]["width"], 512)

    def test_img2img_uses_load_image_and_denoise(self):
        model = registry.get_model("sd15")
        req = validation.validate_request({"prompt": "knight", "model_id": "sd15"})
        graph = workflows.build_graph(model, req, job_id="abc",
                                      uploaded_image="in.png",
                                      checkpoint="v1-5-pruned-emaonly.safetensors")
        self.assertIn("LoadImage", {n["class_type"] for n in graph.values()})
        self.assertLess(graph["6"]["inputs"]["denoise"], 1.0)

    def test_split_file_model_is_refused_honestly(self):
        model = registry.get_model("flux2-klein-4b")
        with self.assertRaises(workflows.WorkflowError):
            workflows.build_graph(model, {"prompt": "x", "width": 1024,
                                          "height": 1024}, job_id="x")


class TestBackendDetection(_Base):
    def test_detects_running_backend_and_gpu(self):
        fake = FakeComfy().start()
        try:
            self.cfg["comfy_url"] = fake.url
            svc = service_mod.ImageGenerationService()
            status = svc.backend_status(force=True)
            self.assertTrue(status["reachable"])
            self.assertEqual(status["device"]["name"], "Fake GPU")
            self.assertEqual(status["comfy_version"], "0.3.0-test")
            models = svc.list_models()
            sd = next(m for m in models if m["id"] == "sd15")
            self.assertTrue(sd["installed"])
        finally:
            fake.stop()

    def test_missing_backend_reports_an_error_not_a_crash(self):
        # detect() also scans the machine's well-known ComfyUI locations, so a
        # developer box with a real checkout would report installed=True. Pin
        # the answer to "no checkout here" so the test asserts the configured
        # path, not whatever happens to be installed on the machine.
        with mock.patch.object(installer, "detect",
                               lambda *_a, **_k: {"found": False, "path": ""}):
            svc = service_mod.ImageGenerationService()
            status = svc.backend_status(force=True)
        self.assertFalse(status["reachable"])
        self.assertEqual(status["installed"], False)   # no main.py in temp dir

    def test_unreachable_backend_fails_the_job_with_guidance(self):
        svc = service_mod.ImageGenerationService()
        job = svc.generate({"prompt": "a lighthouse", "model_id": "sd15"})
        done = self._wait(svc, job["job_id"], timeout=25)
        self.assertEqual(done["status"], service_mod.FAILED)
        self.assertIn("ComfyUI", done["error"])
        recs = svc.history()
        self.assertEqual(recs[0]["status"], service_mod.FAILED)


class TestGeneration(_Base):
    def setUp(self):
        super().setUp()
        self.fake = FakeComfy().start()
        self.cfg["comfy_url"] = self.fake.url
        self.svc = service_mod.ImageGenerationService()

    def tearDown(self):
        self.fake.stop()
        super().tearDown()

    def test_missing_model_message(self):
        self.fake.checkpoints = []
        self.svc.invalidate_health()
        job = self.svc.generate({"prompt": "a lighthouse", "model_id": "sd15"})
        done = self._wait(self.svc, job["job_id"])
        self.assertEqual(done["status"], service_mod.FAILED)
        self.assertIn("not installed", done["error"])

    def test_successful_generation_saves_a_real_image(self):
        job = self.svc.generate({
            "prompt": "silver knight with a red cape",
            "negative_prompt": "blurry",
            "model_id": "sd15", "width": 512, "height": 512, "steps": 12,
            "guidance_scale": 6.5, "seed": 1234, "output_format": "png",
        })
        done = self._wait(self.svc, job["job_id"])
        self.assertEqual(done["status"], service_mod.COMPLETED, done.get("error"))
        self.assertTrue(done["image_path"])
        path = Path(done["image_path"])
        self.assertTrue(path.is_file())
        with Image.open(path) as im:
            self.assertEqual(im.size, (64, 48))   # what the fake backend returned
        self.assertEqual(done["seed"], 1234)
        self.assertEqual(done["settings"]["steps"], 12)
        # The submitted graph carried the real prompt, not a placeholder.
        sent = self.fake.prompt_bodies[0]["prompt"]
        self.assertIn("silver knight", sent["2"]["inputs"]["text"])
        self.assertIn("blurry", sent["3"]["inputs"]["text"])

    def test_jpeg_output_is_transcoded(self):
        job = self.svc.generate({"prompt": "a knight", "model_id": "sd15",
                                 "output_format": "jpg", "seed": 7})
        done = self._wait(self.svc, job["job_id"])
        self.assertEqual(done["status"], service_mod.COMPLETED, done.get("error"))
        path = Path(done["image_path"])
        self.assertEqual(path.suffix.lower(), ".jpg")
        with Image.open(path) as im:
            self.assertEqual(im.format, "JPEG")

    def test_history_survives_a_new_service_instance(self):
        job = self.svc.generate({"prompt": "a castle", "model_id": "sd15",
                                 "seed": 3})
        done = self._wait(self.svc, job["job_id"])
        self.assertEqual(done["status"], service_mod.COMPLETED)
        fresh = service_mod.ImageGenerationService()
        records = fresh.history()
        self.assertTrue(any(r["job_id"] == job["job_id"] for r in records))
        rec = next(r for r in records if r["job_id"] == job["job_id"])
        self.assertTrue(rec["file_exists"])
        self.assertEqual(rec["prompt"], "a castle")

    def test_remove_record_keeps_file_unless_confirmed(self):
        job = self.svc.generate({"prompt": "a castle", "model_id": "sd15",
                                 "seed": 5})
        done = self._wait(self.svc, job["job_id"])
        path = Path(done["image_path"])
        self.svc.remove_record(job["job_id"], delete_file=False)
        self.assertTrue(path.exists())
        self.assertFalse(any(r["job_id"] == job["job_id"]
                             for r in self.svc.history()))

    def test_delete_record_can_delete_the_file(self):
        job = self.svc.generate({"prompt": "a castle", "model_id": "sd15",
                                 "seed": 6})
        done = self._wait(self.svc, job["job_id"])
        path = Path(done["image_path"])
        result = self.svc.remove_record(job["job_id"], delete_file=True)
        self.assertTrue(result["ok"])
        self.assertFalse(path.exists())

    def test_unknown_model_fails_validation(self):
        with self.assertRaises(validation.ValidationError):
            self.svc.generate({"prompt": "a castle", "model_id": "nope"})


class TestCancellation(_Base):
    def test_cancel_stops_a_running_job(self):
        fake = FakeComfy(slow=True).start()
        try:
            self.cfg["comfy_url"] = fake.url
            svc = service_mod.ImageGenerationService()
            job = svc.generate({"prompt": "a slow tower", "model_id": "sd15"})
            deadline = time.time() + 10
            while time.time() < deadline:
                current = svc.get_job(job["job_id"]) or {}
                if current.get("prompt_id"):
                    break
                time.sleep(0.1)
            self.assertTrue((svc.get_job(job["job_id"]) or {}).get("prompt_id"),
                            "job was never submitted to the backend")
            self.assertTrue(svc.cancel_job(job["job_id"])["ok"])
            done = self._wait(svc, job["job_id"])
            self.assertEqual(done["status"], service_mod.CANCELLED)
            self.assertGreaterEqual(fake.interrupted, 1)
        finally:
            fake.stop()


class TestInstallerDiagnostics(_Base):
    """A failed install must say why, not just hand back an exit code.

    The first real install on a Windows machine failed this way: Keys.AI was
    running on the Microsoft Store Python, the venv was created inside the
    MSIX sandbox, and the only message was "exited with code 106".
    """

    def test_working_interpreter_is_recognised(self):
        ok, detail = installer._venv_works(Path(sys.executable), ROOT)
        self.assertTrue(ok, detail)

    def test_broken_interpreter_is_reported(self):
        broken = self.tmp_path / "pyvenv-sandbox" / "python.exe"
        ok, detail = installer._venv_works(broken, self.tmp_path)
        self.assertFalse(ok)
        self.assertTrue(detail.strip())

    def test_failed_step_keeps_the_last_output(self):
        with self.assertRaises(installer.InstallError) as ctx:
            installer._run([sys.executable, "-c",
                            "print('could not resolve host'); raise SystemExit(3)"],
                           self.tmp_path, lambda _m: None, lambda: False,
                           timeout=60)
        message = str(ctx.exception)
        self.assertIn("code 3", message)
        self.assertIn("could not resolve host", message)

    def test_store_python_failure_explains_the_portable_route(self):
        target = self.tmp_path / "ComfyUI"

        def fake_run(cmd, cwd, on_log, should_stop, timeout=None):
            if cmd[0] == "git":                 # pretend the clone succeeded
                target.mkdir(parents=True, exist_ok=True)
                (target / "main.py").write_text("# comfyui")
                return
            # Simulate the venv step producing a launcher that cannot start.
            if "venv" in cmd:
                vpy = target / "venv" / ("Scripts/python.exe"
                                        if sys.platform == "win32"
                                        else "bin/python")
                vpy.parent.mkdir(parents=True, exist_ok=True)
                vpy.write_bytes(b"not an interpreter")
                return
            raise AssertionError(f"unexpected step: {cmd}")

        with mock.patch.object(installer, "_run", side_effect=fake_run), \
                mock.patch.object(installer.shutil, "which", return_value="git"):
            with self.assertRaises(installer.InstallError) as ctx:
                installer.install_comfy(target, on_log=lambda _m: None)
        message = str(ctx.exception)
        self.assertIn("Microsoft", message)
        self.assertIn("portable", message.lower())

    def test_portable_locations_are_detected(self):
        paths = [str(p).replace("\\", "/")
                 for p in installer.candidate_dirs()]
        self.assertTrue(any("ComfyUI_portable" in p for p in paths))
        steps = " ".join(installer.manual_steps())
        self.assertIn("ComfyUI_windows_portable_nvidia.7z", steps)

    def test_detect_finds_a_portable_layout(self):
        portable = self.tmp_path / "ComfyUI_portable"
        inner = portable / "ComfyUI"
        inner.mkdir(parents=True)
        (inner / "main.py").write_text("# comfyui")
        found = installer.detect(str(portable))
        self.assertTrue(found["found"])
        self.assertEqual(Path(found["path"]), inner)


if __name__ == "__main__":
    unittest.main(verbosity=2)
