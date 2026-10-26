-- 02_delivery_performance.sql
--
-- Late-delivery analysis: for every state, what fraction of delivered
-- orders arrived AFTER the estimated delivery date, and by how many days
-- on average? This is exactly the kind of "operational health" query an
-- analyst gets asked for in a business setting.
--
-- Interview talking point: this uses a CTE (WITH ... AS) purely for
-- readability — it names an intermediate result so the final SELECT reads
-- like plain English instead of one deeply nested query.

WITH delivered_orders AS (
    SELECT
        o.order_key,
        c.state,
        o.order_delivered_customer_date,
        o.order_estimated_delivery_date,
        CASE
            WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN 1
            ELSE 0
        END AS is_late,
        CAST(julianday(o.order_delivered_customer_date)
             - julianday(o.order_estimated_delivery_date) AS REAL) AS days_late
    FROM fact_order o
    JOIN dim_customer c ON c.customer_key = o.customer_key
    WHERE o.order_status = 'delivered'
      AND o.order_delivered_customer_date IS NOT NULL
      AND o.order_estimated_delivery_date IS NOT NULL
)
SELECT
    state,
    COUNT(*) AS delivered_orders,
    SUM(is_late) AS late_orders,
    ROUND(100.0 * SUM(is_late) / COUNT(*), 1) AS late_pct,
    ROUND(AVG(CASE WHEN is_late = 1 THEN days_late END), 1) AS avg_days_late_when_late
FROM delivered_orders
GROUP BY state
HAVING COUNT(*) >= 20          -- ignore states with too few orders to be meaningful
ORDER BY late_pct DESC;
