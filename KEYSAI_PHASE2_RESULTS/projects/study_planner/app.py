"""KeysAI_Test_Study_Planner — Flask JSON API + page.

    python seed.py        # write the synthetic dataset
    python app.py         # http://127.0.0.1:5082

Every response is JSON for /api/* — including failures — so the front end never
has to parse an HTML traceback. Status codes:
    200 ok / 201 created / 400 validation / 404 missing / 409 conflict
    405 wrong method / 500 unexpected (message only, no internals leaked)
"""

from __future__ import annotations

import os
import sqlite3
import traceback

from flask import Flask, g, jsonify, render_template, request

import models
import validation
from db import connect, init_db

APP_NAME = "KeysAI_Test_Study_Planner"


def _error(message: str, status: int, fields: dict | None = None):
    payload = {"error": {"message": message}}
    if fields:
        payload["error"]["fields"] = fields
    return jsonify(payload), status


def create_app(db_path: str | os.PathLike | None = None) -> Flask:
    if db_path is not None:
        os.environ["STUDY_PLANNER_DB"] = str(db_path)
    init_db()

    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.config["TESTING"] = False

    # ── connection per request ───────────────────────────────────────────
    @app.before_request
    def _open_db():
        g.db = connect()

    @app.teardown_request
    def _close_db(exc):
        conn = g.pop("db", None)
        if conn is not None:
            try:
                if exc is None:
                    conn.commit()
                else:
                    conn.rollback()
            finally:
                conn.close()

    def _current_user() -> sqlite3.Row | dict | None:
        """Synthetic profile: first seeded user (no authentication here — see
        README 'Known limitations')."""
        return models.list_users(g.db)[0] if models.list_users(g.db) else None

    # ── page ─────────────────────────────────────────────────────────────
    @app.get("/")
    def index():
        user = None
        try:
            users = models.list_users(g.db)
            user = users[0] if users else None
        except sqlite3.Error:
            user = None
        return render_template("index.html", app_name=APP_NAME, user=user,
                               db_error=user is None)

    # ── subjects ─────────────────────────────────────────────────────────
    @app.get("/api/subjects")
    def subjects_list():
        user = _current_user()
        if user is None:
            return _error("No user profile exists yet — run 'python seed.py'.", 409)
        return jsonify(models.list_subjects(g.db, user["id"]))

    @app.post("/api/subjects")
    def subjects_create():
        user = _current_user()
        if user is None:
            return _error("No user profile exists yet — run 'python seed.py'.", 409)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("A JSON object body is required.", 400)
        ok, msg, clean = validation.validate_subject(payload)
        if not ok:
            return _error(msg, 400, clean)
        try:
            subject = models.create_subject(g.db, user["id"], **clean)
        except sqlite3.IntegrityError:
            return _error("That subject already exists.", 409)
        except sqlite3.Error:
            return _error("Database error while creating the subject.", 500)
        return jsonify(subject), 201

    @app.patch("/api/subjects/<int:subject_id>")
    def subjects_update(subject_id: int):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("A JSON object body is required.", 400)
        if models.get_subject(g.db, subject_id) is None:
            return _error(f"Subject {subject_id} does not exist.", 404)
        ok, msg, clean = validation.validate_subject(payload, partial=True)
        if not ok:                    # third element is the fields map on failure
            return _error(msg, 400, clean)
        try:
            subject = models.update_subject(g.db, subject_id, clean)
        except sqlite3.IntegrityError:
            return _error("That subject name is already in use.", 409)
        except sqlite3.Error:
            return _error("Database error while updating the subject.", 500)
        return jsonify(subject)

    @app.delete("/api/subjects/<int:subject_id>")
    def subjects_delete(subject_id: int):
        if models.get_subject(g.db, subject_id) is None:
            return _error(f"Subject {subject_id} does not exist.", 404)
        try:
            models.delete_subject(g.db, subject_id)
        except sqlite3.Error:
            return _error("Database error while deleting the subject.", 500)
        return jsonify({"deleted": subject_id})

    # ── tasks ────────────────────────────────────────────────────────────
    @app.get("/api/tasks")
    def tasks_list():
        args = request.args
        status = args.get("status") or None
        if status and status not in validation.STATUSES:
            return _error(f"status must be one of: {', '.join(validation.STATUSES)}.", 400)
        priority = args.get("priority") or None
        if priority and priority not in validation.PRIORITIES:
            return _error(f"priority must be one of: {', '.join(validation.PRIORITIES)}.", 400)
        subject_id = args.get("subject_id", type=int) if args.get("subject_id") else None
        if args.get("subject_id") and subject_id is None:
            return _error("subject_id must be an integer.", 400)
        user = _current_user()
        try:
            tasks = models.list_tasks(
                g.db,
                user_id=user["id"] if user else None,
                status=status, subject_id=subject_id, priority=priority,
                query=args.get("q") or None,
                due_before=args.get("due_before") or None)
        except sqlite3.Error:
            return _error("Database error while listing tasks.", 500)
        return jsonify(tasks)

    @app.post("/api/tasks")
    def tasks_create():
        user = _current_user()
        if user is None:
            return _error("No user profile exists yet — run 'python seed.py'.", 409)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("A JSON object body is required.", 400)
        if "subject_id" not in payload:
            return _error("Validation failed.", 400,
                          {"subject_id": "A task must belong to a subject."})
        ok, msg, clean = validation.validate_task(payload)
        if not ok:                    # third element is the fields map on failure
            return _error(msg, 400, clean)
        subject = models.get_subject(g.db, clean.get("subject_id", 0))
        if subject is None:
            return _error(f"Subject {clean.get('subject_id')} does not exist.", 409)
        try:
            task = models.create_task(g.db, user_id=user["id"], **clean)
        except sqlite3.IntegrityError:
            return _error("The task references something that no longer exists.", 409)
        except sqlite3.Error:
            return _error("Database error while creating the task.", 500)
        return jsonify(task), 201

    @app.get("/api/tasks/<int:task_id>")
    def tasks_get(task_id: int):
        task = models.get_task(g.db, task_id)
        if task is None:
            return _error(f"Task {task_id} does not exist.", 404)
        return jsonify(task)

    @app.patch("/api/tasks/<int:task_id>")
    def tasks_update(task_id: int):
        if models.get_task(g.db, task_id) is None:
            return _error(f"Task {task_id} does not exist.", 404)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("A JSON object body is required.", 400)
        if not payload:
            return _error("No fields were supplied.", 400)
        ok, msg, clean = validation.validate_task(payload, partial=True)
        if not ok:                    # third element is the fields map on failure
            return _error(msg, 400, clean)
        if "subject_id" in clean and models.get_subject(g.db, clean["subject_id"]) is None:
            return _error(f"Subject {clean['subject_id']} does not exist.", 409)
        try:
            task = models.update_task(g.db, task_id, clean)
        except sqlite3.IntegrityError:
            return _error("The update references something that no longer exists.", 409)
        except sqlite3.Error:
            return _error("Database error while updating the task.", 500)
        return jsonify(task)

    @app.post("/api/tasks/<int:task_id>/complete")
    def tasks_complete(task_id: int):
        if models.get_task(g.db, task_id) is None:
            return _error(f"Task {task_id} does not exist.", 404)
        try:
            return jsonify(models.complete_task(g.db, task_id))
        except sqlite3.Error:
            return _error("Database error while completing the task.", 500)

    @app.delete("/api/tasks/<int:task_id>")
    def tasks_delete(task_id: int):
        if models.get_task(g.db, task_id) is None:
            return _error(f"Task {task_id} does not exist.", 404)
        try:
            models.delete_task(g.db, task_id)
        except sqlite3.Error:
            return _error("Database error while deleting the task.", 500)
        return jsonify({"deleted": task_id})

    # ── sessions ─────────────────────────────────────────────────────────
    @app.get("/api/sessions")
    def sessions_list():
        subject_id = request.args.get("subject_id", type=int) \
            if request.args.get("subject_id") else None
        user = _current_user()
        return jsonify(models.list_sessions(
            g.db, user_id=user["id"] if user else None, subject_id=subject_id))

    @app.post("/api/sessions")
    def sessions_create():
        user = _current_user()
        if user is None:
            return _error("No user profile exists yet — run 'python seed.py'.", 409)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("A JSON object body is required.", 400)
        ok, msg, clean = validation.validate_session(payload)
        if not ok:                    # third element is the fields map on failure
            return _error(msg, 400, clean)
        if models.get_subject(g.db, clean.get("subject_id", 0)) is None:
            return _error(f"Subject {clean.get('subject_id')} does not exist.", 409)
        task_id = clean.get("task_id")
        if task_id is not None and models.get_task(g.db, task_id) is None:
            return _error(f"Task {task_id} does not exist.", 409)
        try:
            session = models.create_session(g.db, user_id=user["id"], **clean)
        except sqlite3.Error:
            return _error("Database error while recording the session.", 500)
        return jsonify(session), 201

    @app.delete("/api/sessions/<int:session_id>")
    def sessions_delete(session_id: int):
        if models.get_session(g.db, session_id) is None:
            return _error(f"Session {session_id} does not exist.", 404)
        models.delete_session(g.db, session_id)
        return jsonify({"deleted": session_id})

    # ── dashboard ────────────────────────────────────────────────────────
    @app.get("/api/dashboard")
    def dashboard():
        user = _current_user()
        if user is None:
            return _error("No user profile exists yet — run 'python seed.py'.", 409)
        import datetime
        try:
            return jsonify(models.dashboard(g.db, user["id"],
                                            datetime.date.today().isoformat()))
        except sqlite3.Error:
            return _error("Database error while building the dashboard.", 500)

    # ── error handling: JSON everywhere, internals never leak ────────────
    @app.errorhandler(404)
    def _not_found(e):
        if request.path.startswith("/api/"):
            return _error("Endpoint not found.", 404)
        return _error("Page not found.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return _error(f"Method {request.method} is not allowed on {request.path}.", 405)

    @app.errorhandler(500)
    def _server_error(e):
        traceback.print_exc()          # console only — never sent to the client
        return _error("Internal server error.", 500)

    return app


def main():
    port = int(os.environ.get("PORT", "5082"))
    app = create_app()
    print(f"[{APP_NAME}] http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
