-- 03_monthly_revenue_trend.sql
--
-- Monthly revenue (from order items, i.e. price only, not freight) plus a
-- month-over-month growth rate. This is the query behind almost every
-- "trend line" chart in a business dashboard.
--
-- Interview talking point: LAG() is a window function that looks at the
-- PREVIOUS row within an ordered window — here, "last month's revenue" —
-- without a self-join. Before window functions this required a much
-- clunkier self-join on "month - 1".

WITH monthly_revenue AS (
    SELECT
        d.year,
        d.month,
        SUM(oi.price) AS revenue,
        COUNT(DISTINCT oi.order_key) AS orders
    FROM fact_order_item oi
    JOIN fact_order o ON o.order_key = oi.order_key
    JOIN dim_date d ON d.date_key = o.purchase_date_key
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
    GROUP BY d.year, d.month
)
SELECT
    year,
    month,
    ROUND(revenue, 2) AS revenue,
    orders,
    ROUND(revenue / orders, 2) AS avg_order_value,
    LAG(revenue) OVER (ORDER BY year, month) AS prev_month_revenue,
    ROUND(
        100.0 * (revenue - LAG(revenue) OVER (ORDER BY year, month))
        / NULLIF(LAG(revenue) OVER (ORDER BY year, month), 0)
    , 1) AS mom_growth_pct
FROM monthly_revenue
ORDER BY year, month;
