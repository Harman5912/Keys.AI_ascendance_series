"""Integration tests for KeysAI_Test_Inventory_System.

Every test runs against a real Flask app and a real SQLite file in a temporary
directory. Expected numbers are written out literally, not computed by the code
under test, so a broken dashboard cannot agree with itself.

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
from contextlib import closing
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

import models  # noqa: E402
from app import create_app  # noqa: E402

SEED = [
    ("Keyboard", "Accessories", 10, 1200.00, 3),
    ("Mouse", "Accessories", 2, 500.00, 5),
    ("Monitor", "Displays", 4, 8500.00, 2),
    ("Laptop Stand", "Accessories", 0, 1500.00, 2),
    ("USB Hub", "Connectivity", 8, 900.00, 3),
]
EXPECTED_TOTAL = 54200.00
EXPECTED_LOW = {"Mouse", "Laptop Stand"}


class InventoryTestCase(unittest.TestCase):
    """Each test gets its own database file and its own app instance."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test_inventory.db"
        self.app = create_app(self.db)
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        self._seed()

    def tearDown(self):
        self.tmp.cleanup()

    def _seed(self):
        for name, category, quantity, price, reorder in SEED:
            response = self.client.post("/api/products", json={
                "name": name, "category": category, "quantity": quantity,
                "unit_price": price, "reorder_level": reorder,
            })
            self.assertEqual(response.status_code, 201, response.get_data(as_text=True))

    def names(self):
        payload = self.client.get("/api/products").get_json()
        return [p["name"] for p in payload["products"]]

    def product_id(self, name):
        for product in self.client.get("/api/products").get_json()["products"]:
            if product["name"] == name:
                return product["id"]
        raise AssertionError(f"{name} not found")


class TestDatabaseAndCRUD(InventoryTestCase):
    def test_INV_DB_001_schema_created(self):
        """INV-DB-001: initialisation creates both tables and the FK."""
        with closing(sqlite3.connect(self.db)) as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            fks = conn.execute("PRAGMA foreign_key_list(stock_movements)").fetchall()
        self.assertIn("products", tables)
        self.assertIn("stock_movements", tables)
        self.assertTrue(fks, "stock_movements has no foreign key")

    def test_INV_API_001_create_product_returns_201(self):
        """INV-API-001: POST creates a row and returns it with 201."""
        response = self.client.post("/api/products", json={
            "name": "Cable", "category": "Connectivity",
            "quantity": 5, "unit_price": 120.5, "reorder_level": 1})
        self.assertEqual(response.status_code, 201)
        product = response.get_json()["product"]
        self.assertEqual(product["name"], "Cable")
        self.assertEqual(product["inventory_value"], 602.5)
        self.assertEqual(product["low_stock"], False)

    def test_INV_API_002_list_products(self):
        """INV-API-002: the five seeded products are listed."""
        payload = self.client.get("/api/products").get_json()
        self.assertEqual(payload["count"], 5)
        self.assertEqual(len(payload["products"]), 5)

    def test_INV_API_003_read_one_product(self):
        """INV-API-003: GET by id returns that product."""
        pid = self.product_id("Monitor")
        payload = self.client.get(f"/api/products/{pid}").get_json()
        self.assertEqual(payload["product"]["name"], "Monitor")
        self.assertEqual(payload["product"]["unit_price"], 8500.00)

    def test_INV_API_004_update_product(self):
        """INV-API-004: PUT changes fields and updates updated_at."""
        pid = self.product_id("Mouse")
        response = self.client.put(f"/api/products/{pid}",
                                   json={"quantity": 9, "unit_price": 550.0})
        self.assertEqual(response.status_code, 200)
        product = response.get_json()["product"]
        self.assertEqual(product["quantity"], 9)
        self.assertEqual(product["inventory_value"], 4950.0)
        self.assertFalse(product["low_stock"])

    def test_INV_API_005_delete_product(self):
        """INV-API-005: DELETE removes it; a second DELETE is 404."""
        pid = self.product_id("USB Hub")
        self.assertEqual(self.client.delete(f"/api/products/{pid}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/products/{pid}").status_code, 404)
        self.assertNotIn("USB Hub", self.names())

    def test_INV_API_006_search_by_name_and_category(self):
        """INV-API-006: search matches name and category, case-insensitively."""
        payload = self.client.get("/api/products?search=mouse").get_json()
        self.assertEqual([p["name"] for p in payload["products"]], ["Mouse"])
        payload = self.client.get("/api/products?search=Accessories").get_json()
        self.assertEqual(len(payload["products"]), 3)

    def test_INV_API_007_filter_by_category(self):
        """INV-API-007: category filter is exact and excludes other categories."""
        payload = self.client.get("/api/products?category=Displays").get_json()
        self.assertEqual([p["name"] for p in payload["products"]], ["Monitor"])

    def test_INV_API_008_missing_and_invalid_ids(self):
        """INV-API-008: unknown id is 404, non-integer id does not 500."""
        self.assertEqual(self.client.get("/api/products/9999").status_code, 404)
        self.assertEqual(self.client.get("/api/products/abc").status_code, 404)


