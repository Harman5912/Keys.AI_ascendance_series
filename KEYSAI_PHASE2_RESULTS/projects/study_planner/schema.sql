-- KeysAI_Test_Study_Planner — relational schema
-- Referential integrity is enforced by SQLite foreign keys; db.py turns
-- PRAGMA foreign_keys ON for every connection, so an orphan row cannot be
-- written by any path (see tests/test_api.py::TestRelationships).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE,
    email      TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS subjects (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT    NOT NULL,
    color      TEXT    NOT NULL DEFAULT '#d4a017',
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS study_tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id)      ON DELETE CASCADE,
    subject_id   INTEGER NOT NULL REFERENCES subjects(id)   ON DELETE CASCADE,
    title        TEXT    NOT NULL,
    notes        TEXT    NOT NULL DEFAULT '',
    due_date     TEXT,                      -- ISO-8601 date (YYYY-MM-DD) or NULL
    priority     TEXT    NOT NULL DEFAULT 'medium'
                 CHECK (priority IN ('low', 'medium', 'high')),
    status       TEXT    NOT NULL DEFAULT 'todo'
                 CHECK (status  IN ('todo', 'in_progress', 'done')),
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS study_sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id)     ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id)  ON DELETE CASCADE,
    task_id    INTEGER          REFERENCES study_tasks(id) ON DELETE SET NULL,
    minutes    INTEGER NOT NULL CHECK (minutes > 0 AND minutes <= 600),
    studied_on TEXT    NOT NULL,             -- ISO-8601 date
    notes      TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_subject  ON study_tasks(subject_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status   ON study_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due      ON study_tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_sessions_subj  ON study_sessions(subject_id);
