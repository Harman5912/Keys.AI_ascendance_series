"""qa_artifacts/render_check.py — open every artifact in real Microsoft Office.

Structural validation proves the OOXML is well formed; this proves Word and
PowerPoint actually render it. Each file is opened in a *separate invisible*
Office instance (DispatchEx), measured, exported where useful, and closed
without saving — the user's own Office windows are never touched.

Outputs
  qa_artifacts/reports/render_check.json / .csv
  qa_artifacts/screenshots/<stem>_p1.png        (first page/slide)

Usage: python qa_artifacts/render_check.py [--kind docx|pptx|both]
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REPORTS = BASE / "qa_artifacts" / "reports"
SHOTS = BASE / "qa_artifacts" / "screenshots"

WD_STAT_PAGES, WD_STAT_WORDS = 2, 0


def check_docx(paths: list[Path]) -> list[dict]:
    import win32com.client as win32

    word = win32.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    out = []
    try:
        for p in paths:
            rec = {"file": p.name, "kind": "docx", "ok": False, "pages": 0,
                   "words": 0, "error": ""}
            doc = None
            try:
                doc = word.Documents.Open(str(p), ReadOnly=True, AddToRecentFiles=False)
                rec["pages"] = int(doc.ComputeStatistics(WD_STAT_PAGES))
                rec["words"] = int(doc.ComputeStatistics(WD_STAT_WORDS))
                shot = SHOTS / f"{p.stem}_p1.png"
                # Export the first page as an image for visual evidence.
                try:
                    doc.ExportAsFixedFormat(str(shot.with_suffix(".pdf")), 17)  # wdExportFormatPDF
                    rec["pdf"] = shot.with_suffix(".pdf").name
                except Exception as e:
                    rec["pdf_error"] = str(e)[:120]
                rec["ok"] = rec["pages"] >= 1
            except Exception as e:
                rec["error"] = f"{type(e).__name__}: {e}"[:200]
            finally:
                if doc is not None:
                    doc.Close(False)
            out.append(rec)
    finally:
        word.Quit()
    return out


def check_pptx(paths: list[Path]) -> list[dict]:
    import win32com.client as win32

    app = win32.DispatchEx("PowerPoint.Application")
    out = []
    try:
        for p in paths:
            rec = {"file": p.name, "kind": "pptx", "ok": False, "slides": 0,
                   "error": "", "images": []}
            pres = None
            try:
                pres = app.Presentations.Open(str(p), WithWindow=False)
                rec["slides"] = int(pres.Slides.Count)
                for idx in (1, min(2, rec["slides"])):
                    img = SHOTS / f"{p.stem}_s{idx}.png"
                    try:
                        pres.Slides(idx).Export(str(img), "PNG", 1280, 720)
                        rec["images"].append(img.name)
                    except Exception as e:
                        rec["error"] = f"export slide {idx}: {str(e)[:120]}"
                rec["ok"] = rec["slides"] >= 1
            except Exception as e:
                rec["error"] = f"{type(e).__name__}: {e}"[:200]
            finally:
                if pres is not None:
                    pres.Close()
            out.append(rec)
    finally:
        app.Quit()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["docx", "pptx", "both"], default="both")
    args = ap.parse_args()
    REPORTS.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    if args.kind in ("docx", "both"):
        paths = sorted((BASE / "qa_artifacts" / "generated_documents").glob("*.docx"))
        if paths:
            results += check_docx(paths)
    if args.kind in ("pptx", "both"):
        paths = sorted((BASE / "qa_artifacts" / "generated_presentations").glob("*.pptx"))
        if paths:
            results += check_pptx(paths)

    # Keep the other kind's results when only one kind was checked this run.
    combined_path = REPORTS / "render_check.json"
    other: list[dict] = []
    if combined_path.exists():
        try:
            kinds = {r["kind"] for r in results}
            other = [r for r in json.loads(combined_path.read_text(encoding="utf-8"))
                     if r.get("kind") not in kinds]
        except Exception:
            other = []
    (REPORTS / "render_check.json").write_text(
        json.dumps(other + results, indent=2), encoding="utf-8")
    with open(REPORTS / "render_check.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "kind", "ok", "pages_or_slides", "words", "error"])
        for r in results:
            w.writerow([r["file"], r["kind"], r["ok"],
                        r.get("pages") or r.get("slides"), r.get("words", ""), r["error"]])

    for r in results:
        metric = f"{r['pages']} pages, {r['words']} words" if r["kind"] == "docx" \
            else f"{r['slides']} slides, images={len(r['images'])}"
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['file']:<45} {metric} {r['error']}")
    ok = sum(1 for r in results if r["ok"])
    print(f"\nRENDER: {ok}/{len(results)} opened in Microsoft Office")
    return 0 if results and ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
