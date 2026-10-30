"""Regression tests for core.app_specs / core.app_builder / core.app_checks.

No model is involved anywhere in this path, so these tests are deterministic and
need no Ollama, no API key and no browser. The dashboard tests do start a real
Flask server on a loopback port — that is the point: the assertion is that the
app answers with data read from its own database.

Run:  python -m unittest qa_artifacts.regression_tests.test_app_builder -v
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from core.app_builder import (DASHBOARD_ENDPOINTS,  # noqa: E402
                              DASHBOARD_NONEMPTY_KEYS, app_kind_for,
                              build_app, build_dashboard, build_python_desktop)
from core.app_checks import verify_workspace  # noqa: E402
from core.app_specs import pick_dashboard, pick_desktop  # noqa: E402

FLEET = ("Build a fleet-operations dashboard: vehicles, trips, fuel and "
         "maintenance costs. Real JSON API, charts and a table.")
LEDGER = ("Python desktop app: a small ledger with entries, search and totals.")


class SpecTests(unittest.TestCase):
    def test_dashboard_spec_is_chosen_from_the_brief(self):
        self.assertEqual(pick_dashboard(FLEET)[0], "fleet")
        self.assertEqual(pick_dashboard(
            "A newsroom analytics dashboard with reads and subscriptions")[0],
            "newsroom")
        self.assertEqual(pick_dashboard(
            "Inventory dashboard: SKUs and reorder points")[0], "inventory")
        self.assertEqual(pick_dashboard(
            "Sales dashboard with orders and revenue")[0], "sales")

    def test_dashboard_falls_back_to_generic(self):
        key, spec = pick_dashboard("A dashboard for something unspecified")
        self.assertEqual(key, "generic")
        self.assertEqual(len(spec["categories"]), len(set(spec["categories"])))

    def test_desktop_spec_is_chosen_from_the_brief(self):
        self.assertEqual(pick_desktop(LEDGER)[0], "ledger")
        self.assertEqual(pick_desktop(
            "Python desktop app: shop inventory with low-stock warnings")[0],
            "inventory")

    def test_low_stock_only_for_inventory(self):
        self.assertFalse(pick_desktop(LEDGER)[1]["low_stock"])
        self.assertTrue(pick_desktop(
            "Python desktop app: stock levels and low-stock warnings")[1]["low_stock"])


class RoutingTests(unittest.TestCase):
    def test_only_mechanically_checkable_kinds_are_routed(self):
        self.assertEqual(app_kind_for("Build a fleet dashboard"), "dashboard")
        self.assertEqual(app_kind_for("Python desktop app: a ledger"),
                         "python-desktop")
        self.assertEqual(app_kind_for("PyQt6 app for expenses"), "python-desktop")

    def test_negated_requirements_do_not_disqualify_the_recipe(self):
        """"no login" is not a request for login.

        Regression: read as a positive, this wording sent ordinary dashboards
        to the agent path, where a build could burn five minutes and fail.
        """
        self.assertEqual(
            app_kind_for("dashboard with charts\nscope: local single user, "
                         "no login, sample data"), "dashboard")
        self.assertEqual(app_kind_for("dashboard without authentication"),
                         "dashboard")
        self.assertEqual(app_kind_for("dashboard with login for the team"), "")

    def test_a_crud_app_is_not_downgraded_to_a_dashboard(self):
        """Regression: an inventory *management system* became a dashboard.

        The dashboard recipe writes one `events` table and read-only endpoints.
        Handing it a data-management request produced a verified dashboard that
        was the wrong artifact — every check passed on the wrong thing.
        """
        brief = ("Build a small inventory management system: Python + Flask + "
                 "SQLite, a JSON API, dashboard statistics and stock movement "
                 "history.")
        self.assertEqual(app_kind_for(brief), "")
        self.assertEqual(app_kind_for("full-stack app with create, edit and "
                                     "delete for products"), "")
        # A genuine reporting request still uses the recipe.
        self.assertEqual(app_kind_for("Build a fleet dashboard with charts"),
                         "dashboard")

    def test_agent_owned_kinds_are_not_hijacked(self):
        for brief in (
            "Build a selling store with a cart and checkout",
            "Electron desktop app: quick notes",
            "Android app: a simple task list",
            "Portfolio website for Aruna Mehta",
            "fix the failing tests in this project",
            "add a health-check endpoint to this project",
        ):
            with self.subTest(brief=brief):
                self.assertEqual(app_kind_for(brief), "")

    def test_build_app_rejects_unknown_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_app("something else entirely", Path(tmp),
                               kind="android")
            self.assertFalse(result["ok"])
            self.assertIn("no deterministic builder", result["message"])


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dashboard_is_built_and_serves_real_data(self):
        result = build_dashboard(FLEET, self.tmp / "fleet")
        self.assertTrue(result["ok"], result["message"])
        self.assertEqual(result["kind"], "dashboard")
        self.assertEqual(result["spec"], "fleet")
        self.assertIn("serves", result["levels"])
        self.assertIn("executes", result["levels"])

        for name in ("app.py", "db.py", "seed.py", "schema.sql",
                     "templates/index.html", "static/dashboard.js",
                     "static/style.css", "requirements.txt"):
            self.assertTrue((self.tmp / "fleet" / name).exists(), name)

        served = [c for c in result["checks"] if c["level"] == "serves"]
        self.assertEqual(len(served), len(DASHBOARD_ENDPOINTS))
        self.assertTrue(all(c["ok"] for c in served))

    def test_serving_empty_database_fails_verification(self):
        """A 200 with empty arrays is not a working dashboard.

        The schema exists and the server answers, so the only thing wrong is
        that no rows are in it — which is exactly what the non-empty assertion
        is for.
        """
        result = build_dashboard(FLEET, self.tmp / "empty")
        self.assertTrue(result["ok"], result["message"])

        workspace = self.tmp / "empty"
        (workspace / "dashboard.db").unlink()
        conn = sqlite3.connect(workspace / "dashboard.db")
        try:
            conn.executescript((workspace / "schema.sql").read_text(
                encoding="utf-8"))
        finally:
            conn.close()

        verification = verify_workspace(
            workspace, entry="app.py", endpoints=DASHBOARD_ENDPOINTS,
            nonempty_keys=DASHBOARD_NONEMPTY_KEYS)
        self.assertFalse(verification["ok"])
        self.assertIn("is empty", verification["message"])

    def test_missing_builder_kind_reports_no_files(self):
        result = build_app(FLEET, self.tmp / "auto")
        self.assertTrue(result["ok"])
        self.assertTrue(result["files"])


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_desktop_app_builds_and_passes_selftest(self):
        result = build_python_desktop(LEDGER, self.tmp / "ledger")
        self.assertTrue(result["ok"], result["message"])
        self.assertEqual(result["kind"], "python-desktop")
        self.assertIn("executes", result["levels"])

        for name in ("main.py", "app/__init__.py", "app/window.py",
                     "app/db.py", "app/theme.py", "requirements.txt",
                     "README.md"):
            self.assertTrue((self.tmp / "ledger" / name).exists(), name)

        executed = [c for c in result["checks"] if c["level"] == "executes"]
        self.assertEqual(len(executed), 1)
        self.assertTrue(executed[0]["ok"])
        self.assertIn("OK", executed[0]["detail"])

    def test_database_files_are_not_left_locked(self):
        """Regression: `with sqlite3.connect(...)` leaves the file open, which
        on Windows makes the workspace undeletable."""
        workspace = self.tmp / "locked"
        self.assertTrue(build_python_desktop(LEDGER, workspace)["ok"])
        shutil.rmtree(workspace)          # raises on Windows if a handle leaks
        self.assertFalse(workspace.exists())


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_syntax_error_fails_the_compile_level(self):
        (self.tmp / "bad.py").write_text("def broken(:\n", encoding="utf-8")
        verification = verify_workspace(self.tmp)
        self.assertFalse(verification["ok"])
        self.assertIn("compiles", verification["message"])

    def test_missing_entry_point_fails_instead_of_being_skipped(self):
        # Something compiles, so the only missing piece is the entry point.
        (self.tmp / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
        verification = verify_workspace(self.tmp, entry="app.py",
                                        endpoints=("/api/health",))
        self.assertFalse(verification["ok"])
        self.assertIn("app.py is missing", verification["message"])

    def test_a_script_that_exits_is_not_a_server(self):
        (self.tmp / "app.py").write_text("print('hi')\n", encoding="utf-8")
        verification = verify_workspace(self.tmp, entry="app.py",
                                        endpoints=("/api/health",))
        self.assertFalse(verification["ok"])
        self.assertIn("did not answer", verification["message"])

    def test_checks_carry_the_command_that_ran(self):
        (self.tmp / "ok.py").write_text("VALUE = 1\n", encoding="utf-8")
        verification = verify_workspace(self.tmp)
        self.assertTrue(verification["ok"], verification["message"])
        self.assertTrue(verification["checks"][0]["command"])


if __name__ == "__main__":
    unittest.main()
