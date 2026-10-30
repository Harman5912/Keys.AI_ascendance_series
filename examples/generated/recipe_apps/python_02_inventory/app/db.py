"""SQLite storage for Stock Control.

All SQL lives here so the window never builds a query string from user input:
`search()` takes a parameter, not concatenated text.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("APP_DB") or (Path(__file__).resolve().parent.parent / "app.db"))

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

SAMPLES = [["Hex bolts M8 (100)", "Hardware", 340, 12.4], ["Shipping boxes", "Packaging", 8, 1.15], ["Gloves (pair)", "Consumables", 24, 3.8], ["Drive belt", "Spares", 2, 46.0], ["Torque wrench", "Tools", 5, 89.0], ["Tape roll", "Packaging", 0, 2.2]]


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
            "SELECT COUNT(*) AS count, COALESCE(SUM(quantity * amount), 0) AS total"
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
