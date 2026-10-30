#!/usr/bin/env python3
"""file_processor.py - Keys.ai Universal File Processor.

Supported types:
  image (jpg/png/gif/webp/bmp/tiff/svg/ico/heic)
  pdf
  docx / text / markdown
  csv / excel (xlsx/xls)
  json / xml
  code (py/js/ts/java/cpp/csharp/go/rs/rb/php/sh/sql/html/css)
  audio (mp3/wav/flac/ogg/m4a/aac/wma)
  video (mp4/mkv/avi/mov/wmv/flv/webm)
  archive (zip/rar/7z/tar/gz)
  pptx / ppt

Actions (auto-selected when not specified):
  image:   describe, analyze, edit, convert, compress, info
  pdf:     summarize, extract_text, analyze, reformat, translate_hint, info
  docx:    summarize, extract_text, analyze, edit, convert, info, create
  text:    summarize, extract_text, analyze, edit, convert, info
  csv:     summarize, analyze, edit, convert, info
  excel:   summarize, analyze, edit, create, info
  json:    summarize, analyze, format, info
  xml:     summarize, analyze, format, info
  code:    explain, analyze, fix, refactor, test, document, info
  audio:   summarize, transcribe, analyze, info
  video:  summarize, analyze, info
  archive: extract, list, info
  pptx:   summarize, extract_text, analyze, edit, create, info

One-shot document/presentation/spreadsheet creation (action="create") also supports:
  .xlsx / .xls        -> excel (create a styled spreadsheet)
  .pptx / .ppt        -> pptx  (create a widescreen presentation)
  .pbix / .powerbi    -> powerbi (emit a Power BI report design artefact set)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from ._powerbi_prompt import _powerbi_prompt as _pp_prompt
except Exception:
    def _pp_prompt(title: str, instruction: str) -> str:
        return f"Power BI design prompt for {title}"

try:
    from ._office_builder import build_docx, build_pptx, build_xlsx
except Exception:                       # pragma: no cover - import guard
    build_docx = build_pptx = build_xlsx = None

_powerbi_prompt = _pp_prompt  # backwards compat for internal calls

try:
    from ._extract_json_helpers import (
        _extract_json,
        _salvage_slides,
        _strip_placeholder_lines,
    )
except Exception:
    def _extract_json(raw: str, opener: str = "[") -> list | dict:
        raise ValueError("no JSON value found in response")

    def _salvage_slides(raw: str) -> list:
        return []

    def _strip_placeholder_lines(text: str) -> str:
        return (text or "").strip()


def _cr(event_type, *, icon="", text="", **kwargs):
    """Lightweight creation-event logger used during artifact creation.

    The real app binds this to the live player/creation bus at call time; in
    standalone scripts and tests it is a no-op.
    """
    pass


def _open_file_default(path: Path) -> bool:
    """Best-effort platform default open for a saved artifact."""
    try:
        if sys.platform == "win32":
            subprocess.run(["explorer", str(path)], check=False)
        else:
            subprocess.run(["open", str(path)], check=False)
    except Exception:
        pass
    return True


def _ask_open_permission(player, path: Path, app: str) -> bool:
    """Ask the live player whether to open the artifact in `app`."""
    if player is None:
        return False
    try:
        reply = player.ask_permission(
            action="open",
            reason=f"Open {path.name} in {app}?",
            location=str(path),
        )
    except Exception:
        return False
    if isinstance(reply, str):
        return reply.strip().lower() not in ("n", "no", "deny", "")
    return bool(reply)


def _gemini_client():
    """Return the cached Gemini-compatible client used for creation prompts."""
    try:
        from brain.brain import Brain
    except Exception:
        return None
    try:
        brain = Brain()
    except Exception:
        return None
    try:
        client = brain.get_client("gemini_compat")
    except Exception:
        return None
    if client is None:
        return None
    return client


def _detect_type(path: Path) -> str:
    """Map a file extension to an internal doc type token."""
    ext = path.suffix.lower()
    type_map = {
        ".docx": "docx",
        ".xlsx": "xlsx",
        ".xls": "xlsx",
        ".pptx": "pptx",
        ".ppt": "pptx",
        ".pdf": "pdf",
        ".pbix": "powerbi",
        ".powerbi": "powerbi",
    }
    return type_map.get(ext, "unknown")


def file_processor(parameters: dict, player=None, speak=None) -> str:
    """Main entry point for the Keys.ai file processor.

    Read actions: info, extract_text, summarize, analyze, to_word, to_pdf,
    validate, format, stats. Create: .docx, .pptx, .xlsx and .pbix (Power BI
    design artefact set). Unsupported requests name the real limitation.
    """
    p = parameters or {}
    action = str(p.get("action") or "").strip().lower()
    file_path = str(p.get("file_path") or "").strip()
    if not file_path:
        return "No file path provided."

    path = Path(file_path).expanduser()
    if action == "create":
        doc_type = _detect_type(path)
        title = p.get("title") or path.stem
        instruction = p.get("instruction") or ""
        if doc_type == "powerbi":
            return _create_powerbi(path, title, instruction, p, player)
        if doc_type == "powerbi":
            return _create_powerbi(path, title, instruction, p, player)
        if doc_type in ("docx", "pptx", "xlsx", "pdf"):
            return _create_office(path, doc_type, title, instruction, p, player)
        suffix = path.suffix.lower() or "(none)"
        return (f"Cannot create '{suffix}'. Supported formats: .docx (Word), "
                ".pptx (PowerPoint), .xlsx (Excel), .pdf (PDF), "
                ".pbix (Power BI artefacts).")

    if not path.exists():
        return f"File not found: {path}"
    if not path.is_file():
        return f"Path is not a file: {path}"

    suffix = path.suffix.lower()
    try:
        from . import _file_readers as readers
        if suffix == ".pdf":
            return readers.read_pdf(path, action or "info")
        if suffix == ".docx":
            return readers.read_docx(path, action or "info")
        if suffix == ".pptx":
            return readers.read_pptx(path, action or "info")
        if suffix in (".xlsx", ".xls"):
            return readers.read_xlsx(path, action or "info")
        if suffix == ".csv":
            return readers.read_csv(path, "stats" if action == "stats" else action)
        if suffix == ".json":
            return readers.read_json(path, action or "info")
        if suffix in (".txt", ".md", ".py", ".js", ".ts", ".html", ".css",
                      ".sql", ".xml", ".yml", ".yaml"):
            return readers.read_text(path, action or "info")
    except Exception as exc:
        return f"Could not process {path.name}: {type(exc).__name__}: {exc}"

    return (f"Unsupported file type '{suffix}' for read actions. "
            "Supported: PDF, DOCX, PPTX, XLSX, CSV, JSON and text/code files.")


def _model_document_plan(path: Path, doc_type: str, title: str,
                          instruction: str, player):
    """Ask the local model for this document's real content.

    Returns a writer-ready argument dict, or {} when the model is unavailable
    or returned nothing usable — the caller then builds the deterministic
    plan, so a document is never worse than before this existed.
    """
    if doc_type == "xlsx":
        return {}      # the workbook builder is data-shaped, not prose-shaped
    try:
        from core.doc_builder import model_doc_plan
    except Exception:
        return {}
    _cr("creation_event", icon="◆", text="Asking the local model for the content...")
    raw, model = model_doc_plan(title, instruction, doc_type,
                                on_log=lambda m: _cr("creation_event", icon="-", text=m))
    if not raw:
        _cr("creation_event", icon="-",
            text=f"{model} gave no usable content — using the built-in plan")
        return {}
    _cr("creation_event", icon="✓", text=f"Content written by {model}")
    if doc_type == "pptx":
        from core.doc_builder import to_outline
        return {"content_by": model, "outline": to_outline(raw, title, instruction),
                "subtitle": raw.get("subtitle", "")}
    return {"content_by": model, "plan": raw}


def _create_office(path: Path, doc_type: str, title: str, instruction: str,
                   parameters: dict, player) -> str:
    """Create a Word, PowerPoint or Excel artifact.

    The local model writes the actual content (sections, bullets, tables) via
    core.doc_builder; python-docx / python-pptx / openpyxl then render it with
    the deterministic styling. If the model is unavailable the built-in plan
    fills the same shape, so a document is always produced.

    The artifact is reopened with the same library before success is reported,
    so a corrupt file is never announced as created.
    """
    if not any((build_docx, build_pptx, build_xlsx)):
        return ("Document creation is unavailable: python-docx, python-pptx or "
                "openpyxl is not installed.")

    label = {"docx": "Word document", "pptx": "PowerPoint presentation",
             "xlsx": "Excel workbook", "pdf": "PDF document"}[doc_type]
    _cr("creation_event", icon="->", text=f"Planning {label}: {title}")
    _cr("creation_progress", pct=0.15)

    # An instruction that is already markdown carries the user's own structure:
    # their headings, their bold runs, their bullet order. A model plan written
    # over it silently replaces that structure (and did — a `## Section` became
    # a Heading 1 section of the model's choosing). The user's formatting wins,
    # so the model is not consulted at all in that case. This also makes the
    # result independent of whether a model happens to be reachable.
    explicit_markdown = False
    if doc_type == "docx":
        from ._office_builder import looks_like_markdown
        explicit_markdown = looks_like_markdown(instruction)
        if explicit_markdown:
            _cr("creation_event", icon="i",
                text="Instruction is markdown — rendering it exactly as written")

    modelled = ({} if explicit_markdown
                else _model_document_plan(path, doc_type, title, instruction, player))

    try:
        if doc_type == "docx":
            from ._office_builder import build_docx_markdown
            if explicit_markdown:
                plan = build_docx_markdown(path, title, instruction)
            elif modelled.get("plan"):
                from core.doc_builder import to_doc_plan
                plan = build_docx(path, title, instruction,
                                  plan=to_doc_plan(modelled["plan"], title, instruction))
            elif looks_like_markdown(instruction):
                plan = build_docx_markdown(path, title, instruction)
            else:
                plan = build_docx(path, title, instruction)
        elif doc_type == "pptx":
            plan = (build_pptx(path, title, instruction,
                               outline=modelled["outline"], subtitle=modelled["subtitle"])
                    if modelled.get("outline") else build_pptx(path, title, instruction))
        elif doc_type == "pdf":
            from ._office_builder import build_pdf
            if modelled.get("plan"):
                from core.doc_builder import to_doc_plan
                plan = build_pdf(path, title, instruction,
                                 plan=to_doc_plan(modelled["plan"], title, instruction))
            else:
                plan = build_pdf(path, title, instruction)
        else:
            plan = build_xlsx(path, title, instruction)
    except Exception as e:
        _cr("creation_event", icon="!", text=f"{label} creation failed: {e}")
        _cr("creation_error", text=str(e))
        return f"Could not create {label}: {type(e).__name__}: {e}"

    if not path.exists() or path.stat().st_size < 1500:
        msg = f"{label} was not written to disk ({path})"
        _cr("creation_error", text=msg)
        return msg

    _cr("creation_progress", pct=0.8)
    detail = f"{len(plan.sections)} sections" if doc_type in ("docx", "pdf") else (
        "slides" if doc_type == "pptx" else "4 worksheets · live formulas · 2 charts")
    try:
        if doc_type == "docx":
            from docx import Document
            words = len(re.findall(r"\w+", " ".join(p.text for p in Document(str(path)).paragraphs)))
            detail = f"{len(plan.sections)} sections · {words} words"
        elif doc_type == "pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            words = len(re.findall(r"\w+", " ".join(
                (page.extract_text() or "") for page in reader.pages)))
            detail = f"{len(reader.pages)} pages · {words} words · parsed OK"
        elif doc_type == "pptx":
            from pptx import Presentation
            prs = Presentation(str(path))
            slides = len(prs.slides)
            charts = sum(1 for s in prs.slides for sh in s.shapes if sh.has_chart)
            detail = f"{slides} widescreen slides · {charts} native chart" + ("s" if charts != 1 else "")
        else:
            from openpyxl import load_workbook
            wb = load_workbook(str(path))
            detail = f"{len(wb.sheetnames)} worksheets · live formulas · 2 charts"
    except Exception as e:
        _cr("creation_event", icon="!", text=f"{label} saved but could not be reopened: {e}")
        return (f"Created {path.name} ({path.stat().st_size} bytes) but reopening it "
                f"failed: {e}")

    _cr("creation_progress", pct=1.0)
    _cr("creation_event", icon="✓", text=f"{label}: {path.name} — {detail}")
    _cr("creation_complete", summary=f"{label} created: {path.name} ({detail})")

    opened = "Not opened (permission not requested).\n"
    if parameters.get("open"):
        if _ask_open_permission(player, path, label):
            _open_file_default(path)
            opened = "Opened in the default application.\n"
        else:
            opened = "Not opened (permission denied).\n"
    return (f"Created {label}: {path.name}\n  Subject : {plan.subject}\n  Detail  : {detail}\n"
            f"  Size    : {path.stat().st_size:,} bytes\n  Saved   : {path}\n{opened}")


def _create_powerbi(path: Path, title: str, instruction: str,
                    parameters: dict, player) -> str:
    """Create a Power BI artifact set: a report spec (.json), a semantic model
    (.json) and a DAX module (.dax/.txt). PBIX binaries cannot be authored from
    Python without the Microsoft SDK and a desktop install, so this path emits the
    design artefacts a report author (or Power BI Desktop) can consume directly.

    A single sector/subject is expressed as a cohesive set of design components:
      - report spec: pages, visuals, filters, theme tokens, interactions
      - semantic model: tables, columns, keys, measures, relationships, roles
      - DAX: measure definitions + calculation groups / time-intelligence helpers
    """
    # unused import kept only as a documentation/dependency note for this path
    try:
        import openpyxl  # noqa: F401
    except Exception:
        pass

    _cr("creation_event", icon="->", text="Designing Power BI report components...")
    _cr("creation_progress", pct=0.1)

    prompt = _powerbi_prompt(title, instruction)

    raw = ""
    try:
        model = _gemini_client()
        response = model.generate_content(prompt)
        raw = response.text
    except Exception as e:
        _cr("creation_event", icon="!", text=f"Power BI AI design failed: {e}")

    spec = None
    if raw:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z0-9]*\s*", "", cleaned)
            cleaned = cleaned.rsplit("```", 1)[0].rstrip()
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            try:
                spec = json.loads(m.group(0))
            except json.JSONDecodeError as e:
                _cr("creation_event", icon="!", text=f"Power BI JSON parse failed: {e}")

    if not spec or not isinstance(spec, dict):
        _cr("creation_event", icon="!", text="Power BI AI design returned no usable spec; using topic-based scaffold")
        spec = _powerbi_default_scaffold(title, instruction)

    # Ensure required top-level keys exist
    if not isinstance(spec.get("report_title"), str):
        spec["report_title"] = title
    if not isinstance(spec.get("theme"), dict):
        spec["theme"] = _powerbi_default_theme()
    if not isinstance(spec.get("pages"), list) or not spec["pages"]:
        spec["pages"] = _powerbi_default_pages(title, instruction)
    if not isinstance(spec.get("semantic_model"), dict):
        spec["semantic_model"] = _powerbi_default_model(title, instruction)
    if not isinstance(spec.get("dax_module"), dict):
        spec["dax_module"] = _powerbi_default_dax(spec)
    if not isinstance(spec.get("qa_checklist"), list):
        spec["qa_checklist"] = _powerbi_default_qa()

    folder = path.parent
    folder.mkdir(parents=True, exist_ok=True)

    spec_out = _powerbi_normalize(spec)
    spec_path = folder / f"{path.stem}_powerbi_report_spec.json"
    spec_path.write_text(json.dumps(spec_out, indent=2, ensure_ascii=False), encoding="utf-8")

    model_path = folder / f"{path.stem}_powerbi_semantic_model.json"
    model_path.write_text(json.dumps(spec.get("semantic_model"), indent=2, ensure_ascii=False), encoding="utf-8")

    dax_text = _powerbi_dax_text(spec)
    dax_path = folder / f"{path.stem}_measures.dax"
    dax_path.write_text(dax_text, encoding="utf-8")

    _cr("creation_progress", pct=0.6)
    _cr("creation_event", icon="✓", text=f"Power BI report spec: {spec_path.name}")
    _cr("creation_event", icon="✓", text=f"Semantic model: {model_path.name}")
    _cr("creation_event", icon="✓", text=f"DAX module: {dax_path.name}")

    _cr("creation_progress", pct=0.8)
    _cr("creation_event", icon="->", text="Applying professional Power BI design components...")

    qa = _powerbi_validate(spec_out)
    if qa["ok"]:
        _cr("creation_event", icon="✓", text="Power BI design passed structural QA")
    else:
        _cr("creation_event", icon="!", text=f"Power BI design QA notes: {qa['notes']}")

    _cr("creation_progress", pct=0.95)
    _cr("creation_event", icon="✓", text=f"Power BI design artefacts saved to: {folder}")

    opened = False
    if _ask_open_permission(player, spec_path, "Power BI report spec"):
        _open_file_default(spec_path)
        opened = True

    _cr("creation_complete", summary=f"Power BI design created for '{spec.get('report_title', title)}'")
    return (
        f"Created Power BI design artefacts for '{spec.get('report_title', title)}':\n"
        f"  Report spec : {spec_path.name}\n"
        f"  Semantic model: {model_path.name}\n"
        f"  DAX module : {dax_path.name}\n"
        f"Saved to: {folder}\n"
        + ("Opened report spec.\n" if opened else "Not opened (no permission).\n")
    )


# =============================================================================
# POWER BI DESIGN SCAFFOLDS / VALIDATION HELPERS
# =============================================================================


def _powerbi_default_theme() -> dict:
    """A professional, accessible Power BI theme token set."""
    return {
        "name": "Keys Professional (dark blue)",
        "dataColors": ["#1F497D", "#4472C4", "#8FAADC", "#C5D9F1", "#262626"],
        "background": "#FFFFFF",
        "foreground": "#262626",
        "tableAccent": "#4472C4",
        "good": "#107C10",
        "neutral": "#767676",
        "bad": "#C00000",
        "visualStyles": {
            "*": {
                "title": {
                    "show": True,
                    "text": "",
                    "fontColor": "#262626",
                    "fontSize": 12,
                    "fontFamily": "Segoe UI",
                },
                "border": {
                    "show": True,
                    "color": "#D9D9D9",
                    "radius": 4,
                },
                "background": {
                    "show": False,
                },
            }
        },
    }


def _powerbi_default_pages(title: str, instruction: str) -> list:
    subject = (instruction or title).strip().split("\n")[0][:120]
    return [
        {
            "name": "Executive Summary",
            "description": f"At-a-glance KPIs and headline trend for {subject}.",
            "filters": ["Date (Date[Date])"],
            "visuals": [
                {"type": "card", "title": "Headline KPI", "measure": "[Total Value]", "format": "Currency", "category": "KPI"},
                {"type": "barchart", "title": "Breakdown by Category", "axis": "[Category]", "values": ["[Total Value]"], "sort_by": "[Total Value]", "category": "Analysis"},
                {"type": "linechart", "title": "Trend Over Time", "axis": "[Date]", "values": ["[Total Value]"], "category": "Trend"},
                {"type": "card", "title": "YTD vs Prior Year", "measure": "[YTD vs PY %]", "format": "0.00%", "category": "KPI"},
            ],
            "interactions": {"cross_filtering": True, "highlighting": True},
        },
        {
            "name": "Detail",
            "description": f"Tabulated detail with supporting context for {subject}.",
            "filters": ["Date (Date[Date])"],
            "visuals": [
                {"type": "matrixtable", "title": "Detail by Segment", "rows": ["[Category]", "[Subcategory]"], "values": ["[Total Value]", "[Count]"], "category": "Detail"},
                {"type": "card", "title": "Selected Segment Total", "measure": "[Total Value]", "format": "Currency", "category": "KPI"},
                {"type": "slicer", "title": "Category", "field": "[Category]", "category": "Filter"},
            ],
            "interactions": {"cross_filtering": True, "highlighting": True},
        },
        {
            "name": "Analysis",
            "description": f"Time-intelligence and variance analysis for {subject}.",
            "filters": ["Date (Date[Date])"],
            "visuals": [
                {"type": "linechart", "title": "Monthly Trend", "axis": "[Date]", "values": ["[Total Value]", "[Prior Year Value]"], "category": "Trend"},
                {"type": "barchart", "title": "Period-over-Period Variance", "axis": "[Category]", "values": ["[Variance]"], "sort_by": "[Variance]", "category": "Analysis"},
                {"type": "card", "title": "Total", "measure": "[Total Value]", "format": "Currency", "category": "KPI"},
                {"type": "card", "title": "Avg", "measure": "[Average]", "format": "Currency", "category": "KPI"},
            ],
            "interactions": {"cross_filtering": True, "highlighting": True},
        },
    ]


def _powerbi_default_model(title: str, instruction: str) -> dict:
    subject = (instruction or title).strip().split("\n")[0][:120]
    return {
        "tables": [
            {
                "name": "Fact",
                "description": f"Transactional/fact records for {subject}.",
                "columns": [
                    {"name": "Key", "data_type": "Text", "is_key": True, "is_measure": False},
                    {"name": "Date", "data_type": "Date", "is_key": False, "is_measure": False},
                    {"name": "Category", "data_type": "Text", "is_key": False, "is_measure": False},
                    {"name": "Subcategory", "data_type": "Text", "is_key": False, "is_measure": False},
                    {"name": "Value", "data_type": "Decimal Number", "is_key": False, "is_measure": False},
                    {"name": "Quantity", "data_type": "Whole Number", "is_key": False, "is_measure": False},
                    {"name": "Cost", "data_type": "Decimal Number", "is_key": False, "is_measure": False},
                ],
                "measures": [
                    {"name": "Total Value", "expression": "SUM(Fact[Value])", "format_string": "Currency"},
                    {"name": "Total Cost", "expression": "SUM(Fact[Cost])", "format_string": "Currency"},
                    {"name": "Count", "expression": "COUNTROWS(Fact)", "format_string": "0"},
                    {"name": "Average", "expression": "AVERAGE(Fact[Value])", "format_string": "Currency"},
                    {"name": "Margin", "expression": "[Total Value] - [Total Cost]", "format_string": "Currency"},
                    {"name": "Margin %", "expression": "DIVIDE([Margin], [Total Value])", "format_string": "0.00%"},
                ],
                "key_columns": ["Key"],
            },
            {
                "name": "Date",
                "description": "Standard calendar/date table for time intelligence.",
                "columns": [
                    {"name": "Date", "data_type": "Date", "is_key": True, "is_measure": False},
                    {"name": "Year", "data_type": "Whole Number", "is_key": False, "is_measure": False},
                    {"name": "Quarter", "data_type": "Text", "is_key": False, "is_measure": False},
                    {"name": "Month", "data_type": "Text", "is_key": False, "is_measure": False},
                    {"name": "MonthNo", "data_type": "Whole Number", "is_key": False, "is_measure": False},
                ],
                "measures": [
                    {"name": "Days in Period", "expression": "COUNTROWS('Date')", "format_string": "0"},
                ],
                "key_columns": ["Date"],
            },
        ],
        "relationships": [
            {"from_table": "Fact", "from_column": "Date", "to_table": "Date", "to_column": "Date", "cross_filter": "single"},
        ],
        "calculation_groups": [
            {
                "name": "Time:",
                "expressions": {
                    "YTD": "CALCULATE(SELECTEDMEASURE(), DATESYTD('Date'[Date]))",
                    "MTD": "CALCULATE(SELECTEDMEASURE(), DATESMTD('Date'[Date]))",
                    "PY": "CALCULATE(SELECTEDMEASURE(), SAMEPERIODLASTYEAR('Date'[Date]))",
                    "YoY %": "VAR PY = CALCULATE(SELECTEDMEASURE(), SAMEPERIODLASTYEAR('Date'[Date])) RETURN DIVIDE(SELECTEDMEASURE() - PY, PY)",
                },
            },
        ],
        "roles": [
            {
                "name": "Regional Reader",
                "description": "Read-only access scoped to a region.",
                "filters": ['Fact[Region] = "North"'],
            },
        ],
    }


def _powerbi_default_dax(spec: dict) -> dict:
    return {
        "measures": [
            {"name": "Total Value", "definition": "SUM(Fact[Value])", "comment": "Headline value KPI across all visuals."},
            {"name": "Total Cost", "definition": "SUM(Fact[Cost])", "comment": "Cost side of the P&L-style view."},
            {"name": "Margin", "definition": "[Total Value] - [Total Cost]", "comment": "Absolute margin."},
            {"name": "Margin %", "definition": "DIVIDE([Margin], [Total Value])", "comment": "Margins as a ratio."},
            {"name": "Count", "definition": "COUNTROWS(Fact)", "comment": "Transaction/record count."},
            {"name": "Average", "definition": "AVERAGE(Fact[Value])", "comment": "Simple average per record."},
            {"name": "YTD vs PY %", "definition": "VAR YTD = CALCULATE([Total Value], DATESYTD('Date'[Date])) VAR PY = CALCULATE([Total Value], SAMEPERIODLASTYEAR('Date'[Date])) RETURN DIVIDE(YTD - PY, PY)", "comment": "Year-to-date growth vs prior year."},
            {"name": "Variance", "definition": "[Total Value] - CALCULATE([Total Value], SAMEPERIODLASTYEAR('Date'[Date]))", "comment": "Period-over-period value variance."},
            {"name": "Prior Year Value", "definition": "CALCULATE([Total Value], SAMEPERIODLASTYEAR('Date'[Date]))", "comment": "Prior-year value for the current filter context."},
        ],
        "calculation_group_members": [
            {"name": "YTD", "expression": "CALCULATE(SELECTEDMEASURE(), DATESYTD('Date'[Date]))", "format_string": "Currency"},
            {"name": "MTD", "expression": "CALCULATE(SELECTEDMEASURE(), DATESMTD('Date'[Date]))", "format_string": "Currency"},
            {"name": "PY", "expression": "CALCULATE(SELECTEDMEASURE(), SAMEPERIODLASTYEAR('Date'[Date]))", "format_string": "Currency"},
            {"name": "YoY %", "expression": "VAR PY = CALCULATE(SELECTEDMEASURE(), SAMEPERIODLASTYEAR('Date'[Date])) RETURN DIVIDE(SELECTEDMEASURE() - PY, PY)", "format_string": "0.00%"},
        ],
        "time_intelligence_helpers": [
            {"name": "Last Date", "definition": "MAX('Date'[Date])"},
            {"name": "Days in Selection", "definition": "DATEDIFF(MIN('Date'[Date]), MAX('Date'[Date]), DAY)"},
        ],
    }


def _powerbi_default_qa() -> list:
    return [
        "Report title and subject overview are concrete and specific to the request.",
        "Every page has a distinct name and at least one KPI or analytical visual.",
        "Theme colours are consistent across pages and visuals.",
        "Each visual has a title, a measure/field, and a sensible format string.",
        "The semantic model contains at least one fact table and one date table.",
        "Key columns are declared for each table that needs them.",
        "Relationships are defined between related tables.",
        "Measures use working DAX (no dangling or fake measure references).",
        "A time-intelligence calculation group (YTD/MTD/PY/YoY) is present.",
        "At least one RLS role is defined with a concrete filter expression.",
        "QA checklist covers both design and data/model dimensions.",
    ]


def _powerbi_default_scaffold(title: str, instruction: str) -> dict:
    return {
        "report_title": title,
        "subject_overview": (instruction or title).strip().split("\n")[0][:300],
        "theme": _powerbi_default_theme(),
        "pages": _powerbi_default_pages(title, instruction),
        "semantic_model": _powerbi_default_model(title, instruction),
        "dax_module": _powerbi_default_dax(_powerbi_default_model(title, instruction)),
        "qa_checklist": _powerbi_default_qa(),
    }


def _powerbi_normalize(spec: dict) -> dict:
    """Produce a stable, readable representation of the report spec for the design artefact."""
    out = {
        "report_title": spec.get("report_title") or "(untitled)",
        "subject_overview": spec.get("subject_overview") or "",
        "theme": spec.get("theme") or _powerbi_default_theme(),
        "pages": list(spec.get("pages") or []),
        "semantic_model": spec.get("semantic_model") or _powerbi_default_model(
            spec.get("report_title", ""), ""),
        "dax_module": spec.get("dax_module") or _powerbi_default_dax({}),
        "qa_checklist": list(spec.get("qa_checklist") or []),
    }
    for page in out["pages"]:
        page.setdefault("name", "(untitled page)")
        page.setdefault("description", "")
        page.setdefault("filters", [])
        page.setdefault("visuals", [])
        page.setdefault("interactions", {})
        for v in page.get("visuals") or []:
            v.setdefault("type", "card")
            v.setdefault("title", "")
            v.setdefault("category", "General")
    return out


def _powerbi_dax_text(spec: dict) -> str:
    """Emit a readable DAX module text file from the dax_module section."""
    lines: list[str] = []
    lines.append("-- Power BI DAX module")
    lines.append(f"-- Report: {spec.get('report_title', '(untitled)')}")
    lines.append("")

    dm = spec.get("dax_module") or {}
    measures = dm.get("measures") or []
    if measures:
        lines.append("-- Measures")
        for m in measures:
            name = m.get("name", "")
            definition = m.get("definition") or ""
            comment = m.get("comment") or ""
            lines.append("")
            if comment:
                lines.append(f"// {comment}")
            lines.append(f"[{name}] := {definition}")

    cg = dm.get("calculation_group_members") or []
    if cg:
        lines.append("")
        lines.append("-- Calculation group members")
        for c in cg:
            name = c.get("name", "")
            expression = c.get("expression") or ""
            fmt = c.get("format_string") or ""
            lines.append("")
            lines.append(f"// {name}")
            lines.append(f"// Format: {fmt}")
            lines.append(f"[{name}] := {expression}")

    helpers = dm.get("time_intelligence_helpers") or []
    if helpers:
        lines.append("")
        lines.append("-- Time intelligence helpers")
        for h in helpers:
            name = h.get("name", "")
            definition = h.get("definition") or ""
            lines.append("")
            lines.append(f"// {name}")
            lines.append(f"[{name}] := {definition}")

    return "\n".join(lines) + "\n"


def _powerbi_validate(spec: dict) -> dict:
    """Lightweight structural QA on the emitted Power BI design artefacts."""
    issues: list[str] = []

    if not isinstance(spec.get("report_title"), str) or not spec["report_title"].strip():
        issues.append("missing/empty report title")
    if not isinstance(spec.get("subject_overview"), str) or not spec["subject_overview"].strip():
        issues.append("missing subject overview")

    pages = spec.get("pages") or []
    if not isinstance(pages, list) or not pages:
        issues.append("no pages defined")
    else:
        names = []
        for page in pages:
            if not isinstance(page, dict):
                issues.append("a page is not an object")
                continue
            name = page.get("name")
            if not isinstance(name, str) or not name.strip():
                issues.append("a page has no name")
            else:
                names.append(name)
            visuals = page.get("visuals") or []
            if not isinstance(visuals, list) or not visuals:
                issues.append(f"page '{name}' has no visuals")
            else:
                for v in visuals:
                    if not isinstance(v, dict):
                        issues.append(f"page '{name}' has a non-object visual")
                        continue
                    if not isinstance(v.get("type"), str):
                        issues.append(f"visual on page '{name}' has no type")
                    if not isinstance(v.get("title"), str) or not v["title"].strip():
                        issues.append(f"visual on page '{name}' has no title")
                    if not isinstance(v.get("measure") or v.get("field") or v.get("axis") or v.get("rows") or v.get("values"), (list, str)):
                        issues.append(f"visual '{v.get('title') or '(untitled)'}' on page '{name}' has no field/measure/axis/rows/values")
        if len(names) != len(set(names)):
            issues.append("page names are not unique")

    model = spec.get("semantic_model") or {}
    if not isinstance(model, dict):
        issues.append("semantic_model is missing or not an object")
    else:
        tables = model.get("tables") or []
        if not isinstance(tables, list) or not tables:
            issues.append("semantic model has no tables")
        else:
            for t in tables:
                if not isinstance(t, dict):
                    issues.append("a table is not an object")
                    continue
                if not isinstance(t.get("name"), str) or not t["name"].strip():
                    issues.append("a table has no name")
                cols = t.get("columns") or []
                if not isinstance(cols, list) or not cols:
                    issues.append(f"table '{t.get('name') or '(untitled)'}' has no columns")
                measures = t.get("measures") or []
                if not isinstance(measures, list):
                    issues.append(f"table '{t.get('name') or '(untitled)'}' measures is not a list")
        rels = model.get("relationships") or []
        if not isinstance(rels, list):
            issues.append("relationships is not a list")

    cg = model.get("calculation_groups") or []
    if not isinstance(cg, list) or not cg:
        issues.append("no calculation groups (time intelligence) defined")

    roles = model.get("roles") or []
    if not isinstance(roles, list) or not roles:
        issues.append("no RLS roles defined")

    dax = spec.get("dax_module") or {}
    if not isinstance(dax, dict):
        issues.append("dax_module is missing or not an object")
    else:
        measures = dax.get("measures") or []
        if not isinstance(measures, list) or not measures:
            issues.append("dax_module has no measures")
        else:
            for m in measures:
                if not isinstance(m, dict):
                    issues.append("a DAX measure is not an object")
                    continue
                if not isinstance(m.get("name"), str) or not m["name"].strip():
                    issues.append("a DAX measure has no name")
                if not isinstance(m.get("definition"), str) or not m["definition"].strip():
                    issues.append(f"DAX measure '{m.get('name') or '(untitled)'}' has no definition")

    qa = spec.get("qa_checklist") or []
    if not isinstance(qa, list) or not qa:
        issues.append("qa_checklist is missing or empty")

    notes = "; ".join(issues) if issues else "all core structural checks passed"
    return {
        "ok": len(issues) == 0,
        "notes": notes,
        "issue_count": len(issues),
    }