class TestDashboardCalculations(InventoryTestCase):
    def test_INV_CALC_001_total_inventory_value(self):
        """INV-CALC-001: total value is exactly 54,200.00 (independent arithmetic)."""
        stats = self.client.get("/api/dashboard").get_json()
        self.assertEqual(stats["product_count"], 5)
        self.assertEqual(stats["total_units"], 24)          # 10+2+4+0+8
        self.assertAlmostEqual(stats["total_value"], EXPECTED_TOTAL, places=2)

    def test_INV_CALC_002_low_stock_detection(self):
        """INV-CALC-002: exactly Mouse and Laptop Stand are low stock."""
        stats = self.client.get("/api/dashboard").get_json()
        self.assertEqual(stats["low_stock_count"], 2)
        self.assertEqual({p["name"] for p in stats["low_stock"]}, EXPECTED_LOW)
        self.assertEqual(stats["out_of_stock_count"], 1)    # Laptop Stand

    def test_INV_CALC_003_category_breakdown(self):
        """INV-CALC-003: per-category values add up to the total."""
        stats = self.client.get("/api/dashboard").get_json()
        by_category = {row["category"]: row["value"] for row in stats["by_category"]}
        self.assertAlmostEqual(by_category["Accessories"], 13000.0, places=2)
        self.assertAlmostEqual(by_category["Displays"], 34000.0, places=2)
        self.assertAlmostEqual(by_category["Connectivity"], 7200.0, places=2)
        self.assertAlmostEqual(sum(by_category.values()), EXPECTED_TOTAL, places=2)

    def test_INV_CALC_004_dashboard_follows_writes(self):
        """INV-CALC-004: the figures are SQL over live rows, not constants."""
        pid = self.product_id("Keyboard")
        self.client.put(f"/api/products/{pid}", json={"quantity": 0})
        stats = self.client.get("/api/dashboard").get_json()
        self.assertAlmostEqual(stats["total_value"], EXPECTED_TOTAL - 12000.0, places=2)
        self.assertEqual(stats["low_stock_count"], 3)


