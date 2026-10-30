-- SAMPLE data for keysai_shop. Re-runnable.
USE keysai_shop;

DELETE FROM order_items;
DELETE FROM orders;
DELETE FROM products;
DELETE FROM customers;
ALTER TABLE customers AUTO_INCREMENT = 1;
ALTER TABLE products AUTO_INCREMENT = 1;
ALTER TABLE orders AUTO_INCREMENT = 1;
ALTER TABLE order_items AUTO_INCREMENT = 1;

INSERT INTO customers (name, email, country, created_at) VALUES
  ('Ada Rowntree',  'ada@example.com',    'GB', '2026-01-12'),
  ('Ben Okafor',    'ben@example.com',    'NG', '2026-02-03'),
  ('Chen Wei',      'chen@example.com',   'SG', '2026-03-21'),
  ('Dana Ilsley',   'dana@example.com',   'US', '2026-05-04');

INSERT INTO products (sku, name, price, active) VALUES
  ('OIL-30',  'Field Facial Oil 30ml', 32.00, 1),
  ('BALM-60', 'Oat Cleansing Balm 60ml', 26.00, 1),
  ('CREAM-50','Nettle Hand Cream 50ml', 18.00, 1),
  ('REFILL',  'Refill pouch', 24.00, 0);

INSERT INTO orders (customer_id, placed_at, status) VALUES
  (1, '2026-06-01 09:14:00', 'paid'),
  (2, '2026-06-02 17:51:00', 'shipped'),
  (1, '2026-06-09 11:02:00', 'paid'),
  (3, '2026-06-11 08:30:00', 'refunded');

INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
  (1, 1, 1, 32.00),
  (1, 3, 2, 18.00),
  (2, 2, 1, 26.00),
  (3, 1, 2, 32.00),
  (4, 2, 1, 26.00);
