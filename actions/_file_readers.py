"""actions/_file_readers.py — real read/convert handlers for the file processor.

The public ``file_processor`` entry point advertises PDF, DOCX, PPTX, XLSX,
CSV, JSON and text reading, but only the create path existed. These handlers
implement the documented actions with the libraries already in requirements:
pypdf, python-docx, python-pptx, openpyxl.

Every handler returns a human-readable string; failures are reported in the
string, never raised at the UI boundary. Unknown actions name the family and
list what is actually supported instead of silently doing nothing.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path


def _not_a_pdf() -> str:
    return ("This file is not a readable PDF. If it is scanned, OCR is required "
            "before text can be extracted.")


def read_pdf(path: Path, action: str) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        return f"Could not open PDF: {type(exc).__name__}: {exc}"
    pages = len(reader.pages)
    info = (f"PDF: {path.name}\nPages: {pages} pages\n"
            f"Size: {path.stat().st_size:,} bytes\n"
            f"Encrypted: {'yes' if reader.is_encrypted else 'no'}")

    if action in ("", "info", "read"):
        return info

    if action in ("extract_text", "extract", "summarize", "analyze", "translate_hint"):
        chunks = []
        for page in reader.pages:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                chunks.append("")
        text = "\n\n".join(c.strip() for c in chunks if c.strip())
        if not text.strip():
            return ("Could not extract text: this PDF contains no selectable text "
                    "(it is probably a scan). OCR is needed.")
        dest = path.with_name(f"{path.stem}_text.txt")
        dest.write_text(text, encoding="utf-8")
        preview = text[:2500] + ("\n…" if len(text) > 2500 else "")
        return (f"Text extracted: {len(text):,} characters from {pages} pages\n"
                f"Saved to: {dest}\n\n{preview}")

    if action in ("to_word", "convert", "convert_to_word"):
        chunks = []
        for page in reader.pages:
            try:
                chunks.append((page.extract_text() or "").strip())
            except Exception:
                continue
        text = "\n\n".join(c for c in chunks if c)
        if not text:
            return "Could not convert: the PDF contains no selectable text."
        from docx import Document
        from docx.shared import Pt

        doc = Document()
        doc.styles["Normal"].font.name = "Calibri"
        doc.styles["Normal"].font.size = Pt(10.5)
        title = doc.add_heading(path.stem.replace("_", " ").title(), level=0)
        for block in re.split(r"\n\s*\n", text):
            clean = re.sub(r"\s+", " ", block).strip()
            if clean:
                doc.add_paragraph(clean)
        dest = path.with_name(f"{path.stem}_converted.docx")
        doc.save(str(dest))
        return (f"Converted to Word: {dest.name}\n"
                f"Saved to: {dest}\nParagraphs: {len(doc.paragraphs)} · {len(text):,} characters")

    return (f"Unknown PDF action: '{action}'. "
            "Supported: info, extract_text, to_word.")


def read_docx(path: Path, action: str) -> str:
    from docx import Document

    doc = Document(str(path))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    headings = [p.text.strip() for p in doc.paragraphs
                if p.style.name.startswith("Heading") and p.text.strip()]
    text = "\n".join(paragraphs)
    words = len(re.findall(r"\w+", text))
    base = (f"DOCX: {path.name}\nParagraphs: {len(paragraphs)}\n"
            f"Headings: {len(headings)}\nWords: {words:,}\n"
            f"Tables: {len(doc.tables)}\nSize: {path.stat().st_size:,} bytes")

    if action in ("", "read", "info"):
        return base
    if action in ("extract_text", "summarize", "analyze"):
        preview = text[:3000] + ("\n…" if len(text) > 3000 else "")
        return f"{base}\n\n{preview}"
    if action in ("edit", "convert"):
        return f"{base}\n\nUse action='edit' with new text to rewrite this document."
    return f"Unknown DOCX action: '{action}'. Supported: info, extract_text, summarize."


def read_pptx(path: Path, action: str) -> str:
    from pptx import Presentation

    prs = Presentation(str(path))
    slides = []
    for i, slide in enumerate(prs.slides, 1):
        parts = []
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text.strip())
        slides.append((i, parts))
    text = "\n\n".join(f"Slide {i}\n" + "\n".join(parts) for i, parts in slides)
    base = (f"PPTX: {path.name}\nSlides: {len(prs.slides)}\n"
            f"Size: {path.stat().st_size:,} bytes")

    if action in ("", "read", "info"):
        return base
    if action in ("extract_text", "summarize", "analyze"):
        return f"{base}\n\n{text[:4000]}"
    if action in ("to_pdf", "convert_to_pdf"):
        return ("Unknown PPTX action: 'to_pdf'. PowerPoint-to-PDF conversion is not "
                "implemented; export from PowerPoint or LibreOffice instead.")
    return f"Unknown PPTX action: '{action}'. Supported: info, extract_text."


def read_xlsx(path: Path, action: str) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), data_only=False)
    lines = [f"XLSX: {path.name}", f"Sheets: {len(wb.sheetnames)} — {', '.join(wb.sheetnames)}",
             f"Size: {path.stat().st_size:,} bytes"]
    for ws in wb.worksheets:
        lines.append(f"\n[{ws.title}] {ws.max_row} rows × {ws.max_column} columns")
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 6), values_only=True):
            values = [str(v) for v in row if v is not None]
            if values:
                lines.append("  " + " | ".join(values[:7]))
    if action in ("", "read", "info", "extract_text", "analyze"):
        return "\n".join(lines)
    return f"Unknown XLSX action: '{action}'. Supported: info, extract_text."


def read_csv(path: Path, action: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return "CSV: empty file"
    headers = rows[0]
    body = rows[1:]
    lines = [f"CSV: {path.name}", f"Rows: {len(body)}", f"Columns: {len(headers)}"]
    numeric: dict[str, list[float]] = {}
    for i, name in enumerate(headers):
        values = []
        for row in body:
            if i < len(row):
                try:
                    values.append(float(row[i]))
                except ValueError:
                    pass
        if values:
            numeric[name] = values
    for name, values in numeric.items():
        lines.append(f"  {name}: min {min(values):g} · max {max(values):g} · "
                     f"mean {sum(values) / len(values):.2f} · sum {sum(values):g}")
    non_numeric = [h for h in headers if h not in numeric]
    if non_numeric:
        lines.append(f"  text columns: {', '.join(non_numeric[:8])}")
    lines.append("Preview: " + " | ".join(headers[:8]))
    for row in body[:3]:
        lines.append("  " + " | ".join(row[:8]))
    return "\n".join(lines)


def read_json(path: Path, action: str) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        if action in ("validate", "info", ""):
            return f"Invalid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}"
        return f"Invalid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}"
    if action in ("validate", "info", ""):
        kind = type(value).__name__
        count = (f"{len(value)} items" if isinstance(value, (list, dict)) else "scalar")
        return f"Valid JSON: {kind} · {count} · {len(raw):,} characters"
    if action == "format":
        pretty = json.dumps(value, indent=2, ensure_ascii=False)
        dest = path.with_name(f"{path.stem}_formatted.json")
        dest.write_text(pretty, encoding="utf-8")
        return f"Formatted JSON saved to: {dest}\n\n{pretty[:1200]}"
    return f"Unknown JSON action: '{action}'. Supported: validate, format, info."


def read_text(path: Path, action: str) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.count("\n") + 1 if text else 0
    base = (f"Text: {path.name}\nLines: {lines:,}\n"
            f"Characters: {len(text):,}\nSize: {path.stat().st_size:,} bytes")
    if action in ("", "read", "extract_text", "summarize", "analyze", "info"):
        preview = text[:4000] + ("\n…" if len(text) > 4000 else "")
        return f"{base}\n\n{preview}"
    return f"Unknown text action: '{action}'. Supported: info, extract_text."
