"""Group F — image and media workflows.

Resize, crop, convert, rotate and inspect run through Pillow on real files, and
each output is decoded again to check its pixels. Generation is tested against
an injected backend: the test proves how the worker handles a real produced
file, an unavailable backend, an authentication failure, a timeout and an empty
result — it does not claim a diffusion model ran (no GPU is exercised here).

Model capability is checked against the AI Image Studio registry, which keeps
vision-only models out of the generator list.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from core.image_studio import registry  # noqa: E402
from universal_agent import validation  # noqa: E402
from universal_agent.workers import Context  # noqa: E402
from universal_agent.workers import images as image_worker  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ua_img_"))
        self.workspace = self.tmp / "workspace"
        self.workspace.mkdir()
        self.photo = self.tmp / "photo.png"
        Image.new("RGBA", (400, 300), (10, 120, 200, 255)).save(self.photo)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ctx(self, request: str, params=None, answers=None, **kwargs) -> Context:
        task = {"id": "t1", "request": request, "answers": answers or {},
                "plan": [], "artifacts": []}
        return Context(task=task, workspace=self.workspace,
                       params=params or {}, **kwargs)

    def run_op(self, request: str, **params) -> dict:
        return image_worker.run(self.ctx(
            request, {"input_file": str(self.photo), **params}))

    def out(self, result: dict) -> Path:
        self.assertTrue(result["ok"], result.get("error"))
        images = [a for a in result["artifacts"]
                  if a["path"].lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
        self.assertTrue(images, result["artifacts"])
        return Path(images[0]["path"])

    def size(self, path: Path) -> tuple[int, int]:
        with Image.open(path) as im:
            return im.size


class TestImageOperations(_Base):
    def test_valid_image_is_inspected(self):
        result = self.run_op("Inspect photo.png")
        self.assertTrue(result["ok"], result["error"])
        text = Path([a for a in result["artifacts"]
                     if a["path"].endswith(".md")][0]["path"]).read_text("utf-8")
        self.assertIn("400×300", text)
        self.assertIn("PNG", text)

    def test_invalid_image_is_reported(self):
        broken = self.tmp / "broken.png"
        broken.write_bytes(b"\x89PNG\r\n\x1a\n definitely not a png")
        result = image_worker.run(self.ctx("Inspect it",
                                           {"input_file": str(broken)}))
        self.assertFalse(result["ok"])
        self.assertIn("not a readable image", result["error"])

    def test_resize_to_requested_dimensions(self):
        result = self.run_op("Resize photo.png to 320x200", operation="resize")
        self.assertEqual(self.size(self.out(result)), (320, 200))

    def test_resize_percentage(self):
        result = self.run_op("Resize photo.png to 50%", operation="resize")
        self.assertEqual(self.size(self.out(result)), (200, 150))

    def test_resize_width_only_keeps_aspect_ratio(self):
        result = self.run_op("Resize photo.png to 800 wide", operation="resize",
                             width=800)
        self.assertEqual(self.size(self.out(result)), (800, 600))

    def test_crop_to_square(self):
        result = self.run_op("Crop photo.png to a square", operation="crop")
        width, height = self.size(self.out(result))
        self.assertEqual(width, height)
        self.assertEqual(height, 300)

    def test_crop_to_sixteen_by_nine(self):
        result = self.run_op("Crop photo.png to 16:9", operation="crop")
        width, height = self.size(self.out(result))
        self.assertAlmostEqual(width / height, 16 / 9, places=2)

    def test_convert_png_to_jpeg_flattens_transparency(self):
        result = self.run_op("Convert photo.png to jpeg", operation="convert",
                             format="jpg")
        path = self.out(result)
        with Image.open(path) as im:
            self.assertEqual(im.format, "JPEG")
            self.assertEqual(im.mode, "RGB")

    def test_convert_png_to_webp(self):
        result = self.run_op("Convert photo.png to webp", operation="convert",
                             format="webp")
        with Image.open(self.out(result)) as im:
            self.assertEqual(im.format, "WEBP")

    def test_rotate_expands_canvas(self):
        result = self.run_op("Rotate photo.png by 90 degrees", operation="rotate")
        self.assertEqual(self.size(self.out(result)), (300, 400))

    def test_unsupported_operation_lists_supported_ones(self):
        result = self.run_op("Resize photo.png", operation="sketch")
        self.assertFalse(result["ok"])
        for name in ("inspect", "resize", "crop", "convert", "rotate", "generate"):
            self.assertIn(name, result["error"])

    def test_ai_edit_request_is_not_silently_an_inspection(self):
        result = self.run_op("Remove the background from photo.png")
        self.assertFalse(result["ok"])
        self.assertIn("not implemented", result["error"])
        self.assertEqual(result["artifacts"], [])

    def test_original_is_preserved_by_default(self):
        before = hashlib.sha256(self.photo.read_bytes()).hexdigest()
        self.assertTrue(self.run_op("Resize photo.png to 320x200",
                                    operation="resize")["ok"])
        self.assertEqual(before,
                         hashlib.sha256(self.photo.read_bytes()).hexdigest())

    def test_edited_copy_is_written_inside_the_workspace(self):
        result = self.run_op("Resize photo.png to 320x200", operation="resize")
        path = self.out(result)
        self.assertEqual(path.parent, self.workspace.resolve())
        self.assertIn("resize", path.name)

    def test_output_image_decodes_and_matches_the_report(self):
        result = self.run_op("Resize photo.png to 320x200", operation="resize")
        check = validation.validate_artifact(self.out(result), self.workspace)
        self.assertTrue(check["ok"], check["detail"])
        self.assertIn("320×200", check["detail"])

    def test_missing_input_is_refused_with_an_explanation(self):
        result = image_worker.run(self.ctx("Resize the image"))
        self.assertFalse(result["ok"])
        self.assertIn("needs an input image", result["error"])

    def test_absent_input_path_is_refused(self):
        result = image_worker.run(self.ctx(
            "Resize it", {"input_file": str(self.tmp / "gone.png"),
                          "operation": "resize"}))
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["error"].lower())


class TestImageGeneration(_Base):
    def _backend(self, payload: dict, calls: list | None = None):
        def backend(job):
            if calls is not None:
                calls.append(job)
            return payload
        return backend

    def _real_file(self) -> Path:
        made = self.tmp / "backend-output.png"
        Image.new("RGB", (64, 48), (200, 30, 60)).save(made)
        return made

    def test_unavailable_backend_is_explicit(self):
        result = image_worker.run(self.ctx(
            "Generate an image of a lighthouse",
            image_backend=self._backend({
                "ok": False,
                "error": "The local image backend (ComfyUI) is not running."})))
        self.assertFalse(result["ok"])
        self.assertIn("ComfyUI", result["error"])
        self.assertFalse([a for a in result["artifacts"]
                          if a["path"].endswith(".png")])

    def test_authentication_failure_is_relayed(self):
        result = image_worker.run(self.ctx(
            "Generate an image of a harbour",
            image_backend=self._backend({
                "ok": False, "error": "401 Unauthorized: check the API key"})))
        self.assertFalse(result["ok"])
        self.assertIn("401", result["error"])

    def test_empty_result_never_becomes_an_artifact(self):
        result = image_worker.run(self.ctx(
            "Generate an image", image_backend=self._backend({"ok": True,
                                                             "images": []})))
        self.assertFalse(result["ok"])
        self.assertIn("No image was produced", result["summary"])

    def test_timeout_is_reported_without_retrying_forever(self):
        calls: list = []

        def slow(_job):
            calls.append(1)
            return {"ok": False, "error": "Generation timed out after 10 minutes."}

        result = image_worker.run(self.ctx("Generate an image of a tower",
                                           image_backend=slow))
        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["error"])
        self.assertEqual(len(calls), 1)

    def test_real_generated_file_is_copied_and_recorded(self):
        produced = self._real_file()
        result = image_worker.run(self.ctx(
            "Generate an image of a lighthouse",
            image_backend=self._backend({"ok": True, "images": [str(produced)],
                                         "model": "SD 1.5", "seed": 42})))
        self.assertTrue(result["ok"], result["error"])
        copied = self.out(result)
        self.assertEqual(copied.parent, self.workspace.resolve())
        self.assertEqual(self.size(copied), (64, 48))
        report = [a for a in result["artifacts"] if a["path"].endswith(".md")]
        self.assertTrue(report)
        text = Path(report[0]["path"]).read_text(encoding="utf-8")
        self.assertIn("SD 1.5", text)
        self.assertIn("42", text)

    def test_generated_image_is_validated(self):
        produced = self._real_file()
        result = image_worker.run(self.ctx(
            "Generate an image",
            image_backend=self._backend({"ok": True, "images": [str(produced)]})))
        check = validation.validate_artifact(self.out(result), self.workspace)
        self.assertTrue(check["ok"], check["detail"])

    def test_unreadable_generated_file_fails_loudly(self):
        junk = self.tmp / "junk.png"
        junk.write_bytes(b"not an image")
        result = image_worker.run(self.ctx(
            "Generate an image",
            image_backend=self._backend({"ok": True, "images": [str(junk)]})))
        self.assertFalse(result["ok"])
        self.assertIn("could not be opened", result["error"])


class TestModelCapability(_Base):
    def test_vision_models_are_not_offered_as_generators(self):
        generator_ids = {m["id"] for m in registry.generator_models()}
        vision_ids = {m["id"] for m in registry.vision_models()}
        self.assertTrue(vision_ids)
        self.assertFalse(generator_ids & vision_ids)

    def test_every_generator_declares_text_to_image(self):
        for model in registry.generator_models():
            self.assertEqual(model["capability"], registry.TEXT2IMG)
            self.assertIn(registry.TEXT2IMG, model["capabilities"])

    def test_editing_capability_is_stated_per_model(self):
        sd15 = registry.get_model("sd15")
        self.assertIsNotNone(sd15)
        self.assertIn(registry.IMG2IMG, sd15["capabilities"])
        self.assertIn("capability", sd15)


class TestImageAssetsInProjects(_Base):
    def test_image_is_placed_in_a_project_and_referenced(self):
        result = self.run_op("Resize photo.png to 200x200", operation="resize")
        source = self.out(result)
        project = self.workspace / "site"
        project.mkdir()
        asset = project / "assets" / "hero.png"
        asset.parent.mkdir()
        shutil.copyfile(source, asset)
        page = project / "index.html"
        page.write_text(
            '<!doctype html><html><body><img src="assets/hero.png" '
            'alt="hero"></body></html>', encoding="utf-8")
        self.assertTrue(asset.is_file())
        html = page.read_text(encoding="utf-8")
        relative = html.split('src="', 1)[1].split('"', 1)[0]
        self.assertTrue((project / relative).is_file())
        self.assertTrue(validation.validate_artifact(asset, self.workspace)["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
