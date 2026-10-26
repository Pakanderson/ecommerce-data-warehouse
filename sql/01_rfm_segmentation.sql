-- 01_rfm_segmentation.sql
--
-- RFM = Recency, Frequency, Monetary — a classic customer segmentation
-- technique. For every customer we compute:
--   Recency   how many days ago was their most recent order?
--   Frequency how many orders have they placed?
--   Monetary  how much have they spent in total (via payments)?
-- then bucket each metric into quintiles (1-5) with NTILE(), and combine
-- the three scores into a single segment label.
--
-- Interview talking point: NTILE(5) is a WINDOW FUNCTION — it computes a
-- value "over" a set of rows without collapsing them into one row per
-- group the way a plain GROUP BY aggregate would. That's the difference
-- between "rank every customer" (window function) and "count how many
-- customers" (aggregate).
--
-- Because Olist's customer_id is actually one-per-order (customer_unique_id
-- is the real recurring person), we group by customer_unique_id here —
-- worth knowing this dataset-specific quirk if asked about it.
--
-- Performance note worth explaining out loud: order_value is computed by
-- pre-aggregating fact_payment with its own GROUP BY (order_totals below)
-- and then JOINing that summary onto fact_order — NOT with a correlated
-- subquery "(SELECT SUM(...) FROM fact_payment WHERE order_key = o.order_key)"
-- inside the SELECT list. A correlated subquery re-runs once PER ROW of
-- fact_order (99k times), each scanning fact_payment — that's why the
-- first version of this query took minutes. Aggregate-then-join does one
-- pass over each table instead. This is a real bug I hit and fixed while
-- building this — a good one to be able to talk through in an interview.

WITH order_totals AS (
    SELECT order_key, SUM(payment_value) AS order_value
    FROM fact_payment
    GROUP BY order_key
),
customer_orders AS (
    SELECT
        c.customer_unique_id,
        o.order_key,
        o.order_purchase_timestamp,
        ot.order_value
    FROM fact_order o
    JOIN dim_customer c ON c.customer_key = o.customer_key
    LEFT JOIN order_totals ot ON ot.order_key = o.order_key
    WHERE o.order_status = 'delivered'
),
rfm_base AS (
    SELECT
        customer_unique_id,
        -- "today" for this static dataset = the most recent purchase date in it
        CAST(julianday((SELECT MAX(order_purchase_timestamp) FROM customer_orders))
             - julianday(MAX(order_purchase_timestamp)) AS INTEGER) AS recency_days,
        COUNT(DISTINCT order_key) AS frequency,
        SUM(order_value) AS monetary
    FROM customer_orders
    GROUP BY customer_unique_id
),
rfm_scored AS (
    SELECT
        customer_unique_id,
        recency_days,
        frequency,
        monetary,
        -- NTILE(5) splits customers into 5 equal-sized buckets ordered by
        -- the metric. For recency we order ASCENDING (fewer days = better,
        -- so it should score 5) — note the flipped 6-x trick below.
        6 - NTILE(5) OVER (ORDER BY recency_days ASC)  AS recency_score,
        NTILE(5) OVER (ORDER BY frequency ASC)          AS frequency_score,
        NTILE(5) OVER (ORDER BY monetary ASC)           AS monetary_score
    FROM rfm_base
)
SELECT
    customer_unique_id,
    recency_days,
    frequency,
    ROUND(monetary, 2) AS monetary,
    recency_score,
    frequency_score,
    monetary_score,
    (recency_score + frequency_score + monetary_score) AS rfm_total,
    CASE
        WHEN recency_score >= 4 AND frequency_score >= 4 AND monetary_score >= 4 THEN 'Champions'
        WHEN recency_score >= 3 AND frequency_score >= 3 THEN 'Loyal Customers'
        WHEN recency_score >= 4 AND frequency_score <= 2 THEN 'New / Promising'
        WHEN recency_score <= 2 AND frequency_score >= 3 THEN 'At Risk'
        WHEN recency_score <= 2 AND frequency_score <= 2 THEN 'Lost'
        ELSE 'Needs Attention'
    END AS rfm_segment
FROM rfm_scored
ORDER BY rfm_total DESC;
