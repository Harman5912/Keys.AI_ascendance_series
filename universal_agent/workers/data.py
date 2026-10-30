"""Data worker — read a real dataset, compute real aggregates, write a workbook.

Supported inputs: CSV and Excel (.xlsx/.xlsm). The original file is never
modified; outputs go to the task workspace.

What is handled explicitly (and reported, not hidden): empty worksheets,
missing or duplicate headers, empty cells, dates, numbers stored as strings,
and mixed-type columns. Aggregates are computed from the rows — a column that
is not mostly numeric is described, not averaged.

No forecasting, correlation or significance claim is made from a handful of
rows: when the sample is too small the report says so.
"""

from __future__ import annotations

import csv
import datetime as _dt
import math
import re
from pathlib import Path

from universal_agent import intake, security
from universal_agent.workers import Context, title_for

MAX_ROWS = 20_000
MAX_COLS = 200


def _clean_header(value, index: int) -> str:
    text = " ".join(str(value if value is not None else "").split())
    return text[:80] or f"column_{index + 1}"


def _dedupe(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for name in headers:
        if name in seen:
            seen[name] += 1
            out.append(f"{name} ({seen[name]})")
        else:
            seen[name] = 1
            out.append(name)
    return out


def _csv_sheets(path: Path) -> dict[str, dict]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with open(path, newline="", encoding=encoding) as fh:
                sample = fh.read(8192)
                fh.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                except Exception:
                    dialect = csv.excel
                reader = csv.reader(fh, dialect)
                rows = [row for row in reader]
            break
        except UnicodeDecodeError:
            rows = None
            continue
        except Exception as exc:
            raise ValueError(f"CSV could not be read: {exc}")
    if rows is None:
        raise ValueError("CSV encoding could not be detected.")
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return {"csv": {"headers": [], "rows": [], "note": "empty file"}}
    headers = _dedupe([_clean_header(c, i) for i, c in enumerate(rows[0])])
    body = rows[1:]
    return {"csv": {"headers": headers, "rows": body,
                    "note": "" if body else "header row only"}}


def _xlsx_sheets(path: Path) -> dict[str, dict]:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(filename=str(path), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError(f"Workbook could not be opened: {exc}")
    sheets: dict[str, dict] = {}
    try:
        for ws in wb.worksheets:
            raw = []
            for row in ws.iter_rows(values_only=True):
                if row is None:
                    continue
                if any(c is not None and str(c).strip() != "" for c in row):
                    raw.append(list(row))
                if len(raw) > MAX_ROWS + 1:
                    break
            if not raw:
                sheets[ws.title] = {"headers": [], "rows": [],
                                    "note": "empty worksheet"}
                continue
            headers = _dedupe([_clean_header(c, i) for i, c in enumerate(raw[0])])
            body = [r[:MAX_COLS] for r in raw[1:]]
            sheets[ws.title] = {
                "headers": headers,
                "rows": body,
                "note": "" if body else "header row only",
            }
    finally:
        try:
            wb.close()
        except Exception:
            pass
    return sheets


def _to_number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_date(value):
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value
    text = str(value or "").strip()
    if not text or len(text) < 8:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d",
                "%Y-%m-%d %H:%M:%S", "%d-%m-%Y"):
        try:
            return _dt.datetime.strptime(text[:len(fmt) + 2].strip(), fmt)
        except Exception:
            continue
    return None


def _profile_column(name: str, values: list) -> dict:
    non_empty = [v for v in values if v is not None and str(v).strip() != ""]
    numbers = [n for n in (_to_number(v) for v in non_empty) if n is not None]
    dates = [d for d in (_to_date(v) for v in non_empty) if d is not None]
    distinct = {str(v).strip() for v in non_empty}
    profile = {
        "name": name,
        "non_empty": len(non_empty),
        "empty": len(values) - len(non_empty),
        "distinct": len(distinct),
        "numeric": len(numbers),
        "dates": len(dates),
        "numeric_as_text": sum(
            1 for v in non_empty
            if isinstance(v, str) and _to_number(v) is not None),
    }
    if numbers and len(numbers) >= max(1, int(len(non_empty) * 0.6)):
        profile["kind"] = "number"
        profile["count"] = len(numbers)
        profile["mean"] = sum(numbers) / len(numbers)
        profile["min"] = min(numbers)
        profile["max"] = max(numbers)
        profile["sum"] = sum(numbers)
    elif dates and len(dates) >= max(1, int(len(non_empty) * 0.6)):
        profile["kind"] = "date"
        profile["earliest"] = min(dates).strftime("%Y-%m-%d")
        profile["latest"] = max(dates).strftime("%Y-%m-%d")
    elif len(numbers) and len(numbers) < len(non_empty):
        profile["kind"] = "mixed"
    else:
        profile["kind"] = "text"
        if distinct:
            top = sorted(distinct, key=lambda v: (-sum(
                1 for x in non_empty if str(x).strip() == v), v))[0]
            profile["top"] = top
    return profile


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def _build_workbook(path: Path, sheets: dict[str, dict],
                    profiles: dict[str, list[dict]], primary: str) -> None:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference

    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"
    summary.append(["Dataset", path.name])
    summary.append(["Generated", _dt.datetime.now().strftime("%Y-%m-%d %H:%M")])
    summary.append([])
    summary.append(["Sheet", "Rows", "Columns", "Note"])
    for name, sheet in sheets.items():
        summary.append([name, len(sheet["rows"]), len(sheet["headers"]),
                        sheet.get("note") or ""])
    summary.append([])
    row = summary.max_row + 1
    summary.cell(row=row, column=1, value="Column profile")
    row += 1
    for header in ("Sheet", "Column", "Kind", "Non-empty", "Missing",
                   "Distinct", "Mean/Info"):
        summary.cell(row=row, column=1 + ("Sheet", "Column", "Kind",
                                          "Non-empty", "Missing", "Distinct",
                                          "Mean/Info").index(header),
                     value=header)
    row += 1
    numeric_rows: list[tuple[str, float]] = []
    for name, cols in profiles.items():
        for prof in cols:
            info = ""
            if prof["kind"] == "number":
                info = _fmt(prof["mean"])
                numeric_rows.append((f"{name}.{prof['name']}", prof["mean"]))
            elif prof["kind"] == "date":
                info = f"{prof.get('earliest')} → {prof.get('latest')}"
            elif prof["kind"] == "text":
                info = f"top: {prof.get('top', '')[:40]}"
            elif prof["kind"] == "mixed":
                info = "mixed types"
            summary.cell(row=row, column=1, value=name)
            summary.cell(row=row, column=2, value=prof["name"])
            summary.cell(row=row, column=3, value=prof["kind"])
            summary.cell(row=row, column=4, value=prof["non_empty"])
            summary.cell(row=row, column=5, value=prof["empty"])
            summary.cell(row=row, column=6, value=prof["distinct"])
            summary.cell(row=row, column=7, value=info)
            row += 1

    for width, letter in ((28, "A"), (32, "B"), (14, "C"), (12, "D"),
                          (10, "E"), (10, "F"), (30, "G")):
        summary.column_dimensions[letter].width = width

    if numeric_rows:
        start = summary.max_row + 2
        summary.cell(row=start - 1, column=1, value="Column means")
        summary.cell(row=start, column=1, value="Column")
        summary.cell(row=start, column=2, value="Mean")
        for i, (label, mean) in enumerate(numeric_rows[:12], 1):
            summary.cell(row=start + i, column=1, value=label)
            summary.cell(row=start + i, column=2, value=round(mean, 4))
        chart = BarChart()
        chart.title = "Mean by numeric column"
        chart.y_axis.title = "Mean"
        data = Reference(summary, min_col=2, min_row=start,
                         max_row=start + min(len(numeric_rows), 12))
        cats = Reference(summary, min_col=1, min_row=start + 1,
                         max_row=start + min(len(numeric_rows), 12))
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        chart.height, chart.width = 8, 18
        summary.add_chart(chart, "I2")

    raw = wb.create_sheet("Data")
    sheet = sheets.get(primary) or next(iter(sheets.values()))
    raw.append([h for h in sheet["headers"]] or ["(empty)"])
    for values in sheet["rows"][:MAX_ROWS]:
        raw.append([v if not isinstance(v, (_dt.date, _dt.time))
                    else str(v) for v in values])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))


