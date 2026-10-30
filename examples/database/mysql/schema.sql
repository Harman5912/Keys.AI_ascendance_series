-- Shop schema for the MySQL example. Idempotent, so it can be re-run.
CREATE DATABASE IF NOT EXISTS keysai_shop
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE keysai_shop;

CREATE TABLE IF NOT EXISTS customers (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(120) NOT NULL,
    email      VARCHAR(160) NOT NULL UNIQUE,
    country    CHAR(2) NOT NULL,
    created_at DATE NOT NULL DEFAULT (CURRENT_DATE)
);

CREATE TABLE IF NOT EXISTS products (
    id       BIGINT AUTO_INCREMENT PRIMARY KEY,
    sku      VARCHAR(32) NOT NULL UNIQUE,
    name     VARCHAR(140) NOT NULL,
    price    DECIMAL(10,2) NOT NULL,
    active   TINYINT(1) NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS orders (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id BIGINT NOT NULL,
    placed_at   DATETIME NOT NULL,
    status      ENUM('pending','paid','shipped','refunded') NOT NULL DEFAULT 'pending',
    CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES customers(id),
    KEY idx_orders_placed (placed_at),
    KEY idx_orders_status (status)
);

CREATE TABLE IF NOT EXISTS order_items (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_id   BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    quantity   INT NOT NULL CHECK (quantity > 0),
    unit_price DECIMAL(10,2) NOT NULL,
    CONSTRAINT fk_items_order FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Revenue per order, so two dashboards can share one definition.
CREATE OR REPLACE VIEW order_revenue AS
SELECT o.id            AS order_id,
       o.customer_id,
       o.status,
       o.placed_at,
       SUM(i.quantity * i.unit_price) AS revenue
FROM orders o
JOIN order_items i ON i.order_id = o.id
GROUP BY o.id, o.customer_id, o.status, o.placed_at;
