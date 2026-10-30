"""Data-access layer — parameterised SQL only, no string-built queries.

Each function takes an open connection so a caller can wrap several writes in
one transaction (Flask commits per request; tests commit explicitly).
"""

from __future__ import annotations

import sqlite3
from typing import Any

# ── helpers ──────────────────────────────────────────────────────────────────

def _row(cur: sqlite3.Cursor) -> dict | None:
    r = cur.fetchone()
    return dict(r) if r else None


def _rows(cur: sqlite3.Cursor) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ── users (test profiles) ────────────────────────────────────────────────────

def create_user(conn: sqlite3.Connection, name: str,
                email: str | None = None) -> dict:
    cur = conn.execute(
        "INSERT INTO users (name, email) VALUES (?, ?)", (name, email))
    return get_user(conn, cur.lastrowid)


def get_user(conn: sqlite3.Connection, user_id: int) -> dict | None:
    return _row(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)))


def list_users(conn: sqlite3.Connection) -> list[dict]:
    return _rows(conn.execute("SELECT * FROM users ORDER BY id"))


# ── subjects ─────────────────────────────────────────────────────────────────

def create_subject(conn: sqlite3.Connection, user_id: int, name: str,
                   color: str = "#d4a017") -> dict:
    cur = conn.execute(
        "INSERT INTO subjects (user_id, name, color) VALUES (?, ?, ?)",
        (user_id, name, color))
    return get_subject(conn, cur.lastrowid)


def get_subject(conn: sqlite3.Connection, subject_id: int) -> dict | None:
    return _row(conn.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,)))


def list_subjects(conn: sqlite3.Connection, user_id: int | None = None) -> list[dict]:
    if user_id is None:
        return _rows(conn.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM study_tasks t "
            " WHERE t.subject_id = s.id) AS task_count "
            "FROM subjects s ORDER BY s.name COLLATE NOCASE"))
    return _rows(conn.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM study_tasks t "
        " WHERE t.subject_id = s.id) AS task_count "
        "FROM subjects s WHERE s.user_id = ? ORDER BY s.name COLLATE NOCASE",
        (user_id,)))


def update_subject(conn: sqlite3.Connection, subject_id: int, fields: dict) -> dict | None:
    sets, values = [], []
    for key in ("name", "color"):
        if key in fields:
            sets.append(f"{key} = ?")
            values.append(fields[key])
    if not sets:
        return get_subject(conn, subject_id)
    values.append(subject_id)
    conn.execute(f"UPDATE subjects SET {', '.join(sets)} WHERE id = ?", values)
    return get_subject(conn, subject_id)


def delete_subject(conn: sqlite3.Connection, subject_id: int) -> bool:
    cur = conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
    return cur.rowcount > 0


# ── tasks ────────────────────────────────────────────────────────────────────

