-- KeysAI_Test_Inventory_System — schema.
-- Constraints live in the database as well as the API, so a direct SQL write
-- cannot create a negative quantity or a negative price even if it bypasses
-- the application layer.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    category      TEXT    NOT NULL,
    quantity      INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    unit_price    REAL    NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
    reorder_level INTEGER NOT NULL DEFAULT 0 CHECK (reorder_level >= 0),
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_name     ON products(name);

CREATE TABLE IF NOT EXISTS stock_movements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL,
    movement_type   TEXT    NOT NULL CHECK (movement_type IN ('in', 'out', 'adjust')),
    quantity_change INTEGER NOT NULL,
    reason          TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_movements_product ON stock_movements(product_id);
