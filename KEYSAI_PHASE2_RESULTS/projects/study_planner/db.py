"""Database layer — connection handling and schema initialisation.

Every connection sets PRAGMA foreign_keys = ON: SQLite does NOT enforce
foreign keys by default, which is the usual way an "integrity" requirement
quietly fails. Parameterised SQL only; no string-built queries anywhere.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")
DEFAULT_DB = Path(__file__).with_name("study_planner.db")
ENV_VAR = "STUDY_PLANNER_DB"


def db_path() -> Path:
    """Active database file (overridable via STUDY_PLANNER_DB)."""
    env = os.environ.get(ENV_VAR)
    return Path(env) if env else DEFAULT_DB


def connect(path: str | os.PathLike | None = None) -> sqlite3.Connection:
    """Open a connection with row dictionaries and FK enforcement."""
    target = Path(path) if path is not None else db_path()
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | os.PathLike | None = None) -> Path:
    """Create tables/indexes if missing. Idempotent.

    NOTE: `with sqlite3.connect(...) as conn` only ends the TRANSACTION — it
    never closes the connection. On Windows that leaves the file locked and
    temporary databases undeletable, so this function closes explicitly.
    """
    target = Path(path) if path is not None else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(target)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return target


def available(path: str | os.PathLike | None = None) -> bool:
    """True when the database file exists (used by the error path when the
    database is missing rather than merely locked)."""
    target = Path(path) if path is not None else db_path()
    return target.exists()
