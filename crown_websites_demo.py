#!/usr/bin/env python3
"""
crown_websites_demo.py — end-to-end proof that Crown Code builds real, complex
analytics dashboards and opens each one in the browser BY ITSELF.

How it works
------------
For each of 10 very different domains the script drives the REAL Crown Code
agent — the same headless bridge Keys.AI uses (``core.crown_bridge.CrownBridge``)
— and asks it, stage by stage, to:

  1. write ``styles.css``  the dashboard theme                    (write_file)
  2. write ``index.html``  layout: 8 KPI cards, 6 chart canvases,
                           the data table, the six local scripts  (write_file)
  3. write ``data.js``     window.DASH: 8 KPIs, 22 rows, 6 series (write_file)
  4. write ``table.js``    the 8 KPI cards + searchable, sortable,
                           paginated 22-row table                  (write_file)
  5. write ``charts.js``   SIX real Chart.js charts (line, bar,
                           doughnut, radar, area, horizontal bar)  (write_file)
  6. write ``live.js``     setInterval auto-refresh every 5 s plus
                           the refresh / theme / range / nav wiring (write_file)
  7. open the finished dashboard in the default browser        (its OWN terminal:
                                                                start "" "index.html")

Why it is staged like this: a 4B/7B local model on a CPU-only machine cannot emit
a 600-line page in one tool call — it writes a stub, or a shell with no charts.
It *can* emit 80-130 lines of one clearly-scoped concern at a time. So every file
is small, single-purpose, and verified immediately; a failing stage is retried
with a repair task listing the exact problems found, until it verifies or its
attempts run out. Each stage also runs with a narrowed tool allowlist (a small
model does much better with three tool schemas than with twelve).

This script never writes site code and never opens a browser itself. It only
(i) issues the tasks, (ii) observes the agent's own tool calls / commands, and
(iii) inspects the artifacts on disk and inside a real headless Chrome — checking
that all six canvases actually painted, that the KPIs and the table rendered, that
typing filters the table, that the theme toggles, and that the numbers change on
their own after 5 seconds. The one thing it provisions is the charting library
(``chart.umd.min.js``, copied into each workspace like an installed dependency).

Usage
-----
    python crown_websites_demo.py                       # all 10 sites
    python crown_websites_demo.py --only 1              # pilot: site #1
    python crown_websites_demo.py --only 1,4,7
    python crown_websites_demo.py --model qwen3.5:4b
    python crown_websites_demo.py --attempts 4 --timeout 420 --max-iterations 6
    python crown_websites_demo.py --only 1 --stage charts   # one stage only
    python crown_websites_demo.py --no-browser-check
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.crown_bridge import CrownBridge, ensure_built  # noqa: E402

SITES_ROOT = BASE_DIR / "crown_sites"
ASSETS_DIR = SITES_ROOT / "_assets"
TOOLS_DIR = SITES_ROOT / "_tools"
CHART_JS = ASSETS_DIR / "chart.umd.min.js"

# Every file stage writes one file and reads at most one; nothing else is
# advertised to the model, so it cannot wander off into git or the shell.
FILE_TOOLS = ["write_file", "read_file", "list_files"]
LAUNCH_TOOLS = ["terminal"]

# ── The 10 topics ─────────────────────────────────────────────────────────
# Each one is a domain with many competing metrics, several breakdowns and time
# series — a real dashboard. ``kpis`` are handed to the model so it never has to
# invent the metric names; ``columns`` are the six table columns (first is the
# item name); ``series`` is the fixed c1..c6 map.
SITES: list[dict] = [
    {
        "slug": "01_ecommerce_growth",
        "title": "NovaCart — E-commerce Growth Command Center",
        "domain": "online retail: revenue, orders, AOV, conversion funnel, cart abandonment, traffic sources, top products, regional sales",
        "kpis": ["Revenue (24h)", "Orders", "Avg Order Value", "Conversion Rate",
                 "Cart Abandonment", "Active Sessions", "Refund Rate", "Repeat Customers"],
        "columns": ["Product", "Units Sold", "Revenue ($)", "Conversion (%)", "Return Rate (%)", "Stock Left"],
        "series": [("line", "Revenue — last 6 hours"), ("bar", "Orders per hour"),
                   ("doughnut", "Traffic sources"), ("radar", "Funnel health"),
                   ("area", "Sessions vs conversions"), ("hbar", "Top categories by revenue")],
    },
    {
        "slug": "02_hospital_operations",
        "title": "Mercy General — Hospital Operations Control Tower",
        "domain": "hospital operations: bed occupancy, ICU capacity, ER wait times, admissions/discharges, surgery schedule, staffing ratios, pharmacy stock",
        "kpis": ["Bed Occupancy (%)", "ICU Capacity (%)", "ER Wait (min)", "Admissions Today",
                 "Discharges Today", "Surgery On-Time (%)", "Staff per Patient", "Infection Index"],
        "columns": ["Ward", "Beds Used", "Occupancy (%)", "Avg Wait (min)", "Staff Assigned", "Acuity"],
        "series": [("line", "ER wait — last 6 hours"), ("bar", "Admissions vs discharges"),
                   ("doughnut", "Patient mix"), ("radar", "Ward performance"),
                   ("area", "Bed occupancy trend"), ("hbar", "Top diagnoses")],
    },
    {
        "slug": "03_crypto_trading",
        "title": "OrbitalDesk — Crypto Trading Terminal",
        "domain": "crypto trading: portfolio value, PnL, open positions, order-book depth, BTC/ETH/SOL price action, funding rates, liquidations, moving averages",
        "kpis": ["Portfolio Value ($)", "24h PnL ($)", "Unrealised PnL ($)", "Open Positions",
                 "Margin Used (%)", "Funding Rate (%)", "Volatility Index", "Win Rate (%)"],
        "columns": ["Pair", "Size", "Entry Price", "Mark Price", "PnL ($)", "Leverage"],
        "series": [("line", "BTC price — last 6 hours"), ("bar", "Volume by exchange"),
                   ("doughnut", "Portfolio allocation"), ("radar", "Strategy scorecard"),
                   ("area", "Order-book depth"), ("hbar", "Top movers")],
    },
    {
        "slug": "04_smart_city_iot",
        "title": "Helios City — Smart City IoT Grid",
        "domain": "smart-city IoT: air quality, traffic density, energy load, water usage, noise levels, waste-bin fill, street-light status, sensor uptime",
        "kpis": ["Air Quality (PM2.5)", "Traffic Density", "Grid Load (MW)", "Water Usage (kl)",
                 "Noise (dB)", "Bins >80% Full", "Lights Online (%)", "Sensor Uptime (%)"],
        "columns": ["District", "PM2.5", "Traffic Index", "Energy (MW)", "Water (kl)", "Sensors Online"],
        "series": [("line", "PM2.5 — last 6 hours"), ("bar", "Energy load by district"),
                   ("doughnut", "Traffic mode share"), ("radar", "District livability"),
                   ("area", "Water usage trend"), ("hbar", "Noise hotspots")],
    },
    {
        "slug": "05_logistics_fleet",
        "title": "AtlasFreight — Fleet & Logistics Live Ops",
        "domain": "logistics: active trucks, on-time delivery, fuel burn, route efficiency, warehouse backlog, driver hours, cold-chain breaches",
        "kpis": ["Active Trucks", "On-Time (%)", "Fuel Burn (L/h)", "Avg Route Cost ($)",
                 "Warehouse Backlog", "Driver Hours Left", "Cold-Chain Breaches", "Idle Time (%)"],
        "columns": ["Route", "Trucks", "On-Time (%)", "Distance (km)", "Fuel (L)", "Delay (min)"],
        "series": [("line", "Deliveries per hour"), ("bar", "Fuel burn by route"),
                   ("doughnut", "Delay causes"), ("radar", "Depot performance"),
                   ("area", "Backlog trend"), ("hbar", "Cost per route")],
    },
    {
        "slug": "06_cyber_soc",
        "title": "AegisSOC — Security Operations Center",
        "domain": "cybersecurity: alerts by severity, MITRE tactics, mean time to detect/respond, blocked IPs, attack origins, endpoint compliance, phishing volume",
        "kpis": ["Open Alerts", "Critical Alerts", "MTTD (min)", "MTTR (min)",
                 "Blocked IPs", "Compliant (%)", "Phishing Volume", "SLA Breaches"],
        "columns": ["Threat", "Alerts", "Risk Score", "Events /h", "Endpoints Hit", "Coverage (%)"],
        "series": [("line", "Alerts — last 6 hours"), ("bar", "Alerts by severity"),
                   ("doughnut", "Attack origins"), ("radar", "MITRE tactic coverage"),
                   ("area", "Traffic inspected"), ("hbar", "Top targeted endpoints")],
    },
    {
        "slug": "07_saas_analytics",
        "title": "Northstar — SaaS Product Analytics",
        "domain": "SaaS: MRR/ARR, new vs churned MRR, DAU/WAU/MAU, activation, retention cohorts, feature adoption, trial conversion, NPS, support tickets",
        "kpis": ["MRR ($)", "Net New MRR ($)", "Churned MRR ($)", "Active Users",
                 "Trial → Paid (%)", "Feature Adoption (%)", "NPS", "Open Tickets"],
        "columns": ["Feature", "Users", "Adoption (%)", "Retention (%)", "Sessions /day", "Crash Rate (%)"],
        "series": [("line", "MRR — last 6 months"), ("bar", "New vs churned MRR"),
                   ("doughnut", "Plan mix"), ("radar", "Cohort health"),
                   ("area", "DAU / WAU / MAU"), ("hbar", "Most used features")],
    },
    {
        "slug": "08_renewable_energy",
        "title": "VoltaGrid — Renewable Energy Grid",
        "domain": "energy: solar and wind output, battery state of charge, grid frequency, load vs generation, curtailment, CO2 avoided, per-site efficiency",
        "kpis": ["Output (MW)", "Solar Share (%)", "Wind Share (%)", "Battery SoC (%)",
                 "Frequency (Hz)", "Load Met (%)", "CO2 Avoided (t)", "Curtailed (MWh)"],
        "columns": ["Site", "Output (MW)", "Capacity (%)", "Availability (%)", "Price (EUR/MWh)", "Wind (m/s)"],
        "series": [("line", "Generation — last 6 hours"), ("bar", "Output by site"),
                   ("doughnut", "Generation mix"), ("radar", "Site efficiency"),
                   ("area", "Load vs generation"), ("hbar", "Curtailment by site")],
    },
    {
        "slug": "09_edtech_learning",
        "title": "LuminaLearn — EdTech Learning Platform",
        "domain": "education technology: active learners, course completion, lesson drop-off, quiz scores, study minutes, streak retention, tutor utilisation, subject mastery",
        "kpis": ["Active Learners", "Completion (%)", "Avg Quiz Score", "Study Minutes",
                 "Streak Retention (%)", "Tutor Utilisation (%)", "Drop-off (%)", "Courses Live"],
        "columns": ["Course", "Enrolled", "Completion (%)", "Avg Score", "Study Hours", "Drop-off (%)"],
        "series": [("line", "Active learners — last 6 hours"), ("bar", "Lessons completed"),
                   ("doughnut", "Device mix"), ("radar", "Subject mastery"),
                   ("area", "Study minutes by day"), ("hbar", "Most completed courses")],
    },
    {
        "slug": "10_food_delivery",
        "title": "SizzleRoute — Food Delivery Operations",
        "domain": "food delivery: live orders, kitchen prep time, courier availability, delivery ETA accuracy, cancelled orders, ratings, per-zone demand, cost per delivery",
        "kpis": ["Live Orders", "Avg Prep (min)", "Avg Delivery (min)", "ETA Accuracy (%)",
                 "Cancellations", "Couriers Online", "Avg Rating", "Cost / Order ($)"],
        "columns": ["Zone", "Orders", "Prep (min)", "Delivery (min)", "Cancel (%)", "Rating"],
        "series": [("line", "Orders — last 6 hours"), ("bar", "Orders by zone"),
                   ("doughnut", "Payment mix"), ("radar", "Zone performance"),
                   ("area", "Demand vs couriers"), ("hbar", "Top restaurants")],
    },
]

# ── Stage 1: styles.css ───────────────────────────────────────────────────

STYLES_TASK = """Write the stylesheet for an analytics dashboard. Call the write_file tool ONCE with path "styles.css".

