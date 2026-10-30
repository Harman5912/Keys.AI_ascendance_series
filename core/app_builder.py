"""
core/app_builder.py — deterministic, self-verifying application builders.

Why this exists
---------------
Two artifact kinds were reported as builds and were not: a dashboard and a
Python desktop app. Both had been handed to the local coding agent, which on
this machine is an 8B model that (a) searched an empty folder and answered
instead of writing, (b) wrote MySQL code for a server that was not running, and
(c) left the static/ files it had planned. File existence was then treated as
success, so the report said "finished" while nothing could be started.

The website path already solved this shape: render the artifact from a plan,
then verify it, and never hand the user a folder that does not run
(`core/site_builder.py`). This module does the same for the two application
kinds whose acceptance is fully mechanical:

    dashboard       Flask + SQLite + JSON API + charts + table
    python-desktop  PyQt6 window over SQLite, with an offscreen --selftest

Both are rendered from `core.app_specs` (labels and sample rows come from the
request), written to a real workspace, and then graded by `core.app_checks`:
does it compile, does the seeder run, does the server answer, does the window
construct offscreen. The result dict carries those checks, so a caller can
never say "done" on the strength of the file list alone.

No model is used here. That is the point: a builder that needs no inference
cannot fail because the model would not call a tool. The design decision is
disclosed in the result (`authored_by`) rather than hidden.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from core.app_checks import verify_workspace
from core.app_specs import pick_dashboard, pick_desktop

# ── templates: dashboard ──────────────────────────────────────────────────

_SCHEMA_SQL = """-- __TITLE__ — schema. Idempotent: safe to run more than once.
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_on  TEXT    NOT NULL,             -- YYYY-MM-DD
    label        TEXT    NOT NULL,             -- the thing being counted
    category     TEXT    NOT NULL,
    quantity     INTEGER NOT NULL DEFAULT 0,
    amount       REAL    NOT NULL DEFAULT 0,
    status       TEXT    NOT NULL DEFAULT 'open',
    note         TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_events_date     ON events(occurred_on);
CREATE INDEX IF NOT EXISTS idx_events_category ON events(category);
"""

_DB_PY = '''"""SQLite access for __TITLE__.

One place opens the database, so every query in the app uses the same file and
the same row factory. The path comes from DB_PATH when set (the verifier points
it at a scratch file), otherwise ./__DB_FILE__ next to this module.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH") or Path(__file__).resolve().with_name("__DB_FILE__"))
SCHEMA = Path(__file__).resolve().with_name("schema.sql")


def connect() -> sqlite3.Connection:
    """A connection with named columns and foreign keys on."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session(path=None):
    """A connection that is always closed.

    `with sqlite3.connect(...)` only commits the transaction — it leaves the
    handle open, which on Windows keeps the file locked and makes the
    database undeletable. Every access here goes through this instead.
    """
    global DB_PATH
    if path is not None:
        DB_PATH = Path(path)
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: str | os.PathLike | None = None) -> Path:
    """Create the tables if they are not there yet. Returns the db path."""
    with session(path) as conn:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    return DB_PATH


def rows(sql: str, params: tuple = ()) -> list[dict]:
    with session() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def one(sql: str, params: tuple = ()) -> dict:
    with session() as conn:
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else {}
'''

_SEED_PY = '''"""Seed __TITLE__ with clearly-labelled SAMPLE rows.

Run once before starting the server:   python seed.py
It is re-runnable: it clears the events table and writes the same rows again,
so the dashboard always tells the same story on a demo machine.

Nothing here is real data. The footer of the page says so too.
"""

from __future__ import annotations

import datetime as dt
import json
import random

from db import DB_PATH, init_db, session

DAYS = 180
SEED_VALUE = 7
LABELS = json.loads("""__LABELS__""")
CATEGORIES = json.loads("""__CATEGORIES__""")
STATUSES = json.loads("""__STATUSES__""")
BASE_AMOUNT = __BASE_AMOUNT__


def build_rows() -> list[tuple]:
    rng = random.Random(SEED_VALUE)
    today = dt.date.today()
    out = []
    for i in range(DAYS):
        day = today - dt.timedelta(days=DAYS - 1 - i)
        for _ in range(rng.randint(1, 3)):
            category = rng.choice(CATEGORIES)
            weight = CATEGORIES.index(category) + 1
            quantity = rng.randint(1, __MAX_QUANTITY__)
            amount = round(BASE_AMOUNT * weight * rng.uniform(0.35, 1.65), 2)
            out.append((
                day.isoformat(),
                rng.choice(LABELS),
                category,
                quantity,
                amount,
                rng.choice(STATUSES),
                "sample row",
            ))
    return out


def main() -> int:
    init_db()
    data = build_rows()
    with session() as conn:
        conn.execute("DELETE FROM events")
        conn.executemany(
            "INSERT INTO events (occurred_on, label, category, quantity, amount,"
            " status, note) VALUES (?, ?, ?, ?, ?, ?, ?)", data)
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        categories = conn.execute(
            "SELECT COUNT(DISTINCT category) FROM events").fetchone()[0]
    print(f"seeded {total} sample rows across {categories} categories into "
          f"{DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

_APP_PY = '''"""__TITLE__ — Flask dashboard over a real SQLite database.

    python seed.py     # once, writes the labelled sample rows
    python app.py      # http://127.0.0.1:__PORT__

