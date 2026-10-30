"""Phase 2 / Stage 3 evidence: can Keys.ai build the inventory app itself?

Runs the real tool path (`crown_code`, agent branch) against an isolated
workspace and records exactly what happened: files written, elapsed time, and
whether the result passes verification. Nothing here is simulated.

Attempt 1 (saved as `agent_inventory_attempt_v1_gate_refusal.json`) was refused
by the requirement gate, which asked which chart types the views should use.
This run supplies that answer, which is what a real user would do next.

Run:  python KEYSAI_PHASE2_RESULTS/tests/agent_inventory_attempt.py
Out:  KEYSAI_PHASE2_RESULTS/logs/agent_inventory_attempt.log
      KEYSAI_PHASE2_RESULTS/logs/agent_inventory_attempt.json
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

OUT = BASE / "KEYSAI_PHASE2_RESULTS"
WORKSPACE = OUT / "projects" / "inventory_system_AGENT_ATTEMPT"
LOG = OUT / "logs" / "agent_inventory_attempt.log"
REPORT = OUT / "logs" / "agent_inventory_attempt.json"

BRIEF = (
    "Build a small inventory management system: Python + Flask + SQLite, "
    "HTML/CSS/JS front end, a JSON API, dashboard statistics and stock "
    "movement history."
)
REQUIREMENTS = (
    "data source: SQLite file in the project folder (no server)\n"
    "entities: products (name, category, quantity, unit_price, reorder_level) "
    "and stock_movements (product_id, movement_type, quantity_change, reason)\n"
    "api: list/create/read/update/delete products, dashboard stats, movement "
    "history\n"
    "metrics: product count, total inventory value, low-stock count, units\n"
    "charts: KPI cards, a low-stock bar and a category breakdown drawn from "
    "the API responses\n"
    "stack: Flask + vanilla HTML/CSS/JS, parameterised SQL only\n"
    "tests: python unittest covering CRUD and the dashboard totals\n"
    "scope: local single user, no login"
)


def main() -> int:
    from actions import crown_code as cc

    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)

    started = time.time()
    lines: list[str] = []

    def log(line: str) -> None:
        lines.append(f"{time.strftime('%H:%M:%S')} {line}")
        print(line, flush=True)

    log(f"workspace: {WORKSPACE}")
    log("calling crown_code(action=build, wait=True, timeout=420)")
    reply = cc.crown_code({
        "description": BRIEF,
        "requirements": REQUIREMENTS,
        "workspace": str(WORKSPACE),
        "wait": True,
        "timeout": 420,
    })
    elapsed = round(time.time() - started, 1)

    files = sorted(str(p.relative_to(WORKSPACE)) for p in WORKSPACE.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts) \
        if WORKSPACE.exists() else []

    expected = ("app.py", "db.py", "schema.sql", "templates/index.html",
                "static/style.css", "requirements.txt", "README.md")
    present = {Path(f).name for f in files}
    missing = [name for name in expected if name not in present]

    record = {
        "test_id": "STAGE3-AGENT-001",
        "what": "Keys.ai builds the inventory system through its own agent path",
        "model": "qwen3:8b (ollama)",
        "seconds": elapsed,
        "reply": reply[-3000:],
        "file_count": len(files),
        "files": files,
        "missing_expected_files": missing,
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("\n".join(lines) + "\n\nREPLY:\n" + reply, encoding="utf-8")
    REPORT.write_text(json.dumps(record, indent=2), encoding="utf-8")

    log(f"done in {elapsed}s · {len(files)} files · missing {len(missing)}")
    for name in missing:
        log(f"  missing: {name}")
    return 0 if not missing and files else 1


if __name__ == "__main__":
    raise SystemExit(main())