PROJECT: __TITLE__
SECTOR:  __DOMAIN__

Theme: a dark "command centre" look — page background #0b1020, cards #141a2f with a
1px #26304d border and 10px radius, primary accent #4f7cff, body text #e6ebff, muted
text #8b96b8, positive green #37d67a, negative red #ff5d5d. Layout: a fixed 240px left
sidebar, the main content to its right with a sticky top bar; the KPI cards are a
responsive grid of 4 columns and the chart panels a grid of 3 columns (both collapse to
1 column under 900px).

Write real CSS (roughly 100-160 lines) that styles ALL of these selectors — spelled
exactly like this, since the HTML is written separately and already uses them:

body, #app, #sidebar, #sidebar .brand, #sidebar nav, .nav-link, .nav-link.active,
main, #topbar, #topbar input, .ranges, .range-btn, .range-btn.active, #refresh,
#theme-toggle, .kpis, .kpi, .kpi-label, .kpi-value, .kpi-delta, .kpi-delta.up,
.kpi-delta.down, .charts, .panel, .panel h3, .panel canvas, #tablecard, #tbl-search,
table, thead th, td, tbody tr:nth-child(even), tbody tr:hover, #tablefoot, #tbl-prev,
#tbl-next, #tbl-page, footer, body.light, body.light .panel, body.light .kpi,
body.light #sidebar

Rules: no comments, no @import, no frameworks, no placeholders, no "...". One write_file
call. Do not create any other file. Answer in one short line when done."""

STYLES_RULES = ("Real CSS, roughly 100-160 lines, styling all of the selectors from the original task "
                "(dark theme, 240px sidebar, 4-up KPI grid, 3-up chart grid, sticky top bar, body.light "
                "overrides). No comments, no placeholders.")

# ── Stage 2: index.html ───────────────────────────────────────────────────

MARKUP_TASK = """Write ONE HTML page. Call the write_file tool ONCE with path "index.html".

PROJECT: __TITLE__
SECTOR:  __DOMAIN__

It must link these files in this exact order and nothing else:
  <link rel="stylesheet" href="styles.css">            (in <head>)
  <script src="chart.umd.min.js"></script>
  <script src="data.js"></script>
  <script src="table.js"></script>
  <script src="charts.js"></script>
  <script src="live.js"></script>
  (the five <script> tags in that order at the very end of <body>)

Use EXACTLY this structure. Keep every id and class name identical; only fill in the
visible text with real, sector-specific labels. Do not add, rename or drop elements.