Every number on the page comes from a SQL query in this file. There are no
arrays of hardcoded figures in the JavaScript, so seeding new rows changes what
the dashboard shows.
"""

from __future__ import annotations

import datetime as dt
import os

from flask import Flask, jsonify, render_template, request

from db import DB_PATH, one, rows

app = Flask(__name__)

RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90, "all": 3650}
UNIT = "__AMOUNT_UNIT__"
PREFIX = "__AMOUNT_PREFIX__"
SERIES_LABEL = "__SERIES_LABEL__"
QUANTITY_LABEL = "__QUANTITY_LABEL__"
KPI_LABELS = __KPI_LABELS__
TITLE = "__TITLE__"
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
    port = int(os.environ.get("PORT") or os.environ.get("APP_PORT") or __PORT__)
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
'''

_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITLE__</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
  <header class="topbar">
    <div class="brand">
      <p class="eyebrow">Dashboard</p>
      <h1>__TITLE__</h1>
    </div>
    <div class="controls">
      <label for="range">Range</label>
      <select id="range">
        <option value="7d">Last 7 days</option>
        <option value="30d" selected>Last 30 days</option>
        <option value="90d">Last 90 days</option>
        <option value="all">All time</option>
      </select>
      <button id="refresh" type="button">Refresh</button>
    </div>
  </header>

  <p id="banner" class="banner" role="status" aria-live="polite" hidden></p>

  <main>
    <section id="kpis" class="kpis" aria-label="Key figures"></section>

    <section class="panels">
      <article class="panel">
        <header class="panel-head">
          <h2>__SERIES_LABEL__</h2>
          <span class="unit">__AMOUNT_UNIT__</span>
        </header>
        <div id="line" class="chart"></div>
      </article>
      <article class="panel">
        <header class="panel-head">
          <h2>By category</h2>
          <span class="unit">__AMOUNT_UNIT__</span>
        </header>
        <div id="bars" class="bars"></div>
      </article>
    </section>

    <section class="panel">
      <header class="panel-head"><h2>Status</h2></header>
      <div id="status" class="status"></div>
    </section>

    <section class="panel">
      <header class="panel-head">
        <h2>Latest rows</h2>
        <span class="unit">50 most recent</span>
      </header>
      <div class="table-wrap">
        <table id="rows">
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Label</th>
              <th scope="col">Category</th>
              <th scope="col" class="num">__QUANTITY_LABEL__</th>
              <th scope="col" class="num">__AMOUNT_UNIT__</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
      <p id="empty" class="empty" hidden>No rows yet. Run <code>python seed.py</code> to add the sample data.</p>
    </section>
  </main>

  <footer class="foot">__NOTE__</footer>

  <script>window.APP = {{ config | tojson }};</script>
  <script src="{{ url_for('static', filename='dashboard.js') }}"></script>
</body>
</html>
"""

_DASH_CSS = """:root {
  --bg: #0f1115;
  --panel: #171a21;
  --line: #262b36;
  --ink: #e8ecf3;
  --muted: #8b95a7;
  --accent: #e8b44a;
  --good: #4cc38a;
  --warn: #e8b44a;
  --bad: #e2604a;
  --radius: 12px;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 15px/1.55 "Segoe UI", system-ui, -apple-system, sans-serif;
}

.topbar {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: flex-end;
  justify-content: space-between;
  padding: 28px clamp(16px, 4vw, 48px) 20px;
  border-bottom: 1px solid var(--line);
}

.eyebrow {
  margin: 0 0 4px;
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--accent);
}

h1 { margin: 0; font-size: clamp(22px, 3vw, 30px); font-weight: 600; letter-spacing: -0.01em; }

.controls { display: flex; align-items: center; gap: 10px; }
.controls label { font-size: 13px; color: var(--muted); }

select, button {
  background: var(--panel);
  color: var(--ink);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 12px;
  font: inherit;
  font-size: 13px;
}

button { cursor: pointer; }
button:hover { border-color: var(--accent); color: var(--accent); }
select:focus-visible, button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

main { padding: 24px clamp(16px, 4vw, 48px) 40px; display: grid; gap: 20px; }

.banner {
  margin: 16px clamp(16px, 4vw, 48px) 0;
  padding: 12px 16px;
  border-radius: var(--radius);
  border: 1px solid var(--line);
  background: var(--panel);
  font-size: 14px;
}
.banner.error { border-color: var(--bad); color: #ffd9d2; }
.banner.busy { border-color: var(--accent); color: var(--accent); }

.kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 14px;
}

.kpi {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 16px 18px;
}

.kpi-label { margin: 0; font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
.kpi-value { margin: 6px 0 2px; font-size: 26px; font-weight: 600; letter-spacing: -0.02em; }
.kpi-hint { margin: 0; font-size: 12px; color: var(--muted); }

.panels { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; }

.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 18px;
  min-width: 0;
}

.panel-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.panel-head h2 { margin: 0; font-size: 14px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--muted); }
.unit { font-size: 12px; color: var(--muted); }

.chart svg { width: 100%; height: auto; display: block; }
.chart .axis { stroke: var(--line); stroke-width: 1; }
.chart .tick { fill: var(--muted); font-size: 11px; }
.chart .area { fill: rgba(232, 180, 74, 0.14); }
.chart .stroke { fill: none; stroke: var(--accent); stroke-width: 2.5; stroke-linejoin: round; stroke-linecap: round; }
.chart .dot { fill: var(--accent); }

.bars { display: grid; gap: 10px; }
.bar-row { display: grid; grid-template-columns: 110px 1fr 84px; align-items: center; gap: 10px; font-size: 13px; }
.bar-name { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-track { background: #10131a; border-radius: 999px; height: 10px; overflow: hidden; }
.bar-fill { height: 100%; background: var(--accent); border-radius: 999px; }
.bar-value { text-align: right; font-variant-numeric: tabular-nums; }

.status { display: flex; flex-wrap: wrap; gap: 10px; }
.pill {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 13px;
  display: inline-flex;
  gap: 8px;
  align-items: center;
}
.pill .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
.pill.open .dot { background: var(--warn); }
.pill.closed .dot { background: var(--good); }
.pill.overdue .dot { background: var(--bad); }

.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
th, td { text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
th { font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tbody tr:hover { background: #1c2028; }
.status-tag { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }

.empty { color: var(--muted); font-size: 14px; margin: 8px 0 0; }

.foot { padding: 18px clamp(16px, 4vw, 48px) 32px; color: var(--muted); font-size: 12.5px; border-top: 1px solid var(--line); }

@media (max-width: 560px) {
  .bar-row { grid-template-columns: 84px 1fr 64px; }
  .controls { width: 100%; }
}
"""