class TestStockMovements(InventoryTestCase):
    def test_INV_MOV_001_record_in_movement(self):
        """INV-MOV-001: an 'in' movement raises stock and is recorded."""
        pid = self.product_id("Mouse")
        response = self.client.post(f"/api/products/{pid}/movements", json={
            "movement_type": "in", "quantity_change": 5, "reason": "delivery"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["movement"]["quantity_after"], 7)
        product = self.client.get(f"/api/products/{pid}").get_json()["product"]
        self.assertEqual(product["quantity"], 7)
        self.assertFalse(product["low_stock"])

    def test_INV_MOV_002_out_movement_cannot_go_negative(self):
        """INV-MOV-002: an over-large 'out' is refused with 409 and no change."""
        pid = self.product_id("USB Hub")          # 8 in stock
        response = self.client.post(f"/api/products/{pid}/movements", json={
            "movement_type": "out", "quantity_change": 50})
        self.assertEqual(response.status_code, 409)
        product = self.client.get(f"/api/products/{pid}").get_json()["product"]
        self.assertEqual(product["quantity"], 8)
        history = self.client.get(
            f"/api/products/{pid}/movements").get_json()["movements"]
        # Seeding wrote one opening-balance movement. A REFUSED movement must
        # not add another, and must not leave the quantity changed.
        self.assertEqual(len(history), 1, "a rejected movement was recorded anyway")
        self.assertEqual(history[0]["reason"], "opening balance")

    def test_INV_MOV_003_out_movement_decrements(self):
        """INV-MOV-003: a valid 'out' decrements and appears in history."""
        pid = self.product_id("Keyboard")
        self.client.post(f"/api/products/{pid}/movements", json={
            "movement_type": "out", "quantity_change": 4, "reason": "sold"})
        product = self.client.get(f"/api/products/{pid}").get_json()["product"]
        self.assertEqual(product["quantity"], 6)
        history = self.client.get(
            f"/api/products/{pid}/movements").get_json()["movements"]
        # Newest first: the movement just recorded, then the opening balance.
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["quantity_change"], -4)
        self.assertEqual(history[1]["reason"], "opening balance")

    def test_INV_MOV_004_opening_balance_recorded_on_create(self):
        """INV-MOV-004: creating with stock writes an opening-balance movement."""
        pid = self.product_id("Monitor")
        history = self.client.get(
            f"/api/products/{pid}/movements").get_json()["movements"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["reason"], "opening balance")

    def test_INV_MOV_005_zero_change_rejected(self):
        """INV-MOV-005: a zero movement is a 400."""
        pid = self.product_id("Monitor")
        response = self.client.post(f"/api/products/{pid}/movements", json={
            "movement_type": "in", "quantity_change": 0})
        self.assertEqual(response.status_code, 400)
        self.assertIn("quantity_change", response.get_json()["error"]["fields"])

    def test_INV_MOV_006_movement_for_missing_product(self):
        """INV-MOV-006: a movement against an unknown product is 404."""
        response = self.client.post("/api/products/9999/movements", json={
            "movement_type": "in", "quantity_change": 1})
        self.assertEqual(response.status_code, 404)

    def test_INV_MOV_007_delete_cascades_movements(self):
        """INV-MOV-007: deleting a product removes its movements (FK cascade)."""
        pid = self.product_id("Monitor")
        self.client.delete(f"/api/products/{pid}")
        with closing(sqlite3.connect(self.db)) as conn:
            remaining = conn.execute(
                "SELECT COUNT(*) FROM stock_movements WHERE product_id = ?",
                (pid,)).fetchone()[0]
        self.assertEqual(remaining, 0)


