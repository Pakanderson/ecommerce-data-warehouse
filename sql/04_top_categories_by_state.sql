-- 04_top_categories_by_state.sql
--
-- For each state, what's the #1 best-selling product category by revenue?
-- Classic "top-N per group" problem, solved with RANK() instead of a
-- correlated subquery or GROUP_CONCAT hack.
--
-- Interview talking point: RANK() OVER (PARTITION BY ... ORDER BY ...) is
-- the standard pattern for "top N within each group". PARTITION BY resets
-- the ranking for every state; without it you'd get one ranking across the
-- whole table instead of one ranking per state.

WITH category_revenue_by_state AS (
    SELECT
        c.state,
        COALESCE(p.category_name_english, 'unknown') AS category,
        SUM(oi.price) AS revenue
    FROM fact_order_item oi
    JOIN fact_order o ON o.order_key = oi.order_key
    JOIN dim_customer c ON c.customer_key = o.customer_key
    LEFT JOIN dim_product p ON p.product_key = oi.product_key
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
    GROUP BY c.state, category
),
ranked AS (
    SELECT
        state,
        category,
        revenue,
        RANK() OVER (PARTITION BY state ORDER BY revenue DESC) AS category_rank
    FROM category_revenue_by_state
)
SELECT state, category AS top_category, ROUND(revenue, 2) AS revenue
FROM ranked
WHERE category_rank = 1
ORDER BY revenue DESC;
