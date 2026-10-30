"""Fleet Operations — Flask dashboard over a real SQLite database.

    python seed.py     # once, writes the labelled sample rows
    python app.py      # http://127.0.0.1:5071

Every number on the page comes from a SQL query in this file. There are no
arrays of hardcoded figures in the JavaScript, so seeding new rows changes what
the dashboard shows.
"""

from __future__ import annotations

import datetime as dt
import os

from flask import Flask, jsonify, render_template, request

from db import DB_PATH, connect, one, rows

app = Flask(__name__)

RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90, "all": 3650}
UNIT = "Cost"
PREFIX = "£"
SERIES_LABEL = "Cost per day"
QUANTITY_LABEL = "Litres"
KPI_LABELS = ["Total cost", "Distance events", "Open issues", "Active vehicles"]
TITLE = "Fleet Operations"
SAMPLE_NOTE = "Sample data seeded by seed.py — illustrative, not a live system."


def _range_key() -> str:
    key = (request.args.get("range") or "30d").strip().lower()
    return key if key in RANGE_DAYS else "30d"


def _cutoff(key: str) -> str:
    days = RANGE_DAYS[key]
    return (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()


@app.get("/")
def index():
    return render_template(
        "index.html", title=TITLE, series_label=SERIES_LABEL,
        unit=UNIT, prefix=PREFIX, note=SAMPLE_NOTE,
        config={"prefix": PREFIX, "unit": UNIT, "series_label": SERIES_LABEL,
                "quantity_label": QUANTITY_LABEL, "title": TITLE},
    )


@app.get("/api/health")
def health():
    try:
        count = one("SELECT COUNT(*) AS n FROM events")
        return jsonify({"ok": True, "rows": count.get("n", 0),
                        "db": str(DB_PATH)})
    except Exception as err:                      # missing table, bad file
        return jsonify({"ok": False,
                        "error": f"{type(err).__name__}: {err}"}), 500


@app.get("/api/kpis")
def kpis():
    key = _range_key()
    cutoff = _cutoff(key)
    try:
        base = one(
            "SELECT COALESCE(SUM(amount), 0) AS total_value,"
            "       COALESCE(SUM(quantity), 0) AS total_quantity,"
            "       COUNT(*) AS records,"
            "       COUNT(DISTINCT category) AS categories,"
            "       COUNT(DISTINCT label) AS labels,"
            "       COALESCE(SUM(CASE WHEN status != 'closed' THEN 1 ELSE 0 END), 0) AS open_items"
            "  FROM events WHERE occurred_on >= ?", (cutoff,))
    except Exception as err:
        return jsonify({"error": f"{type(err).__name__}: {err}"}), 500
    if not base.get("records"):
        return jsonify({"kpis": [], "range": key, "empty": True,
                        "note": SAMPLE_NOTE})
    labels = KPI_LABELS
    return jsonify({
        "range": key,
        "kpis": [
            {"label": labels[0], "value": base["total_value"], "kind": "money",
             "hint": f"{UNIT.lower()} across every row in range"},
            {"label": labels[1], "value": base["total_quantity"], "kind": "number",
             "hint": f"{QUANTITY_LABEL.lower()} recorded"},
            {"label": labels[2], "value": base["open_items"], "kind": "number",
             "hint": "rows whose status is not closed"},
            {"label": labels[3], "value": base["labels"], "kind": "number",
             "hint": f"{base['categories']} categories"},
        ],
        "note": SAMPLE_NOTE,
    })


@app.get("/api/series")
def series():
    key = _range_key()
    cutoff = _cutoff(key)
    try:
        data = rows(
            "SELECT occurred_on AS date, ROUND(SUM(amount), 2) AS value,"
            "       SUM(quantity) AS quantity"
            "  FROM events WHERE occurred_on >= ?"
            " GROUP BY occurred_on ORDER BY occurred_on", (cutoff,))
    except Exception as err:
        return jsonify({"error": f"{type(err).__name__}: {err}"}), 500
    return jsonify({"range": key, "unit": UNIT, "label": SERIES_LABEL,
                    "series": data, "empty": not data})


@app.get("/api/breakdown")
def breakdown():
    key = _range_key()
    cutoff = _cutoff(key)
    try:
        data = rows(
            "SELECT category, ROUND(SUM(amount), 2) AS value,"
            "       SUM(quantity) AS quantity, COUNT(*) AS records"
            "  FROM events WHERE occurred_on >= ?"
            " GROUP BY category ORDER BY value DESC", (cutoff,))
    except Exception as err:
        return jsonify({"error": f"{type(err).__name__}: {err}"}), 500
    return jsonify({"range": key, "unit": UNIT, "breakdown": data,
                    "empty": not data})


@app.get("/api/status")
def status():
    key = _range_key()
    cutoff = _cutoff(key)
    try:
        data = rows(
            "SELECT status, COUNT(*) AS records"
            "  FROM events WHERE occurred_on >= ?"
            " GROUP BY status ORDER BY records DESC", (cutoff,))
    except Exception as err:
        return jsonify({"error": f"{type(err).__name__}: {err}"}), 500
    total = sum(int(r["records"] or 0) for r in data) or 1
    for item in data:
        item["share"] = round(100.0 * int(item["records"] or 0) / total, 1)
    return jsonify({"range": key, "status": data, "empty": not data})


@app.get("/api/rows")
def latest_rows():
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 300)
    except ValueError:
        limit = 50
    try:
        data = rows(
            "SELECT occurred_on, label, category, quantity, amount, status"
            "  FROM events ORDER BY occurred_on DESC, id DESC LIMIT ?", (limit,))
    except Exception as err:
        return jsonify({"error": f"{type(err).__name__}: {err}"}), 500
    return jsonify({"rows": data, "count": len(data), "empty": not data})


if __name__ == "__main__":
    port = int(os.environ.get("PORT") or os.environ.get("APP_PORT") or 5071)
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
