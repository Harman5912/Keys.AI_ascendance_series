"""qa_artifacts/build_scorecard.py — aggregate every result file into SCORECARD.md.

Reads (whatever exists):
  reports/baseline_results.json      repository test files
  reports/TEST_EXECUTION_LOG.csv     the full repeatable suite run
  reports/doc_validation.json        DOCX/PPTX structural checks
  reports/render_check.json          Microsoft Office render check
  reports/site_audit_<kind>.json     Playwright audits
  reports/security_scan.txt          secret/bind scan

Writes: reports/SCORECARD.md

Usage: python qa_artifacts/build_scorecard.py
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REPORTS = BASE / "qa_artifacts" / "reports"


def load_json(name: str, default):
    p = REPORTS / name
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def pct(ok: int, total: int) -> str:
    return f"{ok}/{total} ({round(100 * ok / total) if total else 0}%)"


def main() -> int:
    lines: list[str] = ["# Scorecard — Keys.ai / Crown Code QA", ""]

    # ---------------- repository tests ----------------
    base = load_json("baseline_results.json", [])
    if base:
        ok = sum(1 for r in base if r.get("passed"))
        lines += ["## Repository test files", "",
                  f"**{pct(ok, len(base))} pass** "
                  f"(seconds: {round(sum(r.get('seconds', 0) for r in base), 1)})", ""]

    # ---------------- mission suites ----------------
    log = REPORTS / "TEST_EXECUTION_LOG.csv"
    if log.exists():
        with open(log, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        ok = sum(1 for r in rows if r["result"] == "PASS")
        lines += ["## Mission suites (qa_artifacts)", "",
                  "| suite | result | detail | seconds |", "| --- | --- | --- | --- |"]
        for r in rows:
            lines.append(f"| {r['suite']} | {r['result']} | {r['detail'][:90]} | {r['seconds']} |")
        lines += ["", f"**{pct(ok, len(rows))} suites pass**", ""]

    # ---------------- documents ----------------
    docs = load_json("doc_validation.json", [])
    for kind, label in (("docx", "Word documents"), ("pptx", "Presentations")):
        subset = [d for d in docs if d.get("kind") == kind]
        if not subset:
            continue
        ok = sum(1 for d in subset if d.get("passed"))
        fails = Counter()
        for d in subset:
            for f in d.get("fails", []):
                fails[f.split(":")[0]] += 1
        lines += [f"## {label} — structural validation", "",
                  f"**{pct(ok, len(subset))} pass** "
                  f"(bytes {min(d['bytes'] for d in subset):,}–{max(d['bytes'] for d in subset):,})", ""]
        if fails:
            lines.append("Failing checks: " + ", ".join(f"{k} ×{v}" for k, v in fails.items()))
            lines.append("")

    # ---------------- Office render ----------------
    render = load_json("render_check.json", [])
    if render:
        ok = sum(1 for r in render if r.get("ok"))
        detail = []
        for kind, label in (("docx", "pages"), ("pptx", "slides")):
            sub = [r for r in render if r["kind"] == kind]
            if sub:
                metric = label
                lo = min(r.get(metric, 0) for r in sub)
                hi = max(r.get(metric, 0) for r in sub)
                detail.append(f"{kind}: {len(sub)} files, {label} {lo}–{hi}")
        lines += ["## Microsoft Office render", "",
                  f"**{pct(ok, len(render))} open and render** — " + "; ".join(detail), ""]

    # ---------------- browser audits ----------------
    for kind in ("website", "webapp", "portfolio"):
        data = load_json(f"site_audit_{kind}.json", [])
        if not data:
            continue
        ok = sum(1 for d in data if d.get("passed"))
        fails = Counter()
        for d in data:
            for f in d.get("fails", []):
                fails[f.split(":")[0]] += 1
        lines += [f"## {kind} browser audit", "", f"**{pct(ok, len(data))} pass all checks**", ""]
        if fails:
            lines += ["| failing check | artifacts |", "| --- | --- |"]
            for k, v in fails.most_common():
                lines.append(f"| {k} | {v} |")
            lines.append("")

    # ---------------- security ----------------
    scan = REPORTS / "security_scan.txt"
    if scan.exists():
        text = scan.read_text(encoding="utf-8", errors="replace")
        findings = re.search(r"FINDINGS: (\d+)", text)
        local = re.search(r"Local exposure findings: (\d+)", text)
        lines += ["## Security scan", "",
                  f"Secret-pattern findings: **{findings.group(1) if findings else '?'}**; "
                  f"local-exposure findings: **{local.group(1) if local else '?'}** "
                  "(see BUGS.md B08/B09 for the two fixes).", ""]

    bugs = REPORTS / "BUGS.md"
    if bugs.exists():
        text = bugs.read_text(encoding="utf-8")
        fixed = text.count("**Fixed**")
        reported = text.count("Reported")
        lines += ["## Defects", "",
                  f"Fixed: **{fixed}** · Reported for decision: **{reported}**", ""]

    (REPORTS / "SCORECARD.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
