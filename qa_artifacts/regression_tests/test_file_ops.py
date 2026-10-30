"""File handling + document pipeline tests.

Covers actions/file_controller.py (CRUD, unicode/spaces, safety) and
actions/file_processor.py read paths (PDF/CSV/JSON) plus the DOCX creation
regressions: explicit output path must be honoured, and **bold** markers must
become real bold runs instead of literal asterisks.

All writes go to a temp directory under the user's home (the file controller
refuses anything outside ~), and are removed afterwards.

Run: python -m unittest qa_artifacts.regression_tests.test_file_ops -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

import actions.file_controller as fc  # noqa: E402
import actions.file_processor as fp  # noqa: E402

_opener_patcher = None


def setUpModule():
    """Never launch Word/Excel/PowerPoint while testing document creation."""
    global _opener_patcher
    _opener_patcher = mock.patch.object(fp, "_open_file_default")
    _opener_patcher.start()


def tearDownModule():
    if _opener_patcher is not None:
        _opener_patcher.stop()


class TempWorkspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="keysai_qa_")
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class TestFileController(TempWorkspace):
    def test_create_read_write(self):
        self.assertIn("File created", fc.create_file(str(self.dir), "a.txt", "one"))
        self.assertEqual((self.dir / "a.txt").read_text(encoding="utf-8"), "one")
        self.assertIn("one", fc.read_file(str(self.dir), "a.txt"))
        fc.write_file(str(self.dir), "a.txt", "two")
        self.assertEqual((self.dir / "a.txt").read_text(encoding="utf-8"), "two")

    def test_unicode_and_space_filename(self):
        name = "résumé café ☕ final.txt"
        fc.create_file(str(self.dir), name, "unicode ok")
        self.assertTrue((self.dir / name).exists())
        self.assertIn("unicode ok", fc.read_file(str(self.dir), name))

    def test_rename(self):
        fc.create_file(str(self.dir), "old.txt", "x")
        fc.rename_file(str(self.dir), "old.txt", "new name.txt")
        self.assertFalse((self.dir / "old.txt").exists())
        self.assertTrue((self.dir / "new name.txt").exists())

    def test_copy_and_move(self):
        dest = self.dir / "dest"
        dest.mkdir()
        fc.create_file(str(self.dir), "src.txt", "payload")
        fc.copy_file(str(self.dir), "src.txt", str(dest))
        self.assertTrue((dest / "src.txt").exists())
        self.assertTrue((self.dir / "src.txt").exists())
        fc.move_file(str(self.dir), "src.txt", str(dest))
        self.assertFalse((self.dir / "src.txt").exists())
        self.assertTrue((dest / "src.txt").exists())

    def test_delete_removes_from_place(self):
        fc.create_file(str(self.dir), "gone.txt", "bye")
        fc.delete_file(str(self.dir), "gone.txt")
        self.assertFalse((self.dir / "gone.txt").exists())

    def test_missing_file_is_reported_not_raised(self):
        out = fc.read_file(str(self.dir), "nope.txt")
        self.assertIn("not found", out.lower())

    def test_missing_directory_is_reported(self):
        out = fc.list_files(str(self.dir / "nope"))
        self.assertIn("not found", out.lower())

    def test_refuses_paths_outside_home(self):
        outside = Path("C:/Windows/System32/drivers/etc/hosts") if sys.platform == "win32" \
            else Path("/etc/hosts")
        self.assertFalse(fc._is_safe_path(outside))
        self.assertTrue(fc._is_safe_path(Path.home()))

    def test_write_outside_home_is_denied(self):
        outside = Path("C:/Windows/Temp/keysai_should_not_exist.txt") if sys.platform == "win32" \
            else Path("/tmp/keysai_should_not_exist.txt")
        out = fc.create_file(str(outside.parent), outside.name, "x")
        self.assertIn("denied", out.lower())
        self.assertFalse(outside.exists())

    def test_protected_directory_delete_is_refused(self):
        out = fc.delete_file(str(Path.home() / "Desktop"))
        self.assertIn("protected", out.lower())


class TestFileProcessorReads(TempWorkspace):
    def test_no_path(self):
        self.assertIn("No file path", fp.file_processor({"action": "read"}))

    def test_missing_file(self):
        out = fp.file_processor({"file_path": str(self.dir / "missing.txt"), "action": "extract_text"})
        self.assertIn("File not found", out)

    def test_directory_is_not_a_file(self):
        out = fp.file_processor({"file_path": str(self.dir), "action": "read"})
        self.assertIn("not a file", out)

    def test_create_rejects_unsupported_extension(self):
        out = fp.file_processor({"action": "create", "file_path": str(self.dir / "x.zzz"),
                                 "instruction": "x"})
        self.assertIn("Cannot create", out)
        self.assertFalse((self.dir / "x.zzz").exists())

    def test_create_pdf_writes_a_reopenable_document(self):
        dest = self.dir / "x.pdf"
        out = fp.file_processor({"action": "create", "file_path": str(dest),
                                 "instruction": "x"})
        self.assertIn("Created PDF", out)
        self.assertIn("parsed OK", out)
        self.assertTrue(dest.exists())
        self.assertGreater(dest.stat().st_size, 500)
        self.assertTrue(dest.read_bytes().startswith(b"%PDF"), "not a real PDF")

    def test_csv_stats(self):
        p = self.dir / "data.csv"
        p.write_text("name,score\nA,10\nB,20\nC,30\n", encoding="utf-8")
        out = fp.file_processor({"file_path": str(p), "action": "stats"})
        self.assertIn("score", out.lower())

    def test_json_validate_and_format(self):
        good = self.dir / "ok.json"
        good.write_text('{"a":1}', encoding="utf-8")
        self.assertIn("alid", fp.file_processor({"file_path": str(good), "action": "validate"}))
        bad = self.dir / "bad.json"
        bad.write_text("{nope", encoding="utf-8")
        out = fp.file_processor({"file_path": str(bad), "action": "validate"})
        self.assertTrue("invalid" in out.lower() or "error" in out.lower(), out)

    def test_pptx_to_pdf_is_declared_but_unimplemented(self):
        """The module docstring advertises 'pptx → to_pdf'; the dispatcher does
        not implement it. Recording the gap as a test so it cannot silently
        stay 'supported' without a real implementation."""
        from pptx import Presentation
        p = self.dir / "deck.pptx"
        prs = Presentation()
        prs.slides.add_slide(prs.slide_layouts[0])
        prs.save(str(p))
        out = fp.file_processor({"file_path": str(p), "action": "to_pdf"})
        self.assertIn("Unknown PPTX action", out)


class TestPdfPipeline(TempWorkspace):
    def _pdf(self) -> Path:
        from reportlab.pdfgen import canvas
        p = self.dir / "sample.pdf"
        c = canvas.Canvas(str(p), pagesize=(595, 842))
        c.drawString(72, 760, "Quarterly report")
        c.drawString(72, 740, "Revenue grew across all regions.")
        c.showPage()
        c.save()
        return p

    def test_info(self):
        out = fp.file_processor({"file_path": str(self._pdf()), "action": "info"})
        self.assertIn("1 pages", out)

    def test_extract_text(self):
        out = fp.file_processor({"file_path": str(self._pdf()), "action": "extract_text"})
        self.assertIn("Text extracted", out)
        txt = self.dir / "sample_text.txt"
        self.assertTrue(txt.exists())
        self.assertIn("Revenue grew", txt.read_text(encoding="utf-8"))

    def test_to_word(self):
        out = fp.file_processor({"file_path": str(self._pdf()), "action": "to_word"})
        self.assertIn("Converted", out)
        docx = self.dir / "sample_converted.docx"
        self.assertTrue(docx.exists())
        from docx import Document
        text = "\n".join(p.text for p in Document(str(docx)).paragraphs)
        self.assertIn("Revenue grew", text)

    def test_unknown_pdf_action(self):
        out = fp.file_processor({"file_path": str(self._pdf()), "action": "rotate_pages"})
        self.assertIn("Unknown PDF action", out)


class TestDocxCreation(TempWorkspace):
    """Regression tests for the document-creation repairs."""

    def _create(self, name: str, instruction: str, title: str) -> tuple[Path, str]:
        dest = self.dir / name
        # Force the deterministic fallback path (no model call) but keep the
        # real python-docx rendering that is under test.
        with mock.patch.object(fp, "_gemini_client", side_effect=RuntimeError("offline")):
            fp._fp_cache = None
            out = fp.file_processor({"action": "create", "file_path": str(dest),
                                     "title": title, "instruction": instruction})
        return dest, out

    def test_explicit_absolute_path_is_honoured(self):
        dest, out = self._create("report.docx", "# One\nBody text.", "Report")
        self.assertTrue(dest.exists(), f"file not saved at requested path; output={out!r}")
        self.assertIn(str(dest), out)

    def test_not_opened_claim_is_not_made_when_open_was_skipped(self):
        class Player:
            def ask_decision(self, q, o, **kw):
                return o[0]

            def ask_permission(self, **kw):
                return "deny"

            def write_log(self, *a, **k):
                pass

            def creation_event(self, *a, **k):
                pass

            def creation_progress(self, *a, **k):
                pass

            def creation_complete(self, *a, **k):
                pass

            def begin_creation(self, *a, **k):
                pass

        dest = self.dir / "noperm.docx"
        with mock.patch.object(fp, "_gemini_client", side_effect=RuntimeError("offline")), \
             mock.patch.object(fp, "_open_file_default") as opener:
            fp._fp_cache = None
            out = fp.file_processor({"action": "create", "file_path": str(dest),
                                     "title": "T", "instruction": "# A\nb"}, player=Player())
        self.assertFalse(opener.called)
        self.assertNotIn("Opened in Word", out)
        self.assertIn("Not opened", out)

    def test_markdown_bold_becomes_bold_runs_not_asterisks(self):
        from docx import Document
        dest = self.dir / "md.docx"
        with mock.patch.object(fp, "_gemini_client", side_effect=RuntimeError("offline")):
            fp._fp_cache = None
            fp.file_processor({"action": "create", "file_path": str(dest), "title": "MD",
                               "instruction": "## Section\n- **Achieve** 20% growth\n**Plain heading**"})
        doc = Document(str(dest))
        text = "\n".join(p.text for p in doc.paragraphs)
        self.assertNotIn("**", text, "literal markdown asterisks leaked into the document")
        self.assertIn("Achieve", text)
        styles = {p.style.name for p in doc.paragraphs}
        self.assertIn("Heading 2", styles)
        bold_runs = [r for p in doc.paragraphs for r in p.runs if r.bold]
        self.assertTrue(bold_runs, "no bold run produced from **...**")

    def test_numbered_list_uses_list_number_style(self):
        from docx import Document
        dest = self.dir / "nums.docx"
        with mock.patch.object(fp, "_gemini_client", side_effect=RuntimeError("offline")):
            fp._fp_cache = None
            fp.file_processor({"action": "create", "file_path": str(dest), "title": "N",
                               "instruction": "1. First step\n2. Second step"})
        styles = [p.style.name for p in Document(str(dest)).paragraphs]
        self.assertIn("List Number", styles)


class TestJsonExtraction(unittest.TestCase):
    """Slides/rows must survive fenced output and nested arrays.

    Regression: a non-greedy regex silently failed on ```json fences and on
    arrays of objects, so decks were replaced by a canned template whose text
    had nothing to do with the request.
    """

    def test_fenced_object_array(self):
        raw = '```json\n[{"title": "A", "content": "x"}, {"title": "B", "content": "y"}]\n```'
        self.assertEqual([s["title"] for s in fp._extract_json(raw)], ["A", "B"])

    def test_prose_prefix_is_ignored(self):
        raw = 'Here are the slides:\n[{"title": "Only"}]\nHope that helps.'
        self.assertEqual(fp._extract_json(raw)[0]["title"], "Only")

    def test_nested_rows(self):
        raw = '[["Name", "Score"], ["Alice", 95], ["Bob", 87]]'
        rows = fp._extract_json(raw)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][0], "Alice")

    def test_literal_newlines_inside_strings(self):
        """Local models emit raw control chars inside JSON strings.

        Regression: json.loads raised 'Invalid control character', the PPTX
        path swallowed it and silently built the canned "Prepared by Keys.ai"
        deck instead of the requested slides.
        """
        raw = '```json\n[{"title": "A", "content": "line1\nline2"}]\n```'
        self.assertIn("line1", fp._extract_json(raw)[0]["content"])

    def test_real_model_output_with_doubled_quotes(self):
        """Fixture captured from qwen3:8b: fenced array with ""title": keys."""
        fixture = BASE / "qa_artifacts" / "fixtures" / "pptx_model_output.txt"
        if not fixture.exists():
            self.skipTest("fixture not captured")
        slides = fp._extract_json(fixture.read_text(encoding="utf-8"), "[")
        self.assertIsInstance(slides, list)
        self.assertGreaterEqual(len(slides), 5)
        self.assertTrue(all(isinstance(s, dict) and s.get("title") for s in slides))

    def test_placeholder_lines_are_stripped(self):
        text = ("Title: Sparse Retrieval\nPresenter: [Your Name]\n"
                "Affiliation: [Your Institution]\nReal content [1] stays.")
        cleaned = fp._strip_placeholder_lines(text)
        self.assertNotIn("Your Name", cleaned)
        self.assertNotIn("Your Institution", cleaned)
        self.assertIn("Real content [1] stays.", cleaned)

    def test_salvage_recovers_broken_slides(self):
        broken = ('[{"""title": "Problem" "content": "crops lost"},'
                  '{"title": "Solution", "content": "sensors"},]')
        slides = fp._salvage_slides(broken)
        self.assertEqual([s["title"] for s in slides], ["Problem", "Solution"])
        self.assertEqual(slides[0]["content"], "crops lost")

    def test_salvage_returns_empty_for_prose(self):
        self.assertEqual(fp._salvage_slides("I cannot help with that."), [])

    def test_no_json_raises(self):
        with self.assertRaises(ValueError):
            fp._extract_json("I cannot help with that.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
