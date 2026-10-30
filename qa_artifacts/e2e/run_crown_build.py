"""One real Crown Code build, start to finish, with no stubs.

Runs the actual action layer: crown_code() starts a background job, the real
CrownBridge subprocess drives the local model (qwen3:8b over Ollama), and the
job result is printed when it settles.

Run:  python qa_artifacts/e2e/run_crown_build.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from actions import crown_code as cc  # noqa: E402

BRIEF = (
    "Create wordcount.py in this folder: a Python 3 command-line script that takes "
    "one argument (a text file path), prints 'words: <count>' where count is the "
    "number of whitespace-separated words in the file, and exits with code 2 and a "
    "usage line if the argument is missing. Also create sample.txt with three short "
    "lines of text, test_wordcount.py with unittest tests that cover a normal file "
    "and the missing-argument case, and README.md with the run command. Then run the "
    "tests and the script once and report the actual output."
)

TIMEOUT = 420


def main() -> int:
    ws = Path(__file__).resolve().parent / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    for old in ws.iterdir():
        if old.is_file():
            old.unlink()

    print(f"[e2e] workspace: {ws}")
    started = time.time()
    msg = cc.crown_code({"description": BRIEF, "workspace": str(ws), "timeout": TIMEOUT})
    print("[e2e] crown_code returned in %.1fs:\n%s" % (time.time() - started, msg))

    manager = cc._get_manager()
    job = None
    deadline = time.time() + TIMEOUT + 180
    last = ""
    while time.time() < deadline:
        job = manager.get()
        if job is None:
            print("[e2e] no job registered")
            return 1
        line = f"{job.status} {int(job.progress * 100)}% {job.phase} {job.phase_detail}"
        if line != last:
            print(f"[e2e] {line}", flush=True)
            last = line
        if not job.active:
            break
        time.sleep(2)

    if job is None:
        return 1
    print("\n[e2e] status:", job.status, "elapsed:", round(job.elapsed, 1), "s")
    print("[e2e] files touched:", job.files)
    print("[e2e] error:", job.error or "(none)")
    print("[e2e] result:")
    print(json.dumps({k: v for k, v in (job.result or {}).items() if k != "summary"},
                     indent=2, default=str)[:2000])
    print("\n[e2e] describe:\n" + job.describe(12))

    on_disk = sorted(p.name for p in ws.iterdir() if p.is_file())
    print("\n[e2e] on disk:", on_disk)
    return 0 if job.status == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
