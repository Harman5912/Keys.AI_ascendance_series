"""Group E — spreadsheets, analytics and dashboards.

Each test supplies a real CSV/XLSX file, runs the data worker, then checks the
values in the generated report and workbook against numbers computed here. A
test that only asserted "a file exists" would not prove the arithmetic, so the
expected aggregates are written out explicitly.

Messy data is the point: empty cells, duplicate and missing headers, dates,
numbers stored as text, mixed columns, header-only sheets and empty workbooks.
"""

from __future__ import annotations

import csv
import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openpyxl import Workbook, load_workbook  # noqa: E402

from universal_agent import validation  # noqa: E402
from universal_agent.workers import Context  # noqa: E402
from universal_agent.workers import data as data_worker  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ua_data_"))
        self.workspace = self.tmp / "workspace"
        self.workspace.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def csv(self, rows, name="data.csv") -> Path:
        path = self.tmp / name
        with open(path, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)
        return path

    def xlsx(self, sheets: dict, name="book.xlsx") -> Path:
        path = self.tmp / name
        wb = Workbook()
        first = True
        for title, rows in sheets.items():
            ws = wb.active if first else wb.create_sheet()
            ws.title = title
            first = False
            for row in rows:
                ws.append(row)
        wb.save(path)
        return path

    def run_worker(self, path, request=None, params=None) -> dict:
        request = request or f"Analyse {path} and chart the totals"
        return data_worker.run(
            self.ctx(request, {"input_file": str(path), **(params or {})}))

    def ctx(self, request: str, params=None) -> Context:
        task = {"id": "t1", "request": request, "answers": {},
                "plan": [], "artifacts": []}
        return Context(task=task, workspace=self.workspace, params=params or {})

    def report(self, result: dict) -> str:
        self.assertTrue(result["ok"], result.get("error"))
        path = Path(result["artifacts"][0]["path"])
        return path.read_text(encoding="utf-8")

    def workbook(self, result: dict):
        paths = [a for a in result["artifacts"] if a["path"].endswith(".xlsx")]
        self.assertTrue(paths, "no workbook artifact")
        return load_workbook(paths[0]["path"])


class TestDataReading(_Base):
    def test_single_sheet_csv(self):
        path = self.csv([["month", "revenue"], ["Jan", "10"], ["Feb", "20"]])
        text = self.report(self.run_worker(path))
        self.assertIn("| csv | 2 | 2 |", text)

    def test_multiple_worksheets_are_profiled(self):
        path = self.xlsx({
            "Sales": [["region", "amount"]] + [[f"R{i}", i * 10] for i in range(1, 6)],
            "Refunds": [["region", "amount"], ["R1", 5]],
        })
        text = self.report(self.run_worker(path))
        self.assertIn("Sales", text)
        self.assertIn("Refunds", text)
        self.assertIn("2 worksheets were profiled", text)

    def test_missing_header_cells_get_positional_names(self):
        path = self.csv([["name", ""], ["a", "1"], ["b", "2"]])
        text = self.report(self.run_worker(path))
        self.assertIn("column_2", text)

    def test_duplicate_headers_are_disambiguated(self):
        path = self.csv([["value", "value", "value"],
                         ["1", "2", "3"], ["4", "5", "6"]])
        text = self.report(self.run_worker(path))
        self.assertIn("value (2)", text)
        self.assertIn("value (3)", text)

    def test_empty_cells_are_counted_and_reported(self):
        path = self.csv([["name", "score"], ["a", "10"], ["b", ""], ["c", "30"]])
        text = self.report(self.run_worker(path))
        self.assertIn("empty cells", text)
        self.assertIn("| score | number | 2 | 1 |", text)

    def test_date_column_is_detected(self):
        path = self.csv([["date", "value"],
                         ["2026-01-01", "1"], ["2026-03-15", "2"],
                         ["2026-02-01", "3"]])
        text = self.report(self.run_worker(path))
        self.assertIn("2026-01-01 → 2026-03-15", text)

    def test_numbers_stored_as_text_are_coerced_and_flagged(self):
        path = self.csv([["item", "price"],
                         ["a", "10"], ["b", "20"], ["c", "30"]])
        text = self.report(self.run_worker(path))
        self.assertIn("stored as text", text)
        self.assertIn("mean 20", text)

    def test_mixed_type_column_is_described_not_averaged(self):
        path = self.csv([["label", "value"],
                         ["a", "10"], ["b", "n/a"], ["c", "thirty"],
                         ["d", "40"], ["e", "unknown"]])
        text = self.report(self.run_worker(path))
        self.assertIn("mixed types", text)
        self.assertNotIn("| value | number |", text)

    def test_header_only_sheet_is_reported_as_empty_of_rows(self):
        path = self.xlsx({"Only": [["region", "amount"]]})
        result = self.run_worker(path)
        self.assertTrue(result["ok"], result.get("error"))
        text = self.report(result)
        self.assertIn("header row only", text)

    def test_completely_empty_workbook_fails_clearly(self):
        path = self.tmp / "empty.xlsx"
        Workbook().save(path)
        result = self.run_worker(path)
        self.assertFalse(result["ok"])
        self.assertIn("nothing to analyse", result["error"])

    def test_formula_only_cells_do_not_crash_the_reader(self):
        path = self.tmp / "formulas.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "Calc"
        ws.append(["a", "b", "total"])
        for i in range(1, 12):
            ws.append([i, i * 2, f"=SUM(A{i+1}:B{i+1})"])
        wb.save(path)
        result = self.run_worker(path)
        self.assertTrue(result["ok"], result.get("error"))
        # Cached values are absent without an engine, so the column reads as
        # empty rather than silently as zero.
        self.assertIn("empty cells", self.report(result))


