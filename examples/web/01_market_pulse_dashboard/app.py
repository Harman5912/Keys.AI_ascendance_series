"""Market Pulse — Flask app exposing the dashboard's JSON API."""
from __future__ import annotations

from flask import Flask, jsonify, render_template, request

import db

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/kpis")
def kpis():
    rows = db.summary()
    return jsonify({
        "backend": db.backend_name(),
        "empty": not rows,
        "rows": rows,
    })


@app.get("/api/series")
def api_series():
    symbol = (request.args.get("symbol") or "BTC").upper()
    try:
        days = max(1, min(90, int(request.args.get("days", 30))))
    except ValueError:
        return jsonify({"error": "days must be an integer"}), 400
    rows = db.series(symbol, days)
    if not rows:
        return jsonify({"symbol": symbol, "days": days, "points": [], "empty": True})
    return jsonify({"symbol": symbol, "days": days, "points": rows, "empty": False})


@app.get("/api/volume")
def api_volume():
    try:
        days = max(1, min(60, int(request.args.get("days", 14))))
    except ValueError:
        return jsonify({"error": "days must be an integer"}), 400
    return jsonify({"days": days, "points": db.volume_by_day(days)})


@app.post("/api/seed")
def api_seed():
    inserted = db.seed(force=True)
    return jsonify({"inserted": inserted, "backend": db.backend_name()})


if __name__ == "__main__":
    inserted = db.seed()
    print(f"[market-pulse] backend={db.backend_name()} seeded={inserted} rows")
    print("[market-pulse] http://127.0.0.1:5055")
    app.run(host="127.0.0.1", port=5055, debug=False)
