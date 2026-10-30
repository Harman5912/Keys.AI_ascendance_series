"""Integration tests for KeysAI_Test_Study_Planner (Section 6.3).

Every test runs against a real Flask app and a real SQLite file in a temporary
directory. Expected numbers are computed with RAW SQL in this file — never by
models.dashboard() — so a broken dashboard cannot agree with itself.

Run:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from app import create_app          # noqa: E402
from db import connect, init_db     # noqa: E402
import models                       # noqa: E402

TODAY = dt.date.today()
FUTURE = (TODAY + dt.timedelta(days=7)).isoformat()
FUTURE2 = (TODAY + dt.timedelta(days=10)).isoformat()
PAST = (TODAY - dt.timedelta(days=3)).isoformat()


def day(offset: int) -> str:
    return (TODAY + dt.timedelta(days=offset)).isoformat()


class PlannerCase(unittest.TestCase):
    """Shared fixture: temp database, one user, one subject, live test client."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.db_path = self.dir / "planner.db"
        os.environ["STUDY_PLANNER_DB"] = str(self.db_path)
        init_db(self.db_path)
        conn = connect(self.db_path)
        try:
            self.user = models.create_user(conn, "Synthetic Student",
                                           "student@example.test")
            self.subject = models.create_subject(conn, self.user["id"],
                                                 "Mathematics", "#d4a017")
            self.other_subject = models.create_subject(conn, self.user["id"],
                                                       "Physics", "#4f9dff")
            conn.commit()
        finally:
            conn.close()
        self.app = create_app(self.db_path)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self._tmp.cleanup()

    # helpers -------------------------------------------------------------
    def make_task(self, *, title="Integration practice", subject_id=None,
                  due=FUTURE, priority="medium", status="todo", notes=""):
        return self.client.post("/api/tasks", json={
            "title": title, "subject_id": subject_id or self.subject["id"],
            "due_date": due, "priority": priority, "status": status,
            "notes": notes,
        })

    def raw(self, sql, args=()):
        """Read with an independent, explicitly closed connection."""
        conn = connect(self.db_path)
        try:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]
        finally:
            conn.close()


# ── 6.3 (1) subjects ────────────────────────────────────────────────────────
class TestSubjectCreation(PlannerCase):
    def test_subject_created_and_stored(self):
        res = self.client.post("/api/subjects",
                               json={"name": "Chemistry", "color": "#7bbf6a"})
        self.assertEqual(res.status_code, 201)
        body = res.get_json()
        self.assertEqual(body["name"], "Chemistry")
        rows = self.raw("SELECT name FROM subjects WHERE id = ?", (body["id"],))
        self.assertEqual(rows[0]["name"], "Chemistry")

    def test_duplicate_subject_is_a_409_not_a_silent_second_row(self):
        self.client.post("/api/subjects", json={"name": "Chemistry"})
        res = self.client.post("/api/subjects", json={"name": "Chemistry"})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(len(self.raw("SELECT id FROM subjects "
                                      "WHERE name = 'Chemistry'")), 1)

    def test_subject_requires_a_name(self):
        res = self.client.post("/api/subjects", json={"name": "   "})
        self.assertEqual(res.status_code, 400)
        self.assertIn("name", res.get_json()["error"]["fields"])


# ── 6.3 (2) task ↔ subject relationship ────────────────────────────────────
class TestTaskLinkedToSubject(PlannerCase):
    def test_task_is_linked_to_the_correct_subject(self):
        res = self.make_task(title="Trig identities",
                             subject_id=self.other_subject["id"])
        self.assertEqual(res.status_code, 201)
        task = res.get_json()
        self.assertEqual(task["subject_id"], self.other_subject["id"])
        self.assertEqual(task["subject_name"], "Physics")
        rows = self.raw("SELECT subject_id FROM study_tasks WHERE id = ?",
                        (task["id"],))
        self.assertEqual(rows[0]["subject_id"], self.other_subject["id"])

    def test_task_to_unknown_subject_is_rejected(self):
        res = self.make_task(subject_id=999999)
        self.assertEqual(res.status_code, 409)
        self.assertIn("does not exist", res.get_json()["error"]["message"])


