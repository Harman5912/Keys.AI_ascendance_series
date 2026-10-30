"""Bid load test for the Project Agent's research -> build path.

Two phases, both offline (no network, no models, no Qt):

  A. PLAN — every generated bid goes through intake and the planner. Asserts the
     plan is buildable: known workers, unique step ids, and that a research
     preset chosen on the bid produces a research step *before* the build.

  B. BUILD — a sample of bids runs the whole service: create -> answer the
     agent's questions -> research step -> build step. The builder records the
     brief it receives, so the test can prove the research actually reaches the
     build (a marker sentence that exists only on the researched page must
     appear in the build brief). This is the check that a build is "according
     to the research", not merely after it.

Usage:
    python qa_artifacts/load_test_bids.py                 # 10,000 bids, 200 built
    python qa_artifacts/load_test_bids.py --bids 20000 --full 400
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from universal_agent import intake, planner                      # noqa: E402
from universal_agent.service import ProjectAgentService          # noqa: E402
from universal_agent.tools import github as github_tool          # noqa: E402
from universal_agent.workers import presets as presets_mod       # noqa: E402

# The load test is an offline environment: the public GitHub API is stubbed so
# a bid never waits on the network (or on a 404 for a fake repository).
github_tool.inspect = lambda url: {                     # noqa: E731
    "ok": False, "error": "offline load-test environment",
    "requested_url": str(url)}

SUBJECTS = [
    "invoice tracker", "field service scheduler", "clinic booking system",
    "fleet maintenance dashboard", "grant application portal", "parts catalogue",
    "shift planner", "payroll export tool", "inventory reorder bot",
    "customer churn report", "supplier scorecard", "compliance checklist app",
    "warehouse picking list", "event registration page", "ticket triage board",
    "lease renewal tracker", "safety inspection log", "commission calculator",
    "subscription billing view", "route optimiser", "menu costing sheet",
    "volunteer rota", "lab sample register", "asset depreciation report",
]

AUDIENCES = ["for a small electrical contractor", "for a regional clinic group",
             "for a 40-truck logistics firm", "for a non-profit food bank",
             "for a municipal parks department", "for a SaaS billing team"]

PRESSURES = ["that works offline", "with a printable summary", "with CSV export",
             "that runs on a laptop", "with role-based access",
             "that imports last year's data"]

PRESET_SETS = [
    ["github"],
    ["github", "docs"],
    ["ui_design"],
    ["github", "ui_design"],
    ["national_search"],
    ["docs"],
    [],
]

def make_bids(count: int, rng: random.Random) -> list[dict]:
    """Distinct, plausible bids, deterministic for a given seed."""
    bids = []
    for i in range(count):
        subject = SUBJECTS[i % len(SUBJECTS)]
        audience = AUDIENCES[(i // len(SUBJECTS)) % len(AUDIENCES)]
        pressure = PRESSURES[(i // (len(SUBJECTS) * len(AUDIENCES))) % len(PRESSURES)]
        presets = list(PRESET_SETS[(i // 7) % len(PRESET_SETS)])
        kind = "software" if i % 4 else "research"
        if kind == "software":
            request = f"Build a {subject} {audience} {pressure} (bid #{i + 1})"
        else:
            request = (f"Research the best approach for a {subject} {audience} "
                       f"{pressure} (bid #{i + 1})")
        bids.append({"id": i + 1, "request": request, "kind": kind,
                     "presets": presets})
    return bids


def phase_plan(bids: list[dict]) -> dict:
    """Every bid through intake + planner; assert the plans are buildable."""
    failures: list[str] = []
    with_presets = 0
    for bid in bids:
        intent = intake.classify(bid["request"])
        analysis = intake.analyse(bid["request"], intent,
                                  {"presets": ", ".join(bid["presets"])}
                                  if bid["presets"] else None)
        plan = planner.deterministic_plan(bid["request"], analysis["brief"],
                                          intent, analysis["answers"])
        steps = plan.get("steps") or []
        if not steps:
            failures.append(f"bid {bid['id']}: empty plan")
            continue
        if len({s.get("id") for s in steps}) != len(steps):
            failures.append(f"bid {bid['id']}: duplicate step ids")
        for step in steps:
            if step.get("worker") not in planner.WORKERS:
                failures.append(f"bid {bid['id']}: unknown worker {step.get('worker')}")
        workers = [s.get("worker") for s in steps]
        if bid["presets"] and workers[0] == "research":
            with_presets += 1
            carried = steps[0]["params"].get("presets") or []
            if carried != presets_mod.parse(bid["presets"]):
                failures.append(f"bid {bid['id']}: presets not carried ({carried})")
            if "software" in workers:
                build = steps[workers.index("software")]
                if not build["params"].get("reuse_research"):
                    failures.append(f"bid {bid['id']}: build would ignore research")
        if "software" in workers and "research" in workers:
            if workers.index("research") > workers.index("software"):
                failures.append(f"bid {bid['id']}: build runs before research")
    return {"bids": len(bids), "plans_with_presets_first": with_presets,
            "failures": failures[:40], "failure_count": len(failures)}


def _answer_all(service, task_id: str, rng: random.Random) -> None:
    """Answer the agent's outstanding questions the way a user would."""
    task = service.get_task(task_id) or {}
    answers = {}
    for question in task.get("questions") or []:
        slot = str(question.get("slot") or "")
        if not slot or slot in (task.get("answers") or {}):
            continue
        options = question.get("options") or []
        if slot == "input_file":
            # A user asked for a file gets a real file, not the question's
            # placeholder text — the service validates the path exists.
            answers[slot] = str(_csv_fixture())
            continue
        answers[slot] = (str(question.get("default") or options[0]) if options
                         else str(question.get("hint") or "standard desktop app"))
    if answers:
        try:
            service.answer(task_id, answers)
        except Exception:
            pass