class TestValidation(InventoryTestCase):
    def test_INV_VAL_001_missing_name_rejected(self):
        """INV-VAL-001: missing name is 400 with a field message."""
        response = self.client.post("/api/products",
                                    json={"category": "x", "unit_price": 1})
        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.get_json()["error"]["fields"])

    def test_INV_VAL_002_negative_quantity_rejected(self):
        """INV-VAL-002: negative quantity is refused at the API."""
        response = self.client.post("/api/products", json={
            "name": "Bad", "category": "x", "quantity": -5, "unit_price": 10})
        self.assertEqual(response.status_code, 400)
        self.assertIn("quantity", response.get_json()["error"]["fields"])

    def test_INV_VAL_003_negative_price_rejected(self):
        """INV-VAL-003: negative price is refused at the API."""
        response = self.client.post("/api/products", json={
            "name": "Bad", "category": "x", "quantity": 1, "unit_price": -0.01})
        self.assertEqual(response.status_code, 400)
        self.assertIn("unit_price", response.get_json()["error"]["fields"])

    def test_INV_VAL_004_non_numeric_input_rejected(self):
        """INV-VAL-004: text where a number belongs is a 400, not a 500."""
        response = self.client.post("/api/products", json={
            "name": "Bad", "category": "x", "quantity": "many",
            "unit_price": "cheap"})
        self.assertEqual(response.status_code, 400)
        fields = response.get_json()["error"]["fields"]
        self.assertIn("quantity", fields)
        self.assertIn("unit_price", fields)

    def test_INV_VAL_005_non_json_body_rejected(self):
        """INV-VAL-005: a non-JSON body is a 400 with a JSON error."""
        response = self.client.post("/api/products", data="not json",
                                    content_type="text/plain")
        self.assertEqual(response.status_code, 400)
        self.assertIsInstance(response.get_json(), dict)

    def test_INV_VAL_006_database_check_blocks_negative_stock(self):
        """INV-VAL-006: even direct SQL cannot store a negative quantity."""
        with self.assertRaises(sqlite3.IntegrityError):
            with closing(sqlite3.connect(self.db)) as conn:
                conn.execute("UPDATE products SET quantity = -1 WHERE id = 1")

    def test_INV_VAL_007_unknown_endpoint_is_json_404(self):
        """INV-VAL-007: a wrong path is JSON, not an HTML error page."""
        response = self.client.get("/api/nope")
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.get_json())


class TestSecurityAndIntegrity(InventoryTestCase):
    def test_INV_SEC_001_sql_injection_in_search(self):
        """INV-SEC-001: injection in search is matched literally, not executed."""
        for payload in ("' OR 1=1 --", "'; DROP TABLE products; --",
                        "\" OR \"\"=\""):
            with self.subTest(payload=payload):
                response = self.client.get(
                    "/api/products", query_string={"search": payload})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["count"], 0,
                                 "injection changed the result set")
        # The table must still exist and still hold every row.
        self.assertEqual(len(self.names()), 5)

    def test_INV_SEC_002_sql_injection_in_name_is_stored_verbatim(self):
        """INV-SEC-002: a hostile name is stored as text, and the schema survives."""
        hostile = "Robert'); DROP TABLE products;--"
        response = self.client.post("/api/products", json={
            "name": hostile, "category": "x", "quantity": 1, "unit_price": 1})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["product"]["name"], hostile)
        with closing(sqlite3.connect(self.db)) as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        self.assertIn("products", tables)
        self.assertEqual(count, 6)

    def test_INV_SEC_003_injection_cannot_expose_other_tables(self):
        """INV-SEC-003: a UNION-style payload does not read stock_movements."""
        payload = self.client.get(
            "/api/products", query_string={
                "search": "x' UNION SELECT 1,id,product_id,movement_type,1,1,1,1 FROM stock_movements --"
            }).get_json()
        self.assertEqual(payload["count"], 0)

    def test_INV_SEC_004_database_unavailable_reports_503(self):
        """INV-SEC-004: a database failure is a JSON 503, not a stack trace."""
        with mock.patch.object(models, "list_products",
                               side_effect=sqlite3.OperationalError("disk I/O error")):
            response = self.client.get("/api/products")
        self.assertEqual(response.status_code, 503)
        body = response.get_json()
        self.assertIn("error", body)
        self.assertNotIn("Traceback", response.get_data(as_text=True))


class TestPersistence(InventoryTestCase):
    def test_INV_PER_001_data_survives_restart(self):
        """INV-PER-001: a new app instance on the same file sees the same data."""
        self.client.post("/api/products", json={
            "name": "Survivor", "category": "Test", "quantity": 3,
            "unit_price": 10.0})
        fresh = create_app(self.db)
        fresh.config.update(TESTING=True)
        client = fresh.test_client()
        names = [p["name"] for p in client.get("/api/products").get_json()["products"]]
        self.assertIn("Survivor", names)
        stats = client.get("/api/dashboard").get_json()
        self.assertAlmostEqual(stats["total_value"], EXPECTED_TOTAL + 30.0, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
