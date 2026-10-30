"""Group D — integration into generated outputs (20 scenarios).

These use the shipped :mod:`core.research_browser.integration` code against real
files: a real static site, a real .docx/.pptx/.xlsx (opened again afterwards),
a Python project and an Android resource tree. Where an entire framework cannot
be built here (a full Android build), the test says so instead of pretending.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from browser_fixtures import ROOT

sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from core.research_browser import integration  # noqa: E402


def _png(path: Path, size=(320, 200), colour=(180, 40, 40)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    path.write_bytes(buf.getvalue())
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class IntegrationBase(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="rb_integration_"))
        self.asset = _png(self.temp / "collected" / "photo.png")
        self.asset_hash = _sha(self.asset)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)


class TestWebIntegration(IntegrationBase):
    def _site(self) -> Path:
        root = self.temp / "site"
        (root / "assets").mkdir(parents=True)
        (root / "index.html").write_text(
            "<html><body><h1>Portfolio</h1>\n<!-- KEYS_AI_ASSETS -->\n"
            "</body></html>", encoding="utf-8")
        (root / "about.html").write_text("<html><body>about</body></html>",
                                         encoding="utf-8")
        return root

    def test_d01_adds_a_collected_image_to_an_existing_site(self):
        root = self._site()
        result = integration.add_to_web_project(
            str(self.asset), str(root), alt="A photograph", caption="Hero")
        self.assertTrue(result["ok"], result)
        self.assertTrue(Path(result["dest"]).is_file())

    def test_d02_creates_a_project_that_consumes_the_image(self):
        root = self._site()
        result = integration.add_to_web_project(str(self.asset), str(root))
        page = (root / "index.html").read_text(encoding="utf-8")
        self.assertIn(result["reference"], page)

    def test_d03_reference_points_at_a_real_file(self):
        root = self._site()
        result = integration.add_to_web_project(str(self.asset), str(root))
        verified = integration.verify_reference(
            str(root), result["reference"], page=str(root / "index.html"))
        self.assertTrue(verified["ok"], verified)

    def test_d04_missing_referenced_asset_is_detected(self):
        root = self._site()
        result = integration.add_to_web_project(str(self.asset), str(root))
        Path(result["dest"]).unlink()
        verified = integration.verify_reference(str(root), result["reference"])
        self.assertFalse(verified["ok"])
        self.assertIn("does not exist", verified["error"])

    def test_d05_invalid_source_path_is_reported(self):
        root = self._site()
        result = integration.add_to_web_project(str(self.temp / "nope.png"),
                                                str(root))
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["error"])

    def test_d06_unrelated_files_are_untouched(self):
        root = self._site()
        before = _sha(root / "about.html")
        integration.add_to_web_project(str(self.asset), str(root))
        self.assertEqual(_sha(root / "about.html"), before)

    def test_d07_inserts_with_alt_text_and_caption(self):
        root = self._site()
        result = integration.add_to_web_project(
            str(self.asset), str(root), alt="Silver knight", caption="Hero image")
        page = (root / "index.html").read_text(encoding="utf-8")
        self.assertIn('alt="Silver knight"', page)
        self.assertIn("<figcaption>Hero image</figcaption>", page)

    def test_d08_detects_the_framework_asset_folder(self):
        root = self.temp / "app"
        root.mkdir()
        (root / "package.json").write_text('{"dependencies": {"next": "14"}}',
                                           encoding="utf-8")
        (root / "public").mkdir()
        (root / "index.html").write_text("<html><body></body></html>",
                                         encoding="utf-8")
        info = integration.detect_project(root)
        self.assertEqual(info["type"], "next")
        self.assertEqual(info["asset_dir"], "public")
        result = integration.add_to_web_project(str(self.asset), str(root))
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["dest"].startswith(str(root / "public")))

    def test_d09_reference_collision_does_not_overwrite(self):
        root = self._site()
        first = integration.add_to_web_project(str(self.asset), str(root))
        second_file = _png(self.temp / "other.png", colour=(10, 200, 10))
        second = integration.add_to_web_project(str(second_file), str(root))
        self.assertNotEqual(first["dest"], second["dest"])
        self.assertEqual(_sha(Path(first["dest"])), self.asset_hash)

    def test_d10_unknown_project_is_reported_not_guessed(self):
        root = self.temp / "mystery"
        root.mkdir()
        result = integration.add_to_web_project(str(self.asset), str(root))
        self.assertFalse(result["ok"])
        self.assertIn("asset", result["error"].lower())


class TestDocumentIntegration(IntegrationBase):
    def test_d11_inserts_an_image_into_word(self):
        from docx import Document
        target = self.temp / "report.docx"
        Document().save(str(target))
        result = integration.add_to_docx(str(self.asset), str(target),
                                         caption="Figure 1",
                                         source_note="example.org")
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["verified"])

    def test_d12_word_document_reopens_with_the_picture(self):
        from docx import Document
        target = self.temp / "report.docx"
        Document().save(str(target))
        integration.add_to_docx(str(self.asset), str(target), caption="Figure")
        doc = Document(str(target))
        self.assertEqual(len(doc.inline_shapes), 1)
        text = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("Figure", text)

    def test_d13_inserts_an_image_into_powerpoint(self):
        from pptx import Presentation
        target = self.temp / "deck.pptx"
        Presentation().save(str(target))
        result = integration.add_to_pptx(str(self.asset), str(target),
                                         caption="Reference",
                                         source_note="example.org")
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["verified"])

    def test_d14_powerpoint_reopens_with_the_picture(self):
        from pptx import Presentation
        target = self.temp / "deck.pptx"
        Presentation().save(str(target))
        integration.add_to_pptx(str(self.asset), str(target), caption="Reference")
        prs = Presentation(str(target))
        pictures = [shape for slide in prs.slides for shape in slide.shapes
                    if shape.shape_type == 13]
        self.assertEqual(len(pictures), 1)

    def test_d15_picture_stays_inside_the_slide(self):
        from pptx import Presentation
        target = self.temp / "deck.pptx"
        Presentation().save(str(target))
        integration.add_to_pptx(str(self.asset), str(target))
        prs = Presentation(str(target))
        slide = prs.slides[0]
        picture = [s for s in slide.shapes if s.shape_type == 13][0]
        self.assertLessEqual(picture.left + picture.width, prs.slide_width)
        self.assertLessEqual(picture.top + picture.height, prs.slide_height)

    def test_d16_inserts_an_image_into_excel(self):
        import openpyxl
        target = self.temp / "data.xlsx"
        wb = openpyxl.Workbook()
        wb.active["A1"] = "Collected assets"
        wb.save(str(target))
        result = integration.add_to_xlsx(str(self.asset), str(target), cell="B3")
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["verified"])

    def test_d17_workbook_reopens_with_data_and_image(self):
        import openpyxl
        target = self.temp / "data.xlsx"
        wb = openpyxl.Workbook()
        wb.active["A1"] = "Collected assets"
        wb.save(str(target))
        integration.add_to_xlsx(str(self.asset), str(target))
        again = openpyxl.load_workbook(str(target))
        self.assertEqual(again.active["A1"].value, "Collected assets")
        self.assertTrue(getattr(again.active, "_images", []))

    def test_d18_corrupt_document_fails_honestly(self):
        target = self.temp / "broken.docx"
        target.write_bytes(b"not a docx")
        result = integration.add_to_docx(str(self.asset), str(target))
        self.assertFalse(result["ok"])
        self.assertIn("Could not insert", result["error"])

    def test_d19_caption_and_source_are_recorded(self):
        from docx import Document
        target = self.temp / "report.docx"
        Document().save(str(target))
        integration.add_to_docx(str(self.asset), str(target), caption="Hero",
                                source_note="https://example.org/photo")
        text = "\n".join(p.text for p in Document(str(target)).paragraphs)
        self.assertIn("Hero", text)
        self.assertIn("https://example.org/photo", text)


class TestDesktopAndAndroidIntegration(IntegrationBase):
    def test_d20_integrates_into_a_python_project(self):
        root = self.temp / "pyapp"
        (root / "assets").mkdir(parents=True)
        (root / "main.py").write_text("print('app')\n", encoding="utf-8")
        result = integration.add_to_project(str(self.asset), str(root))
        self.assertTrue(result["ok"], result)
        self.assertTrue(Path(result["dest"]).is_file())
        self.assertEqual(_sha(self.asset), self.asset_hash)

    def test_d21_integrates_into_android_drawables(self):
        root = self.temp / "android"
        res = root / "app" / "src" / "main" / "res" / "drawable-xxhdpi"
        res.mkdir(parents=True)
        (root / "settings.gradle").write_text("rootProject.name='x'\n",
                                              encoding="utf-8")
        weird = _png(self.temp / "Hero Photo.PNG")
        result = integration.add_to_android(str(weird), str(root),
                                            name="Hero Photo")
        self.assertTrue(result["ok"], result)
        name = Path(result["dest"]).name
        self.assertRegex(name, r"^[a-z0-9_]+\.png$")
        self.assertTrue(result["reference"].startswith("@drawable/"))
        verified = integration.verify_reference(str(root), result["reference"])
        self.assertTrue(verified["ok"], verified)

    def test_d22_android_integration_rejects_non_android_folders(self):
        root = self.temp / "notandroid"
        root.mkdir()
        result = integration.add_to_android(str(self.asset), str(root))
        self.assertFalse(result["ok"])
        self.assertIn("Android", result["error"])

    def test_d23_unsupported_project_kind_is_reported(self):
        root = self.temp / "none"
        root.mkdir()
        result = integration.add_to_project(str(self.asset), str(root),
                                            kind="cobol-on-wheels")
        self.assertFalse(result["ok"])
        self.assertIn("Unsupported", result["error"])

    def test_d24_source_asset_is_preserved_by_copying(self):
        root = self.temp / "site"
        (root / "assets").mkdir(parents=True)
        (root / "index.html").write_text("<html><body></body></html>",
                                         encoding="utf-8")
        integration.add_to_web_project(str(self.asset), str(root))
        self.assertTrue(self.asset.is_file())
        self.assertEqual(_sha(self.asset), self.asset_hash)


if __name__ == "__main__":
    unittest.main(verbosity=2)
