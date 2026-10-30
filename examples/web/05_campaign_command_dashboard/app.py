"""Campaign Command — Flask API for the marketing BI dashboard."""
from __future__ import annotations

from flask import Flask, jsonify, render_template, request

import db

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/overview")
def api_overview():
    return jsonify(db.overview())


@app.get("/api/tasks")
def api_tasks():
    return jsonify({"rows": db.tasks()})


@app.patch("/api/tasks/<int:task_id>")
def api_move_task(task_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(db.move_task(task_id, str(payload.get("status", ""))))
    except ValueError as err:
        return jsonify({"error": str(err)}), 400


@app.post("/api/seed")
def api_seed():
    return jsonify({"inserted": db.seed(force=True), "backend": db.backend_name()})


if __name__ == "__main__":
    print(f"[campaign-command] backend={db.backend_name()} seeded={db.seed()}")
    app.run(host="127.0.0.1", port=5057, debug=False)