_DASH_JS = """(function () {
  "use strict";

  var CFG = window.APP || {};
  var prefix = CFG.prefix || "";
  var unit = CFG.unit || "Value";
  var banner = document.getElementById("banner");
  var rangeSelect = document.getElementById("range");
  var state = { range: "30d" };

  function text(el, value) { el.textContent = value; }

  function show(message, kind) {
    banner.textContent = message || "";
    banner.className = "banner " + (kind || "");
    banner.hidden = !message;
  }

  function num(value) {
    var n = Number(value || 0);
    if (!isFinite(n)) { return "0"; }
    return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  }

  function money(value) { return prefix + num(value); }

  function getJSON(url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (resp) {
      if (!resp.ok) { throw new Error(url + " -> HTTP " + resp.status); }
      return resp.json();
    });
  }

  function empty(host, message) {
    var p = document.createElement("p");
    p.className = "empty";
    p.textContent = message;
    host.appendChild(p);
  }

  function renderKPIs(payload) {
    var host = document.getElementById("kpis");
    host.innerHTML = "";
    var items = payload.kpis || [];
    if (!items.length) { empty(host, "No figures for this range."); return; }
    items.forEach(function (kpi) {
      var card = document.createElement("article");
      card.className = "kpi";
      var label = document.createElement("p");
      label.className = "kpi-label";
      label.textContent = kpi.label;
      var value = document.createElement("p");
      value.className = "kpi-value";
      value.textContent = kpi.kind === "money" ? money(kpi.value) : num(kpi.value);
      var hint = document.createElement("p");
      hint.className = "kpi-hint";
      hint.textContent = kpi.hint || "";
      card.appendChild(label);
      card.appendChild(value);
      card.appendChild(hint);
      host.appendChild(card);
    });
  }

  function renderLine(payload) {
    var host = document.getElementById("line");
    host.innerHTML = "";
    var points = payload.series || [];
    if (!points.length) { empty(host, "No data in this range."); return; }

    var W = 640, H = 250;
    var pad = { top: 14, right: 12, bottom: 30, left: 56 };
    var values = points.map(function (p) { return Number(p.value || 0); });
    var max = Math.max.apply(null, values.concat([1]));
    var min = Math.min.apply(null, values.concat([0]));
    var span = (max - min) || 1;
    var innerW = W - pad.left - pad.right;
    var innerH = H - pad.top - pad.bottom;

    function xAt(i) { return pad.left + (i * innerW) / Math.max(points.length - 1, 1); }
    function yAt(v) { return pad.top + innerH - ((v - min) / span) * innerH; }

    var svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' +
      (payload.label || "Series") + ' over time">';

    [0, 0.5, 1].forEach(function (frac) {
      var value = min + span * frac;
      var y = yAt(value);
      svg += '<line class="axis" x1="' + pad.left + '" y1="' + y + '" x2="' + (W - pad.right) + '" y2="' + y + '"/>';
      svg += '<text class="tick" x="' + (pad.left - 8) + '" y="' + (y + 4) + '" text-anchor="end">' + num(value) + "</text>";
    });

    var line = points.map(function (p, i) { return xAt(i) + "," + yAt(Number(p.value || 0)); }).join(" ");
    svg += '<polygon class="area" points="' + pad.left + "," + (pad.top + innerH) + " " + line + " " + (pad.left + innerW) + "," + (pad.top + innerH) + '"/>';
    svg += '<polyline class="stroke" points="' + line + '"/>';

    var last = points.length - 1;
    svg += '<circle class="dot" cx="' + xAt(last) + '" cy="' + yAt(values[last]) + '" r="4"/>';

    svg += '<text class="tick" x="' + pad.left + '" y="' + (H - 8) + '">' + (points[0].date || "") + "</text>";
    svg += '<text class="tick" x="' + (W - pad.right) + '" y="' + (H - 8) + '" text-anchor="end">' +
      (points[points.length - 1].date || "") + "</text>";
    svg += "</svg>";
    host.innerHTML = svg;
  }

  function renderBars(payload) {
    var host = document.getElementById("bars");
    host.innerHTML = "";
    var items = payload.breakdown || [];
    if (!items.length) { empty(host, "No categories in this range."); return; }
    var max = Math.max.apply(null, items.map(function (i) { return Number(i.value || 0); }).concat([1]));
    items.forEach(function (item) {
      var row = document.createElement("div");
      row.className = "bar-row";

      var name = document.createElement("span");
      name.className = "bar-name";
      name.textContent = item.category;
      name.title = item.category;

      var track = document.createElement("span");
      track.className = "bar-track";
      var fill = document.createElement("span");
      fill.className = "bar-fill";
      fill.style.width = Math.max(2, (Number(item.value || 0) / max) * 100) + "%";
      track.appendChild(fill);

      var value = document.createElement("span");
      value.className = "bar-value";
      value.textContent = money(item.value);

      row.appendChild(name);
      row.appendChild(track);
      row.appendChild(value);
      host.appendChild(row);
    });
  }

  function renderStatus(payload) {
    var host = document.getElementById("status");
    host.innerHTML = "";
    var items = payload.status || [];
    if (!items.length) { empty(host, "No statuses in this range."); return; }
    items.forEach(function (item) {
      var pill = document.createElement("span");
      pill.className = "pill " + String(item.status || "").toLowerCase();
      var dot = document.createElement("span");
      dot.className = "dot";
      pill.appendChild(dot);
      pill.appendChild(document.createTextNode(item.status + " · " + num(item.records) + " (" + item.share + "%)"));
      host.appendChild(pill);
    });
  }

  function renderRows(payload) {
    var body = document.querySelector("#rows tbody");
    var note = document.getElementById("empty");
    body.innerHTML = "";
    var items = payload.rows || [];
    if (!items.length) { note.hidden = false; return; }
    note.hidden = true;
    items.forEach(function (item) {
      var tr = document.createElement("tr");
      function cell(value, className) {
        var td = document.createElement("td");
        if (className) { td.className = className; }
        td.textContent = value;
        tr.appendChild(td);
      }
      cell(item.occurred_on || "");
      cell(item.label || "");
      cell(item.category || "");
      cell(num(item.quantity), "num");
      cell(money(item.amount), "num");
      var tag = document.createElement("td");
      var span = document.createElement("span");
      span.className = "status-tag";
      span.textContent = item.status || "";
      tag.appendChild(span);
      tr.appendChild(tag);
      body.appendChild(tr);
    });
  }

  function load() {
    var q = "?range=" + encodeURIComponent(state.range);
    show("Loading…", "busy");
    return Promise.all([
      getJSON("/api/kpis" + q),
      getJSON("/api/series" + q),
      getJSON("/api/breakdown" + q),
      getJSON("/api/status" + q),
      getJSON("/api/rows")
    ]).then(function (results) {
      renderKPIs(results[0]);
      renderLine(results[1]);
      renderBars(results[2]);
      renderStatus(results[3]);
      renderRows(results[4]);
      show("", "");
    }).catch(function (err) {
      show("Could not load the dashboard: " + err.message + ". Is the seeded database present (python seed.py)?", "error");
    });
  }

  function bind() {
    if (rangeSelect) {
      rangeSelect.addEventListener("change", function () {
        state.range = rangeSelect.value;
        load();
      });
    }
    var refresh = document.getElementById("refresh");
    if (refresh) { refresh.addEventListener("click", load); }
    load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
"""

