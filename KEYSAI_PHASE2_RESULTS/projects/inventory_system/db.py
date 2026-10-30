"""Database access for the inventory system.

One place opens the SQLite file. Every caller goes through `session()`, which
commits on success, rolls back on failure and always closes the handle — a
leaked handle on Windows keeps the file locked and makes it undeletable.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEFAULT_DB = BASE / "inventory.db"
SCHEMA = BASE / "schema.sql"


def db_path() -> Path:
    """The database file in use. INVENTORY_DB overrides it (tests rely on that)."""
    return Path(os.environ.get("INVENTORY_DB") or DEFAULT_DB)


def connect(path: str | os.PathLike | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session(path: str | os.PathLike | None = None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: str | os.PathLike | None = None) -> Path:
    """Create the tables if they are absent. Idempotent. Returns the file path."""
    target = Path(path) if path else db_path()
    with session(target) as conn:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    return target
