-- Queries that back the dashboards. Every one runs as-is in MySQL 8+.
USE keysai_shop;

-- 1. Revenue per country, paid and shipped only.
SELECT c.country,
       COUNT(DISTINCT o.id) AS orders,
       ROUND(SUM(r.revenue), 2) AS revenue
FROM order_revenue r
JOIN orders o    ON o.id = r.order_id
JOIN customers c ON c.id = r.customer_id
WHERE r.status IN ('paid', 'shipped')
GROUP BY c.country
ORDER BY revenue DESC;

-- 2. Top products by units and revenue.
SELECT p.sku, p.name,
       SUM(i.quantity) AS units,
       ROUND(SUM(i.quantity * i.unit_price), 2) AS revenue
FROM order_items i
JOIN products p ON p.id = i.product_id
GROUP BY p.id, p.sku, p.name
ORDER BY revenue DESC
LIMIT 5;

-- 3. Daily revenue with a 3-day rolling average (window function).
WITH daily AS (
    SELECT DATE(placed_at) AS day, SUM(revenue) AS revenue
    FROM order_revenue
    WHERE status <> 'refunded'
    GROUP BY DATE(placed_at)
)
SELECT day, revenue,
       ROUND(AVG(revenue) OVER (ORDER BY day ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2)
         AS rolling_3d
FROM daily
ORDER BY day;

-- 4. Customers whose first order is their only order (a win-back list).
SELECT c.name, c.email, MIN(r.placed_at) AS first_order
FROM order_revenue r
JOIN customers c ON c.id = r.customer_id
GROUP BY c.id, c.name, c.email
HAVING COUNT(*) = 1
ORDER BY first_order;

-- 5. Data quality: orders with no line items (should be empty).
SELECT o.id
FROM orders o
LEFT JOIN order_items i ON i.order_id = o.id
WHERE i.id IS NULL;
