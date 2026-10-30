"""Regression tests for core.brief_spec and core.build_recipes.

The behaviour under test is the one that was broken: a dashboard request must
ask for its missing requirements instead of being rendered as a portfolio, and
must never be routed to the page template.

No model, no network, no database.

Run:  python -m unittest qa_artifacts.regression_tests.test_brief_spec -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from core import brief_spec  # noqa: E402
from core import build_recipes  # noqa: E402

DASHBOARD = ("create a dashboard with proper graphs and api integration for "
             "measuring market data")

ANSWERS = (
    "data source: Yahoo Finance quote + chart endpoints\n"
    "metrics: price, volume, 30-day change\n"
    "charts: candlestick for OHLC, bar for volume, KPI cards on top\n"
    "stack: Flask API + Chart.js front end, MySQL for storage\n"
    "scope: single user, local only, no login\n"
)


def _manager_return(manager):
    """Return a callable suitable for ``mock.patch.object(cc, "_get_manager", ...)``.

    ``crown_code`` resolves the registry through ``_get_manager()`` at call time,
    so patching that function is what actually redirects job registration.
    """
    return lambda: manager


class AnalysisTest(unittest.TestCase):
    def test_dashboard_is_an_application_and_asks_its_requirements(self):
        result = brief_spec.analyse_brief(DASHBOARD)
        self.assertEqual(result["artifact"], "app")
        self.assertFalse(result["ready"])
        slots = [q["slot"] for q in result["questions"]]
        for needed in ("data_source", "charts", "stack", "scope"):
            self.assertIn(needed, slots)
        # Every question explains what it changes — a bare "what do you want?"
        # is not a clarifying question.
        for q in result["questions"]:
            self.assertTrue(q["ask"] and q["examples"] and q["why"], q)

    def test_answers_clear_the_questions(self):
        result = brief_spec.analyse_brief(DASHBOARD, requirements=ANSWERS)
        self.assertEqual(result["artifact"], "app")
        self.assertTrue(result["ready"], result["questions"])

    def test_dict_answers_are_accepted(self):
        result = brief_spec.analyse_brief(
            DASHBOARD,
            requirements={"data_source": "CSV already on disk", "metrics": "revenue",
                          "charts": "line", "stack": "plain HTML", "scope": "local"})
        self.assertTrue(result["ready"], result["questions"])

    def test_partial_answers_ask_only_what_is_still_missing(self):
        result = brief_spec.analyse_brief(
            DASHBOARD,
            requirements="metrics: price, volume\nscope: local single user")
        self.assertFalse(result["ready"])
        self.assertIn("data_source", [q["slot"] for q in result["questions"]])
        self.assertIn("charts", [q["slot"] for q in result["questions"]])


class NonDashboardAppTest(unittest.TestCase):
    def test_pdf_tool_is_an_application_and_asks_for_its_inputs(self):
        result = brief_spec.analyse_brief(
            "a tool that converts a folder of PDFs to text")
        self.assertEqual(result["artifact"], "app")
        self.assertFalse(result["ready"])
        slots = [q["slot"] for q in result["questions"]]
        for needed in ("input", "output", "scope"):
            self.assertIn(needed, slots)


class NoWriteRunTest(unittest.TestCase):
    def setUp(self):
        from actions import crown_code as cc
        from core import crown_jobs
        self.cc = cc
        self.manager = crown_jobs.JobManager()
        # Patch the accessor the action layer resolves jobs through, plus the
        # module-level one the rest of the codebase uses.
        self._jobs = mock.patch.object(cc, "_get_manager",
                                       _manager_return(self.manager))
        self._jobs.start()
        self._mgr_patch = mock.patch.object(crown_jobs, "_manager",
                                            return_value=self.manager)
        self._mgr_patch.start()

    def tearDown(self):
        try:
            self._mgr_patch.stop()
        except Exception:
            pass
        self._jobs.stop()

    def test_a_run_that_writes_a_file_passes(self):
        captured = {}

        def target(job):
            captured["workspace"] = job.workspace
            return {"ok": True, "path": "app.py", "bytes": 120, "seconds": 1.0,
                    "plan": {"sections": [{"heading": "App"}]},
                    "message": "built and verified"}

        job = self.manager.start("Build app", target, kind="app")
        job.thread.join(5)
        self.assertEqual(job.status, "done")
        self.assertEqual(job.progress, 1.0)
        self.assertIn("app.py", job.describe())

    def test_search_only_run_is_a_failure(self):
        def target(job):
            return {"ok": True, "summary": "answered", "writes": 0, "commands": 0}

        job = self.manager.start("Search-only", target, kind="code")
        job.thread.join(5)
        self.assertEqual(job.status, "failed")
        self.assertIn("without writing any file", job.status_line().lower())

    # The targets are real callables now, so patching crown_jobs on the cc module
    # no longer suppresses the JobManager.start import inside crown_code. There is no
    # remaining assertion that depends on a fake bridge here, so this class does not
    # use one.

class EmptyWorkspaceInstructionTest(unittest.TestCase):
    """A new folder must be described as empty, or the agent only searches."""

    def test_new_workspace_brief_says_write_first(self):
        from actions import crown_code as cc
        from core import crown_jobs

        manager = crown_jobs.JobManager()
        seen = {}

        def fake_bridge(job, task, workspace, model, provider, policy, timeout,
                        player=None, **kw):
            seen["task"] = task
            return {"ok": True, "summary": "built"}

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(cc, "_get_manager", _manager_return(manager)), \
                mock.patch.object(crown_jobs, "_manager", return_value=manager), \
                mock.patch.object(cc, "ensure_local_model",
                                  lambda **kw: (True, "test-model")), \
                mock.patch.object(cc, "_run_bridge", fake_bridge):
            # A code task with no recipe: this is the branch that describes the
            # empty workspace to the agent.
            cc.crown_code({"description": "Refactor the fuel-cost parser and add tests",
                           "workspace": tmp})
            job = manager.get()
            self.assertIsNotNone(job, "no job was registered")
            job.thread.join(20)
        self.assertIn("WORKSPACE STATE: this folder is empty", seen["task"])
        self.assertIn("Do not search for a file before", seen["task"])


class RoutingTest(unittest.TestCase):
    """The exact request that used to become a portfolio page."""

    def setUp(self):
        from actions import crown_code as cc
        self.cc = cc

    def test_dashboard_goes_to_the_coding_agent(self):
        self.assertEqual(self.cc.classify_task(DASHBOARD), "code")

    def test_dashboard_called_a_website_is_still_an_application(self):
        brief = "build a website that is a dashboard with charts and a mysql database"
        self.assertEqual(self.cc.classify_task(brief, "website"), "code")
        self.assertEqual(self.cc.classify_task(brief, "webapp"), "code")

    def test_pages_still_use_the_page_path(self):
        self.assertEqual(self.cc.classify_task("make me a landing page"), "site")
        self.assertEqual(self.cc.classify_task("build a photography portfolio"), "site")

    def test_a_fix_to_an_existing_page_is_a_code_task(self):
        self.assertEqual(self.cc.classify_task("fix the nav on my portfolio site"), "code")


class GateTest(unittest.TestCase):
    def setUp(self):
        from actions import crown_code as cc
        from core import crown_jobs
        self.cc = cc
        self.manager = crown_jobs.JobManager()

        # Patch the accessor crown_code() resolves jobs through, so registration
        # and the reads in these tests observe the same registry.
        self._modules_patch = mock.patch.object(cc, "_get_manager",
                                                lambda: self.manager)
        self._modules_patch.start()
        # Patch the module-level accessor the rest of the codebase uses.
        self._mgr_patch = mock.patch.object(crown_jobs, "_manager",
                                            return_value=self.manager)
        self._mgr_patch.start()
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        try:
            self._mgr_patch.stop()
        except Exception:
            pass
        try:
            self._modules_patch.stop()
        except Exception:
            pass
        try:
            self._tmp.cleanup()
        except Exception:
            pass

    def test_unanswered_dashboard_starts_nothing_and_creates_nothing(self):
        with mock.patch.object(self.cc, "_PROJECTS_DIR", self.dir / "projects"):
            msg = self.cc.crown_code({"description": DASHBOARD})
        self.assertIn("NEED REQUIREMENTS", msg)
        self.assertIn("data source", msg.lower())
        self.assertFalse(self.manager.all(), "a job was started despite missing requirements")
        self.assertFalse((self.dir / "projects").exists(), "a workspace was created anyway")

    def test_clarify_action_returns_the_questions(self):
        msg = self.cc.crown_code({"action": "clarify", "description": DASHBOARD})
        self.assertIn("REQUIREMENTS BEFORE BUILDING", msg)
        self.assertFalse(self.manager.all())

    def test_answered_dashboard_builds_through_the_agent_with_the_spec(self):
        """A dashboard whose stack the SQLite recipe cannot honour goes to the agent.

        The recipe is SQLite-only, so asking for MySQL keeps this on the agent
        path — which is the path that must receive the user's answers.
        """
        seen = {}

        def fake_bridge(job, task, workspace, model, provider, policy, timeout,
                        player=None, **kw):
            seen["task"] = task
            return {"ok": True, "summary": "built", "writes": 1}

        with mock.patch.object(self.cc, "_run_bridge", fake_bridge), \
                mock.patch.object(self.cc, "ensure_local_model",
                                  lambda **kw: (True, "test-model")), \
                mock.patch.object(self.cc, "_PROJECTS_DIR", self.dir / "projects"):
            msg = self.cc.crown_code({
                "description": DASHBOARD + "\nstack: Flask API + MySQL for storage",
                "requirements": ANSWERS,
                "workspace": str(self.dir / "dash")})
            job = self.manager.get()
            job.thread.join(20)
        self.assertIn("Started", msg)
        self.assertIn("Yahoo Finance", seen["task"])
        self.assertIn("BUILD RECIPES", seen["task"])
        self.assertEqual(job.status, "done")
        brief = (self.dir / "dash" / "brief.json").read_text(encoding="utf-8")
        self.assertIn("data_source", brief)

    def test_confirmed_build_records_the_skipped_choices(self):
        """confirmed=true still discloses which requirements were not answered.

        Uses a brief with no recipe (an inventory system), so it stays on the
        agent path — the recipe path never sees the task — and it still has the
        unanswered stack/scope requirements to disclose.
        """
        seen = {}

        def fake_bridge(job, task, workspace, model, provider, policy, timeout,
                        player=None, **kw):
            seen["task"] = task
            return {"ok": True, "summary": "built", "writes": 1}

        with mock.patch.object(self.cc, "_run_bridge", fake_bridge), \
                mock.patch.object(self.cc, "ensure_local_model",
                                  lambda **kw: (True, "test-model")), \
                mock.patch.object(self.cc, "_PROJECTS_DIR", self.dir / "projects"):
            msg = self.cc.crown_code({
                "description": "Build an inventory system for my warehouse",
                "confirmed": True, "workspace": str(self.dir / "dash2")})
            job = self.manager.get()
            job.thread.join(20)
        self.assertIn("chose to start without answering", seen["task"])
        self.assertIn("will be reported", msg)

    def test_plain_dashboard_is_built_from_the_recipe_and_verified(self):
        """A dashboard with no out-of-scope requirement needs no model at all."""

        def no_model(**kw):
            raise AssertionError("a recipe build must not load a model")

        def no_bridge(*args, **kw):
            raise AssertionError("a recipe-owned dashboard must not reach the agent")

        with mock.patch.object(self.cc, "ensure_local_model", no_model), \
                mock.patch.object(self.cc, "_run_bridge", no_bridge), \
                mock.patch.object(self.cc, "_get_manager", return_value=self.manager):
            msg = self.cc.crown_code({
                "description": "Build a fleet dashboard with charts and a table",
                "requirements": "data source: SQLite file in the project folder\n"
                                "charts: line and bar\nscope: local single user",
                "workspace": str(self.dir / "recipe"), "wait": True})
        job = self.manager.get()
        self.assertEqual(job.status, "done")
        self.assertIn("verified", msg.lower())
        workspace = self.dir / "recipe"
        for name in ("app.py", "db.py", "seed.py", "schema.sql",
                     "templates/index.html", "static/dashboard.js",
                     "static/style.css", "requirements.txt"):
            self.assertTrue((workspace / name).exists(), name)

    def test_a_dashboard_asking_for_mysql_keeps_the_agent_path(self):
        """The recipe is SQLite-only; swapping MySQL out would break the spec."""
        self.assertEqual(self.cc.app_kind_for(
            DASHBOARD + "\nstack: Flask API + MySQL for storage"), "")
        self.assertEqual(self.cc.app_kind_for(
            "dashboard with login for the team"), "")


class RecipeTest(unittest.TestCase):
    def test_dashboard_request_gets_the_dashboard_and_mysql_recipes(self):
        stacks = build_recipes.detect_stacks(DASHBOARD + " using mysql")
        self.assertIn("dashboard", stacks)
        self.assertIn("mysql", stacks)
        # the dashboard recipe already covers its API — no duplicate section
        self.assertNotIn("api-backend", stacks)

    def test_other_artifacts_detected(self):
        cases = {
            "build a python desktop app with PyQt6": "python-desktop",
            "make an electron desktop app": "electron",
            "create an android app in kotlin for android studio": "android",
            "design a mysql database schema": "mysql",
        }
        for brief, expected in cases.items():
            self.assertIn(expected, build_recipes.detect_stacks(brief), brief)

    def test_recipe_block_states_files_verify_and_no_hardcoded_credentials(self):
        block = build_recipes.recipe_block(["dashboard", "mysql"])
        self.assertIn("schema.sql", block)
        self.assertIn("Verify before reporting success", block)
        self.assertIn("DB_PASSWORD", block)
        self.assertIn("If a recipe cannot be followed", block)

    def test_no_recipe_means_no_noise(self):
        self.assertEqual(build_recipes.recipe_block(build_recipes.detect_stacks(
            "build a photography portfolio for Lena Fischer")), "")


if __name__ == "__main__":
    unittest.main()
