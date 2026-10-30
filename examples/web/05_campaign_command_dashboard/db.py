"""Campaign Command — marketing department BI dashboard data layer.

Campaign performance and the work behind it (tasks) live in the same database,
so the dashboard can answer "which channel earns, and what is blocking it".
MySQL when reachable (credentials from .env), SQLite otherwise; the UI names
whichever backend answered.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SQLITE_PATH = HERE / "campaign_command.sqlite3"

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    channel     TEXT NOT NULL,
    spend       REAL NOT NULL,
    revenue     REAL NOT NULL,
    impressions INTEGER NOT NULL,
    clicks      INTEGER NOT NULL,
    day         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    campaign    TEXT NOT NULL,
    owner       TEXT NOT NULL,
    status      TEXT NOT NULL,
    due_day     TEXT NOT NULL,
    progress    INTEGER NOT NULL
);
"""

MYSQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(120) NOT NULL,
    channel     VARCHAR(40)  NOT NULL,
    spend       DECIMAL(12,2) NOT NULL,
    revenue     DECIMAL(12,2) NOT NULL,
    impressions BIGINT NOT NULL,
    clicks      BIGINT NOT NULL,
    day         DATE NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    title       VARCHAR(160) NOT NULL,
    campaign    VARCHAR(120) NOT NULL,
    owner       VARCHAR(60)  NOT NULL,
    status      VARCHAR(20)  NOT NULL,
    due_day     DATE NOT NULL,
    progress    TINYINT NOT NULL
);
"""

CHANNELS = ("Paid search", "Paid social", "Email", "Organic", "Events")
OWNERS = ("Riya", "Tom", "Aisha", "Ben")
TASKS = [
    ("Refresh Q4 paid search ad copy", "Always-on search", "Riya", "doing", 4, 65),
    ("Approve autumn social creative", "Autumn social", "Aisha", "todo", 2, 15),
    ("Fix conversion tracking on /pricing", "Always-on search", "Tom", "doing", 1, 80),
    ("Draft newsletter: harvest drop", "Harvest email", "Ben", "todo", 6, 0),
    ("Pull event leads into the CRM", "September events", "Riya", "done", -1, 100),
    ("Reconcile agency invoice", "Autumn social", "Tom", "done", -3, 100),
    ("Set up A/B test on hero CTA", "Harvest email", "Aisha", "todo", 8, 10),
    ("Monthly channel review deck", "Always-on search", "Ben", "doing", 3, 40),
]


def _env(name: str, default: str = "") -> str:
    if os.environ.get(name):
        return os.environ[name].strip()
    env_file = HERE / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return default


def _mysql():
    try:
        import pymysql
    except ImportError:
        return None
    if not _env("DB_PASSWORD"):
        return None
    try:
        return pymysql.connect(
            host=_env("DB_HOST", "127.0.0.1"), port=int(_env("DB_PORT", "3306")),
            user=_env("DB_USER", "root"), password=_env("DB_PASSWORD"),
            database=_env("DB_NAME", "campaign_command"), autocommit=True,
            cursorclass=pymysql.cursors.DictCursor)
    except Exception:
        return None


def backend_name() -> str:
    return "mysql" if _mysql() else "sqlite"


def connect():
    conn = _mysql()
    if conn is not None:
        return conn
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SQLITE_SCHEMA)
    return conn


def rows(conn, sql: str, params=()) -> list[dict]:
    cur = conn.cursor()
    cur.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def q(sql: str, params=()) -> list[dict]:
    conn = connect()
    try:
        return rows(conn, sql, params)
    finally:
        conn.close()


def seed(force: bool = False) -> int:
    conn = connect()
    try:
        if not force and rows(conn, "SELECT 1 FROM campaigns LIMIT 1"):
            return 0
        cur = conn.cursor()
        cur.execute("DELETE FROM campaigns")
        cur.execute("DELETE FROM tasks")
        today = date.today()
        payload = []
        for d in range(28):
            day = today - timedelta(days=27 - d)
            for i, channel in enumerate(CHANNELS):
                spend = round(180 + i * 95 + (d % 6) * 42 + (d * 7) % 55, 2)
                roas = 2.4 + (i * 0.35) + ((d % 5) - 2) * 0.12
                payload.append((f"{channel} · week {(d // 7) + 1}", channel,
                                spend, round(spend * roas, 2),
                                42000 + i * 8000 + d * 310, 1300 + i * 260 + d * 21,
                                day.isoformat()))
        placeholder = "%s" if backend_name() == "mysql" else "?"
        cur.executemany(
            f"INSERT INTO campaigns (name, channel, spend, revenue, impressions, clicks, day) "
            f"VALUES ({','.join([placeholder] * 7)})", payload)
        task_rows = [(t[0], t[1], t[2], t[3], (today + timedelta(days=t[4])).isoformat(), t[5])
                     for t in TASKS]
        cur.executemany(
            f"INSERT INTO tasks (title, campaign, owner, status, due_day, progress) "
            f"VALUES ({','.join([placeholder] * 6)})", task_rows)
        conn.commit()
        return len(payload) + len(task_rows)
    finally:
        conn.close()


def overview() -> dict:
    totals = q("""
        SELECT SUM(spend) AS spend, SUM(revenue) AS revenue,
               SUM(impressions) AS impressions, SUM(clicks) AS clicks
        FROM campaigns WHERE day >= date('now', '-30 day')
    """ if backend_name() == "sqlite" else """
        SELECT SUM(spend) AS spend, SUM(revenue) AS revenue,
               SUM(impressions) AS impressions, SUM(clicks) AS clicks
        FROM campaigns WHERE day >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
    """)[0]
    spend = float(totals.get("spend") or 0)
    revenue = float(totals.get("revenue") or 0)
    clicks = int(totals.get("clicks") or 0)
    impressions = int(totals.get("impressions") or 0)

    channels = q("""
        SELECT channel, SUM(spend) AS spend, SUM(revenue) AS revenue,
               SUM(clicks) AS clicks, SUM(impressions) AS impressions
        FROM campaigns GROUP BY channel ORDER BY revenue DESC
    """)
    for c in channels:
        c["roas"] = round(float(c["revenue"]) / float(c["spend"] or 1), 2)
        c["cpc"] = round(float(c["spend"]) / float(c["clicks"] or 1), 2)

    trend = q("""
        SELECT day, SUM(spend) AS spend, SUM(revenue) AS revenue
        FROM campaigns GROUP BY day ORDER BY day
    """)
    funnel = [
        {"stage": "Impressions", "value": impressions},
        {"stage": "Clicks", "value": clicks},
        {"stage": "Sessions", "value": int(clicks * 0.72)},
        {"stage": "Leads", "value": int(clicks * 0.11)},
        {"stage": "Customers", "value": int(clicks * 0.021)},
    ]
    return {
        "backend": backend_name(),
        "kpis": {
            "spend": round(spend, 2), "revenue": round(revenue, 2),
            "roas": round(revenue / spend, 2) if spend else 0,
            "ctr": round(clicks / impressions * 100, 2) if impressions else 0,
        },
        "channels": channels, "trend": trend, "funnel": funnel,
    }


def tasks() -> list[dict]:
    return q("SELECT * FROM tasks ORDER BY due_day")


def move_task(task_id: int, status: str) -> dict:
    if status not in ("todo", "doing", "done"):
        raise ValueError("status must be todo, doing or done")
    conn = connect()
    try:
        cur = conn.cursor()
        placeholder = "%s" if backend_name() == "mysql" else "?"
        progress = 100 if status == "done" else 0 if status == "todo" else 50
        cur.execute(f"UPDATE tasks SET status = {placeholder}, progress = {placeholder} "
                    f"WHERE id = {placeholder}", (status, progress, int(task_id)))
        conn.commit()
        return {"id": int(task_id), "status": status, "progress": progress}
    finally:
        conn.close()