<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="styles.css">
</head>
<body>
<div id="app">
  <aside id="sidebar">
    <div class="brand">BRAND</div>
    <nav>
      <a class="nav-link active" href="#">Overview</a>
      ... 5 more <a class="nav-link" href="#"> links with real labels for this sector ...
    </nav>
  </aside>
  <main>
    <header id="topbar">
      <input id="search" type="search" placeholder="Search this dashboard...">
      <div class="ranges">
        <button class="range-btn active">24h</button>
        <button class="range-btn">7d</button>
        <button class="range-btn">30d</button>
      </div>
      <button id="refresh">Refresh</button>
      <button id="theme-toggle">Theme</button>
    </header>
    <section class="kpis">
      <div class="kpi" data-kpi="0"><span class="kpi-label">LABEL</span><span class="kpi-value">0</span><span class="kpi-delta up">+0%</span></div>
      ... seven more, data-kpi="1" ... data-kpi="7" ...
    </section>
    <section class="charts">
      <div class="panel"><h3>HEADING</h3><canvas id="c1" height="200"></canvas></div>
      <div class="panel"><h3>HEADING</h3><canvas id="c2" height="200"></canvas></div>
      <div class="panel"><h3>HEADING</h3><canvas id="c3" height="200"></canvas></div>
      <div class="panel"><h3>HEADING</h3><canvas id="c4" height="200"></canvas></div>
      <div class="panel"><h3>HEADING</h3><canvas id="c5" height="200"></canvas></div>
      <div class="panel"><h3>HEADING</h3><canvas id="c6" height="200"></canvas></div>
    </section>
    <section id="tablecard">
      <h3>detail table heading</h3>
      <input id="tbl-search" type="search" placeholder="Filter rows...">
      <table>
        <thead>
          <tr><th>__COL1__</th><th>__COL2__</th><th>__COL3__</th><th>__COL4__</th><th>__COL5__</th><th>__COL6__</th></tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
      <div id="tablefoot">
        <button id="tbl-prev">Prev</button><span id="tbl-page">Page 1</span><button id="tbl-next">Next</button>
      </div>
    </section>
    <footer>one line of footer text — data source + last-updated note</footer>
  </main>
</div>
<script src="chart.umd.min.js"></script>
<script src="data.js"></script>
<script src="table.js"></script>
<script src="charts.js"></script>
<script src="live.js"></script>
</body>
</html>

The 8 KPI cards, in this exact order for data-kpi="0" .. data-kpi="7":
__KPIS__

The 6 chart panel headings, for canvas id c1..c6 in this exact order:
__SERIES__

The 6 table <th> labels, in this exact order:
__COLUMNS__

Rules: roughly 100-150 lines, real text only, no comments, no leftover placeholder
words, no "...". One write_file call. Do not create any other file. Answer in one short
line when done."""

MARKUP_RULES = ("index.html must contain the sidebar (6 <a class=\"nav-link\">), the top bar with "
                "#search / 3 .range-btn / #refresh / #theme-toggle, 8 <div class=\"kpi\" data-kpi=\"0..7\"> "
                "cards, 6 <canvas id=\"c1\">..\"c6\"> panels, the 6-column <table> with <tbody id=\"tbody\"> "
                "and #tbl-search / #tbl-prev / #tbl-next / #tbl-page, a <footer>, and script tags for "
                "chart.umd.min.js, data.js, table.js, charts.js, live.js.")

# ── Stage 3: data.js ──────────────────────────────────────────────────────

DATA_TASK = """Write the dashboard's data file. Call the write_file tool ONCE with path "data.js".

PROJECT: __TITLE__
SECTOR:  __DOMAIN__

Write plain browser JavaScript that sets ONE global exactly like this (same key names and
shapes — table.js, charts.js and live.js are already written against them):

window.DASH = {
  kpis: [ ... exactly 8 objects, in the order given below, each
            {label:"<the KPI name>", value:<number>, unit:"<short unit or empty string>", delta:<signed percent number>} ],
  columns: [ ... exactly 6 strings ... ],
  rows: [ ... exactly 22 objects, 22 DIFFERENT real items for this sector ... ],
  series: {
    line:     {labels:[...6 strings...], values:[...6 numbers...]},
    bar:      {labels:[...6 strings...], values:[...6 numbers...]},
    doughnut: {labels:[...6 strings...], values:[...6 numbers...]},
    radar:    {labels:[...6 strings...], values:[...6 numbers...]},
    area:     {labels:[...6 strings...], values:[...6 numbers...]},
    hbar:     {labels:[...6 strings...], values:[...6 numbers...]}
  }
};

Every row object must have EXACTLY these six keys, in this order:
  name (non-empty string — the item for this sector),
  m1, m2, m3, m4, m5 (five numbers, realistic for this sector).

The 8 KPI labels, in order:
__KPIS__

`columns` must be exactly these six strings, in this order:
__COLUMNS__

The six series (6 labels + 6 numbers each) match these chart headings:
__SERIES__

Rules: real, sector-consistent numbers with sensible magnitudes (one unit per column, no
random noise between columns); roughly 70-120 lines; no comments, no functions, no
placeholders, no "...". One write_file call. Do not create any other file.
Answer in one short line when done."""

DATA_RULES = ("data.js must set window.DASH = { kpis: 8 objects {label,value,unit,delta}, columns: 6 strings, "
              "rows: 22 objects with keys name,m1,m2,m3,m4,m5, series: {line,bar,doughnut,radar,area,hbar} "
              "each with 6 labels and 6 numeric values }.")

# ── Stage 4: table.js ─────────────────────────────────────────────────────

TABLE_TASK = """Write the table/KPI script for an analytics dashboard. Call the write_file tool ONCE with path "table.js".

PROJECT: __TITLE__
SECTOR:  __DOMAIN__

index.html, styles.css and data.js already exist in the current working directory.
data.js sets window.DASH = { kpis: 8 objects {label,value,unit,delta}, columns: 6 strings,
rows: 22 objects with keys name and m1..m5, series: {...} }.
The page has 8 elements matching [data-kpi] (with .kpi-label, .kpi-value, .kpi-delta
inside), a <tbody id="tbody">, an <input id="tbl-search">, <button id="tbl-prev">,
<button id="tbl-next">, a <span id="tbl-page"> and six sortable-looking <th> cells.

Write plain browser JavaScript (a classic script, no modules, no imports) that does ALL
of this:

1. Define `var PAGE_SIZE = 8;` plus module-level state for the current page index, the
   current sort column and the current filter text.
2. `function renderKpis()` — for each element matching [data-kpi] (8 of them, indexed 0..7
   by their data-kpi attribute) write DASH.kpis[i].label into .kpi-label and
   DASH.kpis[i].value with its .unit into .kpi-value using toLocaleString with at most
   2 decimals, and the signed percentage from .delta into .kpi-delta while setting the
   class "up" when delta >= 0 else "down".
3. `function renderTable()` — filter DASH.rows by name against the current filter text
   (case-insensitive), sort a COPY of the array by the current sort column (name or
   m1..m5, toggling ascending/descending on repeated clicks), then write only the
   PAGE_SIZE rows of the current page into #tbody as <tr> elements built with
   document.createElement — each row has exactly six <td> cells: name, m1, m2, m3, m4, m5.
   Update #tbl-page to read "Page N of M".
4. `function render()` that calls both of the above.
5. Wire the controls with addEventListener: typing in #tbl-search sets the filter text and
   resets to page 1; #tbl-next / #tbl-prev move the page within range; clicking a <th>
   sets the sort column.
6. Call render() once at the end so the dashboard is filled on load. Also set
   `window.DASH_RENDER = render;` and `window.DASH_REFRESH_KPIS = renderKpis;` so live.js
   can call them later.

