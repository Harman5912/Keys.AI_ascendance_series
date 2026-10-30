"""Synthetic test dataset — exactly the five products specified for Phase 2.

Expected values (checked independently in the tests):
    Keyboard      10 x 1200.00 = 12,000.00
    Mouse          2 x  500.00 =  1,000.00
    Monitor        4 x 8500.00 = 34,000.00
    Laptop Stand   0 x 1500.00 =      0.00
    USB Hub        8 x  900.00 =  7,200.00
    total                      = 54,200.00
Low stock (quantity <= reorder_level): Mouse, Laptop Stand.

Run:  python seed.py            (writes into the configured database)
      python seed.py --reset    (deletes existing rows first)
"""

from __future__ import annotations

import sys

import models
from db import db_path, init_db, session

SEED = [
    ("Keyboard", "Accessories", 10, 1200.00, 3),
    ("Mouse", "Accessories", 2, 500.00, 5),
    ("Monitor", "Displays", 4, 8500.00, 2),
    ("Laptop Stand", "Accessories", 0, 1500.00, 2),
    ("USB Hub", "Connectivity", 8, 900.00, 3),
]


def main(reset: bool = False) -> int:
    init_db()
    if reset:
        with session() as conn:
            conn.execute("DELETE FROM stock_movements")
            conn.execute("DELETE FROM products")
        print("cleared existing rows")
    existing = len(models.list_products())
    if existing and not reset:
        print(f"{existing} products already present — nothing to seed "
              f"(use --reset to replace)")
        return 0
    for name, category, quantity, price, reorder in SEED:
        models.create_product({
            "name": name,
            "category": category,
            "quantity": quantity,
            "unit_price": price,
            "reorder_level": reorder,
        })
    stats = models.dashboard()
    print(f"seeded {stats['product_count']} products into {db_path()}")
    print(f"  total inventory value: {stats['total_value']:,.2f}")
    print(f"  low stock: {stats['low_stock_count']} "
          f"({', '.join(p['name'] for p in stats['low_stock'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--reset" in sys.argv))
