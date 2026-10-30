"""qa_artifacts/run_all_tests.py — one reproducible entry point for the QA suite.

Runs, in order:
  1. the repository's own offline test files (via run_baseline.py)
  2. this mission's regression suites (qa_artifacts/regression_tests)
  3. the security scan
  4. document / presentation validation (if artifacts exist)
  5. browser audits of generated websites / webapps / portfolios (if artifacts exist)

Writes:
  qa_artifacts/reports/TEST_EXECUTION_LOG.csv
  qa_artifacts/reports/test_summary.json

Usage: python qa_artifacts/run_all_tests.py [--skip-browser]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REPORTS = BASE / "qa_artifacts" / "reports"
LOGS = BASE / "qa_artifacts" / "logs"


def run(cmd: list[str], log_name: str, timeout: int = 900) -> tuple[int, str, float]:
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / log_name
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(BASE), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        out, err, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else ""
        err = e.stderr if isinstance(e.stderr, str) else ""
        code = -9
    dur = round(time.time() - t0, 1)
    log.write_text(f"$ {' '.join(cmd)}\nexit={code} seconds={dur}\n\n"
                   f"---- stdout ----\n{out}\n---- stderr ----\n{err}\n", encoding="utf-8")
    return code, (out + "\n" + err), dur


def parse_unittest(text: str) -> tuple[int, int, list[str]]:
    ran = re.search(r"^Ran (\d+) tests?", text, re.M)
    total = int(ran.group(1)) if ran else 0
    failed = 0
    m = re.search(r"FAILED \((?:failures=(\d+))?(?:, )?(?:errors=(\d+))?\)", text)
    if m:
        failed = int(m.group(1) or 0) + int(m.group(2) or 0)
    elif re.search(r"^OK", text, re.M):
        failed = 0
    else:
        failed = max(total, 1)
    names = re.findall(r"^(?:FAIL|ERROR): (\S+)", text, re.M)
    return total, failed, names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-browser", action="store_true")
    args = ap.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    now = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")  # noqa: E731

    def add(suite: str, result: str, detail: str, seconds: float, evidence: str,
            model: str = "-", provider: str = "-"):
        rows.append({"timestamp": now(), "suite": suite, "result": result, "seconds": seconds,
                     "model": model, "provider": provider, "detail": detail[:400],
                     "evidence": evidence})

    # 1. repository tests
    code, out, dur = run([sys.executable, "-X", "utf8", "qa_artifacts/run_baseline.py",
                          "--timeout", "240"], "run_all_baseline.log", timeout=1800)
    res = {}
    try:
        res = json.loads((REPORTS / "baseline_results.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    passed = sum(1 for r in res if r.get("passed"))
    for r in res:
        add(f"repo:{r['file']}", "PASS" if r["passed"] else "FAIL",
            "exit=%s" % r["exit_code"], r["seconds"], r["log"])
    add("repo:baseline-total", "PASS" if passed == len(res) and res else "FAIL",
        f"{passed}/{len(res)} test files passed", dur, "qa_artifacts/reports/baseline_results.json")

    # 2. mission regression suites
    for mod in sorted((BASE / "qa_artifacts" / "regression_tests").glob("test_*.py")):
        name = f"qa_artifacts.regression_tests.{mod.stem}"
        code, out, dur = run([sys.executable, "-X", "utf8", "-m", "unittest", name, "-v"],
                             f"run_all_{mod.stem}.log", timeout=900)
        total, failed, names = parse_unittest(out)
        add(f"qa:{mod.stem}", "PASS" if code == 0 and failed == 0 else "FAIL",
            f"{total - failed}/{total} tests passed" + (f"; failing: {names[:4]}" if names else ""),
            dur, f"qa_artifacts/logs/run_all_{mod.stem}.log")

    # 3. security scan
    code, out, dur = run([sys.executable, "-X", "utf8", "qa_artifacts/security_scan.py"],
                         "run_all_security.log", timeout=600)
    findings = re.search(r"FINDINGS: (\d+)", out)
    add("qa:security_scan", "PASS" if code == 0 else "FAIL",
        f"findings={(findings.group(1) if findings else '?')}", dur,
        "qa_artifacts/reports/security_scan.txt")

    # 4. document / presentation validation
    for kind, folder in (("docx", "generated_documents"), ("pptx", "generated_presentations")):
        d = BASE / "qa_artifacts" / folder
        if any(d.glob(f"*.{kind}")):
            code, out, dur = run([sys.executable, "-X", "utf8", "qa_artifacts/validate_docs.py",
                                  "--kind", kind], f"run_all_validate_{kind}.log", timeout=600)
            m = re.search(r"VALIDATION: (\d+)/(\d+)", out)
            add(f"artifacts:{kind}", "PASS" if code == 0 else "FAIL",
                f"{m.group(1)}/{m.group(2)} validated" if m else "no artifacts",
                dur, f"qa_artifacts/reports/doc_validation.csv")

    # 5. browser audits
    if not args.skip_browser:
        for kind, folder in (("website", "generated_websites"), ("webapp", "generated_webapps"),
                             ("portfolio", "generated_portfolios")):
            d = BASE / "qa_artifacts" / folder
            if any(p.is_dir() for p in d.glob("*")):
                code, out, dur = run([sys.executable, "-X", "utf8", "qa_artifacts/audit_sites.py",
                                      "--kind", kind], f"run_all_audit_{kind}.log", timeout=1800)
                m = re.search(r"(\w+): (\d+)/(\d+) passed the browser audit", out)
                add(f"artifacts:{kind}-audit", "PASS" if code == 0 else "FAIL",
                    f"{m.group(2)}/{m.group(3)} passed" if m else "audit did not run",
                    dur, f"qa_artifacts/reports/site_audit_{kind}.csv")

    # write log
    with open(REPORTS / "TEST_EXECUTION_LOG.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["timestamp", "suite", "result", "seconds",
                                           "model", "provider", "detail", "evidence"])
        w.writeheader()
        w.writerows(rows)

    summary = {
        "generated": now(),
        "suites": len(rows),
        "pass": sum(1 for r in rows if r["result"] == "PASS"),
        "fail": sum(1 for r in rows if r["result"] == "FAIL"),
        "total_seconds": round(sum(r["seconds"] for r in rows), 1),
        "failing": [r["suite"] for r in rows if r["result"] == "FAIL"],
    }
    (REPORTS / "test_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
