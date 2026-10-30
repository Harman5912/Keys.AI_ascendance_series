"""Seed Inventory Overview with clearly-labelled SAMPLE rows.

Run once before starting the server:   python seed.py
It is re-runnable: it clears the events table and writes the same rows again,
so the dashboard always tells the same story on a demo machine.

Nothing here is real data. The footer of the page says so too.
"""

from __future__ import annotations

import datetime as dt
import json
import random

from db import DB_PATH, connect, init_db, session

DAYS = 180
SEED_VALUE = 7
LABELS = json.loads("""["SKU-1042", "SKU-2210", "SKU-3390", "SKU-4481", "SKU-5502", "SKU-6613"]""")
CATEGORIES = json.loads("""["Electronics", "Hardware", "Packaging", "Consumables", "Spares"]""")
STATUSES = json.loads("""["open", "closed", "open", "overdue", "closed"]""")
BASE_AMOUNT = 120


def build_rows() -> list[tuple]:
    rng = random.Random(SEED_VALUE)
    today = dt.date.today()
    out = []
    for i in range(DAYS):
        day = today - dt.timedelta(days=DAYS - 1 - i)
        for _ in range(rng.randint(1, 3)):
            category = rng.choice(CATEGORIES)
            weight = CATEGORIES.index(category) + 1
            quantity = rng.randint(1, 12)
            amount = round(BASE_AMOUNT * weight * rng.uniform(0.35, 1.65), 2)
            out.append((
                day.isoformat(),
                rng.choice(LABELS),
                category,
                quantity,
                amount,
                rng.choice(STATUSES),
                "sample row",
            ))
    return out


def main() -> int:
    init_db()
    data = build_rows()
    with session() as conn:
        conn.execute("DELETE FROM events")
        conn.executemany(
            "INSERT INTO events (occurred_on, label, category, quantity, amount,"
            " status, note) VALUES (?, ?, ?, ?, ?, ?, ?)", data)
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        categories = conn.execute(
            "SELECT COUNT(DISTINCT category) FROM events").fetchone()[0]
    print(f"seeded {total} sample rows across {categories} categories into "
          f"{DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