_DASH_README = """# __TITLE__

A dashboard over a real SQLite database: Flask JSON API, KPI cards, a line
chart, a category breakdown, a status summary and a table of the underlying
rows. Charts are drawn as inline SVG by `static/dashboard.js` from the API
responses — there are no hardcoded figures in the front end.

## Run it

```bash
python -m pip install -r requirements.txt
python seed.py          # writes 180 days of labelled SAMPLE rows
python app.py           # http://127.0.0.1:__PORT__
```

## Endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/health` | `{ok, rows, db}` |
| `GET /api/kpis?range=30d` | four KPI cards |
| `GET /api/series?range=30d` | value per day |
| `GET /api/breakdown?range=30d` | value per category |
| `GET /api/status?range=30d` | rows per status with share |
| `GET /api/rows?limit=50` | the most recent rows |

`range` accepts `7d` (default), `30d`, `90d`, `all`.

## Database

`schema.sql` is idempotent and creates one `events` table with indexes on the
date and category. `db.py` opens it; `DB_PATH` overrides the file location, so
the verifier can point the app at a scratch database.

## What is and is not real

- The API, the queries and the charts are real: they read the database.
- **The rows are sample data**, written by `seed.py` and labelled `sample row`
  in the `note` column. The page footer says so too.
- There is no authentication. This is a single-user local tool; do not put it
  on a public network as-is.
"""

# ── templates: python desktop ─────────────────────────────────────────────

_DESK_DB_PY = '''"""SQLite storage for __TITLE__.

All SQL lives here so the window never builds a query string from user input:
`search()` takes a parameter, not concatenated text.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("APP_DB") or (Path(__file__).resolve().parent.parent / "__DB_FILE__"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    category   TEXT    NOT NULL,
    quantity   INTEGER NOT NULL DEFAULT 0,
    amount     REAL    NOT NULL DEFAULT 0,
    note       TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_name ON records(name);
"""

SAMPLES = __SAMPLES__


def connect(path: str | os.PathLike | None = None) -> sqlite3.Connection:
    target = Path(path) if path else DB_PATH
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def session(path: str | os.PathLike | None = None):
    """A connection that is always closed.

    `with sqlite3.connect(...)` only commits — the handle stays open, which on
    Windows keeps the file locked and makes the database undeletable. Every
    access in this module goes through this context manager.
    """
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: str | os.PathLike | None = None) -> Path:
    with session(path) as conn:
        conn.executescript(SCHEMA)
    return Path(path) if path else DB_PATH


def list_records(search: str = "", path: str | os.PathLike | None = None) -> list[dict]:
    sql = ("SELECT id, name, category, quantity, amount, note, created_at"
           "  FROM records")
    params: tuple = ()
    if search:
        sql += " WHERE name LIKE ? OR category LIKE ? OR note LIKE ?"
        like = f"%{search}%"
        params = (like, like, like)
    sql += " ORDER BY id DESC"
    with session(path) as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def add_record(name: str, category: str, quantity: int, amount: float,
               note: str = "", path: str | os.PathLike | None = None) -> int:
    with session(path) as conn:
        cursor = conn.execute(
            "INSERT INTO records (name, category, quantity, amount, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (name.strip(), category.strip(), int(quantity), float(amount),
             note.strip(), dt.datetime.now().isoformat(timespec="seconds")))
        return int(cursor.lastrowid)


def delete_record(record_id: int, path: str | os.PathLike | None = None) -> None:
    with session(path) as conn:
        conn.execute("DELETE FROM records WHERE id = ?", (int(record_id),))


def totals(path: str | os.PathLike | None = None) -> dict:
    with session(path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(__TOTAL_SQL__, 0) AS total"
            "  FROM records").fetchone()
    return {"count": int(row["count"]), "total": float(row["total"])}


def seed_samples(path: str | os.PathLike | None = None) -> int:
    """Insert the demo rows. Idempotent: does nothing when rows exist."""
    init_db(path)
    with session(path) as conn:
        existing = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        if existing:
            return 0
        now = dt.datetime.now().isoformat(timespec="seconds")
        conn.executemany(
            "INSERT INTO records (name, category, quantity, amount, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(name, category, quantity, amount, "sample row", now)
             for name, category, quantity, amount in SAMPLES])
    return len(SAMPLES)
'''