class TestDataAnalysis(_Base):
    def _sales(self) -> Path:
        rows = [["region", "units", "revenue"]]
        for i in range(1, 13):
            rows.append([f"R{i}", str(i * 2), str(i * 100)])
        return self.csv(rows)

    def test_aggregates_match_the_rows(self):
        text = self.report(self.run_worker(self._sales()))
        # units: 2..24 → sum 156, mean 13, min 2, max 24
        self.assertIn("total 156", text)
        self.assertIn("mean 13", text)
        # revenue: 100..1200 → sum 7,800, mean 650
        self.assertIn("total 7,800", text)
        self.assertIn("mean 650", text)
        self.assertIn("100 to 1,200", text)

    def test_small_sample_is_flagged_as_descriptive(self):
        path = self.csv([["value"], ["1"], ["2"], ["3"]])
        text = self.report(self.run_worker(path))
        self.assertIn("Only 3 data row(s)", text)
        self.assertIn("not statistical", text)

    def test_report_states_its_own_limits(self):
        text = self.report(self.run_worker(self._sales()))
        self.assertIn("no forecast, correlation or significance test", text)

    def test_focus_from_answers_appears_in_the_report(self):
        path = self._sales()
        result = data_worker.run(self.ctx(
            f"Analyse {path}",
            {"input_file": str(path), "focus": "Which region sells most?"}))
        self.assertIn("Which region sells most?", self.report(result))

    def test_workbook_has_summary_and_data_sheets(self):
        wb = self.workbook(self.run_worker(self._sales()))
        try:
            self.assertEqual(wb.sheetnames, ["Summary", "Data"])
        finally:
            wb.close()

    def test_workbook_contains_a_chart(self):
        wb = self.workbook(self.run_worker(self._sales()))
        try:
            charts = sum(len(getattr(ws, "_charts", []) or [])
                         for ws in wb.worksheets)
            self.assertGreaterEqual(charts, 1)
        finally:
            wb.close()

    def test_workbook_keeps_the_rows_it_analysed(self):
        wb = self.workbook(self.run_worker(self._sales()))
        try:
            ws = wb["Data"]
            self.assertEqual(ws["A1"].value, "region")
            self.assertEqual(ws.max_row, 13)
        finally:
            wb.close()

    def test_generated_workbook_passes_validation(self):
        result = self.run_worker(self._sales())
        workbook = [a for a in result["artifacts"] if a["path"].endswith(".xlsx")]
        check = validation.validate_artifact(workbook[0]["path"],
                                             self.workspace)
        self.assertTrue(check["ok"], check["detail"])
        self.assertIn("chart(s)", check["detail"])

    def test_original_dataset_is_never_modified(self):
        path = self._sales()
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertTrue(self.run_worker(path)["ok"])
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_unrelated_source_worksheets_are_untouched(self):
        path = self.xlsx({
            "Sales": [["region", "amount"]] + [[f"R{i}", i] for i in range(12)],
            "Archive": [["note"], ["keep me"]],
        })
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        result = self.run_worker(path)
        self.assertTrue(result["ok"])
        self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertIn("Archive", self.report(result))

    def test_output_workbook_is_a_new_file(self):
        path = self._sales()
        result = self.run_worker(path)
        workbook = Path([a for a in result["artifacts"]
                         if a["path"].endswith(".xlsx")][0]["path"])
        self.assertNotEqual(workbook, path)
        self.assertEqual(workbook.parent, self.workspace.resolve())


class TestDataFailures(_Base):
    def test_unsupported_dataset_type_is_named(self):
        path = self.tmp / "notes.txt"
        path.write_text("just text\n", encoding="utf-8")
        result = self.run_worker(path)
        self.assertFalse(result["ok"])
        self.assertIn(".txt", result["error"])

    def test_missing_dataset_is_requested_clearly(self):
        result = data_worker.run(self.ctx("Analyse my spreadsheet"))
        self.assertFalse(result["ok"])
        self.assertIn("No CSV or Excel file", result["error"])

    def test_nonexistent_dataset_is_refused(self):
        result = self.run_worker(self.tmp / "absent.csv")
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["error"].lower())

    def test_unwritable_workbook_fails_instead_of_claiming_success(self):
        path = self.csv([["a"], ["1"], ["2"]])
        with mock.patch.object(data_worker, "_build_workbook",
                               side_effect=PermissionError("disk is read-only")):
            result = self.run_worker(path)
        self.assertFalse(result["ok"])
        self.assertIn("disk is read-only", result["error"])
        self.assertFalse([a for a in result["artifacts"]
                          if a["path"].endswith(".xlsx")])

    def test_cancellation_is_honoured_before_writing_outputs(self):
        path = self.csv([["a"], ["1"], ["2"]])
        ctx = self.ctx(f"Analyse {path}", {"input_file": str(path)})
        ctx.should_cancel = lambda: True
        result = data_worker.run(ctx)
        self.assertFalse(result["ok"])
        self.assertIn("cancel", result["error"].lower())
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_invalid_output_workbook_is_caught_by_validation(self):
        # A workbook that opens is not automatically a valid one: an empty file
        # must be rejected by the validator the service uses.
        bad = self.workspace / "broken.xlsx"
        bad.write_bytes(b"not a zip")
        check = validation.validate_artifact(bad, self.workspace)
        self.assertFalse(check["ok"])
        self.assertIn("could not be reopened", check["detail"])

    def test_text_column_is_not_summarised_as_a_number(self):
        path = self.csv([["name"], ["Ada"], ["Grace"], ["Alan"]])
        text = self.report(self.run_worker(path))
        self.assertIn("| name | text |", text)
        self.assertNotIn("mean", text.split("## Key numbers")[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
