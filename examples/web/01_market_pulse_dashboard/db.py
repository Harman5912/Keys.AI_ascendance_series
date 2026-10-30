"""Market Pulse — Flask dashboard demo (MySQL, with a SQLite fallback).

The dashboard reads its numbers from a database through real JSON endpoints.
Nothing is hardcoded in the front end: if the table is empty, the charts show an
empty state.

MySQL credentials come from .env (DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME).
When PyMySQL or the server is unavailable the same queries run against a local
SQLite file so the demo still starts — the banner in the UI says which backend
is live, so nobody is misled about what they are looking at.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SQLITE_PATH = HERE / "market_pulse.sqlite3"


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    env_file = HERE / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return default


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_ticks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol    TEXT    NOT NULL,
    day       TEXT    NOT NULL,
    price     REAL    NOT NULL,
    volume    REAL    NOT NULL,
    UNIQUE (symbol, day)
);
"""

MYSQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_ticks (
    id      BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol  VARCHAR(16) NOT NULL,
    day     DATE NOT NULL,
    price   DECIMAL(14, 4) NOT NULL,
    volume  BIGINT NOT NULL,
    UNIQUE KEY uniq_symbol_day (symbol, day)
);
"""

SYMBOLS = ("BTC", "ETH", "SOL")


def _mysql():
    try:
        import pymysql  # noqa: F401
    except ImportError:
        return None
    if not _env("DB_PASSWORD"):
        return None
    try:
        import pymysql
        return pymysql.connect(
            host=_env("DB_HOST", "127.0.0.1"), port=int(_env("DB_PORT", "3306")),
            user=_env("DB_USER", "root"), password=_env("DB_PASSWORD"),
            database=_env("DB_NAME", "market_pulse"), autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )
    except Exception:
        return None


def backend_name() -> str:
    return "mysql" if _mysql() else "sqlite"


def connect():
    """One connection for the current request."""
    conn = _mysql()
    if conn is not None:
        return conn
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SQLITE_SCHEMA)
    return conn


def _rows(conn, sql: str, params=()) -> list[dict]:
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    return [dict(r) for r in rows]


def empty() -> bool:
    conn = connect()
    try:
        return not _rows(conn, "SELECT 1 FROM market_ticks LIMIT 1")
    finally:
        conn.close()


def seed(force: bool = False) -> int:
    """Insert clearly-labelled sample rows. Re-runnable."""
    conn = connect()
    try:
        if not force and not empty():
            return 0
        rows = []
        today = date.today()
        base = {"BTC": 61000.0, "ETH": 3300.0, "SOL": 145.0}
        for i in range(30):
            day = today - timedelta(days=29 - i)
            for j, symbol in enumerate(SYMBOLS):
                drift = 1 + (0.012 * ((i + j) % 7 - 3) + 0.004 * i)
                rows.append((symbol, day.isoformat(),
                             round(base[symbol] * drift, 2),
                             int(base[symbol] * 120 * (1 + (i % 5) / 10))))
        cur = conn.cursor()
        if backend_name() == "mysql":
            cur.execute("DELETE FROM market_ticks WHERE 1=1")
            cur.executemany(
                "INSERT INTO market_ticks (symbol, day, price, volume) VALUES (%s,%s,%s,%s)",
                rows)
        else:
            cur.execute("DELETE FROM market_ticks")
            cur.executemany(
                "INSERT INTO market_ticks (symbol, day, price, volume) VALUES (?,?,?,?)", rows)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def summary() -> list[dict]:
    conn = connect()
    try:
        if backend_name() == "mysql":
            sql = """
                SELECT t.symbol, t.day, t.price, t.volume,
                       ROUND((t.price - f.price) / f.price * 100, 2) AS change_pct
                FROM market_ticks t
                JOIN (SELECT symbol, MIN(day) AS first_day FROM market_ticks GROUP BY symbol) x
                  ON x.symbol = t.symbol
                JOIN market_ticks f ON f.symbol = x.symbol AND f.day = x.first_day
                WHERE t.day = (SELECT MAX(day) FROM market_ticks m2 WHERE m2.symbol = t.symbol)
                ORDER BY t.symbol
            """
        else:
            sql = """
                WITH bounds AS (SELECT symbol, MIN(day) AS first_day, MAX(day) AS last_day
                                FROM market_ticks GROUP BY symbol)
                SELECT t.symbol, t.day, t.price, t.volume,
                       ROUND((t.price - f.price) / f.price * 100, 2) AS change_pct
                FROM market_ticks t
                JOIN bounds b ON b.symbol = t.symbol AND b.last_day = t.day
                JOIN market_ticks f ON f.symbol = b.symbol AND f.day = b.first_day
                ORDER BY t.symbol
            """
        return _rows(conn, sql)
    finally:
        conn.close()


def series(symbol: str, days: int = 30) -> list[dict]:
    conn = connect()
    try:
        sql = ("SELECT day, price, volume FROM market_ticks WHERE symbol = "
               + ("%s" if backend_name() == "mysql" else "?")
               + " ORDER BY day DESC LIMIT "
               + ("%s" if backend_name() == "mysql" else "?"))
        rows = _rows(conn, sql, (symbol.upper(), int(days)))
        return list(reversed(rows))
    finally:
        conn.close()


def volume_by_day(days: int = 14) -> list[dict]:
    conn = connect()
    try:
        sql = ("SELECT day, SUM(volume) AS volume FROM market_ticks GROUP BY day "
               "ORDER BY day DESC LIMIT "
               + ("%s" if backend_name() == "mysql" else "?"))
        rows = _rows(conn, sql, (int(days),))
        return list(reversed(rows))
    finally:
        conn.close()