_DESK_THEME_PY = '''"""Colours and the shared stylesheet for __TITLE__."""

from __future__ import annotations

ACCENT = "__ACCENT__"
BG = "#12141a"
PANEL = "#1a1d25"
INK = "#e9edf4"
MUTED = "#8d97a8"
LINE = "#2a2f3a"
WARN = "#e2604a"

STYLESHEET = f"""
QMainWindow, QWidget {{ background: {BG}; color: {INK};
    font-family: 'Segoe UI', system-ui, sans-serif; font-size: 13px; }}
QLabel#title {{ font-size: 19px; font-weight: 600; }}
QLabel#hint {{ color: {MUTED}; }}
QLabel#total {{ font-size: 17px; font-weight: 600; color: {ACCENT}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {PANEL}; border: 1px solid {LINE}; border-radius: 7px;
    padding: 7px 9px; color: {INK}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT}; }}
QPushButton {{ background: {ACCENT}; color: #14161c; border: 0;
    border-radius: 7px; padding: 8px 16px; font-weight: 600; }}
QPushButton:hover {{ background: #f0c667; }}
QPushButton:disabled {{ background: {LINE}; color: {MUTED}; }}
QPushButton#ghost {{ background: transparent; color: {INK};
    border: 1px solid {LINE}; }}
QPushButton#ghost:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QTableWidget {{ background: {PANEL}; border: 1px solid {LINE};
    border-radius: 8px; gridline-color: {LINE}; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED};
    border: 0; border-bottom: 1px solid {LINE}; padding: 7px;
    font-size: 11px; text-transform: uppercase; }}
QTableWidget::item:selected {{ background: #26303f; color: {INK}; }}
QStatusBar {{ color: {MUTED}; }}
"""
'''

_DESK_WINDOW_PY = '''"""The main window for __TITLE__.

The window owns no SQL: everything goes through app.db, so the whole model can
be exercised by `main.py --selftest` with no display.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from app import db
from app.theme import WARN, STYLESHEET

COLUMNS = ("__NAME_LABEL__", "__CATEGORY_LABEL__", "__QUANTITY_LABEL__",
           "__AMOUNT_LABEL__", "Added")
LOW_STOCK_AT = __LOW_STOCK_AT__
LOW_STOCK = __LOW_STOCK__


class Window(QtWidgets.QMainWindow):
    def __init__(self, db_path=None):
        super().__init__()
        db.init_db(db_path)
        self.db_path = db_path
        self.setWindowTitle("__TITLE__")
        self.resize(920, 600)
        self.setStyleSheet(STYLESHEET)
        self._build()
        self.refresh()

    # ── construction ─────────────────────────────────────────────────────
    def _build(self) -> None:
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.setSpacing(12)

        heading = QtWidgets.QLabel("__TITLE__")
        heading.setObjectName("title")
        hint = QtWidgets.QLabel(
            "Stored locally in SQLite. Search filters as you type.")
        hint.setObjectName("hint")
        layout.addWidget(heading)
        layout.addWidget(hint)

        top = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search __ENTITY_MANY__…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.total = QtWidgets.QLabel("")
        self.total.setObjectName("total")
        top.addWidget(self.search, 1)
        top.addWidget(self.total, 0)
        layout.addLayout(top)

        self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(COLUMNS)):
            header.setSectionResizeMode(
                column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        form = QtWidgets.QHBoxLayout()
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("__NAME_LABEL__")
        self.category = QtWidgets.QComboBox()
        self.category.addItems(__CATEGORIES__)
        self.quantity = QtWidgets.QSpinBox()
        self.quantity.setRange(0, 100000)
        self.amount = QtWidgets.QDoubleSpinBox()
        self.amount.setRange(-1000000, 1000000)
        self.amount.setDecimals(2)
        self.add_button = QtWidgets.QPushButton("Add __ENTITY_ONE__")
        self.add_button.clicked.connect(self.add)
        self.delete_button = QtWidgets.QPushButton("Delete selected")
        self.delete_button.setObjectName("ghost")
        self.delete_button.clicked.connect(self.delete)

        form.addWidget(self.name, 2)
        form.addWidget(self.category, 1)
        form.addWidget(self.quantity, 0)
        form.addWidget(self.amount, 0)
        form.addWidget(self.add_button, 0)
        form.addWidget(self.delete_button, 0)
        layout.addLayout(form)

        self.statusBar().showMessage("Ready")

    # ── data ─────────────────────────────────────────────────────────────
    def refresh(self) -> None:
        search = self.search.text().strip()
        records = db.list_records(search, self.db_path)
        self.table.setRowCount(0)
        for record in records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = (
                record["name"],
                record["category"],
                str(record["quantity"]),
                f"{record['amount']:,.2f}",
                str(record["created_at"])[:10],
            )
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                if column >= 2:
                    item.setTextAlignment(
                        QtCore.Qt.AlignmentFlag.AlignRight
                        | QtCore.Qt.AlignmentFlag.AlignVCenter)
                if LOW_STOCK and record["quantity"] <= LOW_STOCK_AT:
                    item.setForeground(QtGui.QColor(WARN))
                self.table.setItem(row, column, item)

        summary = db.totals(self.db_path)
        self.total.setText(
            f"{summary['count']} __ENTITY_MANY__ · __TOTAL_LABEL__ "
            f"{summary['total']:,.2f}")
        self.statusBar().showMessage(
            f"{len(records)} shown" + (f" matching '{search}'" if search else ""))

    def total_value(self) -> float:
        return db.totals(self.db_path)["total"]

    def add(self) -> None:
        name = self.name.text().strip()
        if not name:
            self.statusBar().showMessage("A __NAME_LABEL_LC__ is required.")
            self.name.setFocus()
            return
        db.add_record(name, self.category.currentText(),
                      self.quantity.value(), self.amount.value(),
                      path=self.db_path)
        self.name.clear()
        self.quantity.setValue(0)
        self.amount.setValue(0.0)
        self.refresh()
        self.statusBar().showMessage(f"Added '{name}'.")

    def delete(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self.statusBar().showMessage("Select a row to delete.")
            return
        records = db.list_records(self.search.text().strip(), self.db_path)
        if row >= len(records):
            return
        db.delete_record(records[row]["id"], self.db_path)
        self.refresh()
        self.statusBar().showMessage("Deleted.")
'''

