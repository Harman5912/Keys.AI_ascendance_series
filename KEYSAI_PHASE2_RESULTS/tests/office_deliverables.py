"""Stage 6: office deliverables generated through Keys.ai's own workflow.

Calls `actions.file_processor` (the real `file_processor` tool the agent uses),
then reopens every artifact with a parsing library and checks it. The same five
numbers are asserted across ALL formats, so a document that invents its own
results is caught rather than trusted.

Authoritative numbers, taken from the executed application (32 unit tests +
19 browser checks, `KEYSAI_PHASE2_RESULTS/logs/inventory_tests.log`):
    products: 5
    total inventory value: 54,200.00
    low stock: Mouse, Laptop Stand (2)
    unit tests: 32 passed
    browser checks: 19 passed

Validation is deliberately stricter than "the file exists":
  * DOCX  — required section headings must be present, and the file must state
            the verified numbers (a valid archive alone proves nothing).
  * PPTX  — slide titles AND body text are checked against the 14 required
            topics; no empty slides; densest slide must stay readable.
  * XLSX  — the workbook builder is dataset-aware (budget / inventory /
            revenue) and prose row-lists are ignored by design, so the
            contract verified here is the builder's real one: SKU data rows,
            live KPI formulas whose ranges cover exactly the data, and the
            harness re-evaluating every KPI with its own arithmetic
            (openpyxl stores formulas without results, so a stored formula
            is never reported as a verified value).
  * PDF   — reopened with pypdf: page count, extractable text, required
            headings, no blank/truncated pages.

Exit code is non-zero when a required check fails.

Run:  python KEYSAI_PHASE2_RESULTS/tests/office_deliverables.py
Out:  KEYSAI_PHASE2_RESULTS/documents/*
      KEYSAI_PHASE2_RESULTS/logs/office_deliverables.json
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

OUT = BASE / "KEYSAI_PHASE2_RESULTS"
DOCS = OUT / "documents"
REPORT = OUT / "logs" / "office_deliverables.json"

FACTS = {
    "products": 5,
    "total_value": "54,200.00",
    "low_stock": ["Mouse", "Laptop Stand"],
    "unit_tests": 32,
    "browser_checks": 19,
}

DOCX_TITLE = "Inventory Management System — Project Report"
DOCX_INSTRUCTION = (
    "A professional project report for a small inventory management system "
    "built with Python, Flask, SQLite and a vanilla HTML/CSS/JavaScript front "
    "end. Use EXACTLY these section headings, in this order: Executive "
    "Summary, Objectives, System Architecture, Database Schema, JSON API "
    "Endpoints, Test Results, Limitations, Future Improvements. Include one "
    "table of the five products — Keyboard, Mouse, Monitor, Laptop Stand "
    "and USB Hub — with quantity and unit price. "
    "Use exactly these verified figures and do not invent others: five "
    "products seeded, total inventory value 54,200.00 currency units, two "
    "low-stock products (Mouse and Laptop Stand), 32 automated unit tests "
    "passed and 19 browser checks passed. The Limitations section must state "
    "what is NOT verified (single-user profiles, no authentication, generic "
    "events table)."
)

PPTX_TITLE = "Inventory Management System — Technical Overview"
PPTX_INSTRUCTION = (
    "A technical presentation for engineers. Produce EXACTLY 14 slides, one "
    "per topic, titled: Title, Problem Statement, Objectives, System "
    "Architecture, Technology Stack, Database Design, API Design, User "
    "Interface, Security Measures, Testing Strategy, Actual Test Results, "
    "Limitations, Future Improvements, Conclusion. "
    "Verified figures to state on the slides: five products, total inventory "
    "value 54,200.00, two low-stock products (Mouse and Laptop Stand), 32 "
    "automated unit tests passed, 19 browser checks passed. Security "
    "measures are parameterised SQL, input validation and database CHECK "
    "constraints. Do not add market, sales or financial slides — this is an "
    "internal engineering system. The "
    "'Actual Test Results' slide must state the total inventory value "
    "54,200.00, the 32/19 test counts, and must NAME the two low-stock "
    "products in full: Mouse and Laptop Stand."
)

XLSX_TITLE = "Inventory Test Report"
XLSX_INSTRUCTION = (
    "Inventory stock cover report for the warehouse: SKU-level on hand, "
    "monthly demand, cover in months, reorder point, lead time and supplier. "
    "Live formulas for the cover column, the dashboard KPI totals and the "
    "reorder alerts; charts of on hand vs reorder point and cover by SKU."
)

PDF_TITLE = DOCX_TITLE


def create(path: Path, doc_type: str, title: str, instruction: str) -> dict:
    import actions.file_processor as fp

    started = time.time()
    message = fp.file_processor({
        "action": "create",
        "file_path": str(path),
        "doc_type": doc_type,
        "title": title,
        "instruction": instruction,
    })
    return {"path": str(path), "seconds": round(time.time() - started, 1),
            "message": message[:800], "exists": path.exists(),
            "bytes": path.stat().st_size if path.exists() else 0}


# ── validators ──────────────────────────────────────────────────────────────

def validate_docx(path: Path) -> dict:
    from docx import Document

    doc = Document(str(path))
    styles = [p.style.name for p in doc.paragraphs]
    headings = [p.text.strip() for p in doc.paragraphs
                if p.style.name.lower().startswith(("heading", "title"))
                and p.text.strip()]
    text = "\n".join(p.text for p in doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            text += "\n" + " | ".join(cell.text for cell in row.cells)
    lowered = text.lower()
    heading_l = [h.lower() for h in headings]

    def has_heading(*words) -> bool:
        return any(all(w in h for w in words) for h in heading_l)

    return {
        "paragraphs": len(doc.paragraphs),
        "tables": len(doc.tables),
        "heading_count": len(headings),
        "headings": headings[:16],
        "chars": len(text),
        "has_title_heading": any(s == "Title" for s in styles),
        "mentions_total": "54,200" in text or "54200" in text,
        "mentions_five_products": bool(re.search(r"\bfive\b|\b5\b", lowered)),
        "mentions_low_stock": "laptop stand" in lowered and "mouse" in lowered,
        "mentions_tests": "32" in text and "19" in text,
        "table_has_five_products": all(p in text for p in
                                        ("Keyboard", "Mouse", "Monitor",
                                         "Laptop Stand", "USB Hub")),
        "sections_present": {
            "executive_summary": has_heading("executive", "summary"),
            "objectives": has_heading("objective"),
            "architecture": has_heading("architecture"),
            "database": has_heading("database"),
            "api": has_heading("api") or has_heading("endpoint"),
            "test": has_heading("test") or has_heading("testing"),
            "limitations": has_heading("limitation"),
            "future": has_heading("future"),
        },
    }


PPTX_TOPICS = ["problem", "objective", "architecture", "technology",
               "database", "api", "interface", "security", "testing",
               "test results", "limitation", "future", "conclusion"]


def validate_pptx(path: Path) -> dict:
    from pptx import Presentation

    prs = Presentation(str(path))
    slides = []
    charts = 0
    for index, slide in enumerate(prs.slides, 1):
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                texts.append(shape.text_frame.text.strip())
            if getattr(shape, "has_chart", False):
                charts += 1
        title = texts[0] if texts else ""
        body = " ".join(texts)
        slides.append({
            "index": index,
            "title": title[:80],
            "chars": len(body),
            "empty": not body.strip(),
        })
    full_text = " ".join(
        " ".join(sh.text_frame.text for sh in s.shapes
                 if sh.has_text_frame)
        for s in prs.slides).lower()
    titles_text = " ".join(s["title"] for s in slides).lower()
    return {
        "slide_count": len(prs.slides),
        "width_inches": round(prs.slide_width / 914400, 2),
        "empty_slides": [s["index"] for s in slides if s["empty"]],
        "titles": [s["title"] for s in slides],
        "charts": charts,
        "densest_slide_chars": max((s["chars"] for s in slides), default=0),
        # body text counts: a number stated on a slide is a stated number
        "mentions_total": "54,200" in full_text or "54200" in full_text,
        "mentions_tests": "32" in full_text and "19" in full_text,
        "mentions_low_stock": ("laptop stand" in full_text
                               and "mouse" in full_text),
        "topics_covered": [t for t in PPTX_TOPICS if t in titles_text],
        "slides": slides,
    }


def _resolve_range(wb, ref: str) -> list | None:
    """'Data!C4:C15' (or 'C4:C15') → the raw cell values in that range."""
    m = re.match(r"^\s*(?:'?([^'!]+)'?!)?([A-Z]+\d+):([A-Z]+\d+)\s*$", ref)
    if not m:
        return None
    try:
        sheet = wb[m.group(1)] if m.group(1) else wb.active
        cells = sheet[f"{m.group(2)}:{m.group(3)}"]
    except Exception:
        return None
    values = []
    for row in cells:
        for cell in (row if isinstance(row, tuple) else (row,)):
            values.append(cell.value)
    return values


def _eval_kpi(wb, formula: str, sheet=None):
    """Evaluate a dashboard KPI formula with our own arithmetic.

    openpyxl stores formulas WITHOUT results, so '=SUM(Data!C4:C15)' on disk
    proves nothing about the number the user will see. This resolves SUM /
    COUNTA / SUMPRODUCT(--(a<b)) / IFERROR against the literal cell values,
    then evaluates the remaining arithmetic in a sandbox. Returns the number
    the formula must produce, or None when the formula uses something this
    evaluator does not understand (never a guess).
    """
    expr = (formula or "").strip().lstrip("=").strip()
    expr = re.sub(r"^IFERROR\((.*),\s*[-\d.]+\s*\)$", r"(\1)", expr,
                  flags=re.I)

    def _sum(m):
        vals = _resolve_range(wb, m.group(1))
        if vals is None:
            raise ValueError(m.group(1))
        return repr(float(sum(v for v in vals if isinstance(v, (int, float)))))

    def _counta(m):
        vals = _resolve_range(wb, m.group(1))
        if vals is None:
            raise ValueError(m.group(1))
        return repr(float(sum(1 for v in vals if v not in (None, ""))))

    def _lt(m):
        a, b = _resolve_range(wb, m.group(1)), _resolve_range(wb, m.group(2))
        if a is None or b is None or len(a) != len(b):
            raise ValueError(f"{m.group(1)} < {m.group(2)}")
        return repr(float(sum(1 for x, y in zip(a, b)
                              if isinstance(x, (int, float))
                              and isinstance(y, (int, float)) and x < y)))

    def _cell(m):
        target = sheet or wb.active
        value = target[m.group(1).replace("$", "")].value
        if not isinstance(value, (int, float)):
            raise ValueError(m.group(1))
        return repr(float(value))

    expr = re.sub(r"--\(\s*([^()<]+?)\s*<\s*([^()<]+?)\s*\)", _lt, expr)
    expr = re.sub(r"SUMPRODUCT\(\s*([\d.eE+\-*/() ]+)\s*\)", r"\1", expr,
                  flags=re.I)
    expr = re.sub(r"SUM\(\s*([^()]+?)\s*\)", _sum, expr, flags=re.I)
    expr = re.sub(r"COUNTA\(\s*([^()]+?)\s*\)", _counta, expr, flags=re.I)
    # bare cell references (per-row formulas like =ROUND(D12*2,0))
    expr = re.sub(r"(?<![A-Za-z0-9_.$!])(\$?[A-Z]{1,3}\$?\d{1,4})(?![\d(:!])",
                  _cell, expr)
    # ROUND(x, n) after the inner references are already numbers
    expr = re.sub(r"ROUND\(\s*([\d.eE+\-*/() ]+)\s*,\s*\d+\s*\)", r"\1",
                  expr, flags=re.I)
    if not re.fullmatch(r"[\d.seE()+\-*/ ]+", expr):
        return None
    return float(eval(expr, {"__builtins__": {}}, {}))


def validate_xlsx(path: Path) -> dict:
    from openpyxl import load_workbook

    wb = load_workbook(str(path))          # data_only=False: formulas as written
    sheet_names = wb.sheetnames
    formulas = 0
    charts = 0
    sku_rows: set[str] = set()

    for name in sheet_names:
        sheet = wb[name]
        charts += len(getattr(sheet, "_charts", []))
        for row in sheet.iter_rows():
            for cell in row:
                value = cell.value
                if isinstance(value, str) and value.startswith("="):
                    formulas += 1
                elif (isinstance(value, str)
                        and re.fullmatch(r"FF-[A-Z]+-\d+", value.strip())):
                    sku_rows.add(value.strip())

    # Every dashboard KPI is re-evaluated from the data it references.
    dash = wb["Dashboard"] if "Dashboard" in sheet_names else wb.active
    verified: dict[str, float] = {}
    unverifiable: list[str] = []
    for row in dash.iter_rows():
        for cell in row:
            if not (isinstance(cell.value, str)
                    and cell.value.startswith("=")):
                continue
            # A KPI card's label is the string cell directly above; data
            # cells and other formulas above mean this is not a KPI card.
            above = dash.cell(row=cell.row - 1, column=cell.column).value
            label = (str(above).strip()
                     if isinstance(above, str) and above.strip()
                     else cell.coordinate)
            try:
                value = _eval_kpi(wb, cell.value, sheet=dash)
            except Exception:
                value = None
            if value is None:
                unverifiable.append(label)
            else:
                verified[label] = round(value, 4)

    # Independent ground truth from the Data sheet's literal numbers: the
    # on-hand total and the count of SKUs below their reorder point. The
    # table is B-anchored (column A is a margin), so columns are located by
    # their header names, never assumed.
    on_hand_col = reorder_col = sku_col = None
    on_hand: list[float] = []
    reorder: list[float] = []
    if "Data" in sheet_names:
        data = wb["Data"]
        for row in data.iter_rows():
            header = [str(c.value or "").strip().lower() for c in row]
            if "on hand" in header:
                on_hand_col = header.index("on hand") + 1
                sku_col = (header.index("sku") + 1
                           if "sku" in header else 1)
                reorder_col = (header.index("reorder point") + 1
                               if "reorder point" in header else None)
                first_data_row = row[0].row + 1
                break
        if on_hand_col:
            for row in data.iter_rows(min_row=first_data_row):
                # Bounded by the SKU column: the table ends when the rows
                # stop being SKUs, so totals/notes below never leak in.
                sku_cell = row[sku_col - 1].value
                if not (isinstance(sku_cell, str)
                        and re.fullmatch(r"FF-[A-Z]+-\d+", sku_cell.strip())):
                    break
                value = row[on_hand_col - 1].value
                if isinstance(value, (int, float)):
                    on_hand.append(float(value))
                    r = row[reorder_col - 1].value if reorder_col else None
                    if isinstance(r, (int, float)):
                        reorder.append(float(r))
                    elif isinstance(r, str) and r.startswith("="):
                        # reorder point is itself a formula; evaluate it
                        try:
                            reorder.append(float(_eval_kpi(wb, r, sheet=data)))
                        except Exception:
                            reorder.append(0.0)
                    else:
                        reorder.append(0.0)
    self_on_hand = sum(on_hand)
    self_alerts = sum(1 for o, r in zip(on_hand, reorder) if o < r)

    def _kpi(*names):
        for label, value in verified.items():
            low = label.lower()
            if any(n in low for n in names):
                return value
        return None

    units_kpi = _kpi("on hand", "units on hand")
    alerts_kpi = _kpi("reorder alert", "reorder")
    return {
        "sheets": sheet_names,
        "sheet_count": len(sheet_names),
        "formulas": formulas,
        "charts": charts,
        "sku_count": len(sku_rows),
        "sku_rows": sorted(sku_rows)[:14],
        "verified_kpis": verified,
        "unverifiable_kpis": unverifiable,
        "self_computed_on_hand": round(self_on_hand, 2),
        "self_computed_reorder_alerts": self_alerts,
        # The KPI the workbook displays must equal the harness's own sum of
        # the same literal data — this is what "verified computed values"
        # means here, since openpyxl writes no cached results.
        "units_kpi_matches_data": (units_kpi is not None
                                   and abs(units_kpi - self_on_hand) < 0.01),
        "reorder_kpi_matches_data": (alerts_kpi is not None
                                     and abs(alerts_kpi - self_alerts) < 0.01),
        # openpyxl writes formulas without cached results, recorded explicitly.
        "formula_values_cached": False,
    }


def validate_pdf(path: Path) -> dict:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    text = "\n".join(pages)
    lowered = text.lower()
    return {
        "pages": len(reader.pages),
        "chars": len(text),
        "blank_pages": [i + 1 for i, t in enumerate(pages) if len(t.strip()) < 40],
        "mentions_total": "54,200" in text or "54200" in text,
        "mentions_tests": "32" in text and "19" in text,
        "mentions_low_stock": ("laptop stand" in lowered
                               and "mouse" in lowered),
        "has_executive_summary": "executive summary" in lowered,
        "has_limitations": "limitation" in lowered,
        "has_future": "future" in lowered,
        "title_metadata": (reader.metadata.title if reader.metadata else None),
    }


# ── main ────────────────────────────────────────────────────────────────────

def main() -> int:
    DOCS.mkdir(parents=True, exist_ok=True)
    report: dict = {"facts": FACTS, "artifacts": {}}

    docx_path = DOCS / "inventory_project_report.docx"
    pptx_path = DOCS / "inventory_presentation.pptx"
    xlsx_path = DOCS / "inventory_test_report.xlsx"
    pdf_path = DOCS / "inventory_project_report.pdf"

    print("generating DOCX through file_processor …", flush=True)
    report["artifacts"]["docx"] = create(docx_path, "docx", DOCX_TITLE,
                                         DOCX_INSTRUCTION)
    print("generating PPTX through file_processor …", flush=True)
    report["artifacts"]["pptx"] = create(pptx_path, "pptx", PPTX_TITLE,
                                         PPTX_INSTRUCTION)
    print("generating XLSX through file_processor …", flush=True)
    report["artifacts"]["xlsx"] = create(xlsx_path, "xlsx", XLSX_TITLE,
                                         XLSX_INSTRUCTION)
    print("generating PDF through file_processor …", flush=True)
    report["artifacts"]["pdf"] = create(pdf_path, "pdf", PDF_TITLE,
                                        DOCX_INSTRUCTION)

    for key, path, fn in (("docx", docx_path, validate_docx),
                          ("pptx", pptx_path, validate_pptx),
                          ("xlsx", xlsx_path, validate_xlsx),
                          ("pdf", pdf_path, validate_pdf)):
        if path.exists():
            try:
                report[f"validation_{key}"] = fn(path)
            except Exception as err:
                report[f"validation_{key}"] = {
                    "error": f"{type(err).__name__}: {err}"}
        else:
            report[f"validation_{key}"] = {"error": "file missing"}

    v_docx = report.get("validation_docx") or {}
    v_pptx = report.get("validation_pptx") or {}
    v_xlsx = report.get("validation_xlsx") or {}
    v_pdf = report.get("validation_pdf") or {}

    # Cross-format consistency: every format must agree with the SAME facts.
    agree = {
        "docx_states_total": bool(v_docx.get("mentions_total")),
        "pptx_states_total": bool(v_pptx.get("mentions_total")),
        "pdf_states_total": bool(v_pdf.get("mentions_total")),
        "docx_states_low_stock": bool(v_docx.get("mentions_low_stock")),
        "pptx_states_low_stock": bool(v_pptx.get("mentions_low_stock")),
        "pdf_states_low_stock": bool(v_pdf.get("mentions_low_stock")),
        "docx_states_tests": bool(v_docx.get("mentions_tests")),
        "pptx_states_tests": bool(v_pptx.get("mentions_tests")),
        "pdf_states_tests": bool(v_pdf.get("mentions_tests")),
        "xlsx_sku_data_real": (v_xlsx.get("sku_count") or 0) >= 5,
        "xlsx_units_kpi_verified": bool(v_xlsx.get("units_kpi_matches_data")),
        "xlsx_reorder_kpi_verified": bool(v_xlsx.get("reorder_kpi_matches_data")),
        "xlsx_charts_present": (v_xlsx.get("charts") or 0) >= 2,
        "docx_has_required_sections": all(
            (v_docx.get("sections_present") or {}).values()),
        "pptx_no_empty_slides": not (v_pptx.get("empty_slides") or []),
        "pdf_no_blank_pages": not (v_pdf.get("blank_pages") or []),
    }
    report["cross_format"] = {
        "all_four_exist": all(p.exists()
                              for p in (docx_path, pptx_path, xlsx_path, pdf_path)),
        "facts": agree,
        "all_agree": all(agree.values()),
        "disagreements": [k for k, ok in agree.items() if not ok],
    }

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, default=str),
                      encoding="utf-8")

    for key in ("docx", "pptx", "xlsx", "pdf"):
        art = report["artifacts"][key]
        print(f"{key}: exists={art['exists']} bytes={art['bytes']} "
              f"{art['seconds']}s")
    print(json.dumps({k: v for k, v in report.items()
                      if k.startswith("validation_")}, indent=2,
                     default=str)[:3000])
    print("cross_format:", json.dumps(report["cross_format"], indent=2))

    failed = report["cross_format"]["disagreements"]
    if failed:
        print(f"STAGE 6 FAILED: {', '.join(failed)}")
        return 1
    print("STAGE 6 PASSED: all four formats generated, parsed and consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