# ── 6.3 (3) update ─────────────────────────────────────────────────────────
class TestTaskUpdate(PlannerCase):
    def test_task_update_persists_every_changed_field(self):
        task = self.make_task().get_json()
        res = self.client.patch(f"/api/tasks/{task['id']}", json={
            "title": "Trig identities — corrected title",
            "due_date": FUTURE2, "priority": "high",
            "status": "in_progress", "notes": "two pages left",
        })
        self.assertEqual(res.status_code, 200)
        rows = self.raw(
            "SELECT title, due_date, priority, status, notes FROM study_tasks "
            "WHERE id = ?", (task["id"],))
        self.assertEqual(rows[0], {
            "title": "Trig identities — corrected title",
            "due_date": FUTURE2, "priority": "high",
            "status": "in_progress", "notes": "two pages left",
        })


# ── 6.3 (4) completion ─────────────────────────────────────────────────────
class TestTaskCompletion(PlannerCase):
    def test_marking_complete_sets_status_and_timestamp(self):
        task = self.make_task().get_json()
        res = self.client.post(f"/api/tasks/{task['id']}/complete")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "done")
        rows = self.raw("SELECT status, completed_at FROM study_tasks "
                        "WHERE id = ?", (task["id"],))
        self.assertEqual(rows[0]["status"], "done")
        self.assertIsNotNone(rows[0]["completed_at"],
                             "completed_at must be set when a task is done")

    def test_returning_a_done_task_to_todo_clears_the_timestamp(self):
        task = self.make_task().get_json()
        self.client.post(f"/api/tasks/{task['id']}/complete")
        self.client.patch(f"/api/tasks/{task['id']}", json={"status": "todo"})
        rows = self.raw("SELECT status, completed_at FROM study_tasks "
                        "WHERE id = ?", (task["id"],))
        self.assertEqual(rows[0]["status"], "todo")
        self.assertIsNone(rows[0]["completed_at"])


# ── 6.3 (5) deadlines ──────────────────────────────────────────────────────
class TestDeadlines(PlannerCase):
    def test_malformed_deadlines_are_rejected(self):
        for bad in ("not-a-date", "2026-13-45", "next tuesday", "03/11/2026",
                    20261103, ["2026-11-03"]):
            res = self.make_task(title="Deadline check", due=bad)
            self.assertEqual(res.status_code, 400,
                             f"accepted a malformed deadline: {bad!r}")
            body = res.get_json()
            self.assertIn("due_date", body["error"].get("fields", {}),
                          f"no field message for {bad!r}")

    def test_past_deadlines_are_rejected(self):
        res = self.make_task(title="Deadline check", due=PAST)
        self.assertEqual(res.status_code, 400)
        self.assertIn("past", res.get_json()["error"]["fields"]["due_date"])

    def test_valid_and_empty_deadlines_are_accepted(self):
        self.assertEqual(self.make_task(due=FUTURE).status_code, 201)
        self.assertEqual(self.make_task(due=None).status_code, 201)
        self.assertIsNone(self.make_task(due=None).get_json()["due_date"])


