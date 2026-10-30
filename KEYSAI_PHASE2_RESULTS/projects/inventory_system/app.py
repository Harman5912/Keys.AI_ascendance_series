"""KeysAI_Test_Inventory_System — Flask API + page.

    python seed.py        # write the synthetic dataset
    python app.py         # http://127.0.0.1:5081

Errors are JSON in every case, including an unexpected database failure: the
front end never has to parse an HTML traceback.
"""

from __future__ import annotations

import os
import sqlite3

from flask import Flask, jsonify, render_template, request

import models
import validation
from db import init_db

APP_NAME = "KeysAI_Test_Inventory_System"


def _error(message: str, status: int, fields: dict | None = None):
    payload = {"error": {"message": message}}
    if fields:
        payload["error"]["fields"] = fields
    return jsonify(payload), status


def create_app(db_path: str | os.PathLike | None = None) -> Flask:
    if db_path is not None:
        os.environ["INVENTORY_DB"] = str(db_path)
    init_db()

    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # ── page ─────────────────────────────────────────────────────────────
    @app.get("/")
    def index():
        return render_template("index.html", app_name=APP_NAME)

    # ── health ───────────────────────────────────────────────────────────
    @app.get("/api/health")
    def health():
        try:
            stats = models.dashboard()
            return jsonify({"ok": True, "products": stats["product_count"]})
        except sqlite3.Error as err:
            return _error(f"database unavailable: {err}", 503)

    @app.get("/api/categories")
    def categories():
        products = models.list_products()
        return jsonify({"categories": sorted({p["category"] for p in products})})

    # ── products ─────────────────────────────────────────────────────────
    @app.get("/api/products")
    def products_list():
        search = (request.args.get("search") or "").strip()
        category = (request.args.get("category") or "").strip()
        items = models.list_products(search=search, category=category)
        return jsonify({"products": items, "count": len(items),
                        "search": search, "category": category})

    @app.post("/api/products")
    def products_create():
        payload = request.get_json(silent=True)
        if payload is None:
            return _error("request body must be JSON", 400)
        data, errors = validation.validate_product(payload)
        if errors:
            return _error("validation failed", 400, errors)
        product = models.create_product(data)
        return jsonify({"product": product}), 201

    @app.get("/api/products/<int:product_id>")
    def products_read(product_id: int):
        try:
            return jsonify({"product": models.get_product(product_id)})
        except models.NotFound as err:
            return _error(str(err), 404)

    @app.put("/api/products/<int:product_id>")
    def products_update(product_id: int):
        payload = request.get_json(silent=True)
        if payload is None:
            return _error("request body must be JSON", 400)
        data, errors = validation.validate_product(payload, partial=True)
        if errors:
            return _error("validation failed", 400, errors)
        try:
            product = models.update_product(product_id, data)
        except models.NotFound as err:
            return _error(str(err), 404)
        return jsonify({"product": product})

    @app.delete("/api/products/<int:product_id>")
    def products_delete(product_id: int):
        try:
            models.delete_product(product_id)
        except models.NotFound as err:
            return _error(str(err), 404)
        return "", 204

    # ── movements ────────────────────────────────────────────────────────
    @app.get("/api/products/<int:product_id>/movements")
    def movements_list(product_id: int):
        try:
            items = models.list_movements(product_id)
        except models.NotFound as err:
            return _error(str(err), 404)
        return jsonify({"movements": items, "count": len(items)})

    @app.post("/api/products/<int:product_id>/movements")
    def movements_create(product_id: int):
        payload = request.get_json(silent=True)
        if payload is None:
            return _error("request body must be JSON", 400)
        data, errors = validation.validate_movement(payload)
        if errors:
            return _error("validation failed", 400, errors)
        try:
            movement = models.record_movement(product_id, data)
        except models.NotFound as err:
            return _error(str(err), 404)
        except models.InsufficientStock as err:
            return _error(str(err), 409)
        return jsonify({"movement": movement}), 201

    # ── dashboard ────────────────────────────────────────────────────────
    @app.get("/api/dashboard")
    def dashboard():
        return jsonify(models.dashboard())

    # ── error handling ───────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(_err):
        return _error("endpoint not found", 404)

    @app.errorhandler(405)
    def bad_method(_err):
        return _error("method not allowed", 405)

    @app.errorhandler(sqlite3.Error)
    def database_error(err):
        # A database outage is reported as a 503 with a message, never a crash
        # and never a 200 carrying an error string.
        return _error(f"database unavailable: {err}", 503)

    @app.errorhandler(500)
    def server_error(err):
        return _error("internal error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT") or 5081)
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
