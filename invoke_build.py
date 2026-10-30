"""
invoke_build.py — run the three target builds through the app's own action.

Each target already has a brief.json in builds/<name>. This script calls
actions.crown_code.crown_code for each one with the requirements the recipe
builder needs in order to skip the intake gate, plus confirmed=true, and
wait=True so we get a final result back in-process.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from actions.crown_code import crown_code  # noqa: E402


LOG = PROJECT_ROOT / "builds" / "stream.log"


def log(line: str) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {line}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_brief(target_dir: Path) -> dict:
    return json.loads((target_dir / "brief.json").read_text(encoding="utf-8"))


def save_result(target_dir: Path, label: str, elapsed: float, result: str) -> Path:
    out = {
        "label": label,
        "dir": str(target_dir),
        "elapsed_s": round(elapsed, 1),
        "result": result,
    }
    path = LOG.parent / f"{target_dir.name}.result.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def run_one(target_dir: Path, label: str, requirements: str, timeout_s: int = 900) -> None:
    brief_file = target_dir / "brief.json"
    if not brief_file.exists():
        log(f"SKIP {label}: no brief.json")
        return

    brief = load_brief(target_dir)
    task = str(brief.get("request") or "").strip()

    log(f"=== START {label} in {target_dir} ===")
    log(f"task: {task[:160]}")
    log(f"requirements: {requirements[:160]}")

    t0 = time.time()
    result = crown_code(
        parameters={
            "action": "build",
            "description": task,
            "requirements": requirements,
            "confirmed": True,
            "workspace": str(target_dir),
            "wait": True,
            "timeout": str(timeout_s),
        },
    )
    elapsed = time.time() - t0
    log(f"--- {label} finished in {elapsed:.0f}s ---")
    log(f"result:\n{result}")
    path = save_result(target_dir, label, elapsed, result)
    log(f"wrote {path.name}")


def main() -> int:
    # Requirement answers that satisfy the intake gate for each recipe kind.
    # These are the user's answers in their words; confirmed=true says go ahead.
    targets = [
        (
            PROJECT_ROOT / "builds" / "pygame_lane_rush",
            "pygame_lane_rush",
            "single user local game, no login, no network, pygame window, "
            "score lives game over restart pause",
            900,
        ),
        (
            PROJECT_ROOT / "builds" / "sql_dashboard",
            "sql_dashboard",
            "single user local tool, no login, sqlite file on this machine, "
            "sample data seeded by seed.py, two chart types line and bar or pie, "
            "kpi row, data table, range filter 7d 30d 90d all, real sql queries",
            900,
        ),
        (
            PROJECT_ROOT / "builds" / "sql_core",
            "sql_core",
            "input: pipeline reads a folder of incoming CSV event files from an "
            "incoming folder the user sets at run time; output: curated tables in "
            "the same sqlite database plus a run log table that records each run; "
            "sqlite by default, same schema runs on mysql by changing the connection, "
            "automation is real and re-runnable",
            900,
        ),
    ]
    failed = 0
    for d, label, requirements, timeout in targets:
        try:
            run_one(d, label, requirements, timeout)
        except Exception as e:
            log(f"FAILED to invoke {label}: {e}")
            failed += 1
    log(f"=== ALL DONE ({failed} invocation failures) ===")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
