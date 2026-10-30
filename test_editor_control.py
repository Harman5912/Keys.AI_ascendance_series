"""Offscreen unit tests for the editor_control tool (Copilot-style visual editing).

Run: python test_editor_control.py
Covers: app picking, open/edit/insert/verify dispatch, UI-drive success + fallback,
office-doc routing, and new-file creation. All heavy deps mocked.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from actions import editor_control as ec  # noqa: E402


class AppPickTests(unittest.TestCase):
    def test_code_file_picks_vscode(self):
        self.assertEqual(ec._pick_app(Path("main.py")), "vscode")
        self.assertEqual(ec._pick_app(Path("app.js")), "vscode")

    def test_docs_pick_office(self):
        self.assertEqual(ec._pick_app(Path("r.docx")), "word")
        self.assertEqual(ec._pick_app(Path("s.xlsx")), "excel")
        self.assertEqual(ec._pick_app(Path("t.pptx")), "powerpoint")


class DispatchTests(unittest.TestCase):
    def test_missing_file_path(self):
        out = ec.editor_control({"action": "edit"})
        self.assertIn("file_path", out)

    def test_unknown_action(self):
        out = ec.editor_control({"action": "nope", "file_path": "x.py"})
        self.assertIn("Unknown editor_control action", out)

    def test_edit_requires_content(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.py"
            p.write_text("x = 1", encoding="utf-8")
            out = ec.editor_control({"action": "edit", "file_path": str(p)})
        self.assertIn("Provide 'content'", out)

    def test_open_reports_success(self):
        with mock.patch.object(ec, "_launch", return_value=True) as m:
            out = ec.editor_control({"action": "open", "file_path": "C:/tmp/a.py"})
        m.assert_called_once()
        self.assertIn("Opened a.py", out)

    def test_open_reports_failure(self):
        with mock.patch.object(ec, "_launch", return_value=False):
            out = ec.editor_control({"action": "open", "file_path": "C:/tmp/a.py"})
        self.assertIn("Could not open", out)


class EditFlowTests(unittest.TestCase):
    def test_new_file_created_and_opened(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "new.py"
            with mock.patch.object(ec, "_launch", return_value=True) as m:
                out = ec.editor_control(
                    {"action": "edit", "file_path": str(p), "content": "print(1)"}
                )
            m.assert_called_once()
            self.assertIn("Created and opened", out)
            self.assertEqual(p.read_text(encoding="utf-8"), "print(1)")

    def test_visual_edit_verified(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "app.py"
            p.write_text("old", encoding="utf-8")
            with mock.patch.object(ec, "_launch", return_value=True), \
                 mock.patch.object(ec, "_drive_visual_edit",
                                   return_value="Verified: app.py on disk matches the new content.") as dv:
                out = ec.editor_control(
                    {"action": "edit", "file_path": str(p), "content": "new"}
                )
            dv.assert_called_once()
            self.assertIn("like Copilot", out)

    def test_visual_edit_falls_back_to_direct_write(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "app.py"
            p.write_text("old", encoding="utf-8")
            with mock.patch.object(ec, "_launch", return_value=True), \
                 mock.patch.object(ec, "_drive_visual_edit", return_value=""):
                out = ec.editor_control(
                    {"action": "edit", "file_path": str(p), "content": "new"}
                )
            self.assertIn("written directly", out)
            self.assertEqual(p.read_text(encoding="utf-8"), "new")

    def test_edit_when_app_cannot_launch(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "app.py"
            p.write_text("old", encoding="utf-8")
            with mock.patch.object(ec, "_launch", return_value=False):
                out = ec.editor_control(
                    {"action": "edit", "file_path": str(p), "content": "new"}
                )
            self.assertIn("could not open", out)
            self.assertEqual(p.read_text(encoding="utf-8"), "new")


class OfficeRoutingTests(unittest.TestCase):
    def test_office_doc_edit_uses_library_then_opens(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.docx"
            p.write_text("fake", encoding="utf-8")
            with mock.patch.object(ec, "_office_edit", return_value="Edited r.docx.") as oe, \
                 mock.patch.object(ec, "_launch", return_value=True) as m:
                out = ec.editor_control(
                    {"action": "edit", "file_path": str(p),
                     "find": "a", "replace": "b"}
                )
            oe.assert_called_once()
            m.assert_called_once()
            self.assertIn("Edited r.docx", out)
            self.assertIn("Word", out)  # app name shown

    def test_office_content_only_is_rejected(self):
        """Raw full-text content cannot be applied to structured office formats -
        the edit must not silently do nothing while reporting success."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.docx"
            p.write_text("fake", encoding="utf-8")
            with mock.patch.object(ec, "_office_edit") as oe, \
                 mock.patch.object(ec, "_launch") as m:
                out = ec.editor_control(
                    {"action": "edit", "file_path": str(p), "content": "totally new doc"}
                )
            oe.assert_not_called()
            m.assert_not_called()
            self.assertIn("Structured office documents", out)


class InsertVerifyTests(unittest.TestCase):
    def test_insert_appends_directly_when_launch_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "n.txt"
            p.write_text("hi", encoding="utf-8")
            with mock.patch.object(ec, "_launch", return_value=False):
                out = ec.editor_control(
                    {"action": "insert", "file_path": str(p), "text": " there"}
                )
            self.assertIn("Appended", out)
            self.assertEqual(p.read_text(encoding="utf-8"), "hi there")

    def test_verify_matches(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "v.txt"
            p.write_text("abc", encoding="utf-8")
            out = ec.editor_control(
                {"action": "verify", "file_path": str(p), "expected": "abc"}
            )
        self.assertIn("Verified", out)

    def test_verify_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "v.txt"
            p.write_text("abc", encoding="utf-8")
            out = ec.editor_control(
                {"action": "verify", "file_path": str(p), "expected": "xyz"}
            )
        self.assertIn("mismatch", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
