"""qa_artifacts/run_batch.py — run one artifact generator per subprocess with a
hard timeout, so a hung model call can never stall the whole batch.

Usage:
  python qa_artifacts/run_batch.py --kind docx --timeout 300
  python qa_artifacts/run_batch.py --kind pptx --timeout 360 --ids P01,P02
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOG = BASE / "qa_artifacts" / "logs"
REPORTS = BASE / "qa_artifacts" / "reports"


def spec_ids(kind: str) -> list[str]:
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen_docs", BASE / "qa_artifacts" / "gen_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return [s["id"] for s in (mod.DOC_SPECS if kind == "docx" else mod.PPT_SPECS)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["docx", "pptx"], required=True)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--ids", default="")
    ap.add_argument("--model", default="qwen3:8b")
    args = ap.parse_args()

    ids = [i.strip() for i in args.ids.split(",") if i.strip()] or spec_ids(args.kind)
    LOG.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    results = []

    for rid in ids:
        log = LOG / f"gen_{args.kind}_{rid}.log"
        t0 = time.time()
        timed_out = False
        try:
            proc = subprocess.run(
                [sys.executable, "-X", "utf8", str(BASE / "qa_artifacts" / "gen_docs.py"),
                 "--kind", args.kind, "--only", rid, "--model", args.model],
                cwd=str(BASE), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=args.timeout,
            )
            out, err, code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as e:
            timed_out, code = True, -9
            out = e.stdout if isinstance(e.stdout, str) else ""
            err = e.stderr if isinstance(e.stderr, str) else ""
        dur = round(time.time() - t0, 1)
        log.write_text(f"# {rid} exit={code} timeout={timed_out} seconds={dur}\n"
                       f"# ---- stdout ----\n{out}\n# ---- stderr ----\n{err}\n", encoding="utf-8")
        rec = {"id": rid, "kind": args.kind, "exit": code, "timed_out": timed_out,
               "seconds": dur, "log": str(log.relative_to(BASE)).replace("\\", "/"),
               "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        results.append(rec)
        status = "TIMEOUT" if timed_out else ("OK" if code == 0 else f"EXIT {code}")
        print(f"[{rid}] {status} in {dur}s -> {rec['log']}", flush=True)

    (REPORTS / f"batch_{args.kind}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    # Restore the user's file_processor model no matter what happened.
    subprocess.run([sys.executable, "-c",
                    "from core.api_config import set_task_model;"
                    "set_task_model('file_processor','gemini','gemini-2.5-flash')"],
                   cwd=str(BASE), capture_output=True)
    bad = [r for r in results if r["timed_out"] or r["exit"] != 0]
    print(f"\n{args.kind}: {len(results) - len(bad)}/{len(results)} runs completed"
          + (f"; problems: {[r['id'] for r in bad]}" if bad else ""))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
