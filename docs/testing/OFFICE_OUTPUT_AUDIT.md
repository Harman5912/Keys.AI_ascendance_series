# Office output audit — reopening every generated artifact

Script: `qa_artifacts/audit_docs/verify_office_outputs.py`
Outputs: `qa_artifacts/audit_docs/out/`
Run: `python qa_artifacts/audit_docs/verify_office_outputs.py`

The script does not trust the builder's return value. Each file is reopened with
an independent parser and checked for the structure the request asked for.

| Artifact | Producer | Reopened with |
| --- | --- | --- |
| DOCX | `actions._office_builder.build_docx` | python-docx |
| PPTX | `actions._office_builder.build_pptx` | python-pptx |
| XLSX | `actions._office_xlsx.build_xlsx` | openpyxl |
| PDF | `actions.file_processor` (`action=create`) | `%PDF-` bytes + pypdf |

## Result: 23 of 24 checks pass

DOCX (39,258 bytes)
7 heading-styled sections, 33 non-empty paragraphs, 2 tables (11 rows), no
`**`/`##` markdown leakage, subject named in the text.

PPTX (36,654 bytes)
6 slides, every slide has a title, titles are distinct, no empty slide, 16:9
(12192000 × 6858000 EMU). **No speaker notes: 0 of 6 slides.**

XLSX (14,399 bytes)
4 sheets (Dashboard, Trend, Data, Assumptions), 68 rows, 69 formula cells, 2
charts.

PDF (3,867 bytes)
Real `%PDF-` header, 2 pages, 977 characters of extractable text, text matches
the requested document (not a placeholder).

## Findings

**1. PPTX has no speaker notes (missing feature).**
`build_pptx` never writes `slide.notes_slide`. The audit brief asks for speaker
notes where the format supports them; python-pptx supports them. Every deck this
app generates ships without notes. Not fixed here — adding notes changes every
generated deck and deserves its own review.

**2. The deterministic document outline does not follow the subject.**
`doc_type("Q3 Inventory Report — Warehouse Operations", …)` resolves to `report`,
whose fixed outline is a software-delivery template:

```
Project Overview · System Architecture · Components · Data Flow
Performance Results · Known Limitations · Future Work
```

An inventory report therefore opens with "this report covers the delivery of …,
from the initial requirements through to the performance results measured in the
pilot environment" — true of a software project, false of a warehouse report.
Sections for the actual subject (stock levels, supplier performance, cost
breakdown) are not produced.

This affects the deterministic fallback path. The app's model-driven path
(`core/doc_builder` → `build_docx(plan=...)`) supplies its own headings and was
**not** exercised in this audit (it needs a model call); nothing here should be
read as evidence about that path.

**3. Everything else held.** The format checks that matter — real container
format, reopenable pages/slides/sheets, present text, present formulas, present
charts, no markdown artefacts — pass for all four formats.

## Not covered

* Rendered appearance (no PDF/PNG rendering step was run, so overflow and
  visual layout are unverified).
* Charts were counted, not visually inspected (`ws._charts`).
* The model-driven plan path for DOCX/PPTX/XLSX.
