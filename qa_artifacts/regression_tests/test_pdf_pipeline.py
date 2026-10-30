"""PDF read-pipeline tests over 10 real PDFs.

Keys.ai can read and convert PDFs but has no PDF *creation* action, so the
fixtures are built by qa_artifacts/make_pdf_fixtures.py (reportlab) and fed
through the public file_processor entry point, the same call the app makes.

Run: python -m unittest qa_artifacts.regression_tests.test_pdf_pipeline -v
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

import actions.file_processor as fp  # noqa: E402

FIXTURES = BASE / "qa_artifacts" / "fixtures" / "pdf"
EXPECTED = {
    "P01_quarterly_report": "Revenue grew 14%",
    "P02_policy": "three days per week",
    "P03_invoice": "INV-2041",
    "P04_contract": "net 45 days",
    "P05_research": "Kalman",
    "P06_manual": "green LED",
    "P07_minutes": "Quorum present",
    "P08_syllabus": "exactly-once",
    "P09_unicode": "Frühstück",
}


class TestPdfReadPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FIXTURES.is_dir():
            raise unittest.SkipTest("run qa_artifacts/make_pdf_fixtures.py first")
        cls._tmp = tempfile.TemporaryDirectory(prefix="keysai_pdf_")
        cls.dir = Path(cls._tmp.name)
        for p in FIXTURES.glob("*.pdf"):
            shutil.copy2(p, cls.dir / p.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_pdf(self, name: str, action: str, **params):
        return fp.file_processor({"action": action, "file_path": str(self.dir / name), **params})

    def test_all_text_pdfs_extract_and_convert(self):
        for stem, needle in EXPECTED.items():
            with self.subTest(pdf=stem):
                name = f"{stem}.pdf"
                info = self.run_pdf(name, "info")
                self.assertIn("PDF:", info)
                self.assertIn("pages", info)

                out = self.run_pdf(name, "extract_text")
                self.assertIn("Text extracted", out)
                txt = self.dir / f"{stem}_text.txt"
                self.assertTrue(txt.exists(), "extract_text did not write a .txt")
                body = txt.read_text(encoding="utf-8")
                self.assertIn(needle, body)

                conv = self.run_pdf(name, "to_word")
                self.assertIn("Converted to Word", conv)
                docx = self.dir / f"{stem}_converted.docx"
                self.assertTrue(docx.exists() and docx.stat().st_size > 2000)
                from docx import Document
                text = "\n".join(p.text for p in Document(str(docx)).paragraphs)
                self.assertIn(needle, text)

    def test_unicode_survives_pdf_roundtrip(self):
        self.run_pdf("P09_unicode.pdf", "to_word")
        from docx import Document
        text = "\n".join(p.text for p in Document(str(self.dir / "P09_unicode_converted.docx")).paragraphs)
        self.assertIn("Café", text)
        self.assertIn("Zürich", text)

    def test_image_only_pdf_reports_no_text(self):
        out = self.run_pdf("P10_scanned_no_text.pdf", "extract_text")
        self.assertIn("Could not extract text", out)

    def test_unknown_action_is_reported(self):
        out = self.run_pdf("P01_quarterly_report.pdf", "merge")
        self.assertIn("Unknown PDF action", out)

    def test_pdf_creation_writes_a_real_pdf(self):
        """The writer that used to be missing now produces a reopenable PDF.

        Asserted against the bytes and a second parser, not just the tool's own
        "parsed OK" line.
        """
        dest = self.dir / "requested.pdf"
        out = fp.file_processor({"action": "create", "file_path": str(dest),
                                 "title": "Report", "instruction": "Write a report"})
        self.assertIn("Created PDF", out)
        self.assertIn("parsed OK", out)
        self.assertTrue(dest.exists(), "create reported success but wrote nothing")
        self.assertGreater(dest.stat().st_size, 500)
        self.assertTrue(dest.read_bytes().startswith(b"%PDF"), "not a real PDF")
        from pypdf import PdfReader
        reader = PdfReader(str(dest))
        self.assertGreaterEqual(len(reader.pages), 1)
        self.assertIn("Report", "".join(page.extract_text() or "" for page in reader.pages))

    def test_pptx_to_pdf_is_advertised_but_missing(self):
        """Docstring advertises pptx->pdf; the handler does not implement it."""
        src = self.dir / "deck.pptx"
        from pptx import Presentation
        prs = Presentation()
        prs.slides.add_slide(prs.slide_layouts[0]).shapes.title.text = "Deck"
        prs.save(str(src))
        out = fp.file_processor({"action": "to_pdf", "file_path": str(src)})
        self.assertIn("Unknown PPTX action", out)
        self.assertFalse((self.dir / "deck.pdf").exists())


class TestPdfManifest(unittest.TestCase):
    def test_ten_fixtures_present(self):
        manifest = json.loads((FIXTURES / "_fixtures.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(manifest), 10)
        self.assertTrue(all((FIXTURES / m["file"]).exists() for m in manifest))


if __name__ == "__main__":
    unittest.main(verbosity=2)