# ── 6.3 (6)(7) filtering ───────────────────────────────────────────────────
class TestFilters(PlannerCase):
    def setUp(self):
        super().setUp()
        self.a = self.make_task(title="Alpha todo", status="todo").get_json()
        self.b = self.make_task(title="Beta doing",
                                status="in_progress").get_json()
        self.c = self.make_task(title="Gamma done", status="done",
                                subject_id=self.other_subject["id"],
                                due=None).get_json()

    def test_filter_by_status(self):
        res = self.client.get("/api/tasks?status=in_progress")
        self.assertEqual(res.status_code, 200)
        titles = [t["title"] for t in res.get_json()]
        self.assertEqual(titles, ["Beta doing"])
        done = self.client.get("/api/tasks?status=done").get_json()
        self.assertEqual([t["title"] for t in done], ["Gamma done"])

    def test_filter_by_subject(self):
        res = self.client.get(
            f"/api/tasks?subject_id={self.other_subject['id']}")
        self.assertEqual([t["title"] for t in res.get_json()], ["Gamma done"])

    def test_filters_compose_and_search_matches_notes(self):
        res = self.client.get(
            f"/api/tasks?subject_id={self.subject['id']}&status=todo&q=Alpha")
        self.assertEqual([t["title"] for t in res.get_json()], ["Alpha todo"])

    def test_unknown_status_value_is_a_400_not_a_silent_empty_list(self):
        res = self.client.get("/api/tasks?status=finished")
        self.assertEqual(res.status_code, 400)

    def test_search_survives_sql_injection_attempts(self):
        hostile = "'; DROP TABLE study_tasks; --"
        res = self.client.get("/api/tasks", query_string={"q": hostile})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), [])   # matches nothing, harmlessly
        self.assertEqual(
            len(self.raw("SELECT name FROM sqlite_master WHERE type='table' "
                         "AND name='study_tasks'")), 1, "table was dropped!")
        # and the stored rows are untouched
        self.assertEqual(len(self.raw("SELECT id FROM study_tasks")), 3)


# ── 6.3 (8) dashboard counts ───────────────────────────────────────────────
class TestDashboard(PlannerCase):
    """Counts are built straight from the tables (like seed data that arrived
    on an earlier day), then compared with raw SQL written in this file."""

    def setUp(self):
        super().setUp()
        conn = connect(self.db_path)
        try:
            # independent fixture: 3 todo, 2 done, 1 in progress, 1 overdue-open
            uid, s1, s2 = (self.user["id"], self.subject["id"],
                           self.other_subject["id"])
            models.create_task(conn, user_id=uid, subject_id=s1, title="T1",
                               due_date=FUTURE, status="todo")
            models.create_task(conn, user_id=uid, subject_id=s1, title="T2",
                               due_date=FUTURE, status="todo")
            models.create_task(conn, user_id=uid, subject_id=s1, title="T3",
                               due_date=day(-1), status="todo")   # overdue
            models.create_task(conn, user_id=uid, subject_id=s2, title="T4",
                               due_date=day(-2), status="done")
            models.create_task(conn, user_id=uid, subject_id=s2, title="T5",
                               due_date=day(-5), status="done")
            models.create_task(conn, user_id=uid, subject_id=s1, title="T6",
                               due_date=FUTURE, status="in_progress")
            conn.commit()
        finally:
            conn.close()
        self.client.post("/api/sessions", json={
            "subject_id": self.subject["id"], "minutes": 45, "notes": "drills"})
        self.client.post("/api/sessions", json={
            "subject_id": self.other_subject["id"], "minutes": 20})

    def test_dashboard_matches_independent_raw_sql(self):
        res = self.client.get("/api/dashboard")
        self.assertEqual(res.status_code, 200)
        api = res.get_json()

        expected = self.raw(
            "SELECT COUNT(*) AS total,"
            " SUM(CASE WHEN status='todo' THEN 1 ELSE 0 END) AS todo,"
            " SUM(CASE WHEN status='in_progress' THEN 1 ELSE 0 END) AS in_progress,"
            " SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done,"
            " SUM(CASE WHEN due_date IS NOT NULL AND due_date < ? "
            "          AND status != 'done' THEN 1 ELSE 0 END) AS overdue"
            " FROM study_tasks WHERE user_id = ?",
            (TODAY.isoformat(), self.user["id"]))[0]

        self.assertEqual(api["tasks"]["total"], expected["total"])
        self.assertEqual(api["tasks"]["todo"], expected["todo"])
        self.assertEqual(api["tasks"]["in_progress"], expected["in_progress"])
        self.assertEqual(api["tasks"]["done"], expected["done"])
        self.assertEqual(api["tasks"]["overdue"], expected["overdue"])

        # literal expectations, written out — not derived from the API
        self.assertEqual(api["tasks"]["total"], 6)
        self.assertEqual(api["tasks"]["todo"], 3)
        self.assertEqual(api["tasks"]["in_progress"], 1)
        self.assertEqual(api["tasks"]["done"], 2)
        self.assertEqual(api["tasks"]["overdue"], 1)

        minutes = self.raw("SELECT COALESCE(SUM(minutes),0) AS m "
                           "FROM study_sessions WHERE user_id = ?",
                           (self.user["id"],))[0]["m"]
        self.assertEqual(api["sessions"]["total_minutes"], minutes)
        self.assertEqual(api["sessions"]["total_minutes"], 65)


