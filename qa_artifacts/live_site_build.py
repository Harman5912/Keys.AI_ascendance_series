"""qa_artifacts/live_site_build.py — end-to-end check of the Crown Code site path.

Proves, against the real local model and a real browser:
  1. a portfolio request returns immediately and runs as a background job;
  2. progress can be read WHILE it builds (action=status and the brain's
     progress fast-path), so the conversation is never blocked;
  3. the finished index.html passes the structural checks AND the Chromium
     audit (no console errors, no overflow at 375/1280 px, working focus).

Run:  python qa_artifacts/live_site_build.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

LOGS = BASE / "qa_artifacts" / "logs"
REPORTS = BASE / "qa_artifacts" / "reports"
OUT = BASE / "qa_artifacts" / "live_build" / "portfolio_lena"

BRIEF = ("Build a portfolio website for the fictional photographer Lena Fischer. "
         "A gallery of nine tiles built from CSS gradients (no external files), "
         "a working category filter (portraits, landscape, studio), an about "
         "section, a booking enquiry form with validation, and a footer.")


class Player:
    """Minimal stand-in for the UI: records what the workspace would show."""

    def __init__(self):
        self.events: list[tuple] = []
        self.phases: list[tuple] = []
        self.progress: list[float] = []

    def _rec(self, *args):
        self.events.append(args)

    def __getattr__(self, name):
        if name.startswith("creation_") or name in ("write_log", "begin_creation",
                                                    "terminal_output", "ask_permission"):
            return (lambda *a, **k: self._rec(name, *a))
        raise AttributeError(name)

    def creation_phase(self, name, pct=-1.0, eta=0.0):
        self.phases.append((name, round(pct, 3), eta))

    def creation_progress(self, pct):
        self.progress.append(round(float(pct), 3))


def main() -> int:
    from actions.crown_code import crown_code
    from core import crown_jobs
    from core.site_checks import browser_audit, check_html

    LOGS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    if (OUT / "index.html").exists():
        (OUT / "index.html").unlink()

    player = Player()
    report: dict = {"brief": BRIEF, "workspace": str(OUT)}
    out_path = LOGS / "live_site_build.log"

    def say(line: str) -> None:
        print(line, flush=True)
        with out_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    out_path.write_text("", encoding="utf-8")
    say("=" * 78)
    say("LIVE SITE BUILD — Crown Code background job + progress + Chromium audit")
    say("=" * 78)

    # 1 ── the request must return at once and hand back a job id
    t0 = time.time()
    msg = crown_code({"description": BRIEF, "workspace": str(OUT), "kind": "portfolio",
                      "model": "qwen3:8b"}, player=player)
    call_seconds = time.time() - t0
    job = crown_jobs.get()
    report["start_call_seconds"] = round(call_seconds, 2)
    report["start_message"] = msg
    report["job_id"] = job.id if job else ""
    say(f"[1] request returned in {call_seconds:.2f}s with job={getattr(job, 'id', None)}")
    say("    " + msg.replace("\n", "\n    "))

    # 2 ── progress must be readable while the build runs
    progress_samples: list[str] = []
    mid_run_status = ""
    brain_answer = ""
    brain = None
    try:
        from brain.brain import KeysBrain
        brain = KeysBrain(enabled=True)
    except Exception as e:                                   # pragma: no cover
        say(f"[2] brain unavailable for the progress fast-path: {e}")

    index = OUT / "index.html"
    deadline = time.time() + 1500
    asked_brain = False
    first_page_seconds = None
    while job and job.active and time.time() < deadline:
        if first_page_seconds is None and index.exists():
            first_page_seconds = round(time.time() - t0, 1)
            say(f"[2] a working index.html exists after {first_page_seconds}s")
        line = crown_jobs.status_text(job.id)
        if not progress_samples or progress_samples[-1] != line:
            progress_samples.append(line)
            say("[2] status: " + line.replace("\n", " | "))
        if not mid_run_status and job.progress > 0.05:
            mid_run_status = crown_code({"action": "status", "job_id": job.id})
            say("[2] action=status while running:\n    " + mid_run_status.replace("\n", "\n    "))
        if brain is not None and not asked_brain and job.progress > 0.08:
            asked_brain = True
            answer = brain._build_progress("how's it going with the build?")
            brain_answer = answer or ""
            say("[2] brain progress answer: " + (brain_answer.splitlines() or ["(none)"])[0])
        time.sleep(3)

    if job:
        try:
            job.thread.join(30)
        except Exception:
            pass
    report["progress_samples"] = progress_samples[-6:]
    report["mid_run_status"] = mid_run_status
    report["brain_progress_answer"] = brain_answer
    report["first_page_seconds"] = first_page_seconds

    # 3 ── the artifact must pass structure + browser
    ok, problems = check_html(index, "portfolio")
    audit = browser_audit(index)
    html = index.read_text(encoding="utf-8", errors="replace") if index.exists() else ""
    job_result = dict(job.result) if job else {}
    report.update({
        "final_status": job.status if job else "no-job",
        "mode": (job_result.get("mode") if job else "") or "",
        "build_seconds": round(job.elapsed, 1) if job else 0.0,
        "result": {k: v for k, v in job_result.items()
                   if k in ("ok", "bytes", "seconds", "model", "notes", "used_fallback",
                            "mode", "checklist_score", "planner_model")},
        "checks_ok": ok, "checks_problems": problems,
        "browser": audit,
        "bytes": len(html),
        "phases_seen": sorted({p[0] for p in player.phases}),
        "progress_events": len(player.progress),
        "has_filter_js": "data-filter" in html or "filter" in html,
        "has_form": "<form" in html and "required" in html,
        "has_focus": ":focus-visible" in html,
        "no_external_assets": ("http://" not in html.replace("http://www.w3.org", "")
                               and "https://" not in html),
    })
    say("")
    say(f"[3] job status: {report['final_status']}  bytes={len(html)}")
    say(f"    checks: {'PASS' if ok else 'FAIL ' + str(problems)}")
    say(f"    browser: {audit.get('status')} {audit.get('problems')}")
    say(f"    phases seen: {report['phases_seen']}")
    say(f"    model used: {job_result.get('model', '')}")

    # The request must return at once (the build runs in the background) and a
    # working page must exist within a minute, long before the run finishes.
    passed = (report["final_status"] == "done" and ok
              and audit.get("status") == "ok" and call_seconds < 45
              and bool(mid_run_status) and bool(brain_answer)
              and bool(first_page_seconds) and first_page_seconds < 90
              and report["build_seconds"] < 300)
    report["passed"] = passed
    (REPORTS / "live_site_build.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    say("")
    say(f"first page after: {report['first_page_seconds']}s (target < 90s)")
    say(f"build seconds: {report['build_seconds']} (fast-path target: < 300s)")
    say(f"mode: {report['mode']}")
    say(f"RESULT: {'PASS' if passed else 'FAIL'} (report: qa_artifacts/reports/live_site_build.json)")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
