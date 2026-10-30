"""Ledger Lite — data layer for the PyQt6 desktop example.

MySQL first (credentials from .env), SQLite fallback so the app always starts.
The status bar says which one is live.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SQLITE_PATH = HERE / "ledger_lite.sqlite3"

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    title   TEXT NOT NULL,
    body    TEXT NOT NULL DEFAULT '',
    status  TEXT NOT NULL DEFAULT 'open',
    created TEXT NOT NULL
);
"""

MYSQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id      BIGINT AUTO_INCREMENT PRIMARY KEY,
    title   VARCHAR(140) NOT NULL,
    body    TEXT NOT NULL,
    status  VARCHAR(16) NOT NULL DEFAULT 'open',
    created DATE NOT NULL
);
"""


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
            database=_env("DB_NAME", "ledger_lite"), autocommit=True,
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


def list_notes(search: str = "") -> list[dict]:
    conn = connect()
    try:
        cur = conn.cursor()
        like = "%" + (search or "").strip() + "%"
        if search:
            cur.execute("SELECT id, title, body, status, created FROM notes "
                        "WHERE title LIKE %s OR body LIKE %s ORDER BY id DESC", (like, like)) \
                if backend_name() == "mysql" else \
                cur.execute("SELECT id, title, body, status, created FROM notes "
                            "WHERE title LIKE ? OR body LIKE ? ORDER BY id DESC", (like, like))
        else:
            cur.execute("SELECT id, title, body, status, created FROM notes ORDER BY id DESC")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def add_note(title: str, body: str) -> int:
    if not title.strip():
        raise ValueError("title is required")
    conn = connect()
    try:
        cur = conn.cursor()
        if backend_name() == "mysql":
            cur.execute("INSERT INTO notes (title, body, status, created) "
                        "VALUES (%s, %s, 'open', CURDATE())", (title.strip(), body.strip()))
        else:
            cur.execute("INSERT INTO notes (title, body, status, created) "
                        "VALUES (?, ?, 'open', date('now'))", (title.strip(), body.strip()))
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def toggle_status(note_id: int) -> str:
    conn = connect()
    try:
        cur = conn.cursor()
        placeholder = "%s" if backend_name() == "mysql" else "?"
        cur.execute(f"UPDATE notes SET status = CASE WHEN status = 'open' THEN 'done' "
                    f"ELSE 'open' END WHERE id = {placeholder}", (int(note_id),))
        conn.commit()
        cur.execute(f"SELECT status FROM notes WHERE id = {placeholder}", (int(note_id),))
        row = cur.fetchone()
        return dict(row)["status"] if row else ""
    finally:
        conn.close()


def seed() -> int:
    conn = connect()
    try:
        if conn.cursor().execute("SELECT COUNT(*) FROM notes").fetchone()[0]:
            return 0
    finally:
        conn.close()
    for title, body in (
        ("Invoice 1042 — Northwind", "Chase the outstanding £840 before Friday."),
        ("Renew domain keysai.app", "Renewal is due in eleven days; card on file."),
        ("Quarterly VAT return", "Numbers pulled from the ledger; needs a second look."),
    ):
        add_note(title, body)
    return 3