# ── 6.3 (9)(10) persistence & restart ──────────────────────────────────────
class TestPersistence(PlannerCase):
    def test_session_rows_survive_a_fresh_connection(self):
        res = self.client.post("/api/sessions", json={
            "subject_id": self.subject["id"], "minutes": 30,
            "studied_on": day(-1), "notes": "long division"})
        self.assertEqual(res.status_code, 201)
        sid = res.get_json()["id"]

        raw = sqlite3.connect(str(self.db_path))      # unrelated client
        try:
            row = raw.execute("SELECT minutes, notes FROM study_sessions "
                              "WHERE id = ?", (sid,)).fetchone()
        finally:
            raw.close()
        self.assertEqual(row, (30, "long division"))

    def test_data_survives_application_restart(self):
        task = self.make_task(title="Survives restart").get_json()
        self.client.post("/api/sessions", json={
            "subject_id": self.subject["id"], "minutes": 10})

        # "restart": brand-new app instance, brand-new connection pool
        os.environ["STUDY_PLANNER_DB"] = str(self.db_path)
        restarted = create_app(self.db_path)
        client = restarted.test_client()
        titles = [t["title"] for t in client.get("/api/tasks").get_json()]
        self.assertIn("Survives restart", titles)
        self.assertEqual(client.get("/api/dashboard").get_json()
                         ["sessions"]["total_minutes"], 10)


# ── 6.3 (11) API failure handling ──────────────────────────────────────────
class TestApiFailures(PlannerCase):
    def test_unknown_task_is_404_json(self):
        res = self.client.get("/api/tasks/424242")
        self.assertEqual(res.status_code, 404)
        self.assertIn("does not exist", res.get_json()["error"]["message"])

    def test_unknown_endpoint_is_404_json(self):
        res = self.client.get("/api/nope")
        self.assertEqual(res.status_code, 404)
        self.assertIn("error", res.get_json())

    def test_wrong_method_is_405_json(self):
        res = self.client.put("/api/tasks")
        self.assertEqual(res.status_code, 405)
        self.assertIn("not allowed", res.get_json()["error"]["message"])

    def test_non_json_body_is_400(self):
        res = self.client.post("/api/tasks", data="title=x",
                               content_type="text/plain")
        self.assertEqual(res.status_code, 400)

    def test_database_failure_returns_500_json_not_a_traceback(self):
        import app as app_module

        def boom(*a, **k):
            raise sqlite3.OperationalError("disk I/O error")

        original = app_module.models.list_tasks
        app_module.models.list_tasks = boom
        try:
            res = self.client.get("/api/tasks")
        finally:
            app_module.models.list_tasks = original
        self.assertEqual(res.status_code, 500)
        body = res.get_json()
        self.assertIn("error", body)
        self.assertNotIn("Traceback", res.get_data(as_text=True))
        self.assertNotIn("disk I/O error", res.get_data(as_text=True),
                         "internal error text leaked to the client")

    def test_missing_database_profile_is_409_not_a_crash(self):
        conn = connect(self.db_path)
        try:
            conn.execute("DELETE FROM users")
            conn.commit()
        finally:
            conn.close()
        res = self.client.get("/api/dashboard")
        self.assertEqual(res.status_code, 409)
        self.assertIn("seed", res.get_json()["error"]["message"])