# Search hits are generated per query and remembered, so the page a later
# fetch returns is about the topic that was searched — the same shape a real
# search engine has, without the network.
_PAGES: dict[str, str] = {}
_PAGES_LOCK = threading.Lock()

_FIXTURE: Path | None = None


def _csv_fixture() -> Path:
    """One real CSV the test user can point the agent at."""
    global _FIXTURE
    if _FIXTURE is None:
        path = Path(tempfile.mkdtemp(prefix="loadtest_data_")) / "figures.csv"
        path.write_text("month,revenue\n2026-01,1200\n2026-02,1450\n",
                        encoding="utf-8")
        _FIXTURE = path
    return _FIXTURE


def _page_for(query: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", query)
             if w.lower() not in {"build", "research", "with", "that", "works",
                                  "from", "their", "into", "this", "about"}]
    topic = " ".join(words[:5]) or "the subject"
    return (f"{topic.title()} — reference notes. "
            f"The {topic} workflow creates one record per entry, keeps a status "
            f"field and returns an id from a single call. "
            f"Teams using {topic} export a monthly summary and review overdue "
            f"items first, because overdue work is the most expensive kind. "
            f"Documents for {topic} must stay readable offline and print cleanly.")


def _fake_search(query: str, limit: int = 5) -> list[dict]:
    slug = hashlib.sha1(str(query).encode("utf-8")).hexdigest()[:10]
    url = f"https://docs.example.com/{slug}"
    with _PAGES_LOCK:
        _PAGES[url] = _page_for(query)
    return [{"title": f"Reference: {query[:60]}", "url": url,
             "snippet": str(query)[:120]}]


_HTML = ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
         "<title>Built page</title></head><body><h1>Built</h1>"
         "<p>Generated in the load-test environment.</p></body></html>")


def _fake_fetch(url: str, timeout: float = 12.0) -> str:
    with _PAGES_LOCK:
        page = _PAGES.get(url)
    if page:
        return page
    return ("An invoice records a sale: line items, quantities, prices, tax and a "
            "due date. It is issued by the seller and kept for accounting, and a "
            "dashboard groups them by customer, status and month so overdue work "
            "is visible without opening each one individually in turn.")


def _fake_browser(url: str, dest: str = "") -> dict:
    """Design-reference screenshots, offline: a real PNG in the workspace."""
    target_dir = Path(dest) if dest else Path(tempfile.mkdtemp(prefix="refs_"))
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"ref_{hashlib.sha1(str(url).encode()).hexdigest()[:8]}.png"
    try:
        from PIL import Image
        Image.new("RGB", (160, 120), (12, 34, 56)).save(target, "PNG")
    except Exception:
        target.write_bytes(b"\x89PNG\r\n\x1a\n")
    return {"ok": True, "screenshot": str(target),
            "palette": ["#0c2238", "#ffffff"], "url": str(url)}