_DESK_MAIN_PY = '''"""__TITLE__ — entry point.

    python main.py              # open the window
    python main.py --seed       # add the demo sample rows, then open
    python main.py --selftest   # build the window offscreen, print OK, exit
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile


def main() -> int:
    parser = argparse.ArgumentParser(description="__TITLE__")
    parser.add_argument("--selftest", action="store_true",
                        help="construct the window offscreen and exit")
    parser.add_argument("--seed", action="store_true",
                        help="insert the labelled sample rows first")
    args = parser.parse_args()

    if args.selftest:
        # No display, no user: this is the check the build runs.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6 import QtWidgets

    from app import db
    from app.window import Window

    app = QtWidgets.QApplication(sys.argv[:1])

    if args.selftest:
        with tempfile.TemporaryDirectory() as scratch:
            path = os.path.join(scratch, "selftest.db")
            inserted = db.seed_samples(path)
            window = Window(db_path=path)
            window.refresh()
            rows = window.table.rowCount()
            total = window.total_value()
            window.close()
            if rows != inserted:
                print(f"selftest FAILED: {rows} rows shown, {inserted} inserted")
                return 1
            if total == 0:
                print("selftest FAILED: total is zero after seeding")
                return 1
        print(f"selftest: {rows} rows, total {total:,.2f}")
        print("OK")
        return 0

    if args.seed:
        count = db.seed_samples()
        print(f"seeded {count} sample rows" if count
              else "sample rows already present")

    window = Window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
'''

_DESK_REQUIREMENTS = """PyQt6>=6.6
"""

_DESK_README = """# __TITLE__

A PyQt6 desktop application over a local SQLite database: a table, live search,
an add form, delete, and a running total in the header.

## Run it

```bash
python -m pip install -r requirements.txt
python main.py --seed     # optional: add clearly-labelled sample rows
python main.py            # open the window
```

## Verify it without clicking

```bash
python main.py --selftest
```

That builds the window on Qt's `offscreen` platform against a throwaway
database, checks the row count and total, prints `OK` and exits 0. It needs no
display, so it is safe to run in CI.

## Files

| File | Purpose |
|---|---|
| `main.py` | entry point, `--seed` and `--selftest` |
| `app/window.py` | the QMainWindow: table, search, form, totals |
| `app/db.py` | all SQL — schema, list, add, delete, totals |
| `app/theme.py` | palette and stylesheet |

## Storage

One SQLite file, `app.db`, next to `main.py`. Override it with the `APP_DB`
environment variable. Sample rows are labelled `sample row` in the `note`
column; delete them from the window when you start using it for real.
"""


# ── rendering helpers ─────────────────────────────────────────────────────

def _render(template: str, **tokens) -> str:
    """Substitute __TOKEN__ markers. No format(), so braces stay literal."""
    out = template
    for key, value in tokens.items():
        out = out.replace(f"__{key.upper()}__", str(value))
    return out


