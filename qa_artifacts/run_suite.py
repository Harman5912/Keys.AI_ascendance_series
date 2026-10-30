"""Run the whole regression suite one file per process.

Why not plain ``pytest qa_artifacts/regression_tests``? Several modules build a
real QApplication (some with QtWebEngine). Running them all in one interpreter
means the Qt state of one module is torn down underneath the next, and the
process dies with a segmentation fault that says nothing about the tests. Each
file passes on its own, so that is how the suite is run: one process per file,
which is also how any CI for a Qt app has to do it.

    python qa_artifacts/run_suite.py              # every test file
    python qa_artifacts/run_suite.py --timeout 180
    python qa_artifacts/run_suite.py test_globe   # files matching a substring

Exit code 0 only when every file passes.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "qa_artifacts" / "regression_tests"
SUMMARY = re.compile(r"(\d+) (passed|failed|error|skipped)")


def run(path: Path, timeout: float) -> tuple[str, int, str, float]:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(path), "-q", "--no-header",
             "-p", "no:cacheprovider"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=timeout,
        )
        code = proc.returncode
        out = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        code = 124
        out = f"timed out after {int(timeout)}s"
    spent = time.perf_counter() - started
    counts = {}
    for number, word in SUMMARY.findall(out):
        counts[word] = counts.get(word, 0) + int(number)
    if counts:
        detail = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
    else:
        detail = out.strip().splitlines()[-1][:90] if out.strip() else "(no output)"
    return path.stem, code, detail, spent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("match", nargs="?", default="")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    files = sorted(TESTS.glob("test_*.py"))
    if args.match:
        files = [f for f in files if args.match in f.name]
    if not files:
        print("no test files matched")
        return 2

    failures: list[str] = []
    print(f"running {len(files)} file(s), one process each, "
          f"{int(args.timeout)}s limit each\n", flush=True)
    for path in files:
        name, code, detail, spent = run(path, args.timeout)
        ok = code == 0
        print(f"{'PASS' if ok else 'FAIL'}  {name:38s} {spent:6.1f}s  {detail}",
              flush=True)
        if not ok:
            failures.append(name)

    print()
    print(f"{len(files) - len(failures)}/{len(files)} files passed")
    if failures:
        print("failed: " + ", ".join(failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