def run(ctx: Context) -> dict:
    answers = ctx.task.get("answers") or {}
    raw_input = str(ctx.params.get("input_file") or answers.get("input_file")
                    or intake.extract_input_file(ctx.task.get("request") or ""))
    if not raw_input:
        return {"ok": False, "summary": "No dataset was supplied.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": "No CSV or Excel file was named in the request.",
                "notes": []}
    try:
        source = intake.resolve_input_path(raw_input)
    except security.SecurityError as exc:
        return {"ok": False, "summary": "The dataset path was refused.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": str(exc), "notes": []}

    suffix = source.suffix.lower()
    if suffix not in (".csv", ".xlsx", ".xlsm"):
        return {"ok": False, "summary": "Unsupported dataset type.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": (f"'{suffix or 'unknown'}' is not supported for data "
                          "analysis. Use CSV or .xlsx."),
                "notes": []}

    ctx.log(f"Data: reading {source.name}")
    try:
        sheets = (_csv_sheets(source) if suffix == ".csv"
                  else _xlsx_sheets(source))
    except Exception as exc:
        return {"ok": False, "summary": "The dataset could not be read.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": str(exc), "notes": []}

    usable = {name: s for name, s in sheets.items() if s["headers"]}
    if not usable:
        return {"ok": False, "summary": "The dataset has no readable table.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": ("Every worksheet was empty or had no header row; "
                          "there is nothing to analyse."),
                "notes": []}

    primary = max(usable, key=lambda n: len(usable[n]["rows"]))
    profiles: dict[str, list[dict]] = {}
    total_rows = 0
    for name, sheet in usable.items():
        total_rows += len(sheet["rows"])
        cols = []
        for idx, header in enumerate(sheet["headers"]):
            values = [row[idx] if idx < len(row) else None
                      for row in sheet["rows"]]
            cols.append(_profile_column(header, values))
        profiles[name] = cols
    if ctx.check_cancel():
        return {"ok": False, "summary": "Analysis cancelled.", "error": "cancelled"}

    title = title_for(str(ctx.task.get("request") or "")) or source.stem
    focus = str(ctx.params.get("focus") or answers.get("focus") or
                "Summarise the dataset and report its key numbers")

    warnings: list[str] = []
    for name, sheet in sheets.items():
        if sheet.get("note"):
            warnings.append(f"{name}: {sheet['note']}")
        gaps = sum(1 for col in profiles.get(name, []) if col["empty"])
        if gaps:
            warnings.append(f"{name}: {gaps} column(s) contain empty cells")
        for col in profiles.get(name, []):
            if col["kind"] == "mixed":
                warnings.append(
                    f"{name}.{col['name']}: mixed types "
                    f"({col['numeric']} numeric of {col['non_empty']})")
            if col["numeric_as_text"]:
                warnings.append(
                    f"{name}.{col['name']}: {col['numeric_as_text']} number(s) "
                    "stored as text")
    if total_rows < 10:
        warnings.append(
            f"Only {total_rows} data row(s) — conclusions are descriptive, not "
            "statistical.")

    def _limitations() -> list[str]:
        out = list(warnings)
        out.append("Averages and totals describe the supplied rows only; no "
                   "forecast, correlation or significance test is claimed.")
        if len(usable) > 1:
            out.append(f"{len(usable)} worksheets were profiled; the workbook "
                       f"output contains the largest one ('{primary}').")
        return out

    overview = [
        f"# Dataset analysis: {source.name}",
        "",
        f"Analysed: {_dt.datetime.now().strftime('%Y-%m-%d %H:%M')}  ·  "
        f"sheets: {len(usable)}  ·  rows: {total_rows}",
        "",
        "## Focus",
        "",
        focus,
        "",
        "## Sheets",
        "",
        "| Sheet | Rows | Columns | Note |",
        "|---|---|---|---|",
    ]
    for name, sheet in sheets.items():
        overview.append(f"| {name} | {len(sheet['rows'])} | "
                        f"{len(sheet['headers'])} | {sheet.get('note') or ''} |")

    overview += ["", "## Column profile (largest sheet)", "",
                 "| Column | Kind | Non-empty | Missing | Distinct | Key value |",
                 "|---|---|---|---|---|---|"]
    for prof in profiles[primary]:
        key = ""
        if prof["kind"] == "number":
            key = (f"mean {_fmt(prof['mean'])}, min {_fmt(prof['min'])}, "
                   f"max {_fmt(prof['max'])}")
        elif prof["kind"] == "date":
            key = f"{prof.get('earliest')} → {prof.get('latest')}"
        elif prof["kind"] == "text":
            key = f"top: {prof.get('top', '')[:40]}"
        elif prof["kind"] == "mixed":
            key = "mixed types"
        overview.append(
            f"| {prof['name']} | {prof['kind']} | {prof['non_empty']} | "
            f"{prof['empty']} | {prof['distinct']} | {key} |")

    numeric = [p for p in profiles[primary] if p["kind"] == "number"]
    if numeric:
        overview += ["", "## Key numbers", ""]
        for prof in numeric[:8]:
            overview.append(
                f"- **{prof['name']}** — total {_fmt(prof['sum'])}, "
                f"mean {_fmt(prof['mean'])}, range {_fmt(prof['min'])} to "
                f"{_fmt(prof['max'])} across {prof['count']} values.")

    overview += ["", "## Limitations", ""]
    overview += [f"- {line}" for line in _limitations()]
    report_path = ctx.write_text("analysis.md", "\n".join(overview).strip() + "\n")

    workbook_path = ctx.workspace / "analysis.xlsx"
    workbook_path = security.resolve_within(ctx.workspace, workbook_path)
    try:
        _build_workbook(workbook_path, sheets, profiles, primary)
    except Exception as exc:
        return {"ok": False, "summary": "The analysis workbook could not be written.",
                "artifacts": [ctx.artifact(report_path, "markdown",
                                           "Dataset analysis")],
                "evidence": [], "warnings": warnings,
                "error": f"Workbook write failed: {exc}", "notes": []}

    ctx.log(f"Data: {total_rows} rows, {len(numeric)} numeric column(s)")
    return {
        "ok": True,
        "summary": (f"Analysed {total_rows} row(s) across {len(usable)} "
                    f"sheet(s); {len(numeric)} numeric column(s)."),
        "artifacts": [
            ctx.artifact(report_path, "markdown", "Dataset analysis report"),
            ctx.artifact(workbook_path, "xlsx",
                         "Workbook with summary table and column chart"),
        ],
        "evidence": [],
        "warnings": warnings,
        "error": "",
        "notes": [f"primary sheet: {primary}"],
    }


__all__ = ["run"]