def create_task(conn: sqlite3.Connection, *, user_id: int, subject_id: int,
                title: str, notes: str = "", due_date: str | None = None,
                priority: str = "medium", status: str = "todo") -> dict:
    cur = conn.execute(
        "INSERT INTO study_tasks (user_id, subject_id, title, notes, due_date, "
        " priority, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, subject_id, title, notes, due_date, priority, status))
    return get_task(conn, cur.lastrowid)


def get_task(conn: sqlite3.Connection, task_id: int) -> dict | None:
    return _row(conn.execute(
        "SELECT t.*, s.name AS subject_name, s.color AS subject_color "
        "FROM study_tasks t JOIN subjects s ON s.id = t.subject_id "
        "WHERE t.id = ?", (task_id,)))


def update_task(conn: sqlite3.Connection, task_id: int, fields: dict) -> dict | None:
    allowed = {"title", "notes", "due_date", "priority", "status",
               "subject_id", "completed_at"}
    sets, values = [], []
    for key in sorted(allowed):
        if key in fields:
            sets.append(f"{key} = ?")
            values.append(fields[key])
    # keep completed_at consistent with status in the SAME statement, so a
    # status flip can never be persisted half-done (done without a timestamp,
    # or a timestamp on a task that is no longer done).
    if "status" in fields and "completed_at" not in fields:
        if fields["status"] == "done":
            sets.append("completed_at = datetime('now')")
        else:
            sets.append("completed_at = NULL")
    if not sets:
        return get_task(conn, task_id)
    sets.append("updated_at = datetime('now')")
    values.append(task_id)
    conn.execute(f"UPDATE study_tasks SET {', '.join(sets)} WHERE id = ?", values)
    return get_task(conn, task_id)


def complete_task(conn: sqlite3.Connection, task_id: int) -> dict | None:
    conn.execute(
        "UPDATE study_tasks SET status = 'done', completed_at = datetime('now'), "
        " updated_at = datetime('now') WHERE id = ?", (task_id,))
    return get_task(conn, task_id)


def delete_task(conn: sqlite3.Connection, task_id: int) -> bool:
    cur = conn.execute("DELETE FROM study_tasks WHERE id = ?", (task_id,))
    return cur.rowcount > 0


def list_tasks(conn: sqlite3.Connection, *, user_id: int | None = None,
               status: str | None = None, subject_id: int | None = None,
               priority: str | None = None, query: str | None = None,
               due_before: str | None = None) -> list[dict]:
    """Filtered listing. Filters compose (AND); every value is bound, never
    interpolated, so search text cannot alter the statement."""
    sql = ("SELECT t.*, s.name AS subject_name, s.color AS subject_color "
           "FROM study_tasks t JOIN subjects s ON s.id = t.subject_id")
    where, args = [], []
    if user_id is not None:
        where.append("t.user_id = ?")
        args.append(user_id)
    if status:
        where.append("t.status = ?")
        args.append(status)
    if subject_id is not None:
        where.append("t.subject_id = ?")
        args.append(subject_id)
    if priority:
        where.append("t.priority = ?")
        args.append(priority)
    if due_before:
        where.append("t.due_date IS NOT NULL AND t.due_date <= ?")
        args.append(due_before)
    if query:
        where.append("(t.title LIKE ? ESCAPE '\\' OR t.notes LIKE ? ESCAPE '\\')")
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        args.extend([f"%{escaped}%", f"%{escaped}%"])
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += (" ORDER BY CASE t.status WHEN 'in_progress' THEN 0 WHEN 'todo' "
            "THEN 1 ELSE 2 END, t.due_date IS NULL, t.due_date, "
            "CASE t.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, t.id")
    return _rows(conn.execute(sql, args))


# ── sessions ─────────────────────────────────────────────────────────────────

def create_session(conn: sqlite3.Connection, *, user_id: int, subject_id: int,
                   minutes: int, studied_on: str, task_id: int | None = None,
                   notes: str = "") -> dict:
    cur = conn.execute(
        "INSERT INTO study_sessions (user_id, subject_id, task_id, minutes, "
        " studied_on, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, subject_id, task_id, minutes, studied_on, notes))
    return get_session(conn, cur.lastrowid)


def get_session(conn: sqlite3.Connection, session_id: int) -> dict | None:
    return _row(conn.execute(
        "SELECT ss.*, s.name AS subject_name FROM study_sessions ss "
        "JOIN subjects s ON s.id = ss.subject_id WHERE ss.id = ?", (session_id,)))


def list_sessions(conn: sqlite3.Connection, *, user_id: int | None = None,
                  subject_id: int | None = None) -> list[dict]:
    sql = ("SELECT ss.*, s.name AS subject_name FROM study_sessions ss "
           "JOIN subjects s ON s.id = ss.subject_id")
    where, args = [], []
    if user_id is not None:
        where.append("ss.user_id = ?")
        args.append(user_id)
    if subject_id is not None:
        where.append("ss.subject_id = ?")
        args.append(subject_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ss.studied_on DESC, ss.id DESC"
    return _rows(conn.execute(sql, args))


def delete_session(conn: sqlite3.Connection, session_id: int) -> bool:
    cur = conn.execute("DELETE FROM study_sessions WHERE id = ?", (session_id,))
    return cur.rowcount > 0


# ── dashboard (single query set, always straight from the tables) ────────────

def dashboard(conn: sqlite3.Connection, user_id: int,
               today: str) -> dict[str, Any]:
    """Statistics computed by SQLite itself — the API never caches or
    re-counts in Python, so the numbers cannot drift from the tables."""
    counts = _row(conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(CASE WHEN status = 'todo' THEN 1 ELSE 0 END)        AS todo,"
        " SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) AS in_progress,"
        " SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END)        AS done,"
        " SUM(CASE WHEN due_date IS NOT NULL AND due_date < ? AND status != 'done'"
        "          THEN 1 ELSE 0 END)                             AS overdue,"
        " SUM(CASE WHEN priority = 'high' AND status != 'done'"
        "          THEN 1 ELSE 0 END)                             AS high_priority"
        " FROM study_tasks WHERE user_id = ?", (today, user_id)))
    counts = {k: int(v or 0) for k, v in counts.items()}

    by_status = {r["status"]: r["n"] for r in _rows(conn.execute(
        "SELECT status, COUNT(*) AS n FROM study_tasks WHERE user_id = ?"
        " GROUP BY status", (user_id,)))}

    by_subject = _rows(conn.execute(
        "SELECT s.id, s.name, s.color,"
        " COUNT(t.id) AS task_count,"
        " SUM(CASE WHEN t.status = 'done' THEN 1 ELSE 0 END) AS done_count"
        " FROM subjects s LEFT JOIN study_tasks t ON t.subject_id = s.id"
        " WHERE s.user_id = ? GROUP BY s.id ORDER BY s.name COLLATE NOCASE",
        (user_id,)))

    minutes = _row(conn.execute(
        "SELECT COALESCE(SUM(minutes), 0) AS total_minutes,"
        " COUNT(*) AS sessions"
        " FROM study_sessions WHERE user_id = ?", (user_id,)))

    minutes_by_subject = _rows(conn.execute(
        "SELECT s.name, COALESCE(SUM(ss.minutes), 0) AS minutes"
        " FROM subjects s LEFT JOIN study_sessions ss ON ss.subject_id = s.id"
        " WHERE s.user_id = ? GROUP BY s.id ORDER BY minutes DESC",
        (user_id,)))

    n_subjects = _row(conn.execute(
        "SELECT COUNT(*) AS n FROM subjects WHERE user_id = ?", (user_id,)))["n"]

    return {
        "tasks": counts,
        "by_status": by_status,
        "by_subject": by_subject,
        "sessions": {"total_minutes": int(minutes["total_minutes"]),
                     "count": int(minutes["sessions"])},
        "minutes_by_subject": minutes_by_subject,
        "subjects": int(n_subjects),
        "as_of": today,
    }
