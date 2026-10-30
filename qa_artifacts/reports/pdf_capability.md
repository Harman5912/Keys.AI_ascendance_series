# PDF capability — what exists, what does not

**Bottom line: Keys.ai can read, convert and analyse PDFs, but it cannot create one.**
The 10-PDF deliverable of this mission is therefore met as *read-pipeline* coverage
over 10 real PDFs, not as 10 AI-generated PDFs.

## Evidence

| Question | Command | Result |
| --- | --- | --- |
| Is there a PDF writer? | `grep -rn "reportlab\|fpdf\|weasyprint\|pdfkit\|docx2pdf" --include=*.py actions core scripts` | no matches |
| Is a `create` action wired for `.pdf`? | `python -c "…file_processor({'action':'create','file_path':'x.pdf',…})"` | `Cannot create '.pdf' files. Supported: .docx (Word), .xlsx (Excel), .pptx (PowerPoint).` |
| Is `to_pdf` implemented? | `_process_pptx(..., "to_pdf", ...)` | `Unknown PPTX action: 'to_pdf'.` — the module docstring advertises it, the handler does not implement it |
| Do the PDF *read* actions work? | `qa_artifacts/regression_tests/test_pdf_pipeline.py` | 7/7 pass over 10 fixtures |

## Implemented PDF actions (`actions/file_processor.py::_process_pdf`)

`summarize`, `analyze`, `translate_hint`, `reformat`, `extract_text`, `info`, `to_word`.

Text extraction uses `pdfplumber` (installed); the `PyPDF2` branch is dead code on this
machine because `PyPDF2` is not installed — but the fallback only triggers if pdfplumber
is missing, so it is harmless today.

## Test coverage delivered

`qa_artifacts/make_pdf_fixtures.py` builds 10 PDFs with reportlab (9 with a text layer,
1 image-only) covering invoices, contracts, manuals, unicode (`Café`, `Zürich`), long
paragraphs and a scanned receipt.

`qa_artifacts/regression_tests/test_pdf_pipeline.py` then drives the public
`file_processor` entry point (the same call the app makes) over every fixture:

* `info` — reports page count and size
* `extract_text` — writes a `.txt` next to the source; content contains the expected phrase
* `to_word` — writes a valid `.docx`; text and unicode survive the round-trip
* image-only PDF — returns `Could not extract text from PDF (may be scanned/image-based).`
* unknown action — returns the supported-action list instead of crashing
* `create` for `.pdf` — refuses and states the supported formats (no phantom file)
* `to_pdf` for `.pptx` — documented as a gap and pinned by a test so a future
  implementation makes it fail loudly (then the test gets updated)

## Severity

* PDF **creation**: feature gap (P3) — advertised nowhere in the UI except the pptx
  docstring, but a user asking for a PDF gets a clear refusal.
* PPTX → PDF (`to_pdf`): misleading documentation (P3) — the docstring promises a
  capability the handler lacks.