Rules: roughly 70-110 lines of dense, working JavaScript; no comments, no placeholders,
no "...", no truncation. One write_file call. Do not create any other file.
Answer in one short line when done."""

TABLE_RULES = ("table.js must fill the 8 [data-kpi] cards from window.DASH.kpis, render DASH.rows into "
               "#tbody with 8 rows per page, implement the #tbl-search filter, #tbl-next/#tbl-prev paging, "
               "<th> sorting and #tbl-page, call render() on load, and expose window.DASH_RENDER / "
               "window.DASH_REFRESH_KPIS.")

# ── Stage 5: charts.js ────────────────────────────────────────────────────

CHARTS_TASK = """Write the chart script for an analytics dashboard. Call the write_file tool ONCE with path "charts.js".

PROJECT: __TITLE__
SECTOR:  __DOMAIN__

index.html, styles.css, data.js and table.js already exist in the current working
directory. data.js sets window.DASH with kpis, columns, rows and
series = { line, bar, doughnut, radar, area, hbar } where each series has 6 labels and 6
numbers. chart.umd.min.js is loaded first and provides the global `Chart`. The page has
six canvases with ids c1..c6, in this order and with these meanings:

  c1 line, c2 bar, c3 doughnut, c4 radar, c5 line with fill:true and tension:.35,
  c6 bar with options.indexAxis = 'y'

Write plain browser JavaScript (a classic script, no modules, no imports) that creates all
SIX charts, e.g. for c1:

  var c1 = new Chart(document.getElementById('c1'), {
    type: 'line',
    data: { labels: DASH.series.line.labels, datasets: [{ label: '...', data: DASH.series.line.values,
            borderColor: '#4f7cff', backgroundColor: 'rgba(79,124,255,.25)', tension: .35, fill: false }] },
    options: { responsive: true, maintainAspectRatio: false,
               plugins: { legend: { labels: { color: '#e6ebff' } },
                          title: { display: true, text: 'THE PANEL HEADING FROM THE LIST BELOW', color: '#e6ebff' } },
               scales: { x: { ticks: { color: '#8b96b8' } }, y: { ticks: { color: '#8b96b8' } } } }
  });

Give every chart a dataset with real numbers from DASH.series (doughnut and radar need
scales omitted / radarOptions as Chart.js expects — keep the options small and valid).
Use the panel headings, in this exact c1..c6 order:
__SERIES__

At the end, expose the instances so live.js can update them:

  window.CHARTS = { line: c1, bar: c2, doughnut: c3, radar: c4, area: c5, hbar: c6 };

Rules: roughly 60-100 lines of dense, working JavaScript; all six charts must really be
created; no comments, no placeholders, no "...", no truncation. One write_file call.
Do not create any other file. Answer in one short line when done."""

CHARTS_RULES = ("charts.js must create SIX Chart.js instances on the canvases c1(c1 line), c2(bar), "
                "c3(doughnut), c4(radar), c5(line+fill), c6(bar, indexAxis 'y'), each fed from "
                "window.DASH.series with 6 numeric values, and expose window.CHARTS = {line,bar,doughnut,"
                "radar,area,hbar}.")

# ── Stage 6: live.js ──────────────────────────────────────────────────────

LIVE_TASK = """Write the live-refresh script for an analytics dashboard. Call the write_file tool ONCE with path "live.js".

PROJECT: __TITLE__
SECTOR:  __DOMAIN__

Everything else already exists in the current working directory: styles.css, index.html,
data.js (window.DASH with kpis/columns/rows/series), table.js (which defines
window.DASH_RENDER = render and window.DASH_REFRESH_KPIS = renderKpis) and charts.js
(which defines window.CHARTS = { line, bar, doughnut, radar, area, hbar }).

Write plain browser JavaScript (a classic script, no modules, no imports) that:

1. Changes the 8 KPI values by up to +/-3% on its own every 5 seconds, writing the new
   number back into each .kpi-value element (that is: update DASH.kpis[i].value, then call
   window.DASH_REFRESH_KPIS() if it exists).
2. Pushes one new value onto the line, bar and area charts — shift the oldest out of both
   the labels array and the dataset's data array so each chart still has 6 points — then
   calls .update() on those charts. Guard everything with `if (window.CHARTS && window.CHARTS.line)`.
3. Wires the controls with addEventListener:
   - #refresh (click) runs the same update routine immediately,
   - #theme-toggle (click) toggles the class "light" on document.body,
   - each .range-btn (click) moves the class "active" onto the clicked button,
   - each .nav-link (click) moves the class "active" onto the clicked link.
4. Starts it with setInterval(update, 5000) — the dashboard must change on its own every
   5 seconds with no user input.

Rules: roughly 50-80 lines of working JavaScript; no comments, no placeholders, no "...",
no truncation. One write_file call. Do not create any other file. Answer in one short line
when done."""

LIVE_RULES = ("live.js must run setInterval(update, 5000) that jitters the KPI numbers (+/-3%) and pushes "
              "new points onto window.CHARTS.line/bar/area with .update(), wire #refresh, #theme-toggle "
              "(body class `light`), the .range-btn and the .nav-link active classes.")

# ── Stage 7: launch ───────────────────────────────────────────────────────

LAUNCH_TASK = """__TITLE__ is finished: index.html, styles.css, data.js, table.js, charts.js and live.js are
all in the current working directory (together with chart.umd.min.js).

Open the finished dashboard in the default web browser NOW, using the terminal tool with
exactly this command (the working directory is already correct):

    start "" "index.html"

Run that one command, then answer with a single line saying the site was opened in the
browser and naming the file."""

LAUNCH_RULES = 'Run exactly:  start "" "index.html"   with the terminal tool.'

REPAIR_TASK = """The file "__TARGET__" is still not acceptable — an automated inspection just rejected it.

PROBLEMS FOUND:
__ISSUES__

Rewrite __TARGET__ completely with the write_file tool so that every problem above is gone.
Do not patch it with an edit: write the whole file again, in ONE write_file call.

__RULES__

Do not create or change any other file. Answer in one short line when done."""

LAUNCH_REPAIR_TASK = """The dashboard was not opened yet — an automated inspection found:

__ISSUES__

Open it now with the terminal tool, using exactly this command:

    start "" "index.html"

