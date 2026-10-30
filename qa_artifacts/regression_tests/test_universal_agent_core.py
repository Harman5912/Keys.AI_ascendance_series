"""Regression tests: Universal Project Agent core.

Covers task state and persistence, intake questions and defaults, workspace
security, the planner's bounded model refinement, and the service's
run/validate/repair/approve/cancel/resume loop with deterministic fake workers.

Model-dependent behaviour is mocked here on purpose; the real integration
points (documents, data, images, browser, research) are tested in
test_universal_agent_workers.py.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from universal_agent import intake, models, planner, security  # noqa: E402
from universal_agent.models import Status  # noqa: E402
from universal_agent.service import ProjectAgentService  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ua_core_"))
        self._patches = [
            mock.patch.object(models, "TASKS_DIR", self.tmp / "tasks"),
            mock.patch.object(models, "AUDIT_PATH", self.tmp / "audit.jsonl"),
        ]
        for p in self._patches:
            p.start()
        self.workspace_root = self.tmp / "workspaces"

    def tearDown(self):
        # Let any in-flight task thread finish before its temp directory goes
        # away, otherwise a late models.save() races the cleanup.
        for svc in getattr(self, "_services", []):
            try:
                svc.cancel_all()
                for thread in list(getattr(svc, "_threads", {}).values()):
                    thread.join(3.0)
            except Exception:
                pass
        time.sleep(0.05)
        for p in reversed(self._patches):
            p.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def service(self, executors=None, **kwargs):
        svc = ProjectAgentService(
            executors=executors or {},
            use_model_planner=kwargs.pop("use_model_planner", False),
            workspace_root=self.workspace_root,
            **kwargs)
        self._services = getattr(self, "_services", [])
        self._services.append(svc)
        return svc

    def wait(self, service, task_id, statuses=("COMPLETED", "FAILED",
                                               "CANCELLED", "WAITING_FOR_USER",
                                               "WAITING_FOR_APPROVAL"),
             timeout=20.0):
        deadline = time.time() + timeout
        task = None
        while time.time() < deadline:
            task = service.get_task(task_id)
            if task and task["status"] in statuses:
                return task
            time.sleep(0.05)
        self.fail(f"task did not reach {statuses}: {task}")


def _write(ctx, name="report.md", body="Real content, long enough to validate. [1]\n"):
    p = ctx.write_text(name, "# Report\n\n" + body * 3)
    return {"ok": True, "summary": "worker done",
            "artifacts": [ctx.artifact(p, "markdown", "report")],
            "evidence": [], "warnings": [], "error": "", "notes": []}


class TestState(_Base):
    def test_valid_transition(self):
        task = models.new_task("do a thing", "research")
        models.set_status(task, Status.READY)
        models.set_status(task, Status.PLANNING)
        self.assertEqual(task["status"], "PLANNING")

    def test_illegal_transition_rejected(self):
        task = models.new_task("do a thing", "research")
        with self.assertRaises(models.StateError):
            models.set_status(task, Status.COMPLETED)

    def test_persistence_round_trip(self):
        task = models.new_task("persist me", "research")
        task["answers"] = {"depth": "deep"}
        task["plan"] = {"steps": [{"id": "s1", "worker": "research"}]}
        models.set_status(task, Status.READY)
        models.save(task)
        loaded = models.load(task["id"])
        self.assertEqual(loaded["answers"]["depth"], "deep")
        self.assertEqual(loaded["plan"]["steps"][0]["worker"], "research")

    def test_recoverable_classification(self):
        task = models.new_task("x", "research")
        models.set_status(task, Status.READY)
        models.set_status(task, Status.RUNNING)
        self.assertTrue(models.recoverable(task))
        task["status"] = "COMPLETED"
        self.assertFalse(models.recoverable(task))

    def test_two_tasks_isolated(self):
        a = models.new_task("a", "research")
        b = models.new_task("b", "research")
        models.save(a)
        models.save(b)
        a["answers"] = {"only": "a"}
        models.save(a)
        self.assertNotIn("only", models.load(b["id"])["answers"])

    def test_cancelled_task_is_terminal(self):
        task = models.new_task("x", "research")
        models.set_status(task, Status.READY)
        models.set_status(task, Status.RUNNING)
        models.set_status(task, Status.CANCELLED)
        with self.assertRaises(models.StateError):
            models.set_status(task, Status.RUNNING)

    def test_failure_does_not_touch_other_task(self):
        good = models.new_task("good", "research")
        bad = models.new_task("bad", "research")
        models.set_status(good, Status.READY)
        models.set_status(bad, Status.READY)
        models.set_status(bad, Status.RUNNING)
        models.set_status(bad, Status.FAILED)
        models.save(good)
        models.save(bad)
        self.assertEqual(models.load(good["id"])["status"], "READY")
        self.assertEqual(models.load(bad["id"])["status"], "FAILED")

    def test_audit_log_is_truthful(self):
        entry = security.audit_line("task.approval", "id title", "rejected")
        models.audit(entry)
        rows = models.read_audit()
        self.assertTrue(any(r["outcome"] == "rejected" for r in rows))

    def test_delete_removes_task(self):
        task = models.new_task("delete me", "research")
        models.save(task)
        self.assertTrue(models.delete(task["id"]))
        self.assertIsNone(models.load(task["id"]))

    def test_list_tasks_newest_first(self):
        for i in range(3):
            task = models.new_task(f"task {i}", "research")
            task["updated_at"] = f"2026-01-0{i + 1} 10:00:00"
            models.save(task)
        listed = models.list_tasks()
        self.assertEqual(listed[0]["request"], "task 2")


class TestIntake(_Base):
    def test_fully_specified_research_does_not_ask_required(self):
        result = intake.analyse(
            "Research the state of local LLM runtimes in depth and write a "
            "markdown report")
        self.assertEqual(result["pending_required"], [])
        self.assertEqual(result["intent"], "research")

    def test_incomplete_portfolio_asks(self):
        result = intake.analyse("Build a portfolio website")
        self.assertTrue(result["pending_required"])
        self.assertEqual(result["intent"], "software")

    def test_service_pauses_for_answers(self):
        svc = self.service()
        task = svc.create("Build a portfolio website")
        self.assertEqual(task["status"], "WAITING_FOR_USER")
        self.assertTrue(task["questions"])
        self.assertFalse(task["workspace"] == "")

    def test_answers_are_not_asked_again(self):
        first = intake.analyse("Build a portfolio website")
        slot = first["pending_required"][0]["slot"]
        second = intake.analyse("Build a portfolio website", answers={slot: "x"})
        slots = [q["slot"] for q in second["pending_required"]]
        self.assertNotIn(slot, slots)

    def test_optional_defaults_recorded_as_assumptions(self):
        result = intake.analyse("Research local LLM runtimes")
        self.assertEqual(result["defaults"].get("depth"), "standard")
        self.assertTrue(any("depth" in a for a in result["assumptions"]))

    def test_research_format_default(self):
        result = intake.analyse("Research the history of the transistor")
        self.assertEqual(result["defaults"].get("format"), "markdown")

    def test_document_format_default(self):
        result = intake.analyse("Create a report about solar panels")
        self.assertEqual(result["defaults"].get("format"), "word")

    def test_browser_requires_url(self):
        result = intake.analyse("Open a website and check the pricing page")
        self.assertTrue(any(q["slot"] == "url" for q in result["pending_required"]))

    def test_image_edit_requires_file(self):
        result = intake.analyse("Resize my photo to 800x600")
        self.assertTrue(any(q["slot"] == "input_file"
                            for q in result["pending_required"]))

    def test_data_requires_file(self):
        result = intake.analyse("Analyse the sales spreadsheet")
        self.assertTrue(any(q["slot"] == "input_file"
                            for q in result["pending_required"]))

    def test_classification_matrix(self):
        cases = {
            "Build a portfolio website for a photographer": "software",
            "Research and compare local LLM runtimes": "research",
            "Create a PDF report about solar energy": "documents",
            "Analyse this CSV file C:/data/x.csv": "data",
            "Resize photo.png to 800x600": "images",
            "Open https://example.com and read the page": "browser",
            "What should I do about the launch?": "general",
        }
        for request, expected in cases.items():
            with self.subTest(request=request):
                self.assertEqual(intake.classify(request), expected)

    def test_brief_keeps_answers_and_criteria(self):
        result = intake.analyse("Research X", answers={
            "depth": "deep", "format": "pdf"})
        brief = result["brief"]
        self.assertEqual(brief["answers"]["depth"], "deep")
        self.assertTrue(brief["acceptance_criteria"])
        self.assertIn("citation", " ".join(brief["acceptance_criteria"]).lower())

    def test_analysis_uses_defaults_without_blocking(self):
        result = intake.analyse("Research the history of C")
        self.assertEqual(result["pending_required"], [])
        self.assertEqual(result["answers"].get("depth"), "standard")


class TestSecurity(_Base):
    def test_path_traversal_rejected(self):
        root = self.tmp / "ws"
        root.mkdir()
        with self.assertRaises(security.SecurityError):
            security.resolve_within(root, root / ".." / "escape.txt")

    def test_absolute_outside_rejected(self):
        root = self.tmp / "ws"
        root.mkdir()
        outside = self.tmp / "outside.txt"
        outside.write_text("x")
        with self.assertRaises(security.SecurityError):
            security.resolve_within(root, outside)

    def test_safe_filename_strips_directories(self):
        self.assertEqual(security.safe_filename("../../etc/passwd"),
                         "passwd")
        self.assertEqual(security.safe_filename("a<b>c?.md"), "abc.md")

    def test_unique_path_never_overwrites(self):
        d = self.tmp / "out"
        d.mkdir()
        first = security.unique_path(d, "x.md")
        first.write_text("one")
        second = security.unique_path(d, "x.md")
        self.assertNotEqual(first, second)

    def test_input_file_validation(self):
        empty = self.tmp / "empty.csv"
        empty.write_text("")
        with self.assertRaises(security.SecurityError):
            security.validate_input_file(empty)
        missing = self.tmp / "missing.csv"
        with self.assertRaises(security.SecurityError):
            security.validate_input_file(missing)
        ok = self.tmp / "ok.csv"
        ok.write_text("a,b\n1,2\n")
        self.assertEqual(security.validate_input_file(ok), ok.resolve())

    def test_unsupported_input_suffix_refused(self):
        weird = self.tmp / "thing.exe"
        weird.write_bytes(b"MZ")
        with self.assertRaises(security.SecurityError):
            security.validate_input_file(weird)

    def test_secret_redaction(self):
        text = ("key sk-abcdefghijklmnopqrstuvwx and AIza"
                "123456789012345678901234567890123 and password=hunter2")
        clean = security.redact_secrets(text)
        self.assertNotIn("sk-abcdefghijklmnop", clean)
        self.assertNotIn("hunter2", clean)
        self.assertIn("***", clean)

    def test_approval_policy_semantics(self):
        self.assertFalse(security.requires_approval("create"))
        self.assertTrue(security.requires_approval("create", destructive=True))
        self.assertTrue(security.requires_approval("send", external=True))

    def test_outside_artifact_fails_the_task(self):
        svc = self.service()

        def outside(ctx):
            p = self.tmp / "escaped.md"
            p.write_text("outside the workspace")
            return {"ok": True, "summary": "wrote outside",
                    "artifacts": [{"path": str(p), "kind": "markdown"}],
                    "evidence": [], "warnings": [], "error": "", "notes": []}

        svc._executors = {"research": outside}
        task = svc.create("Research x")
        done = self.wait(svc, task["id"], statuses=("COMPLETED", "FAILED"))
        self.assertEqual(done["status"], "FAILED")
        self.assertIn("outside", done["error"].lower())

    def test_worker_secret_never_reaches_events(self):
        svc = self.service()

        def leaky(ctx):
            raise RuntimeError("provider rejected key sk-abcdefghijklmnop123")

        svc._executors = {"research": leaky}
        task = svc.create("Research x")
        done = self.wait(svc, task["id"], statuses=("COMPLETED", "FAILED"))
        self.assertEqual(done["status"], "FAILED")
        self.assertNotIn("sk-abcdefghijklmnop123",
                         json.dumps(done["events"]) + (done.get("error") or ""))
        self.assertIn("***", done["error"])


class TestPlanner(_Base):
    def _brief(self, request, intent="research"):
        analysis = intake.analyse(request, intent)
        return analysis["brief"], analysis["answers"]

    def test_research_plan(self):
        brief, answers = self._brief("Research local runtimes")
        plan = planner.deterministic_plan("Research local runtimes", brief,
                                          "research", answers)
        self.assertEqual(plan["steps"][0]["worker"], "research")
        self.assertTrue(plan["acceptance_criteria"])

    def test_software_plan(self):
        brief, answers = self._brief("Build a CLI tool", "software")
        plan = planner.deterministic_plan("Build a CLI tool", brief, "software",
                                          answers)
        # Every build researches first, with or without presets, so the build
        # runs against what the research found.
        workers = [s["worker"] for s in plan["steps"]]
        self.assertEqual(workers, ["research", "software"])
        self.assertTrue(plan["steps"][1]["params"]["reuse_research"])
        self.assertTrue(plan["steps"][0]["params"]["feed_build"])

    def test_document_format_from_request(self):
        brief, answers = self._brief("Create a PowerPoint about rivers", "documents")
        plan = planner.deterministic_plan("Create a PowerPoint about rivers",
                                          brief, "documents", answers)
        self.assertEqual(plan["steps"][0]["params"]["format"], "pptx")

    def test_image_dimensions_parsed(self):
        brief, answers = self._brief("Resize photo.png to 800x600", "images")
        plan = planner.deterministic_plan("Resize photo.png to 800x600", brief,
                                          "images", answers)
        self.assertEqual(plan["steps"][0]["params"]["width"], 800)
        self.assertEqual(plan["steps"][0]["params"]["height"], 600)

    def test_model_failure_keeps_deterministic_plan(self):
        brief, answers = self._brief("Research x")
        plan = planner.deterministic_plan("Research x", brief, "research", answers)

        def boom(_p, _s):
            raise RuntimeError("no model")

        refined = planner.refine(plan, "Research x", answers, complete=boom)
        self.assertEqual(refined["source"], "deterministic")
        self.assertIn("unavailable", refined["note"])

    def test_malformed_json_keeps_plan(self):
        brief, answers = self._brief("Research x")
        plan = planner.deterministic_plan("Research x", brief, "research", answers)
        refined = planner.refine(plan, "Research x", answers,
                                 complete=lambda _p, _s: "not json at all")
        self.assertIn("invalid JSON", refined["note"])
        self.assertEqual(refined["steps"][0]["worker"], "research")

    def test_planner_timeout_is_bounded(self):
        brief, answers = self._brief("Research x")
        plan = planner.deterministic_plan("Research x", brief, "research", answers)

        def slow(_p, _s):
            time.sleep(0.5)
            return "{}"

        started = time.monotonic()
        refined = planner.refine(plan, "Research x", answers, complete=slow,
                                 timeout=0.1)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertIn("timed out", refined["note"])

    def test_model_cannot_invent_a_worker(self):
        brief, answers = self._brief("Research x")
        plan = planner.deterministic_plan("Research x", brief, "research", answers)
        fake = json.dumps({"steps": [{"title": "Do magic"}],
                           "acceptance_criteria": ["It is magic"]})
        refined = planner.refine(plan, "Research x", answers,
                                 complete=lambda _p, _s: fake)
        self.assertEqual(refined["steps"][0]["worker"], "research")


class TestService(_Base):
    def test_successful_task_completes_with_verified_artifact(self):
        svc = self.service(executors={"research": _write})
        task = svc.create("Research local LLM runtimes")
        done = self.wait(svc, task["id"], statuses=("COMPLETED", "FAILED"))
        self.assertEqual(done["status"], "COMPLETED", done.get("error"))
        self.assertEqual(len(done["artifacts"]), 1)
        self.assertTrue(done["artifacts"][0]["validated"])
        self.assertTrue(Path(done["artifacts"][0]["path"]).is_file())
        self.assertIn("verified", done["result"]["validation"].lower())

    def test_worker_failure_fails_task(self):
        def broken(ctx):
            return {"ok": False, "summary": "no", "artifacts": [], "evidence": [],
                    "warnings": [], "error": "backend missing", "notes": []}

        svc = self.service(executors={"research": broken})
        task = svc.create("Research x")
        done = self.wait(svc, task["id"], statuses=("COMPLETED", "FAILED"))
        self.assertEqual(done["status"], "FAILED")
        self.assertIn("backend missing", done["error"])

    def test_validation_failure_triggers_one_repair(self):
        calls = {"n": 0}

        def flaky(ctx):
            calls["n"] += 1
            if calls["n"] == 1:
                p = ctx.write_text("report.md", "")   # empty → invalid
                return {"ok": True, "summary": "first", "artifacts": [
                    ctx.artifact(p, "markdown", "empty")], "evidence": [],
                    "warnings": [], "error": "", "notes": []}
            return _write(ctx, body="Repaired content that validates. [1]\n")

        svc = self.service(executors={"research": flaky})
        task = svc.create("Research x")
        done = self.wait(svc, task["id"], statuses=("COMPLETED", "FAILED"))
        self.assertEqual(calls["n"], 2)
        self.assertEqual(done["status"], "COMPLETED", done.get("error"))
        self.assertEqual(len(done["artifacts"]), 1)

    def test_persistent_validation_failure_fails_after_repair(self):
        calls = {"n": 0}

        def always_empty(ctx):
            calls["n"] += 1
            p = ctx.write_text(f"report-{calls['n']}.md", "")
            return {"ok": True, "summary": "empty", "artifacts": [
                ctx.artifact(p, "markdown", "empty")], "evidence": [],
                "warnings": [], "error": "", "notes": []}

        svc = self.service(executors={"research": always_empty})
        task = svc.create("Research x")
        done = self.wait(svc, task["id"], statuses=("COMPLETED", "FAILED"))
        self.assertEqual(done["status"], "FAILED")
        self.assertEqual(calls["n"], 2)
        self.assertIn("could not be verified", done["error"].lower())

    def test_cancellation_stops_a_running_worker(self):
        def slow(ctx):
            ctx.write_text("partial.md", "partial work")
            for _ in range(80):
                if ctx.should_cancel():
                    return {"ok": False, "summary": "cancelled", "artifacts": [],
                            "evidence": [], "warnings": [],
                            "error": "cancelled", "notes": []}
                time.sleep(0.05)
            return _write(ctx)

        svc = self.service(executors={"research": slow})
        task = svc.create("Research x")
        time.sleep(0.4)
        svc.cancel(task["id"])
        done = self.wait(svc, task["id"], statuses=("CANCELLED", "FAILED",
                                                    "COMPLETED"))
        self.assertEqual(done["status"], "CANCELLED")
        self.assertEqual(done["error"], "Cancelled by user.")

    def test_approval_approve_continues(self):
        svc = self.service(executors={"research": _write},
                           approval_workers={"research"})
        task = svc.create("Research x")
        waiting = self.wait(svc, task["id"], statuses=("WAITING_FOR_APPROVAL",
                                                       "COMPLETED", "FAILED"))
        self.assertEqual(waiting["status"], "WAITING_FOR_APPROVAL")
        self.assertEqual(waiting["approval"]["status"], "pending")
        svc.approve(task["id"], True, "go ahead")
        done = self.wait(svc, task["id"], statuses=("COMPLETED", "FAILED"))
        self.assertEqual(done["status"], "COMPLETED", done.get("error"))
        self.assertEqual(done["approval"]["status"], "approved")

    def test_approval_reject_fails_task(self):
        svc = self.service(executors={"research": _write},
                           approval_workers={"research"})
        task = svc.create("Research x")
        self.wait(svc, task["id"], statuses=("WAITING_FOR_APPROVAL", "FAILED"))
        svc.approve(task["id"], False, "not allowed")
        done = self.wait(svc, task["id"], statuses=("FAILED", "COMPLETED"))
        self.assertEqual(done["status"], "FAILED")
        self.assertIn("rejected", done["error"])

    def test_answers_start_the_task(self):
        svc = self.service(executors={"research": _write})
        task = svc.create("Build a portfolio website")
        self.assertEqual(task["status"], "WAITING_FOR_USER")
        task = svc.answer(task["id"], {"subject": "a photographer"})
        self.assertIn(task["status"], ("PLANNING", "RUNNING", "READY",
                                       "COMPLETED"))
        self.assertNotEqual(task["status"], "WAITING_FOR_USER")

    def test_resume_after_interruption(self):
        svc = self.service(executors={"research": _write})
        task = svc.create("Research x", auto_start=False)
        internal = svc._get(task["id"])
        models.set_status(internal, Status.PLANNING)
        models.save(internal)
        restarted = self.service(executors={"research": _write})
        loaded = restarted.get_task(task["id"])
        self.assertTrue(loaded["needs_resume"])
        restarted.resume(task["id"])
        done = self.wait(restarted, task["id"], statuses=("COMPLETED", "FAILED"))
        self.assertEqual(done["status"], "COMPLETED", done.get("error"))

    def test_failed_task_can_be_retried(self):
        state = {"fail": True}

        def sometimes(ctx):
            if state["fail"]:
                return {"ok": False, "summary": "down", "artifacts": [],
                        "evidence": [], "warnings": [], "error": "backend down",
                        "notes": []}
            return _write(ctx)

        svc = self.service(executors={"research": sometimes})
        task = svc.create("Research x")
        self.wait(svc, task["id"], statuses=("FAILED",))
        state["fail"] = False
        svc.start(task["id"])
        done = self.wait(svc, task["id"], statuses=("COMPLETED", "FAILED"))
        self.assertEqual(done["status"], "COMPLETED", done.get("error"))

    def test_two_concurrent_tasks_do_not_share_artifacts(self):
        started = threading.Barrier(2)

        def both(ctx):
            started.wait(timeout=5)
            time.sleep(0.2)
            return _write(ctx, name=f"report-{ctx.task['id']}.md")

        svc = self.service(executors={"research": both})
        a = svc.create("Research alpha thing")
        b = svc.create("Research beta thing")
        da = self.wait(svc, a["id"], statuses=("COMPLETED", "FAILED"))
        db = self.wait(svc, b["id"], statuses=("COMPLETED", "FAILED"))
        self.assertEqual(da["status"], "COMPLETED")
        self.assertEqual(db["status"], "COMPLETED")
        paths_a = {x["path"] for x in da["artifacts"]}
        paths_b = {x["path"] for x in db["artifacts"]}
        self.assertTrue(paths_a)
        self.assertTrue(paths_b)
        self.assertFalse(paths_a & paths_b)
        self.assertNotEqual(da["workspace"], db["workspace"])

    def test_report_text_reflects_real_state(self):
        svc = self.service(executors={"research": _write})
        task = svc.create("Research x")
        done = self.wait(svc, task["id"], statuses=("COMPLETED", "FAILED"))
        text = svc.report_text(done["id"])
        self.assertIn("COMPLETED", text)
        self.assertIn("report.md", text)

    def test_timed_out_step_fails_instead_of_hanging(self):
        def hangs(ctx):
            time.sleep(5)
            return _write(ctx)

        svc = self.service(executors={"research": hangs},
                           step_timeout_overrides={"research": 0.3})
        task = svc.create("Research x")
        started = time.monotonic()
        done = self.wait(svc, task["id"], statuses=("FAILED", "COMPLETED"),
                         timeout=15)
        self.assertEqual(done["status"], "FAILED")
        self.assertIn("limit", done["error"].lower())
        self.assertLess(time.monotonic() - started, 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
