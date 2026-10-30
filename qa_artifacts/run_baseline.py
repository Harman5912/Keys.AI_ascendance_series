"""qa_artifacts/run_baseline.py — run the repository's existing test suite.

Runs every test_*.py in the project root (except the ones listed in SKIP, which
are run separately because they drive a real local model / real agent loop or
open a browser window), with a per-file timeout, and writes machine-readable
results to qa_artifacts/reports/baseline_results.json + .csv.

Usage:  python qa_artifacts/run_baseline.py [--timeout 240] [--include-slow]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "qa_artifacts" / "reports"
LOGS = BASE / "qa_artifacts" / "logs"

# Tests that talk to a real local model / spawn the Crown Code agent / open a
# browser window. They are exercised by dedicated runs, not this batch.
SLOW = {
    "test_crown_code.py",     # real Ollama inference + Crown Code agent loop
    "test_crown_flow.py",     # same, through the in-app dispatch path
    "test_browser_control.py",  # fake session, but keep it separate if Playwright is busy
}


def run_one(path: Path, timeout: int) -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["NO_COLOR"] = "1"
    started = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", path.name],
            cwd=str(BASE), env=env, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
        code, out, err = proc.returncode, proc.stdout, proc.stderr
        timed_out = False
    except subprocess.TimeoutExpired as e:
        code, timed_out = -9, True
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        err = (e.stderr or "") if isinstance(e.stderr, str) else ""
    dur = round(time.time() - started, 2)

    log = LOGS / f"baseline_{path.stem}.log"
    log.write_text(
        f"# {path.name}  exit={code}  seconds={dur}  timeout={timed_out}\n"
        f"# ---- stdout ----\n{out}\n# ---- stderr ----\n{err}\n",
        encoding="utf-8",
    )
    tail = [ln for ln in (out or "").splitlines() if ln.strip()][-12:]
    return {
        "file": path.name,
        "exit_code": code,
        "timed_out": timed_out,
        "seconds": dur,
        "passed": code == 0 and not timed_out,
        "log": str(log.relative_to(BASE)).replace("\\", "/"),
        "tail": tail,
        "stderr_tail": [ln for ln in (err or "").splitlines() if ln.strip()][-6:],
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--include-slow", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    files = sorted(BASE.glob("test_*.py"))
    if not args.include_slow:
        files = [f for f in files if f.name not in SLOW]

    results = []
    for f in files:
        print(f"== {f.name} ...", flush=True)
        r = run_one(f, args.timeout)
        results.append(r)
        print(f"   {'PASS' if r['passed'] else 'FAIL'}  exit={r['exit_code']}  "
              f"{r['seconds']}s  log={r['log']}", flush=True)
        if not r["passed"]:
            for ln in (r["tail"] or [])[-5:]:
                print(f"      | {ln}", flush=True)

    (OUT / "baseline_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    with open(OUT / "baseline_results.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "passed", "exit_code", "timed_out",
                                           "seconds", "log", "timestamp"])
        w.writeheader()
        for r in results:
            w.writerow({k: r[k] for k in w.fieldnames})

    passed = sum(1 for r in results if r["passed"])
    print(f"\nBASELINE: {passed}/{len(results)} files passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