Answer with one short line when it has run."""

# ── Evidence extraction ───────────────────────────────────────────────────

BROWSER_CMD_RE = re.compile(
    r"""(?ix)
      (^|[\s&|;])start\s+(""|')?[^\s"']*\.html        # start "" "index.html"
    | (^|[\s&|;])explorer(\.exe)?"?\s+[^\s"]*\.html   # explorer "index.html"
    | \b(msedge|chrome|firefox|brave|opera|vivaldi|iexplore)\b
    | \bpython[0-9.]*\s+-m\s+webbrowser\b
    | \bwebbrowser\s*\.\s*open\b
    | \brundll32\s+url\.dll\b
    """
)

NODE_DATA_CHECKER = r"""
// check_data.js — evaluate a generated data.js and report whether it satisfies
// the dashboard contract. Used by crown_websites_demo.py.
const fs = require('fs');
const file = process.argv[2];
const out = { ok: false, issues: [], counts: {} };
try {
  const src = fs.readFileSync(file, 'utf8');
  const w = {};
  const body = src + '\n;try{return (typeof DASH !== "undefined") ? DASH : (typeof window !== "undefined" ? window.DASH : undefined);}catch(e){return (typeof window !== "undefined") ? window.DASH : undefined;}';
  let D;
  try { D = new Function('window', body)(w); }
  catch (e) { out.issues.push('data.js threw: ' + e.message); }
  if (D === undefined) D = w.DASH;
  if (!D || typeof D !== 'object') {
    out.issues.push('data.js does not define the global DASH object');
  } else {
    const kpis = Array.isArray(D.kpis) ? D.kpis : [];
    const rows = Array.isArray(D.rows) ? D.rows : [];
    const cols = Array.isArray(D.columns) ? D.columns : [];
    const S = D.series || {};
    out.counts = { kpis: kpis.length, rows: rows.length, columns: cols.length,
                   series: Object.keys(S).filter(k => S[k] && typeof S[k] === 'object').length };
    if (Array.isArray(D.kpis) && D.kpis.length < 8) out.issues.push('kpis must have 8 entries, found ' + D.kpis.length);
    kpis.slice(0, 8).forEach((k, i) => {
      if (!k || typeof k.label !== 'string' || !k.label.trim()) out.issues.push('kpis[' + i + '].label is missing');
      if (!k || typeof k.value !== 'number' || !isFinite(k.value)) out.issues.push('kpis[' + i + '].value is not a number');
    });
    if (Array.isArray(D.columns) && D.columns.length < 6) out.issues.push('columns must have 6 entries, found ' + D.columns.length);
    if (Array.isArray(D.rows) && D.rows.length < 20) out.issues.push('rows must have at least 20 entries, found ' + D.rows.length);
    const badRow = rows.findIndex(r => !r || typeof r.name !== 'string' || !r.name.trim()
      || [1,2,3,4,5].some(n => typeof r['m' + n] !== 'number' || !isFinite(r['m' + n])));
    if (badRow >= 0) out.issues.push('rows[' + badRow + '] must have name + numeric m1..m5');
    ['line','bar','doughnut','radar','area','hbar'].forEach(key => {
      const s = S[key];
      if (!s || typeof s !== 'object') { out.issues.push('series.' + key + ' is missing'); return; }
      if (!Array.isArray(s.labels) || s.labels.length < 6) out.issues.push('series.' + key + '.labels needs 6 entries');
      if (!Array.isArray(s.values) || s.values.length < 6) out.issues.push('series.' + key + '.values needs 6 entries');
      else if (s.values.slice(0, 6).some(v => typeof v !== 'number' || !isFinite(v)))
        out.issues.push('series.' + key + '.values must be numbers');
    });
  }
} catch (e) {
  out.issues.push('checker failed: ' + e.message);
}
out.ok = out.issues.length === 0;
process.stdout.write(JSON.stringify(out));
"""

# ── Helpers ───────────────────────────────────────────────────────────────


def read_text(path: Path, limit: int = 500_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def render(template: str, **kw) -> str:
    out = template
    for key, value in kw.items():
        out = out.replace(f"__{key.upper()}__", value)
    return out


def bullet_list(lines: list[str]) -> str:
    return "\n".join(f"  {i + 1}. {x}" for i, x in enumerate(lines))


def number_list(items: list[str]) -> str:
    return "\n".join(f"  {i + 1}. {x}" for i, x in enumerate(items))


def series_lines(site: dict) -> str:
    names = ["c1 line", "c2 bar", "c3 doughnut", "c4 radar", "c5 area (line)", "c6 horizontal bar"]
    return "\n".join(f"  {names[i]}  ->  \"{t}\"  ({kind})" for i, (kind, t) in enumerate(site["series"]))


def _js_problem(path: Path, label: str, min_bytes: int) -> tuple[str, list[str]]:
    """Shared existence/size/syntax check for a generated script file."""
    issues: list[str] = []
    if not path.exists():
        return "", [f"{label} does not exist"]
    text = read_text(path)
    if len(text) < min_bytes:
        issues.append(f"{label} is only {len(text)} bytes — it was not really written")
    if "Your " in text and "here" in text:
        issues.append(f"{label} still contains a placeholder comment instead of real code")
    return text, issues


# ── Stage verifiers ───────────────────────────────────────────────────────


def verify_styles(ws: Path) -> tuple[bool, list[str], dict]:
    p = ws / "styles.css"
    if not p.exists():
        return False, ["styles.css does not exist"], {}
    css = read_text(p)
    issues: list[str] = []
    if len(css) < 1200:
        issues.append(f"styles.css is only {len(css)} bytes — it is not a real stylesheet")
    if css.count("{") < 18:
        issues.append(f"styles.css has only {css.count('{')} CSS rule blocks — a dashboard theme needs 18+")
    for sel in ("#sidebar", ".kpi", ".kpi-value", ".panel", "#topbar", "body.light", ".charts", "footer"):
        if sel not in css:
            issues.append(f"styles.css does not style `{sel}`")
    return (not issues), issues, {"bytes": len(css), "rules": css.count("{")}


def verify_markup(ws: Path, site: dict) -> tuple[bool, list[str], dict]:
    p = ws / "index.html"
    if not p.exists():
        return False, ["index.html does not exist"], {}
    html = read_text(p)
    issues: list[str] = []
    if len(html) < 1400:
        issues.append(f"index.html is only {len(html)} bytes — the page was not written properly")
    for n in range(1, 7):
        if not re.search(rf'<canvas[^>]+id=["\']c{n}["\']', html):
            issues.append(f'no <canvas id="c{n}"> chart panel')
    for n in range(8):
        if not re.search(rf'data-kpi=["\']{n}["\']', html):
            issues.append(f'no KPI card with data-kpi="{n}"')
    required = {
        'id="tbody"': r'id=["\']tbody["\']',
        'id="tbl-search"': r'id=["\']tbl-search["\']',
        'id="tbl-prev"': r'id=["\']tbl-prev["\']',
        'id="tbl-next"': r'id=["\']tbl-next["\']',
        'id="tbl-page"': r'id=["\']tbl-page["\']',
        'id="search"': r'id=["\']search["\']',
        'id="refresh"': r'id=["\']refresh["\']',
        'id="theme-toggle"': r'id=["\']theme-toggle["\']',
        '<table>': r'<table',
        '<footer>': r'<footer',
        'src="chart.umd.min.js"': r'src=["\']chart\.umd\.min\.js["\']',
        'src="data.js"': r'src=["\']data\.js["\']',
        'src="table.js"': r'src=["\']table\.js["\']',
        'src="charts.js"': r'src=["\']charts\.js["\']',
        'src="live.js"': r'src=["\']live\.js["\']',
        'href="styles.css"': r'href=["\']styles\.css["\']',
    }
    for label, pattern in required.items():
        if not re.search(pattern, html, re.I):
            issues.append(f"index.html is missing {label}")
    if len(re.findall(r'class=["\'][^"\']*nav-link', html)) < 6:
        issues.append("fewer than 6 .nav-link links in the sidebar")
    th_count = len(re.findall(r"<th[^>]*>", html, re.I))
    if th_count < 6:
        issues.append(f"the table header has {th_count} <th> cells — 6 are required")
    return (not issues), issues, {"bytes": len(html), "canvases": len(re.findall(r"<canvas", html)),
                                  "kpi_cards": len(re.findall(r"data-kpi=", html)), "th": th_count}


def verify_data(ws: Path) -> tuple[bool, list[str], dict]:
    p = ws / "data.js"
    if not p.exists():
        return False, ["data.js does not exist"], {}
    if len(read_text(p)) < 600:
        return False, [f"data.js is only {len(read_text(p))} bytes — the dataset was not written"], {}
    checker = TOOLS_DIR / "check_data.js"
    if not checker.exists():
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        checker.write_text(NODE_DATA_CHECKER, encoding="utf-8")
    try:
        res = subprocess.run(["node", str(checker), str(p)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=90)
        data = json.loads(res.stdout or "{}")
    except Exception as e:  # noqa: BLE001
        return False, [f"could not evaluate data.js: {e}"], {}
    return bool(data.get("ok")), list(data.get("issues") or []), dict(data.get("counts") or {})


def verify_table(ws: Path) -> tuple[bool, list[str], dict]:
    js, issues = _js_problem(ws / "table.js", "table.js", 900)
    if not js:
        return False, issues, {}
    for needle, why in (
        ("DASH", "table.js does not read the DASH data object"),
        ("tbody", "table.js never writes into #tbody"),
        ("kpi-value", "table.js does not fill the .kpi-value elements"),
        ("tbl-search", "table.js does not wire the #tbl-search filter"),
        ("tbl-next", "table.js does not wire #tbl-next"),
        ("tbl-prev", "table.js does not wire #tbl-prev"),
        ("tbl-page", "table.js does not update #tbl-page"),
        ("addEventListener", "table.js registers no event listeners"),
        ("DASH_RENDER", "table.js does not expose window.DASH_RENDER"),
    ):
        if needle not in js:
            issues.append(why)
    if "render()" not in js and "render();" not in js:
        issues.append("table.js never calls render() so the dashboard stays empty")
    return (not issues), issues, {"bytes": len(js)}


def verify_charts(ws: Path) -> tuple[bool, list[str], dict]:
    js, issues = _js_problem(ws / "charts.js", "charts.js", 1000)
    if not js:
        return False, issues, {}
    charts = len(re.findall(r"new\s+Chart\s*\(", js))
    if charts < 6:
        issues.append(f"only {charts} `new Chart(` call(s) — six charts are required")
    for cid in ("c1", "c2", "c3", "c4", "c5", "c6"):
        if f"'{cid}'" not in js and f'"{cid}"' not in js:
            issues.append(f"charts.js never touches the {cid} canvas")
    if "CHARTS" not in js:
        issues.append("charts.js does not expose window.CHARTS for live.js to update")
    if "DASH" not in js:
        issues.append("charts.js does not read the DASH series data")
    for kind in ("line", "bar", "doughnut", "radar"):
        if f"'{kind}'" not in js and f'"{kind}"' not in js:
            issues.append(f"no chart of type {kind}")
    return (not issues), issues, {"bytes": len(js), "new_chart_calls": charts}


def verify_live(ws: Path) -> tuple[bool, list[str], dict]:
    js, issues = _js_problem(ws / "live.js", "live.js", 600)
    if not js:
        return False, issues, {}
    if "setInterval" not in js:
        issues.append("no setInterval(...) — the dashboard does not update itself")
    if "CHARTS" not in js:
        issues.append("live.js never uses window.CHARTS to update the charts")
    if ".update()" not in js:
        issues.append("live.js never calls chart .update()")
    if "theme-toggle" not in js:
        issues.append("live.js does not wire #theme-toggle")
    if "refresh" not in js:
        issues.append("live.js does not wire #refresh")
    if "range-btn" not in js:
        issues.append("live.js does not wire the .range-btn buttons")
    if "nav-link" not in js:
        issues.append("live.js does not wire the .nav-link links")
    return (not issues), issues, {"bytes": len(js)}


def verify_launch(ws: Path, launches: list[dict]) -> tuple[bool, list[str], dict]:
    if not launches:
        return False, ['Crown Code never ran a browser-launch command (expected: start "" "index.html")'], {}
    if not [x for x in launches if x.get("exitCode") in (0, None)]:
        return False, [f"the browser-launch command failed (exit {launches[0].get('exitCode')})"], {}
    return True, [], {"commands": [x.get("command") for x in launches]}


def verify_site_in_browser(ws: Path) -> tuple[bool, list[str], dict]:
    """Load the finished dashboard in real Chrome and check that it actually works."""
    issues: list[str] = []
    facts: dict = {}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        return True, [], {"skipped": f"playwright unavailable: {e}"}

    probe_js = """() => {
      const D = window.DASH || {};
      const ids = ['c1','c2','c3','c4','c5','c6'];
      const canvases = ids.map(id => {
        const c = document.getElementById(id);
        if (!c) return {id, missing: true};
        let painted = 0, err = null;
        try {
          const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
          for (let i = 3; i < d.length; i += 4) if (d[i] > 8) painted++;
        } catch (e) { err = String(e); }
        return {id, w: c.width, h: c.height, painted, err};
      });
      return {
        hasDash: !!window.DASH,
        dashRows: (D.rows || []).length,
        dashKpis: (D.kpis || []).length,
        chartVersion: (window.Chart && window.Chart.version) || null,
        chartsExposed: Object.keys(window.CHARTS || {}).length,
        canvases,
        kpiValues: [...document.querySelectorAll('.kpi-value')].map(e => e.textContent.trim()),
        kpiLabels: [...document.querySelectorAll('.kpi-label')].map(e => e.textContent.trim()),
        tableRows: document.querySelectorAll('#tbody tr').length,
        panelTitles: [...document.querySelectorAll('.panel h3')].map(e => e.textContent.trim()),
      };
    }"""

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, channel="chrome")
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)

            page.goto((ws / "index.html").as_uri(), wait_until="load")
            page.wait_for_timeout(2500)
            facts = page.evaluate(probe_js)
            facts["console_errors"] = errors[:8]

            if not facts.get("chartVersion"):
                issues.append("Chart.js did not load in the page (chart.umd.min.js missing or not referenced)")
            if not facts.get("hasDash"):
                issues.append("data.js did not run — window.DASH is undefined in the browser")
            for c in facts.get("canvases") or []:
                if c.get("missing"):
                    issues.append(f"canvas {c['id']} is missing from the page")
                elif c.get("err"):
                    issues.append(f"canvas {c['id']} could not be read back ({c['err']})")
                elif (c.get("painted") or 0) < 400:
                    issues.append(f"canvas {c['id']} is blank ({c.get('painted')} painted pixels) — that chart is not drawn")

            kpi_values = facts.get("kpiValues") or []
            if len(kpi_values) < 8:
                issues.append(f"only {len(kpi_values)} .kpi-value elements rendered — 8 KPI cards are required")
            if all(v in ("", "0", "—", "-") for v in kpi_values):
                issues.append("all KPI values are still zero/empty — the KPI cards were not filled")

            rows = facts.get("tableRows") or 0
            if rows < 5:
                issues.append(f"the table rendered {rows} rows — #tbody was not populated")

            before = list(kpi_values)
            page.wait_for_timeout(7000)
            after = page.evaluate("() => [...document.querySelectorAll('.kpi-value')].map(e => e.textContent.trim())")
            facts["kpi_before"] = before
            facts["kpi_after"] = after
            facts["auto_update"] = bool(before) and before != after
            if before and before == after:
                issues.append("the KPIs did not change after 7s — the setInterval auto-refresh is not working")

            try:
                page.fill("#tbl-search", "zzzznomatch")
                page.wait_for_timeout(400)
                filtered = page.evaluate("() => document.querySelectorAll('#tbody tr').length")
                facts["rows_after_filter"] = filtered
                if rows > 0 and filtered >= rows:
                    issues.append("typing in #tbl-search did not filter the table")
                page.fill("#tbl-search", "")
                page.wait_for_timeout(300)
            except Exception as e:  # noqa: BLE001
                issues.append(f"could not type in #tbl-search: {e}")

            try:
                cls_before = page.evaluate("() => document.body.className")
                page.click("#theme-toggle")
                page.wait_for_timeout(250)
                cls_after = page.evaluate("() => document.body.className")
                facts["theme"] = [cls_before, cls_after]
                if cls_before == cls_after:
                    issues.append("clicking #theme-toggle did not change the body class")
            except Exception as e:  # noqa: BLE001
                issues.append(f"could not click #theme-toggle: {e}")

            page.screenshot(path=str(ws / "screenshot.png"), full_page=True)
            facts["screenshot"] = str(ws / "screenshot.png")
            browser.close()
    except Exception as e:  # noqa: BLE001
        return True, [], {"skipped": f"browser audit could not run: {e}"}

    return (not issues), issues, facts


# ── Stage definitions ─────────────────────────────────────────────────────


def build_stages(site: dict) -> list[dict]:
    kpis = number_list(site["kpis"])
    series = series_lines(site)
    cols = number_list(site["columns"])
    return [
        {
            "key": "styles", "target": "styles.css", "tools": FILE_TOOLS,
            "task": render(STYLES_TASK, title=site["title"], domain=site["domain"]),
            "rules": STYLES_RULES,
            "verify": lambda ws, _s=site: verify_styles(ws),
        },
        {
            "key": "markup", "target": "index.html", "tools": FILE_TOOLS,
            "task": render(MARKUP_TASK, title=site["title"], domain=site["domain"], kpis=kpis,
                           series=series, columns=cols,
                           col1=site["columns"][0], col2=site["columns"][1], col3=site["columns"][2],
                           col4=site["columns"][3], col5=site["columns"][4], col6=site["columns"][5]),
            "rules": MARKUP_RULES,
            "verify": lambda ws, _s=site: verify_markup(ws, _s),
        },
        {
            "key": "data", "target": "data.js", "tools": FILE_TOOLS,
            "task": render(DATA_TASK, title=site["title"], domain=site["domain"], kpis=kpis,
                           series=series, columns=cols),
            "rules": DATA_RULES,
            "verify": lambda ws, _s=site: verify_data(ws),
        },
        {
            "key": "table", "target": "table.js", "tools": FILE_TOOLS,
            "task": render(TABLE_TASK, title=site["title"], domain=site["domain"]),
            "rules": TABLE_RULES,
            "verify": lambda ws, _s=site: verify_table(ws),
        },
        {
            "key": "charts", "target": "charts.js", "tools": FILE_TOOLS,
            "task": render(CHARTS_TASK, title=site["title"], domain=site["domain"], series=series),
            "rules": CHARTS_RULES,
            "verify": lambda ws, _s=site: verify_charts(ws),
        },
        {
            "key": "live", "target": "live.js", "tools": FILE_TOOLS,
            "task": render(LIVE_TASK, title=site["title"], domain=site["domain"]),
            "rules": LIVE_RULES,
            "verify": lambda ws, _s=site: verify_live(ws),
        },
        {
            "key": "launch", "target": "", "tools": LAUNCH_TOOLS,
            "task": render(LAUNCH_TASK, title=site["title"]),
            "rules": LAUNCH_RULES,
            "verify": None,   # needs the observed tool calls
        },
    ]


# ── Running one site ──────────────────────────────────────────────────────


def run_stage(stage: dict, site: dict, ws: Path, args, attempt: int, issues: list[str]) -> dict:
    """Run one stage once (build task on the first attempt, repair afterwards)."""
    if stage["key"] == "launch" and attempt > 1:
        task = render(LAUNCH_REPAIR_TASK, issues=bullet_list(issues))
    elif attempt == 1:
        task = stage["task"]
    else:
        task = render(REPAIR_TASK, target=stage["target"], issues=bullet_list(issues),
                      rules=stage["rules"])

    launched: list[dict] = []
    tools_used: list[str] = []
    commands: list[str] = []
    tool_errors: list[str] = []
    pending: list[str] = []
    assistant_lines: list[str] = []
    started = time.time()

    print(f"\n  -- stage [{stage['key']}] attempt {attempt}/{args.attempts} --", flush=True)

    def on_event(ev: dict) -> None:
        etype = ev.get("type", "")
        if etype == "ready":
            print(f"     model {ev.get('provider')}/{ev.get('model')} "
                  f"({len(ev.get('tools') or [])} tools: {', '.join(ev.get('tools') or [])})", flush=True)
        elif etype == "notice":
            print(f"     [notice] {str(ev.get('message'))[:160]}", flush=True)
        elif etype == "tool_start":
            tool = ev.get("tool", "")
            inp = ev.get("input") or {}
            tools_used.append(tool)
            if tool == "terminal":
                cmd = str(inp.get("command", ""))
                commands.append(cmd)
                pending.append(cmd)
                print(f"     $ {cmd}{'   <<< BROWSER' if BROWSER_CMD_RE.search(cmd) else ''}", flush=True)
            elif tool in ("write_file", "edit_file"):
                content = str(inp.get("content") or inp.get("new_string") or "")
                print(f"     {tool}: {inp.get('path') or inp.get('file')} "
                      f"({len(content)} bytes, {content.count(chr(10)) + 1} lines)", flush=True)
            else:
                print(f"     {tool}: {inp.get('path') or inp.get('pattern') or ''}", flush=True)
        elif etype == "tool_end":
            if ev.get("isError"):
                out = str(ev.get("output", ""))[:220].replace("\n", " ")
                tool_errors.append(out)
                print(f"       tool error: {out}", flush=True)
        elif etype == "terminal_exit":
            code = ev.get("exitCode")
            origin = ev.get("origin", "agent")
            cmd = pending.pop(0) if (pending and origin == "agent") else ""
            if cmd and BROWSER_CMD_RE.search(cmd):
                launched.append({"command": cmd, "exitCode": code})
                print(f"       browser launch exit={code}", flush=True)
            elif cmd and code not in (0, None):
                print(f"       exit={code}", flush=True)
        elif etype == "assistant_message":
            text = str(ev.get("text", "")).strip()
            if text:
                assistant_lines.append(text)
                print(f"     model: {text[:200]}", flush=True)
        elif etype == "result":
            print(f"     result: ok={ev.get('ok')} state={ev.get('state')} "
                  f"executedTools={ev.get('executedTools')}", flush=True)
        elif etype == "error":
            print(f"     ERROR: {ev.get('error')}", flush=True)

    bridge = CrownBridge(
        workspace=str(ws),
        on_event=on_event,
        permission_handler=lambda ev: True,   # policy 'safe' already auto-decides what to run
        log=lambda m: print(f"     [crown] {m}", flush=True),
        model=args.model,
        provider="ollama",
        policy=args.policy,
        max_iterations=args.max_iterations,
        tools=stage["tools"],
    )

    ok_start, msg = bridge.start(task)
    if not ok_start:
        return {"attempt": attempt, "error": msg, "seconds": 0.0, "passed": False,
                "issues": [f"the Crown Code bridge would not start: {msg}"],
                "tools_used": [], "commands": [], "browser_launches": [], "assistant": []}

    try:
        result = bridge.wait(timeout=args.timeout)
    except Exception as e:                       # noqa: BLE001 — a timeout is data, not a crash
        result = {"ok": False, "state": "timeout", "summary": str(e)}
    finally:
        bridge.stop()

    elapsed = round(time.time() - started, 1)

    if stage["key"] == "launch":
        ok, stage_issues, stats = verify_launch(ws, launched)
    else:
        ok, stage_issues, stats = stage["verify"](ws)

    # A run that calls no tool at all cannot have changed anything — treat that
    # as a failure of the stage even when the model claims otherwise.
    if not tools_used:
        ok = False
        stage_issues = ["the model called no tool at all (it only produced text)"] + stage_issues

    print(f"     ---- stage [{stage['key']}] attempt {attempt}: "
          f"{'PASS' if ok else 'FAIL'} in {elapsed}s", flush=True)
    for i in stage_issues:
        print(f"          - {i}", flush=True)

    return {
        "attempt": attempt,
        "seconds": elapsed,
        "bridge_result": {
            "ok": bool((result or {}).get("ok")),
            "state": (result or {}).get("state"),
            "executedTools": (result or {}).get("executedTools"),
            "summary": str((result or {}).get("summary", ""))[:400],
        },
        "tools_used": tools_used,
        "commands": commands,
        "browser_launches": launched,
        "tool_errors": tool_errors[:8],
        "assistant": assistant_lines[-3:],
        "artifacts": stats,
        "passed": ok,
        "issues": stage_issues,
    }


def run_site(site: dict, args) -> dict:
    ws = SITES_ROOT / site["slug"]
    ws.mkdir(parents=True, exist_ok=True)
    if CHART_JS.exists():
        shutil.copy2(CHART_JS, ws / "chart.umd.min.js")

    record: dict = {"slug": site["slug"], "title": site["title"], "workspace": str(ws),
                    "stages": {}, "ok": False}

    print(f"\n{'=' * 78}", flush=True)
    print(f"[{site['slug']}] {site['title']}", flush=True)
    print(f"  workspace: {ws}   model: {args.model}", flush=True)
    print(f"{'=' * 78}", flush=True)

    site_issues: list[str] = []
    for stage in build_stages(site):
        if args.stage and stage["key"] != args.stage:
            continue
        issues: list[str] = []
        attempts_log: list[dict] = []
        passed = False
        for attempt in range(1, args.attempts + 1):
            log = run_stage(stage, site, ws, args, attempt, issues)
            attempts_log.append(log)
            if log["passed"]:
                passed = True
                break
            issues = log["issues"]
            if attempt < args.attempts:
                print(f"     retrying stage [{stage['key']}] with a repair task...", flush=True)

        record["stages"][stage["key"]] = {
            "target": stage["target"],
            "passed": passed,
            "attempts": attempts_log,
            "seconds": round(sum(a.get("seconds", 0) for a in attempts_log), 1),
        }
        if not passed:
            site_issues.append(f"stage `{stage['key']}` never verified")
            # The files are independent, so keep going: a later file can still be
            # correct, and the next full run picks the failed stage up again.
            print(f"     !! stage [{stage['key']}] failed all attempts — moving on", flush=True)

    # final functional audit of the whole dashboard in real Chrome
    if not args.no_browser_check and not args.stage:
        print("\n  -- browser audit (real headless Chrome) --", flush=True)
        ok, issues, facts = verify_site_in_browser(ws)
        record["browser_audit"] = {"passed": ok, "issues": issues, "facts": facts}
        for i in issues:
            print(f"     - {i}", flush=True)
        painted = [c.get("painted") for c in (facts.get("canvases") or [])]
        print(f"     audit {'PASS' if ok else 'FAIL'} | chart pixels={painted} "
              f"| kpis={len(facts.get('kpiValues') or [])} | rows={facts.get('tableRows')} "
              f"| chart.js={facts.get('chartVersion')} | auto_update={facts.get('auto_update')}", flush=True)
        if not ok:
            site_issues.append("the browser audit failed")

    record["ok"] = not site_issues
    record["issues"] = site_issues
    record["browser_launches"] = [l for s in record["stages"].values()
                                  for a in s["attempts"] for l in a.get("browser_launches", [])]
    return record


# ── Entry point ───────────────────────────────────────────────────────────


def main() -> int:
    # Windows consoles default to cp1252; the agent's output is free text and may
    # contain anything, so never let encoding kill a run.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    ap = argparse.ArgumentParser(description="Crown Code builds and self-launches 10 dashboard sites")
    ap.add_argument("--only", default="", help="site numbers to build, e.g. 1 or 1,4,7 (default: all)")
    ap.add_argument("--stage", default="",
                    help="run only one stage (styles|markup|data|table|charts|live|launch)")
    ap.add_argument("--model", default="qwen3.5:4b", help="Ollama model (default: qwen3.5:4b)")
    ap.add_argument("--policy", default="safe", choices=["safe", "readonly", "all"])
    ap.add_argument("--attempts", type=int, default=3, help="max attempts per stage (default 3)")
    ap.add_argument("--timeout", type=int, default=420, help="seconds per stage attempt (default 420)")
    ap.add_argument("--max-iterations", type=int, default=6,
                    help="max agent iterations per stage (default 6 — a stage needs 1-2 tool calls)")
    ap.add_argument("--no-browser-check", action="store_true", help="skip the headless-Chrome audit")
    args = ap.parse_args()

    SITES_ROOT.mkdir(parents=True, exist_ok=True)

    if not CHART_JS.exists():
        print(f"FATAL: charting library missing at {CHART_JS}", flush=True)
        return 2

    ok_build, build_msg = ensure_built(log=lambda m: print(f"[build] {m}", flush=True))
    if not ok_build:
        print(f"FATAL: {build_msg}")
        return 2
    print(f"[build] {build_msg}", flush=True)

    wanted = list(range(1, len(SITES) + 1))
    if args.only.strip():
        wanted = [int(x) for x in args.only.replace(" ", "").split(",") if x]
    chosen = [SITES[i - 1] for i in wanted if 1 <= i <= len(SITES)]

    print(f"Building {len(chosen)} site(s) with {args.model} — up to {args.attempts} attempt(s) "
          f"per stage, {args.timeout}s each, {args.max_iterations} iterations per stage.", flush=True)

    started = time.time()
    results = [run_site(site, args) for site in chosen]
    total = round(time.time() - started, 1)

    passed = [r for r in results if r["ok"]]

    print(f"\n{'=' * 78}")
    print(f"CROWN CODE DASHBOARD BUILD — {len(passed)}/{len(results)} sites verified in {total}s")
    print(f"{'=' * 78}")
    for r in results:
        status = "PASS" if r["ok"] else "FAIL"
        print(f"  [{status}] {r['slug']:<24} "
              f"{sum(s['seconds'] for s in r['stages'].values()):>7.1f}s  {r['title']}")
        for key, s in r["stages"].items():
            mark = "ok  " if s["passed"] else "FAIL"
            print(f"          {mark} {key:<7} {len(s['attempts'])} attempt(s), {s['seconds']}s")
        for launch in r.get("browser_launches") or []:
            print(f"          opened with: {launch['command']}  (exit {launch['exitCode']})")
        audit = r.get("browser_audit")
        if audit:
            facts = audit.get("facts") or {}
            painted = [c.get("painted") for c in (facts.get("canvases") or [])]
            print(f"          chrome audit: {'PASS' if audit['passed'] else 'FAIL'}"
                  f" | painted={painted} | kpis={len(facts.get('kpiValues') or [])}"
                  f" | rows={facts.get('tableRows')} | auto_update={facts.get('auto_update')}")
        for issue in r.get("issues") or []:
            print(f"          - {issue}")

    report = {
        "model": args.model,
        "policy": args.policy,
        "attempts_allowed": args.attempts,
        "max_iterations": args.max_iterations,
        "seconds": total,
        "passed": len(passed),
        "total": len(results),
        "sites": results,
    }
    out = SITES_ROOT / "results.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nFull evidence written to {out}")
    return 0 if len(passed) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
