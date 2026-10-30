"""qa_artifacts/validate_docs.py — independently validate generated DOCX/PPTX.

Reopens every artifact with python-docx / python-pptx (no UI, no model) and
checks structure, content completeness, placeholder leakage and formatting.
Writes qa_artifacts/reports/doc_validation.json + .csv.

Usage: python qa_artifacts/validate_docs.py [--kind docx|pptx]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REPORTS = BASE / "qa_artifacts" / "reports"

PLACEHOLDER_PATTERNS = [
    r"\bTODO\b", r"\bTBD\b", r"\[insert", r"\[your", r"lorem ipsum",
    r"\{\{", r"\bXXX\b", r"info@company\.com", r"Prepared by Keys\.ai",
    r"\bplaceholder\b", r"<[a-z_]+>",
]


def _required_keywords() -> dict:
    """Import the specs so validation uses the same required-content lists."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen_docs", BASE / "qa_artifacts" / "gen_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = {}
    for s in mod.DOC_SPECS:
        out[s["id"]] = {"required": s.get("required", []), "min_paragraphs": s.get("min_paragraphs", 0),
                        "title": s["title"], "kind": "docx"}
    for s in mod.PPT_SPECS:
        out[s["id"]] = {"required": [], "min_slides": s.get("min_slides", 0),
                        "title": s["title"], "kind": "pptx"}
    return out


def validate_docx(path: Path, spec: dict) -> dict:
    from docx import Document
    checks: dict[str, tuple[bool, str]] = {}

    with open(path, "rb") as fh:
        sig = fh.read(4)
    checks["zip_signature"] = (sig == b"PK\x03\x04", f"signature={sig!r}")
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            integrity = z.testzip()
        checks["wordml_present"] = ("word/document.xml" in names, f"{len(names)} parts")
        checks["zip_integrity"] = (integrity is None, "testzip()")
    except Exception as e:
        checks["wordml_present"] = (False, str(e))
        checks["zip_integrity"] = (False, str(e))

    doc = Document(str(path))
    paras = doc.paragraphs
    texts = [p.text.strip() for p in paras]
    styles = [p.style.name for p in paras]
    body = "\n".join(texts)
    headings = [t for t, s in zip(texts, styles) if s.startswith("Heading")]
    bullets = [s for s in styles if s == "List Bullet"]
    numbered = [s for s in styles if s == "List Number"]

    checks["opens"] = (True, f"{len(paras)} paragraphs")
    checks["title_present"] = (bool(texts) and (spec["title"][:25].lower() in body.lower()),
                               f"first={texts[0][:60] if texts else ''!r}")
    checks["headings"] = (len(headings) >= 3, f"{len(headings)} heading paragraphs")
    checks["paragraph_count"] = (len([t for t in texts if t]) >= spec.get("min_paragraphs", 0),
                                 f"{len([t for t in texts if t])} non-empty "
                                 f"(min {spec.get('min_paragraphs', 0)})")
    checks["lists"] = (len(bullets) + len(numbered) >= 2,
                       f"{len(bullets)} bullets, {len(numbered)} numbered")

    missing = [k for k in spec.get("required", []) if k.lower() not in body.lower()]
    checks["required_content"] = (not missing, f"missing={missing}" if missing else "all present")

    leaked = re.findall(r"\*\*", body)
    checks["no_markdown_artifacts"] = (not leaked, f"{len(leaked)} '**' markers")
    found = [p for p in PLACEHOLDER_PATTERNS if re.search(p, body, re.I)]
    checks["no_placeholders"] = (not found, f"found={found}" if found else "clean")

    # Consecutive repeated headings signal a truncated/restarted generation.
    # Repeated sub-labels under different parents (e.g. "Decisions:" per agenda
    # item) are legitimate structure, so only adjacent repeats are flagged.
    dupes = {b for a, b in zip(headings, headings[1:]) if a == b}
    checks["no_duplicate_sections"] = (not dupes, f"dupes={sorted(dupes)}" if dupes else "none")

    # Unicode survives (em dash / accents used by the prompts).
    non_ascii = [c for c in body if ord(c) > 127]
    checks["unicode_preserved"] = (len(non_ascii) > 0, f"{len(non_ascii)} non-ascii chars")

    words = len(re.findall(r"\w+", body))
    checks["word_count"] = (words >= 120, f"{words} words")
    checks["file_size"] = (path.stat().st_size > 3000, f"{path.stat().st_size} bytes")

    return {"checks": checks, "headings": headings, "words": words,
            "paragraphs": len([t for t in texts if t])}