# ── 6.3 (13) relationships ─────────────────────────────────────────────────
class TestRelationships(PlannerCase):
    def test_foreign_keys_are_enforced_by_our_connection(self):
        conn = connect(self.db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO study_tasks (user_id, subject_id, title) "
                    "VALUES (?, 999999, 'orphan')", (self.user["id"],))
        finally:
            conn.close()

    def test_deleting_a_subject_cascades_to_its_tasks(self):
        task = self.make_task(subject_id=self.other_subject["id"]).get_json()
        res = self.client.delete(f"/api/subjects/{self.other_subject['id']}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            self.raw("SELECT id FROM study_tasks WHERE id = ?", (task["id"],)),
            [])

    def test_session_task_link_can_be_null_but_never_dangling(self):
        task = self.make_task().get_json()
        bad = self.client.post("/api/sessions", json={
            "subject_id": self.subject["id"], "minutes": 15,
            "task_id": 999999})
        self.assertEqual(bad.status_code, 409)
        good = self.client.post("/api/sessions", json={
            "subject_id": self.subject["id"], "minutes": 15,
            "task_id": task["id"]})
        self.assertEqual(good.status_code, 201)


# ── 6.3 (12) frontend reflects backend (HTTP-level) ────────────────────────
class TestFrontendContract(PlannerCase):
    def test_page_serves_the_widgets_the_api_fills(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        for marker in ('id="task-rows"', 'id="kpi-total"', 'id="task-form"',
                       'id="filters"', 'id="minutes-chart"', "static/app.js"):
            self.assertIn(marker, html)

    def test_served_script_is_wired_to_the_real_api(self):
        js = self.client.get("/static/app.js").get_data(as_text=True)
        for endpoint in ("/api/tasks", "/api/dashboard", "/api/subjects",
                         "/api/sessions", "/complete", "DELETE"):
            self.assertIn(endpoint, js)

    def test_new_task_reaches_the_endpoints_the_page_calls(self):
        """The exact call sequence the browser makes for a new task."""
        self.make_task(title="Frontend-visible task")
        tasks = self.client.get("/api/tasks?q=Frontend-visible").get_json()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "Frontend-visible task")
        dash = self.client.get("/api/dashboard").get_json()
        self.assertEqual(dash["tasks"]["total"],
                         len(self.raw("SELECT id FROM study_tasks")))


# ── input validation / hostile input ───────────────────────────────────────
class TestValidation(PlannerCase):
    def test_negative_and_absurd_session_minutes_rejected(self):
        for minutes in (0, -30, 601, "30", 12.5, True):
            res = self.client.post("/api/sessions", json={
                "subject_id": self.subject["id"], "minutes": minutes})
            self.assertEqual(res.status_code, 400,
                             f"accepted minutes={minutes!r}")

    def test_invalid_priority_and_status_rejected(self):
        self.assertEqual(self.make_task(priority="urgent").status_code, 400)
        self.assertEqual(self.make_task(status="finished").status_code, 400)

    def test_task_without_subject_rejected(self):
        res = self.client.post("/api/tasks", json={"title": "No subject"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("subject_id", res.get_json()["error"]["fields"])

    def test_empty_title_rejected(self):
        self.assertEqual(self.make_task(title="   ").status_code, 400)

    def test_hostile_search_cannot_escape_the_query(self):
        for hostile in ("%' OR '1'='1", "%", "_", "\\"):
            res = self.client.get("/api/tasks",
                                  query_string={"q": hostile})
            self.assertEqual(res.status_code, 200)
        # wildcards are treated literally: they match only what they say
        res = self.client.get("/api/tasks", query_string={"q": "%"})
        self.assertEqual(res.get_json(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