def _write(workspace: Path, relative: str, content: str) -> Path:
    """Write inside the workspace and nowhere else.

    Every path written today is a constant from a template, so this is defence
    in depth rather than a live hole: if a name ever becomes derived from input,
    `../` must not be able to leave the project directory.
    """
    root = Path(workspace).resolve()
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise ValueError(
            f"refusing to write outside the workspace: {relative!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def _py_literal(value) -> str:
    """A Python-valid literal from JSON (JSON is valid Python for these)."""
    return json.dumps(value, ensure_ascii=False)


def _list_files(workspace: Path) -> list[str]:
    """The files a user should see — bytecode caches are not one of them."""
    return sorted(str(p.relative_to(workspace)) for p in workspace.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts)


def _clean_cache(workspace: Path) -> None:
    """Compiling for verification leaves __pycache__ behind; remove it so the
    delivered project contains only what was written."""
    import shutil as _shutil

    for cache in workspace.rglob("__pycache__"):
        if cache.is_dir():
            _shutil.rmtree(cache, ignore_errors=True)


# ── dashboard ─────────────────────────────────────────────────────────────

DASHBOARD_PORT = 5071

DASHBOARD_ENDPOINTS = ("/api/health", "/api/kpis?range=30d",
                       "/api/series?range=30d", "/api/breakdown?range=30d",
                       "/api/status?range=30d", "/api/rows?limit=50")

DASHBOARD_REQUIRED_KEYS = {
    "/api/kpis?range=30d": ["kpis", "range"],
    "/api/series?range=30d": ["series"],
    "/api/breakdown?range=30d": ["breakdown"],
    "/api/status?range=30d": ["status"],
    "/api/rows?limit=50": ["rows"],
}

# A 200 carrying an empty array means the server never reached its database.
# These keys must contain rows for the dashboard to count as serving.
DASHBOARD_NONEMPTY_KEYS = {
    "/api/kpis?range=30d": ["kpis"],
    "/api/series?range=30d": ["series"],
    "/api/breakdown?range=30d": ["breakdown"],
    "/api/rows?limit=50": ["rows"],
}


def build_dashboard(brief: str, out_dir: Path | str,
                    on_phase=None, on_log=None, port: int = DASHBOARD_PORT,
                    verify: bool = True, browser: bool = False) -> dict:
    """Render and verify a dashboard. Returns a result dict; never raises."""
    started = time.time()
    workspace = Path(out_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    spec_key, spec = pick_dashboard(brief)
    title = spec["title"]
    db_file = "dashboard.db"

    def phase(name: str, pct: float, detail: str = "") -> None:
        if on_phase:
            on_phase(name, pct, detail)

    def log(line: str) -> None:
        if on_log:
            on_log(line)

    phase("plan", 0.05, f"{spec_key} dashboard")
    log(f"Plan: {spec['title']} — {len(spec['categories'])} categories, "
        f"{spec['amount_unit'].lower()} as the measure")

    tokens = dict(
        title=title,
        db_file=db_file,
        labels=_py_literal(spec["labels"]),
        categories=_py_literal(spec["categories"]),
        statuses=_py_literal(spec["statuses"]),
        base_amount=25 if spec_key == "newsroom" else 120,
        max_quantity=40 if spec_key == "newsroom" else 12,
        amount_unit=spec["amount_unit"],
        amount_prefix=spec["amount_prefix"],
        series_label=spec["series_label"],
        quantity_label=spec["quantity_label"],
        kpi_labels=_py_literal(list(spec["kpi_labels"])),
        note="Sample data seeded by seed.py — illustrative, not a live system.",
        port=port,
    )

    phase("write", 0.25, "database schema")
    _write(workspace, "schema.sql", _render(_SCHEMA_SQL, **tokens))
    _write(workspace, "db.py", _render(_DB_PY, **tokens))
    phase("write", 0.4, "seeder")
    _write(workspace, "seed.py", _render(_SEED_PY, **tokens))
    phase("write", 0.55, "JSON API")
    _write(workspace, "app.py", _render(_APP_PY, **tokens))
    phase("write", 0.75, "page shell and charts")
    _write(workspace, "templates/index.html", _render(_INDEX_HTML, **tokens))
    # Replace the stylesheet's hardcoded :root with generated, contrast-checked
    # tokens; every rule below it keeps using the same variable names.
    _css = _DASH_CSS
    try:
        from core.design_system import build_tokens as _build_tokens
        _root = _build_tokens(brief or title, kind="dashboard").to_css()
        if _css.lstrip().startswith(":root"):
            _css = _root + _css.split("}", 1)[1]
    except Exception as _exc:
        log(f"design tokens unavailable ({_exc}); using the fixed palette")
    _write(workspace, "static/style.css", _css)
    _write(workspace, "static/dashboard.js", _DASH_JS)
    _write(workspace, "requirements.txt", "Flask>=3.0\n")
    _write(workspace, ".env.example",
           "# Optional overrides. The verifier sets DB_PATH to a scratch file.\n"
           f"DB_PATH={db_file}\nPORT={port}\n")
    _write(workspace, "README.md", _render(_DASH_README, **tokens))
    files = _list_files(workspace)
    log(f"Wrote {len(files)} files")

    phase("verify", 0.85, "compiling, seeding, starting the server"
          + (" and rendering it in Chromium" if browser else ""))
    verification = verify_workspace(
        workspace, kind="dashboard", entry="app.py",
        endpoints=DASHBOARD_ENDPOINTS,
        required_keys=DASHBOARD_REQUIRED_KEYS,
        nonempty_keys=DASHBOARD_NONEMPTY_KEYS, seed="seed.py",
        browser=browser,
        screenshot=workspace / "dashboard.png") if verify else {
            "ok": True, "checks": [], "levels": [], "counts": {},
            "message": "verification skipped"}
    for check in verification["checks"]:
        log(f"{'PASS' if check['ok'] else 'FAIL'} {check['check']}")
    _clean_cache(workspace)

    total_bytes = sum((workspace / f).stat().st_size for f in files
                      if (workspace / f).exists())
    phase("done", 1.0, verification["message"])
    return {
        "ok": bool(verification["ok"]),
        "kind": "dashboard",
        "spec": spec_key,
        "title": title,
        "path": str(workspace),
        "entry": "app.py",
        "files": files,
        "bytes": total_bytes,
        "seconds": round(time.time() - started, 1),
        "checks": verification["checks"],
        "levels": verification["levels"],
        "message": str(verification["message"]),
        "authored_by": "recipe renderer (no model)",
        "run": f"python seed.py && python app.py  ({port})",
    }


# ── python desktop (PyQt6, SQLite, design-tokens theme) ───────────────────

def build_python_desktop(brief: str, out_dir: Path | str,
                         on_phase=None, on_log=None,
                         verify: bool = True) -> dict:
    """Render and verify a PyQt6 desktop app. Returns a result dict.

    Only responses that already live in this file are returned here. Anything
    that asks for a database server, a login, or a bigger set of files than the
    recipe writes still routes to the agent, so this function does not have to
    own every Python app a user might describe.
    """
    started = time.time()
    workspace = Path(out_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    spec_key, spec = pick_desktop(brief)
    title = spec["title"]
    db_file = "app.db"

    def phase(name: str, pct: float, detail: str = "") -> None:
        if on_phase:
            on_phase(name, pct, detail)

    def log(line: str) -> None:
        if on_log:
            on_log(line)

    phase("plan", 0.05, f"{spec_key} desktop app")
    log(f"Plan: {title} — table, live search, add form, running total")

    tokens = dict(
        title=title,
        db_file=db_file,
        entity_one=spec["entity_one"],
        entity_many=spec["entity_many"],
        name_label=spec["name_label"],
        name_label_lc=spec["name_label"].lower(),
        category_label=spec["category_label"],
        quantity_label=spec["quantity_label"],
        amount_label=spec["amount_label"],
        categories=_py_literal(spec["categories"]),
        samples=_py_literal([list(row) for row in spec["samples"]]),
        total_label=spec["total_label"],
        total_sql=("SUM(quantity * amount)" if spec["total_mode"] == "sum_value"
                   else "SUM(amount)"),
        low_stock="True" if spec["low_stock"] else "False",
        low_stock_at=5,
        accent="#e8b44a",
    )

    phase("write", 0.2, "storage layer")
    _write(workspace, "app/__init__.py",
           '"""' + title + ' — application package."""\n\n__all__ = ["db", "theme", "window"]\n')
    _write(workspace, "app/db.py", _render(_DESK_DB_PY, **tokens))
    # Theme from the design system: its palette is contrast-checked when it is
    # generated, so the built-in theme meets the same bar as everything else.
    try:
        from core.design_system import build_tokens as _build_tokens
        theme_source = _build_tokens(brief or title,
                                     kind="python-desktop").to_qt_theme(title)
    except Exception as _exc:
        log(f"design tokens unavailable ({_exc}); using the fixed theme")
        theme_source = _render(_DESK_THEME_PY, **tokens)
    _write(workspace, "app/theme.py", theme_source)
    phase("write", 0.5, "window")
    _write(workspace, "app/window.py", _render(_DESK_WINDOW_PY, **tokens))
    phase("write", 0.7, "entry point")
    _write(workspace, "main.py", _render(_DESK_MAIN_PY, **tokens))
    _write(workspace, "requirements.txt", _DESK_REQUIREMENTS)
    _write(workspace, "README.md", _render(_DESK_README, **tokens))
    files = _list_files(workspace)
    log(f"Wrote {len(files)} files")

    phase("verify", 0.85, "compiling and running --selftest")
    verification = verify_workspace(
        workspace, kind="python-desktop", entry="main.py") if verify else {
            "ok": True, "checks": [], "levels": [], "counts": {},
            "message": "verification skipped"}
    for check in verification["checks"]:
        log(f"{'PASS' if check['ok'] else 'FAIL'} {check['check']}")
    _clean_cache(workspace)

    total_bytes = sum((workspace / f).stat().st_size for f in files
                      if (workspace / f).exists())
    phase("done", 1.0, verification["message"])
    return {
        "ok": bool(verification["ok"]),
        "kind": "python-desktop",
        "spec": spec_key,
        "title": title,
        "path": str(workspace),
        "entry": "main.py",
        "files": files,
        "bytes": total_bytes,
        "seconds": round(time.time() - started, 1),
        "checks": verification["checks"],
        "levels": verification["levels"],
        "message": str(verification["message"]),
        "authored_by": "recipe renderer (no model)",
        "run": "python main.py",
    }


# ── routing ───────────────────────────────────────────────────────────────

# The rendered recipes are single-user and file-backed (SQLite). A request that
# explicitly asks for a database server or for sign-in is not served by them:
# swapping MySQL for SQLite, or dropping authentication, would silently replace
# a requirement the user stated. Those go to the agent, which can implement
# what was asked for.
_OUT_OF_RECIPE_SCOPE = re.compile(
    r"\b(mysql|mariadb|postgres(?:ql)?|mongo(?:db)?|supabase|firebase|"
    r"redis|login|log[- ]in|sign[- ]?in|sign[- ]?up|authentication|auth|"
    r"oauth|multi[- ]user|user accounts|roles?|permissions?)\b",
    re.I,
)

# A data-management application is not a reporting dashboard. The dashboard
# recipe writes one `events` table and read-only endpoints; handing it a request
# for "inventory management with add/edit/delete" produced a verified dashboard
# that was the wrong artifact entirely — the worst kind of pass, because every
# check succeeded on something the user did not ask for.
_CRUD_INTENT = re.compile(
    r"\b(crud|management system|management app|record management|"
    r"full[- ]stack|create[, /]+edit|add[, /]+and[, /]+edit|"
    r"add[, /]+edit[, /]+(?:delete|remove)|edit[, /]+and[, /]+delete)\b",
    re.I,
)

# Requirements routinely say what is NOT wanted ("no login", "without auth").
# Read as a positive, that wording would push a perfectly ordinary dashboard
# onto the agent path and cost minutes — the exact false positive this removes.
_NEGATED_SCOPE = re.compile(
    r"\b(?:no|not|never|without|free of|zero)\s+(?:any\s+|a\s+)?"
    r"(?:log[- ]?in|sign[- ]?in|sign[- ]?up|authentication|auth|oauth|"
    r"multi[- ]user|user accounts|users? accounts|roles?|permissions?|"
    r"mysql|mariadb|postgres(?:ql)?|mongo(?:db)?)\b",
    re.I,
)


def _strip_negations(text: str) -> str:
    return _NEGATED_SCOPE.sub("", text or "")


def app_kind_for(brief: str) -> str:
    """'dashboard', 'python-desktop' or '' — which builder owns this request.

    Only the two kinds with a complete, mechanical acceptance check are routed
    here, and only when the request does not name something the recipe would
    have to substitute away. Stores, Android, Electron, and any dashboard that
    asks for MySQL or a login still go to the agent.
    """
    from core.build_recipes import detect_stacks

    text = brief or ""
    stacks = detect_stacks(text)
    if "ecommerce" in stacks or "android" in stacks or "electron" in stacks:
        return ""
    if _OUT_OF_RECIPE_SCOPE.search(_strip_negations(text)):
        return ""
    if _CRUD_INTENT.search(text):
        return ""
    if "dashboard" in stacks:
        return "dashboard"
    # A game is its own builder. It comes before python-desktop so that
    # "a pygame game" is not built as a PyQt window with no loop.
    if "game" in stacks:
        return "game"
    if "python-desktop" in stacks:
        return "python-desktop"
    return ""


def build_app(brief: str, out_dir: Path | str, kind: str = "",
              on_phase=None, on_log=None, verify: bool = True,
              browser: bool = False) -> dict:
    """Dispatch to the builder for `kind` (detected when not given)."""
    kind = (kind or app_kind_for(brief) or "").strip().lower()
    if kind == "dashboard":
        return build_dashboard(brief, out_dir, on_phase=on_phase,
                               on_log=on_log, verify=verify, browser=browser)
    if kind == "python-desktop":
        return build_python_desktop(brief, out_dir, on_phase=on_phase,
                                    on_log=on_log, verify=verify)
    if kind == "game":
        from core.game_builder import build_game
        return build_game(brief, out_dir, on_phase=on_phase, on_log=on_log,
                          verify=verify)
    return {"ok": False, "kind": kind, "path": str(out_dir), "files": [],
            "checks": [], "seconds": 0.0,
            "message": f"no deterministic builder for kind {kind!r}"}
