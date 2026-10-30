"""Data access for the inventory system.

Every query here is parameterised. No SQL string is ever built from user input,
which is what makes the SQL-injection tests pass by construction rather than by
escaping.
"""

from __future__ import annotations

import datetime as dt

from db import session


class NotFound(Exception):
    """No product with that id."""


class InsufficientStock(Exception):
    """A movement would take the quantity below zero."""

    def __init__(self, product_id: int, available: int, requested: int):
        self.product_id = product_id
        self.available = available
        self.requested = requested
        super().__init__(
            f"movement of {requested} would leave a negative quantity "
            f"(available {available})")


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _row_to_product(row) -> dict:
    product = dict(row)
    product["unit_price"] = round(float(product["unit_price"]), 2)
    product["inventory_value"] = round(
        product["quantity"] * product["unit_price"], 2)
    product["low_stock"] = product["quantity"] <= product["reorder_level"]
    return product


_SELECT = ("SELECT id, name, category, quantity, unit_price, reorder_level,"
           "       created_at, updated_at FROM products")


def list_products(search: str = "", category: str = "") -> list[dict]:
    sql = _SELECT + " WHERE 1 = 1"
    params: list = []
    if search:
        # Parameterised LIKE: hostile text is matched literally, never executed.
        sql += " AND (name LIKE ? OR category LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY id"
    with session() as conn:
        return [_row_to_product(r) for r in conn.execute(sql, params).fetchall()]


def get_product(product_id: int) -> dict:
    with session() as conn:
        row = conn.execute(_SELECT + " WHERE id = ?", (product_id,)).fetchone()
    if row is None:
        raise NotFound(f"product {product_id} not found")
    return _row_to_product(row)


def create_product(data: dict) -> dict:
    now = _now()
    with session() as conn:
        cursor = conn.execute(
            "INSERT INTO products (name, category, quantity, unit_price,"
            " reorder_level, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (data["name"], data["category"], data.get("quantity", 0),
             round(float(data["unit_price"]), 2), data.get("reorder_level", 0),
             now, now))
        new_id = int(cursor.lastrowid)
        if data.get("quantity"):
            conn.execute(
                "INSERT INTO stock_movements (product_id, movement_type,"
                " quantity_change, reason, created_at) VALUES (?, 'in', ?, ?, ?)",
                (new_id, data["quantity"], "opening balance", now))
    return get_product(new_id)


def update_product(product_id: int, data: dict) -> dict:
    if not data:
        return get_product(product_id)
    assignments = ", ".join(f"{field} = ?" for field in data)
    params = list(data.values()) + [_now(), product_id]
    with session() as conn:
        cursor = conn.execute(
            f"UPDATE products SET {assignments}, updated_at = ? WHERE id = ?",
            params)
        if cursor.rowcount == 0:
            raise NotFound(f"product {product_id} not found")
    return get_product(product_id)


def delete_product(product_id: int) -> None:
    with session() as conn:
        cursor = conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        if cursor.rowcount == 0:
            raise NotFound(f"product {product_id} not found")


def list_movements(product_id: int) -> list[dict]:
    with session() as conn:
        exists = conn.execute("SELECT 1 FROM products WHERE id = ?",
                              (product_id,)).fetchone()
        if exists is None:
            raise NotFound(f"product {product_id} not found")
        rows = conn.execute(
            "SELECT id, product_id, movement_type, quantity_change, reason,"
            " created_at FROM stock_movements WHERE product_id = ?"
            " ORDER BY id DESC", (product_id,)).fetchall()
    return [dict(r) for r in rows]


def record_movement(product_id: int, data: dict) -> dict:
    """Apply a movement and update the quantity in one transaction."""
    change = int(data["quantity_change"])
    now = _now()
    with session() as conn:
        row = conn.execute("SELECT quantity FROM products WHERE id = ?",
                           (product_id,)).fetchone()
        if row is None:
            raise NotFound(f"product {product_id} not found")
        available = int(row["quantity"])
        resulting = available + change
        if resulting < 0:
            raise InsufficientStock(product_id, available, change)
        conn.execute(
            "UPDATE products SET quantity = ?, updated_at = ? WHERE id = ?",
            (resulting, now, product_id))
        cursor = conn.execute(
            "INSERT INTO stock_movements (product_id, movement_type,"
            " quantity_change, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (product_id, data["movement_type"], change, data.get("reason", ""),
             now))
        movement_id = int(cursor.lastrowid)
    return {"id": movement_id, "product_id": product_id,
            "movement_type": data["movement_type"], "quantity_change": change,
            "reason": data.get("reason", ""), "created_at": now,
            "quantity_after": resulting}


def dashboard() -> dict:
    """Every figure is computed by SQL over the real rows."""
    with session() as conn:
        totals = conn.execute(
            "SELECT COUNT(*) AS product_count,"
            "       COALESCE(SUM(quantity), 0) AS total_units,"
            "       COALESCE(SUM(quantity * unit_price), 0) AS total_value,"
            "       COALESCE(SUM(CASE WHEN quantity <= reorder_level"
            "                         THEN 1 ELSE 0 END), 0) AS low_stock_count,"
            "       COALESCE(SUM(CASE WHEN quantity = 0 THEN 1 ELSE 0 END), 0)"
            "           AS out_of_stock_count"
            "  FROM products").fetchone()
        low = conn.execute(
            _SELECT + " WHERE quantity <= reorder_level ORDER BY quantity, name"
        ).fetchall()
        by_category = conn.execute(
            "SELECT category, COUNT(*) AS products,"
            "       COALESCE(SUM(quantity), 0) AS units,"
            "       COALESCE(SUM(quantity * unit_price), 0) AS value"
            "  FROM products GROUP BY category ORDER BY value DESC").fetchall()
    return {
        "product_count": int(totals["product_count"]),
        "total_units": int(totals["total_units"]),
        "total_value": round(float(totals["total_value"]), 2),
        "low_stock_count": int(totals["low_stock_count"]),
        "out_of_stock_count": int(totals["out_of_stock_count"]),
        "low_stock": [_row_to_product(r) for r in low],
        "by_category": [dict(r) for r in by_category],
    }
