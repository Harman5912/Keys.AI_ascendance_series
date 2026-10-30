"""SQLite access for Fleet Operations.

One place opens the database, so every query in the app uses the same file and
the same row factory. The path comes from DB_PATH when set (the verifier points
it at a scratch file), otherwise ./dashboard.db next to this module.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH") or Path(__file__).resolve().with_name("dashboard.db"))
SCHEMA = Path(__file__).resolve().with_name("schema.sql")


def connect() -> sqlite3.Connection:
    """A connection with named columns and foreign keys on."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | os.PathLike | None = None) -> Path:
    """Create the tables if they are not there yet. Returns the db path."""
    global DB_PATH
    if path is not None:
        DB_PATH = Path(path)
    with connect() as conn:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    return DB_PATH


def rows(sql: str, params: tuple = ()) -> list[dict]:
    with connect() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def one(sql: str, params: tuple = ()) -> dict:
    with connect() as conn:
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else {}
