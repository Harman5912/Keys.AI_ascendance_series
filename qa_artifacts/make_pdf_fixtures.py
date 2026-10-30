"""qa_artifacts/make_pdf_fixtures.py — build 10 real PDFs for the read pipeline.

Keys.ai has NO PDF *creation* path (see reports/pdf_capability.md), so PDFs are
produced here with reportlab purely as test input: 9 text PDFs with different
structures/lengths plus 1 image-only PDF to exercise the "no extractable text"
branch.

Usage: python qa_artifacts/make_pdf_fixtures.py
"""
from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "qa_artifacts" / "fixtures" / "pdf"

DOCS = [
    ("P01_quarterly_report", "Quarterly Business Review — Q3",
     ["Revenue grew 14% quarter over quarter, driven by enterprise renewals.",
      "Gross margin held at 71%; support costs fell after automation.",
      "Risks: two large renewals slip into Q4; hiring lag in platform team."]),
    ("P02_policy", "Remote Work Policy",
     ["Employees may work remotely up to three days per week.",
      "Managers must document expectations in the team charter.",
      "Equipment is provided; security training is mandatory."]),
    ("P03_invoice", "Invoice INV-2041",
     ["Bill to: Northwind Bakery, 14 Mill Lane.",
      "Line items: platform licence 12 months, onboarding, support.",
      "Total due: 18,400 USD within 30 days."]),
    ("P04_contract", "Master Services Agreement (Excerpt)",
     ["Section 4. Payment terms: net 45 days from invoice date.",
      "Section 9. Liability is capped at fees paid in the prior 12 months.",
      "Section 12. Either party may terminate for material breach."]),
    ("P05_research", "Sensor Fusion for Cold-Chain Logistics",
     ["We evaluated three fusion strategies across 240 shipments.",
      "A Kalman-filter ensemble reduced false alarms by 38%.",
      "Battery life remained above 11 days in all trials."]),
    ("P06_manual", "Gateway G2 Installation Manual",
     ["Step 1: mount the bracket on a flat surface.",
      "Step 2: connect power and wait for the green LED.",
      "Step 3: pair the sensor using the mobile app."]),
    ("P07_minutes", "Board Minutes — September",
     ["Quorum present; minutes of the prior meeting approved.",
      "The board approved the 2027 operating budget.",
      "Audit committee to report back in November."]),
    ("P08_syllabus", "Introduction to Data Engineering",
     ["Weeks 1-3: batch pipelines and schema design.",
      "Weeks 4-6: streaming, exactly-once semantics.",
      "Assessment: two projects and a final exam."]),
    ("P09_unicode", "Café Menus — Zürich",
     ["Frühstück: Rösti mit Speck und Käse.",
      "Mittagessen: Älplermagronen mit Apfelmus.",
      "Nachtisch: Crème brûlée, 8.50 CHF."]),
    ("P10_scanned_no_text", "Scanned Receipt (image only)",
     []),  # rendered as vector art only — no text layer
]

styles = getSampleStyleSheet()


def write_text_pdf(path: Path, title: str, paras: list[str]) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    c.setFont("Helvetica-Bold", 18)
    c.drawString(inch, height - inch, title)
    c.setFont("Helvetica", 11)
    y = height - 1.4 * inch
    for p in paras:
        for line in _wrap(p, 88):
            if y < inch:
                c.showPage()
                c.setFont("Helvetica", 11)
                y = height - inch
            c.drawString(inch, y, line)
            y -= 15
    c.showPage()
    c.save()


def write_scanned_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    for row in range(14):
        c.rect(inch, 8.6 * inch - row * 22, 4.5 * inch, 18, stroke=1, fill=0)
    c.setFillColorRGB(0.75, 0.75, 0.75)
    c.rect(inch, 2 * inch, 2 * inch, 0.6 * inch, stroke=0, fill=1)
    c.showPage()
    c.save()


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for slug, title, paras in DOCS:
        path = OUT / f"{slug}.pdf"
        if paras:
            write_text_pdf(path, title, paras)
        else:
            write_scanned_pdf(path)
        manifest.append({"file": path.name, "title": title, "paragraphs": len(paras),
                         "bytes": path.stat().st_size,
                         "text_layer": bool(paras)})
    (OUT / "_fixtures.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for m in manifest:
        print(f"{m['file']:<32} {m['bytes']:>7} B  text_layer={m['text_layer']}")
    print(f"\n{len(manifest)} PDFs -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