def phase_build(bids: list[dict], workers: int, seed: int,
                keep_workspaces: bool = False) -> dict:
    """Run the sampled bids through the real service, research included."""
    rng = random.Random(seed + 1)
    root = Path(tempfile.mkdtemp(prefix="loadtest_ws_"))
    built: dict[int, str] = {}
    lock = threading.Lock()

    def build_project(payload: dict) -> dict:
        workspace = Path(payload["workspace"])
        workspace.mkdir(parents=True, exist_ok=True)
        page = workspace / "index.html"
        page.write_text(_HTML, encoding="utf-8")
        with lock:
            built[payload["task"]["id"]] = str(payload.get("brief") or "")
        return {"ok": True, "summary": "built in the test environment",
                "artifacts": [str(page)], "notes": []}

    # No model in this environment: the service's default would reach for the
    # configured LLM, which is exactly the network the load test must not need.
    service = ProjectAgentService(
        complete=lambda prompt, system="": "", search=_fake_search,
        fetch=_fake_fetch, browser=_fake_browser, build_project=build_project,
        use_model_planner=False, workspace_root=str(root))

    queue = list(bids)
    progress = {"done": 0}
    results: dict = {"completed": 0, "failed": 0, "builds": 0,
                     "research_in_build": 0, "builds_without_research": 0,
                     "unbuilt": 0, "failures": [], "slowest": 0.0,
                     "total_seconds": 0.0,
                     # Kept separate from the capped `failures` list so a wave
                     # of one problem cannot hide the other kind.
                     "status_failure_count": 0, "status_failures": [],
                     "fidelity_by_reason": {}, "fidelity_failures": [],
                     "unbuilt_ids": []}
    lock_state = threading.Lock()

    def run_batch(batch: list[dict]) -> None:
        for bid in batch:
            started = time.perf_counter()
            try:
                task = service.create(bid["request"],
                                      answers={"presets": ", ".join(bid["presets"]),
                                               "depth": "quick"}
                                      if bid["presets"] else {"depth": "quick"})
            except Exception as exc:
                with lock_state:
                    results["failed"] += 1
                    results["failures"].append(f"bid {bid['id']}: create {exc}")
                continue
            tid = task["id"]
            deadline = time.time() + 120
            while time.time() < deadline:
                current = service.get_task(tid) or {}
                status = str(current.get("status") or "")
                if status == "WAITING_FOR_USER":
                    _answer_all(service, tid, rng)
                    time.sleep(0.01)
                    continue
                if status in ("COMPLETED", "FAILED", "CANCELLED"):
                    break
                time.sleep(0.02)
            final = service.get_task(tid) or {}
            elapsed = time.perf_counter() - started
            with lock_state:
                progress["done"] += 1
                if progress["done"] % 500 == 0:
                    print(f"  ... {progress['done']} bids run", flush=True)
            with lock_state:
                results["total_seconds"] += elapsed
                results["slowest"] = max(results["slowest"], elapsed)
                if str(final.get("status")) != "COMPLETED":
                    results["failed"] += 1
                    results["status_failure_count"] += 1
                    if len(results["status_failures"]) < 40:
                        results["status_failures"].append(
                            f"bid {bid['id']}: {final.get('status')} "
                            f"{str(final.get('error'))[:300]}")
                else:
                    results["completed"] += 1
            report_text = _report_text(final)
            steps = ((final.get("plan") or {}).get("steps") or [])
            expects_build = any(s.get("worker") == "software" for s in steps)
            brief = built.get(tid)
            if brief is None:
                if expects_build:
                    with lock_state:
                        results["unbuilt"] += 1
                        if len(results["unbuilt_ids"]) < 40:
                            results["unbuilt_ids"].append(str(bid["id"]))
                continue
            with lock_state:
                results["builds"] += 1
                problem = _fidelity_problem(brief, report_text)
                if problem is None:
                    results["research_in_build"] += 1
                else:
                    results["builds_without_research"] += 1
                    results["fidelity_by_reason"][problem] = \
                        results["fidelity_by_reason"].get(problem, 0) + 1
                    if len(results["fidelity_failures"]) < 40:
                        results["fidelity_failures"].append(
                            f"bid {bid['id']}: {problem}")

    threads = [threading.Thread(target=run_batch,
                                args=(queue[i::workers],), daemon=True)
               for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    results["sample"] = len(bids)
    results["mean_seconds"] = (results["total_seconds"] / len(bids)
                               if bids else 0.0)
    if keep_workspaces:
        results["workspace_root"] = str(root)
    else:
        shutil.rmtree(root, ignore_errors=True)
    # One capped list for the summary, fed from each bucket so neither kind of
    # failure can push the other out of the report.
    results["failures"] = (results["status_failures"]
                           + results["fidelity_failures"]
                           + [f"bid {i}: plan had a build step but no build ran"
                              for i in results["unbuilt_ids"]])[:40]
    return results


def _report_text(task: dict) -> str:
    """The research report this task produced, if it produced one."""
    for artifact in task.get("artifacts") or []:
        if not str(artifact.get("name") or "").endswith(".md"):
            continue
        try:
            return Path(str(artifact.get("path"))).read_text(
                encoding="utf-8", errors="replace")
        except Exception:
            continue
    return ""


def _fidelity_problem(brief: str, report: str) -> str | None:
    """Why the build brief does NOT carry the research, or None if it does.

    The build must receive the research report's own words: the findings block
    and at least one quoted line from it. Checking for a topic word would pass
    even when nothing was read, so this compares against the report text.
    """
    if "RESEARCH GATHERED EARLIER IN THIS TASK" not in brief:
        return "build brief did not include the research section"
    if not report:
        return "no research report was written"
    quotes = [line.strip("- “”\u201c\u201d ") for line in report.splitlines()
              if line.startswith("- “")]
    if not quotes:
        return "research report contained no quoted finding"
    if not any(quote[:40] in brief for quote in quotes):
        return "build brief carried none of the report's findings"
    if "## Findings" not in brief:
        return "build brief carried the report without its findings section"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bids", type=int, default=10_000)
    parser.add_argument("--full", type=int, default=200,
                        help="how many bids run the whole research->build path")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--report", default=str(ROOT / "qa_artifacts"
                                                 / "load_test_report.json"))
    parser.add_argument("--keep-workspaces", action="store_true",
                        help="keep the per-bid workspaces for inspection")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    started = time.perf_counter()
    bids = make_bids(args.bids, rng)
    print(f"generated {len(bids)} bids")

    plan_started = time.perf_counter()
    plan = phase_plan(bids)
    plan_seconds = time.perf_counter() - plan_started
    print(f"phase A (plan): {plan['bids']} bids in {plan_seconds:.1f}s"
          f"  presets-first={plan['plans_with_presets_first']}"
          f"  failures={plan['failure_count']}")

    sample = [b for b in bids if b["kind"] == "software"][:args.full]
    build = (phase_build(sample, args.workers, args.seed, args.keep_workspaces)
             if sample else {})
    if build:
        print(f"phase B (build): {build['sample']} bids in "
              f"{build['total_seconds']:.1f}s total, mean {build['mean_seconds']:.2f}s, "
              f"slowest {build['slowest']:.2f}s")
        print(f"  completed={build['completed']} failed={build['failed']} "
              f"builds={build['builds']} research-in-brief={build['research_in_build']} "
              f"missing-research={build['builds_without_research']} "
              f"unbuilt={build['unbuilt']}")
        if build.get("status_failure_count"):
            print(f"  status failures ({build['status_failure_count']}):")
            for line in build.get("status_failures") or []:
                print("   -", line)
        if build.get("fidelity_by_reason"):
            print("  fidelity problems by reason:")
            for reason, count in sorted(build["fidelity_by_reason"].items(),
                                        key=lambda kv: -kv[1]):
                print(f"   - {count} x {reason}")

    failures = plan["failures"] + (build.get("failures") or [])
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seed": args.seed,
        "bids": len(bids),
        "plan": plan,
        "build": build,
        "seconds": round(time.perf_counter() - started, 1),
        "failures": failures,
        "ok": not plan["failure_count"] and not (build.get("failures") or []),
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"report: {args.report}")
    if not report["ok"]:
        print("FAILURES:")
        for line in failures[:20]:
            print(" -", line)
        return 1
    print("OK — every bid planned, every sampled build carried its research")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
