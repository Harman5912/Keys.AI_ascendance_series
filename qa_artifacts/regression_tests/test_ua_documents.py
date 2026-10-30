"""Group D — documents: read, create, reopen, validate.

Every document here is a real file produced by the app's Office/PDF builders
and reopened by a real parser. Nothing is asserted from the builder's return
value: the test reads the artefact back the way a user would.

Reading uses ``actions/_file_readers``, the handlers behind the existing
``file_processor`` call, so these tests cover the same code the chat agent uses.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from actions import _file_readers as readers  # noqa: E402
from universal_agent import security, validation  # noqa: E402
from universal_agent.workers import Context  # noqa: E402
from universal_agent.workers import documents as doc_worker  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ua_docs_"))
        self.workspace = self.tmp / "workspace"
        self.workspace.mkdir()
        # Offline, fast: the builders may otherwise fetch cover images.
        self._img = mock.patch("actions._office_builder._image_fetch_retry",
                               lambda *a, **k: None)
        self._img.start()

    def tearDown(self):
        self._img.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ctx(self, request: str, params=None, answers=None) -> Context:
        task = {"id": "t1", "request": request, "answers": answers or {},
                "plan": [], "artifacts": []}
        return Context(task=task, workspace=self.workspace,
                       params=params or {})

    def build(self, request: str, fmt: str) -> dict:
        result = doc_worker.run(self.ctx(request, {"format": fmt}))
        self.assertTrue(result["ok"], result.get("error"))
        return result

    def path(self, result: dict, suffix: str | None = None) -> Path:
        for artifact in result["artifacts"]:
            p = Path(artifact["path"])
            if suffix is None or p.suffix == suffix:
                return p
        self.fail(f"no artifact with suffix {suffix}")


class TestDocumentReading(_Base):
    def test_plain_text_file_is_read(self):
        path = self.tmp / "notes.txt"
        path.write_text("Quarterly notes.\nRevenue grew.\n", encoding="utf-8")
        out = readers.read_text(path, "extract_text")
        self.assertIn("Quarterly notes", out)
        self.assertIn("Lines: 3", out)

    def test_word_document_is_read(self):
        result = self.build("Create a Word report about renewable energy", "docx")
        out = readers.read_docx(self.path(result), "extract_text")
        self.assertIn("DOCX:", out)
        self.assertIn("Paragraphs:", out)

    def test_powerpoint_is_read(self):
        result = self.build("Create a PowerPoint about rivers", "pptx")
        out = readers.read_pptx(self.path(result), "info")
        self.assertIn("Slides:", out)

    def test_excel_workbook_is_read(self):
        result = self.build("Create an Excel budget workbook", "xlsx")
        out = readers.read_xlsx(self.path(result), "info")
        self.assertIn("Sheets:", out)

    def test_pdf_is_read(self):
        result = self.build("Create a PDF about solar panels", "pdf")
        out = readers.read_pdf(self.path(result), "info")
        self.assertIn("Pages:", out)

    def test_corrupted_pdf_is_reported_not_raised(self):
        path = self.tmp / "broken.pdf"
        path.write_bytes(b"%PDF-1.4\nthis is not really a pdf\n")
        out = readers.read_pdf(path, "extract_text")
        self.assertIn("Could not open PDF", out)
        check = validation.validate_artifact(path)
        self.assertFalse(check["ok"])

    def test_unsupported_input_type_is_refused(self):
        path = self.tmp / "payload.exe"
        path.write_bytes(b"MZ\x00\x00")
        with self.assertRaises(security.SecurityError):
            security.validate_input_file(path)


class TestDocumentCreation(_Base):
    def test_word_report_is_created_and_reopens(self):
        result = self.build("Create a Word report about wind power", "docx")
        path = self.path(result, ".docx")
        check = validation.validate_artifact(path)
        self.assertTrue(check["ok"], check["detail"])
        self.assertIn("paragraph", check["detail"])

    def test_word_report_keeps_supplied_names_and_figures(self):
        result = self.build(
            "Create a Word report about Ada Lovelace and the 1843 notes",
            "docx")
        text = readers.read_docx(self.path(result), "extract_text")
        self.assertIn("Ada Lovelace", text)

    def test_word_report_keeps_unicode_names(self):
        result = self.build("Create a Word report about José Fernández", "docx")
        text = readers.read_docx(self.path(result), "extract_text")
        self.assertIn("José", text)

    def test_pdf_is_created_and_readable(self):
        result = self.build("Create a PDF about tidal energy", "pdf")
        path = self.path(result, ".pdf")
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        self.assertGreaterEqual(len(reader.pages), 1)
        check = validation.validate_artifact(path)
        self.assertTrue(check["ok"], check["detail"])

    def test_presentation_has_multiple_slides(self):
        result = self.build("Create a PowerPoint presentation about rivers",
                            "pptx")
        from pptx import Presentation
        prs = Presentation(str(self.path(result, ".pptx")))
        self.assertGreaterEqual(len(prs.slides), 2)
        check = validation.validate_artifact(self.path(result, ".pptx"))
        self.assertIn("slide", check["detail"])

    def test_slide_count_matches_the_generated_deck(self):
        result = self.build("Create a PowerPoint about oceans", "pptx")
        from pptx import Presentation
        prs = Presentation(str(self.path(result, ".pptx")))
        check = validation.validate_artifact(self.path(result, ".pptx"))
        self.assertIn(f"{len(prs.slides)} slide(s)", check["detail"])

    def test_excel_workbook_is_created_with_content(self):
        result = self.build("Create an Excel budget workbook", "xlsx")
        from openpyxl import load_workbook
        wb = load_workbook(str(self.path(result, ".xlsx")))
        try:
            self.assertTrue(wb.sheetnames)
            rows = sum(1 for ws in wb.worksheets
                       for _ in ws.iter_rows(values_only=True))
            self.assertGreater(rows, 0)
        finally:
            wb.close()

    def test_format_comes_from_the_request_wording(self):
        result = doc_worker.run(self.ctx("Create a PowerPoint about oceans"))
        self.assertTrue(result["ok"])
        self.assertEqual(self.path(result).suffix, ".pptx")

    def test_explicit_format_overrides_the_wording(self):
        result = doc_worker.run(self.ctx(
            "Create a PDF about oceans", {"format": "docx"}))
        self.assertTrue(result["ok"])
        self.assertEqual(self.path(result).suffix, ".docx")

    def test_every_artifact_is_inside_the_workspace(self):
        for fmt in ("docx", "pdf", "pptx", "xlsx"):
            result = self.build(f"Create a report about topic {fmt}", fmt)
            for artifact in result["artifacts"]:
                self.assertTrue(
                    security.is_within(artifact["path"], self.workspace))

    def test_deliverable_list_matches_the_files_on_disk(self):
        result = self.build("Create a Word report about batteries", "docx")
        kinds = {a["kind"] for a in result["artifacts"]}
        self.assertEqual(kinds, {"docx"})
        for artifact in result["artifacts"]:
            self.assertTrue(Path(artifact["path"]).is_file())

    def test_unsafe_output_name_stays_inside_the_workspace(self):
        result = self.build(
            "Create a Word document about ../../etc/passwd and cats", "docx")
        path = self.path(result)
        self.assertEqual(path.parent, self.workspace.resolve())
        self.assertNotIn("..", path.name)

    def test_one_request_writes_one_deliverable(self):
        result = self.build("Create a Word report about tides", "docx")
        self.assertEqual(len(result["artifacts"]), 1)


class TestDocumentFailures(_Base):
    def test_builder_error_is_reported(self):
        def boom(*_a, **_k):
            raise RuntimeError("renderer crashed")

        with mock.patch("actions._office_builder.build_docx", boom):
            result = doc_worker.run(self.ctx("Create a Word report",
                                             {"format": "docx"}))
        self.assertFalse(result["ok"])
        self.assertIn("renderer crashed", result["error"])

    def test_empty_output_is_rejected(self):
        def empty(target, *_a, **_k):
            Path(target).write_bytes(b"")
            return Path(target)

        with mock.patch("actions._office_builder.build_pdf", empty):
            result = doc_worker.run(self.ctx("Create a PDF", {"format": "pdf"}))
        self.assertFalse(result["ok"])
        self.assertIn("no file", result["summary"].lower())

    def test_missing_office_library_is_explained(self):
        def missing(*_a, **_k):
            raise ImportError("python-pptx is not installed")

        with mock.patch("actions._office_builder.build_pptx", missing):
            result = doc_worker.run(self.ctx("Create a PowerPoint",
                                             {"format": "pptx"}))
        self.assertFalse(result["ok"])
        self.assertIn("python-pptx", result["error"])

    def test_truncated_docx_fails_validation(self):
        path = self.workspace / "truncated.docx"
        path.write_bytes(b"PK\x03\x04broken archive")
        check = validation.validate_artifact(path)
        self.assertFalse(check["ok"])
        self.assertIn("could not be reopened", check["detail"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
