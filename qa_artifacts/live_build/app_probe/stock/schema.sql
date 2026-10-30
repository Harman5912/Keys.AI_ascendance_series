-- Inventory Overview — schema. Idempotent: safe to run more than once.
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
