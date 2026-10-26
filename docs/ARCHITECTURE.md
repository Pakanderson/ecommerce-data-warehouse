# Architecture & design decisions

This document explains *why* the project is built the way it is, not just
what the code does. Read this once, and you should be able to defend every
decision if someone pushes back on it.

## 1. Why a star schema instead of one big flat table?

The raw data already comes as 8 separate CSVs, so *some* normalization
already exists. The design decision was how to connect them:

- **One giant flat table** (join everything into one wide table) would
  duplicate customer/product/seller attributes on every single row —
  wasteful, and a nightmare to update if, say, a seller's city changes.
- **A star schema** stores each real-world "thing" (a customer, a product,
  a seller, a calendar day) exactly once, in its own dimension table, and
  links to it from fact tables using a small integer key. This is the
  standard shape for analytical databases (as opposed to *transactional*
  databases, which look different) because it makes typical business
  questions — "revenue by state", "orders by category" — a simple JOIN +
  GROUP BY instead of complicated logic.

## 2. Surrogate keys vs. business keys

Every dimension table has two kinds of identifier:

- **Business key** (`customer_id`, `product_id`, ...): the identifier that
  came from the source system. Useful for tracing a row back to the
  original CSV, but it's a string, and strings are slower to join on and
  sometimes change format between systems.
- **Surrogate key** (`customer_key`, `product_key`, ...): an
  auto-incrementing integer that WE invented when we loaded the row into
  our warehouse. This is what fact tables use for their foreign keys.
  Integers join faster than strings, and using our own key means the
  warehouse doesn't break if the source system ever changes its ID format.

This is standard practice in every real data warehouse — if you've never
seen it before, this project is a genuine, working example of it.

## 3. Picking the grain of each fact table

"Grain" = what one row represents. Getting this wrong is the most common
real mistake in warehouse design, because it's tempting to mix grains in
one table (e.g., one row per order, but with columns for the first
product's name — what about the second product?). Here:

- `fact_order`: one row per **order**. Order-level facts only (status,
  timestamps).
- `fact_order_item`: one row per **line item within an order**. An order
  with 3 different products = 3 rows here.
- `fact_payment`: one row per **payment record**. Olist orders can be
  split across multiple payment methods, so this can't live on
  `fact_order` either.
- `fact_review`: one row per **review**.

Notice these four fact tables share a grain hierarchy but are NOT merged
into one table — merging them would force you to pick one grain and
either duplicate order-level data across item rows, or lose item-level
detail. Keeping them separate, connected by `order_key`, is what lets you
ask questions at whichever grain you need.

## 4. Idempotency: "full refresh" vs. "incremental"

This pipeline does a **full refresh** on every run: `Base.metadata.drop_all()`
then `create_all()`, then reload everything from the CSVs. That's a
completely legitimate pattern when:

- the source data is small enough to reprocess entirely quickly (this one
  takes under 20 seconds), and
- you don't need to preserve history of what the warehouse looked like at
  a previous point in time.

It also makes **idempotency trivial to prove**: run the pipeline once, run
it five times, the result is byte-for-byte the same, because every run
starts from a clean slate. `tests/test_etl.py::test_pipeline_is_idempotent`
checks exactly this.

The companion project, `supply-chain-pipeline`, deliberately does the
opposite — an **incremental** load using a watermark, which is what you'd
reach for once full-refresh stops being fast enough (e.g. millions of rows
arriving daily). Being able to explain *when you'd choose one over the
other* is a stronger signal than knowing only one pattern.

## 5. Indexing

SQLite (like most databases) automatically indexes primary keys and
columns with a `UNIQUE` constraint, but **not** plain foreign key columns.
Early in building this project, `sql/01_rfm_segmentation.sql` took minutes
to run because of exactly this — a lookup against `fact_payment.order_key`
was doing a full table scan for every one of ~99,000 orders. The fix was
two things:

1. Add explicit indexes on every foreign key column that queries actually
   filter or join on (see `Index(...)` entries in `src/models.py`).
2. Rewrite the query to aggregate `fact_payment` once (`GROUP BY order_key`)
   and JOIN the result, instead of running a correlated subquery per row
   of `fact_order`.

Both fixes are visible in the code and worth being able to explain — this
is a genuine performance bug you hit and fixed, not a hypothetical one.

## 6. Why SQLAlchemy ORM instead of raw SQL / pandas `.to_sql()`

`pandas.DataFrame.to_sql()` would have been faster to write, but it
infers column types from the DataFrame and doesn't give you real foreign
key constraints, primary keys, or indexes — you'd get a database that
*looks* relational but isn't actually enforcing any of the rules that make
one useful. Defining the schema explicitly in `src/models.py` with
SQLAlchemy's ORM means:

- the schema is documented in one readable place, in Python, under version
  control
- foreign key and uniqueness constraints are actually enforced by the
  database, not just assumed
- the same model classes can be reused to query the data with the ORM
  (see the surrogate-key lookups in `src/etl.py`'s `load()` function),
  not just to build the schema
