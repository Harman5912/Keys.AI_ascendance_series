"""Synthetic dataset for KeysAI_Test_Study_Planner (never real people data).

    python seed.py            # create/reset the database and load fixtures
    python seed.py --keep     # load only what is missing

Deadlines are generated RELATIVE to today so the fixtures stay valid under the
"deadlines must be today or later" rule, and one task is deliberately created
with a due date of *yesterday while still open* — that is the overdue case the
dashboard must count. Re-running seed.py resets to a known state.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
from pathlib import Path

from db import DEFAULT_DB, connect, init_db
import models

TODAY = dt.date.today()


def _day(offset: int) -> str:
    return (TODAY + dt.timedelta(days=offset)).isoformat()


USERS = [
    ("Synthetic Student", "student@example.test"),
    ("Synthetic Tutor", "tutor@example.test"),
]

SUBJECTS = [                       # (user_index, name, color)
    (0, "Mathematics", "#d4a017"),
    (0, "Physics", "#4f9dff"),
    (0, "History", "#e26d5c"),
    (1, "Chemistry", "#7bbf6a"),
]

# (user_index, subject_name, title, due offset, priority, status, notes)
TASKS = [
    (0, "Mathematics", "Integration by parts — 20 problems", 1, "high", "todo",
     "Pages 142–145, skip Q7–Q9."),
    (0, "Mathematics", "Revise trigonometric identities", 4, "medium", "in_progress",
     "Double-angle formulae first."),
    (0, "Mathematics", "Marked assignment corrections", -1, "high", "todo",
     "Overdue on purpose: the dashboard must count this as overdue."),
    (0, "Physics", "Lab report: pendulum experiment", 2, "high", "in_progress",
     "Include the error analysis table."),
    (0, "Physics", "Read chapter 4 — thermodynamics", 6, "low", "todo", ""),
    (0, "Physics", "Formula sheet", 0, "medium", "done", "Completed today."),
    (0, "History", "Essay: causes of the 1848 revolutions", 9, "medium", "todo",
     "1500 words, cite at least four sources."),
    (0, "History", "Timeline of the Cold War", 3, "low", "done", ""),
    (1, "Chemistry", "Balance the redox equations set B", 5, "high", "todo", ""),
]

# (user_index, subject_name, minutes, day offset, notes, task title or None)
SESSIONS = [
    (0, "Mathematics", 45, -6, "Integration practice", "Integration by parts — 20 problems"),
    (0, "Mathematics", 30, -4, "Flashcards", None),
    (0, "Physics", 60, -3, "Lab write-up draft", "Lab report: pendulum experiment"),
    (0, "History", 25, -1, "Source reading", None),
    (1, "Chemistry", 50, -2, "Redox drills", None),
    (0, "Physics", 40, 0, "Chapter 4 recap", "Read chapter 4 — thermodynamics"),
]


def seed(reset: bool = True) -> Path:
    path = init_db()
    conn = connect(path)
    try:
        if reset:
            for table in ("study_sessions", "study_tasks", "subjects", "users"):
                conn.execute(f"DELETE FROM {table}")   # fixed table names only
        conn.commit()

        if reset or not models.list_users(conn):
            user_ids = [models.create_user(conn, n, e)["id"] for n, e in USERS]
        else:
            user_ids = [u["id"] for u in models.list_users(conn)]

        subject_ids: dict[str, int] = {}
        for ui, name, color in SUBJECTS:
            subject_ids[name] = models.create_subject(
                conn, user_ids[ui], name, color)["id"]

        task_ids: dict[str, int] = {}
        for ui, subject, title, due, priority, status, notes in TASKS:
            task = models.create_task(
                conn, user_id=user_ids[ui], subject_id=subject_ids[subject],
                title=title, notes=notes, due_date=_day(due),
                priority=priority, status=status)
            if status == "done":
                conn.execute(
                    "UPDATE study_tasks SET completed_at = datetime('now') "
                    "WHERE id = ?", (task["id"],))
            task_ids[title] = task["id"]

        for ui, subject, minutes, offset, notes, task_title in SESSIONS:
            models.create_session(
                conn, user_id=user_ids[ui], subject_id=subject_ids[subject],
                minutes=minutes, studied_on=_day(offset), notes=notes,
                task_id=task_ids.get(task_title))

        conn.commit()
    finally:
        conn.close()        # `with conn` would NOT close it (transaction only)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep", action="store_true",
                    help="do not reset existing rows")
    args = ap.parse_args()
    path = seed(reset=not args.keep)
    conn = connect(path)
    try:
        n_tasks = conn.execute("SELECT COUNT(*) FROM study_tasks").fetchone()[0]
        n_sess = conn.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0]
        n_sub = conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]
    finally:
        conn.close()
    print(f"seeded {path}: {n_sub} subjects, {n_tasks} tasks, {n_sess} sessions")


if __name__ == "__main__":
    main()