def validate_pptx(path: Path, spec: dict) -> dict:
    from pptx import Presentation
    from pptx.util import Emu
    checks: dict[str, tuple[bool, str]] = {}

    with open(path, "rb") as fh:
        sig = fh.read(4)
    checks["zip_signature"] = (sig == b"PK\x03\x04", f"signature={sig!r}")
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            integrity = z.testzip()
        checks["zip_integrity"] = (integrity is None, "testzip()")
        checks["presentation_part"] = ("ppt/presentation.xml" in names, f"{len(names)} parts")
    except Exception as e:
        checks["zip_integrity"] = (False, str(e))
        checks["presentation_part"] = (False, str(e))

    prs = Presentation(str(path))
    slides = list(prs.slides)
    titles, bodies, overflow = [], [], []
    for idx, slide in enumerate(slides, 1):
        t = ""
        if slide.shapes.title is not None:
            t = (slide.shapes.title.text or "").strip()
        titles.append(t)
        body = []
        for shape in slide.shapes:
            if shape.has_text_frame and shape != slide.shapes.title:
                body.append(shape.text_frame.text or "")
            # crude overflow signal: a text box wider than the slide or text
            # considerably longer than its box can show at the set size
            if shape.has_text_frame and shape.width and shape.width > prs.slide_width:
                overflow.append(f"slide {idx} shape wider than slide")
        bodies.append("\n".join(body))

    all_text = "\n".join(titles + bodies)
    checks["opens"] = (True, f"{len(slides)} slides")
    checks["slide_count"] = (len(slides) >= spec.get("min_slides", 0),
                             f"{len(slides)} slides (min {spec.get('min_slides', 0)})")
    checks["titles_on_every_slide"] = (all(t for t in titles),
                                       f"untitled slides={[i+1 for i, t in enumerate(titles) if not t]}")
    checks["distinct_titles"] = (len(set(t.lower() for t in titles)) == len(titles),
                                 f"{len(set(titles))} unique of {len(titles)}")
    checks["body_content"] = (sum(len(b) for b in bodies) >= 150,
                              f"{sum(len(b) for b in bodies)} body chars")
    checks["no_blank_slides"] = (all(len(b) > 0 for b in bodies), f"{len(slides)} slides checked")

    leaked = re.findall(r"\*\*", all_text)
    checks["no_markdown_artifacts"] = (not leaked, f"{len(leaked)} '**' markers")
    found = [p for p in PLACEHOLDER_PATTERNS if re.search(p, all_text, re.I)]
    checks["no_placeholders"] = (not found, f"found={found}" if found else "clean")

    # Fallback template detection: the generic "Prepared by Keys.ai"/"info@company.com"
    # deck must never be presented as generated content.
    fallback_marks = ["Prepared by Keys.ai", "info@company.com", "TAM: $50B by 2027"]
    used_fallback = any(m in all_text for m in fallback_marks)
    checks["not_fallback_template"] = (not used_fallback,
                                       "fallback template detected" if used_fallback else "model content")

    checks["widescreen"] = (abs(prs.slide_width - Emu(12192000)) < Emu(50000),
                            f"width={prs.slide_width} height={prs.slide_height}")
    checks["no_overflow"] = (not overflow, "; ".join(overflow[:3]) if overflow else "none")
    checks["file_size"] = (path.stat().st_size > 15000, f"{path.stat().st_size} bytes")

    return {"checks": checks, "titles": titles, "slides": len(slides)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["docx", "pptx", "both"], default="both")
    args = ap.parse_args()

    specs = _required_keywords()
    results = []
    for kind, folder in (("docx", "generated_documents"), ("pptx", "generated_presentations")):
        if args.kind not in (kind, "both"):
            continue
        d = BASE / "qa_artifacts" / folder
        for path in sorted(d.glob(f"*.{kind}")):
            spec = specs.get(path.name.split("_")[0], {"required": [], "min_paragraphs": 0,
                                                       "min_slides": 0, "title": "",
                                                       "kind": kind})
            rec = {"file": path.name, "kind": kind, "path": str(path.relative_to(BASE)).replace("\\", "/"),
                   "bytes": path.stat().st_size, "error": ""}
            try:
                detail = validate_docx(path, spec) if kind == "docx" else validate_pptx(path, spec)
            except Exception as e:
                rec.update({"passed": False, "fails": [f"validator error: {e}"], "checks": {}})
                results.append(rec)
                continue
            fails = [f"{name}: {msg}" for name, (ok, msg) in detail["checks"].items() if not ok]
            rec["passed"] = not fails
            rec["fails"] = fails
            rec["checks"] = {name: {"ok": ok, "detail": msg}
                             for name, (ok, msg) in detail["checks"].items()}
            if kind == "docx":
                rec["headings"] = detail["headings"]
                rec["words"] = detail["words"]
                rec["paragraphs"] = detail["paragraphs"]
            else:
                rec["titles"] = detail["titles"]
                rec["slides"] = detail["slides"]
            results.append(rec)
            print(f"{'PASS' if rec['passed'] else 'FAIL'}  {path.name}  "
                  f"({rec['bytes']} B)" + ("" if rec["passed"] else f"\n      - " + "\n      - ".join(fails)),
                  flush=True)

    REPORTS.mkdir(parents=True, exist_ok=True)
    kind_name = args.kind if args.kind in ("docx", "pptx") else "both"
    (REPORTS / f"doc_validation_{kind_name}.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8")

    # Combined view: keep the other kind's results when only one was validated.
    combined_path = REPORTS / "doc_validation.json"
    combined: list[dict] = []
    if combined_path.exists():
        try:
            combined = [r for r in json.loads(combined_path.read_text(encoding="utf-8"))
                        if r.get("kind") != kind_name]
        except Exception:
            combined = []
    combined = combined + results
    combined_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    with open(REPORTS / "doc_validation.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "kind", "passed", "bytes", "words_or_slides", "fails"])
        for r in results:
            metric = r.get("words") if r["kind"] == "docx" else r.get("slides")
            w.writerow([r["file"], r["kind"], r["passed"], r["bytes"], metric, " | ".join(r.get("fails", []))])

    passed = sum(1 for r in results if r["passed"])
    print(f"\nVALIDATION: {passed}/{len(results)} artifacts pass all structural checks")
    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
