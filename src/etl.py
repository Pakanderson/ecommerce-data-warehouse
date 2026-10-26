"""
etl.py — the actual Extract, Transform, Load pipeline.

The three functions below (extract, transform, load) map directly onto the
three letters of "ETL". Keeping them as separate functions — rather than one
giant script — is deliberate: each one is independently testable (see
tests/test_etl.py), and each one has a single, nameable job:

  EXTRACT   read the raw CSVs into pandas DataFrames, exactly as they are.
  TRANSFORM clean them and reshape them into the star schema from models.py.
  LOAD      write the transformed data into the database.

Design decision worth explaining out loud in an interview:
This pipeline does a "full refresh" on every run — it drops and rebuilds all
tables from the source CSVs each time. That's a completely standard,
legitimate ETL pattern when the source data is small enough to reprocess
entirely (this one is: under 100MB) and you don't need history of what the
warehouse looked like yesterday. It also makes the pipeline trivially
IDEMPOTENT: run it once, run it five times, you get the exact same result —
no duplicate rows, no "did I already load this?" bugs. The companion
project (supply-chain-pipeline) shows the other common pattern —
INCREMENTAL loading with a watermark, which is what you reach for once the
source data gets too large to reprocess in full every time.
"""

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from src.models import (
    Base, DimCustomer, DimSeller, DimProduct, DimDate,
    FactOrder, FactOrderItem, FactPayment, FactReview, EtlRunLog,
)

logger = logging.getLogger("ecommerce_etl")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

DATE_COLUMNS = {
    "orders": [
        "order_purchase_timestamp", "order_approved_at",
        "order_delivered_carrier_date", "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ],
    "order_items": ["shipping_limit_date"],
    "reviews": ["review_creation_date", "review_answer_timestamp"],
}


# ---------------------------------------------------------------------------
# EXTRACT
# ---------------------------------------------------------------------------

def extract() -> dict[str, pd.DataFrame]:
    """Read every raw CSV into a DataFrame, unmodified. Returns a dict keyed
    by a short, friendly name (not the filename) so the rest of the code
    doesn't have to know Olist's file-naming conventions."""
    logger.info("EXTRACT: reading raw CSVs from %s", RAW_DIR)

    raw = {
        "customers": pd.read_csv(RAW_DIR / "olist_customers_dataset.csv"),
        "orders": pd.read_csv(RAW_DIR / "olist_orders_dataset.csv"),
        "order_items": pd.read_csv(RAW_DIR / "olist_order_items_dataset.csv"),
        "payments": pd.read_csv(RAW_DIR / "olist_order_payments_dataset.csv"),
        "reviews": pd.read_csv(RAW_DIR / "olist_order_reviews_dataset.csv"),
        "products": pd.read_csv(RAW_DIR / "olist_products_dataset.csv"),
        "sellers": pd.read_csv(RAW_DIR / "olist_sellers_dataset.csv"),
        "category_translation": pd.read_csv(RAW_DIR / "product_category_name_translation.csv"),
    }

    for name, df in raw.items():
        logger.info("  %-20s %6d rows, %2d columns", name, len(df), df.shape[1])

    return raw


# ---------------------------------------------------------------------------
# TRANSFORM
# ---------------------------------------------------------------------------

def _parse_dates(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    df = df.copy()
    for col in columns:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def transform(raw: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """
    Clean the raw tables and reshape them into the star-schema tables
    defined in models.py. Returns plain DataFrames (not ORM objects yet) —
    load() is the step that turns these into database rows.
    """
    logger.info("TRANSFORM: cleaning data and building star schema tables")

    # --- dim_customer -------------------------------------------------
    customers = raw["customers"].drop_duplicates(subset="customer_id").copy()
    customers = customers.rename(columns={
        "customer_zip_code_prefix": "zip_code_prefix",
        "customer_city": "city",
        "customer_state": "state",
    })[["customer_id", "customer_unique_id", "zip_code_prefix", "city", "state"]]
    customers["zip_code_prefix"] = customers["zip_code_prefix"].astype(str)

    # --- dim_seller -----------------------------------------------------
    sellers = raw["sellers"].drop_duplicates(subset="seller_id").copy()
    sellers = sellers.rename(columns={
        "seller_zip_code_prefix": "zip_code_prefix",
        "seller_city": "city",
        "seller_state": "state",
    })[["seller_id", "zip_code_prefix", "city", "state"]]
    sellers["zip_code_prefix"] = sellers["zip_code_prefix"].astype(str)

    # --- dim_product ------------------------------------------------------
    # translate the Portuguese category name to English so the warehouse
    # is readable without a lookup table at query time
    products = raw["products"].merge(
        raw["category_translation"], on="product_category_name", how="left"
    )
    products = products.drop_duplicates(subset="product_id").copy()
    products = products.rename(columns={
        "product_weight_g": "weight_g",
        "product_length_cm": "length_cm",
        "product_height_cm": "height_cm",
        "product_width_cm": "width_cm",
        "product_photos_qty": "photos_qty",
    })[["product_id", "product_category_name_english", "weight_g",
        "length_cm", "height_cm", "width_cm", "photos_qty"]]
    products = products.rename(columns={"product_category_name_english": "category_name_english"})

    # --- orders / order_items / payments / reviews: parse date columns ---
    orders = _parse_dates(raw["orders"], DATE_COLUMNS["orders"])
    order_items = _parse_dates(raw["order_items"], DATE_COLUMNS["order_items"])
    reviews = _parse_dates(raw["reviews"], DATE_COLUMNS["reviews"])
    payments = raw["payments"].copy()

    # --- dim_date: every distinct calendar date that appears anywhere ----
    all_dates = pd.concat([
        orders["order_purchase_timestamp"].dt.date,
        orders["order_approved_at"].dt.date,
        orders["order_delivered_carrier_date"].dt.date,
        orders["order_delivered_customer_date"].dt.date,
        orders["order_estimated_delivery_date"].dt.date,
        order_items["shipping_limit_date"].dt.date,
        reviews["review_creation_date"].dt.date,
        reviews["review_answer_timestamp"].dt.date,
    ]).dropna().unique()
    dim_date = pd.DataFrame({"full_date": sorted(all_dates)})

    return {
        "dim_customer": customers,
        "dim_seller": sellers,
        "dim_product": products,
        "dim_date": dim_date,
        "orders": orders,
        "order_items": order_items,
        "payments": payments,
        "reviews": reviews,
    }


# ---------------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------------

def _bulk_insert(session: Session, model, records: list[dict]) -> None:
    """Thin wrapper so every bulk load logs how many rows it wrote."""
    if not records:
        return
    session.bulk_insert_mappings(model, records)
    logger.info("  loaded %6d rows into %s", len(records), model.__tablename__)


def load(session: Session, tables: dict[str, pd.DataFrame]) -> int:
    """
    Load the transformed tables into the database in dependency order:
    dimensions first (so we have surrogate keys to reference), then facts.

    Returns the total number of rows written, purely so the caller can log
    a nice summary / record it in the EtlRunLog control table.
    """
    logger.info("LOAD: writing star schema into the database")
    total_rows = 0

    # ---- dimensions first --------------------------------------------
    _bulk_insert(session, DimCustomer, tables["dim_customer"].to_dict("records"))
    _bulk_insert(session, DimSeller, tables["dim_seller"].to_dict("records"))
    _bulk_insert(session, DimProduct, tables["dim_product"].to_dict("records"))

    dim_date_records = [
        {
            "date_key": DimDate.key_for(d),
            "full_date": d,
            "year": d.year,
            "month": d.month,
            "day": d.day,
            "quarter": (d.month - 1) // 3 + 1,
            "day_of_week": d.strftime("%A"),
            "is_weekend": 1 if d.weekday() >= 5 else 0,
        }
        for d in tables["dim_date"]["full_date"]
    ]
    _bulk_insert(session, DimDate, dim_date_records)
    session.flush()
    total_rows += (
        len(tables["dim_customer"]) + len(tables["dim_seller"])
        + len(tables["dim_product"]) + len(dim_date_records)
    )

    # Build lookup dicts: business key -> surrogate key. This is the classic
    # "surrogate key lookup" step every star-schema ETL needs before it can
    # load facts, because facts store the surrogate key, not the business key.
    customer_key_by_id = dict(
        session.query(DimCustomer.customer_id, DimCustomer.customer_key).all()
    )
    seller_key_by_id = dict(
        session.query(DimSeller.seller_id, DimSeller.seller_key).all()
    )
    product_key_by_id = dict(
        session.query(DimProduct.product_id, DimProduct.product_key).all()
    )

    def date_key(ts) -> int | None:
        if pd.isna(ts):
            return None
        return DimDate.key_for(ts.date())

    # ---- fact_order -----------------------------------------------------
    orders = tables["orders"]
    order_records = []
    for row in orders.itertuples(index=False):
        order_records.append({
            "order_id": row.order_id,
            "customer_key": customer_key_by_id.get(row.customer_id),
            "purchase_date_key": date_key(row.order_purchase_timestamp),
            "order_status": row.order_status,
            "order_purchase_timestamp": _none_if_nat(row.order_purchase_timestamp),
            "order_approved_at": _none_if_nat(row.order_approved_at),
            "order_delivered_carrier_date": _none_if_nat(row.order_delivered_carrier_date),
            "order_delivered_customer_date": _none_if_nat(row.order_delivered_customer_date),
            "order_estimated_delivery_date": _none_if_nat(row.order_estimated_delivery_date),
        })
    _bulk_insert(session, FactOrder, order_records)
    session.flush()
    total_rows += len(order_records)

    order_key_by_id = dict(session.query(FactOrder.order_id, FactOrder.order_key).all())

    # ---- fact_order_item --------------------------------------------------
    order_items = tables["order_items"]
    item_records = []
    for row in order_items.itertuples(index=False):
        order_key = order_key_by_id.get(row.order_id)
        if order_key is None:
            continue  # orphan item with no matching order; skip + could log
        item_records.append({
            "order_key": order_key,
            "order_item_id": int(row.order_item_id),
            "product_key": product_key_by_id.get(row.product_id),
            "seller_key": seller_key_by_id.get(row.seller_id),
            "price": float(row.price),
            "freight_value": float(row.freight_value),
            "shipping_limit_date": _none_if_nat(row.shipping_limit_date),
        })
    _bulk_insert(session, FactOrderItem, item_records)
    total_rows += len(item_records)

    # ---- fact_payment ----------------------------------------------------
    payments = tables["payments"]
    payment_records = []
    for row in payments.itertuples(index=False):
        order_key = order_key_by_id.get(row.order_id)
        if order_key is None:
            continue
        payment_records.append({
            "order_key": order_key,
            "payment_sequential": int(row.payment_sequential),
            "payment_type": row.payment_type,
            "payment_installments": int(row.payment_installments),
            "payment_value": float(row.payment_value),
        })
    _bulk_insert(session, FactPayment, payment_records)
    total_rows += len(payment_records)

    # ---- fact_review -----------------------------------------------------
    reviews = tables["reviews"]
    review_records = []
    seen_review_ids: set[str] = set()
    for row in reviews.itertuples(index=False):
        order_key = order_key_by_id.get(row.order_id)
        if order_key is None or row.review_id in seen_review_ids:
            continue
        seen_review_ids.add(row.review_id)
        review_records.append({
            "review_id": row.review_id,
            "order_key": order_key,
            "review_score": int(row.review_score),
            "review_creation_date": _none_if_nat(row.review_creation_date),
            "review_answer_timestamp": _none_if_nat(row.review_answer_timestamp),
        })
    _bulk_insert(session, FactReview, review_records)
    total_rows += len(review_records)

    session.commit()
    return total_rows


def _none_if_nat(ts):
    """pandas represents a missing timestamp as NaT; SQLAlchemy wants a
    plain None for a NULL column. Small glue function, used everywhere
    a source date might be missing (e.g. an order that hasn't shipped yet
    has no order_delivered_customer_date)."""
    return None if pd.isna(ts) else ts.to_pydatetime()


# ---------------------------------------------------------------------------
# ORCHESTRATION — ties extract -> transform -> load together with logging
# and a full-refresh reset, and records the run in EtlRunLog.
# ---------------------------------------------------------------------------

def run_full_pipeline(engine) -> int:
    """
    Run the whole pipeline against the given SQLAlchemy engine.
    Full refresh: drops and recreates every table, then reloads from the
    raw CSVs. Safe to call repeatedly (idempotent — see module docstring).
    Returns the total number of rows loaded.
    """
    from sqlalchemy.orm import Session as SASession

    logger.info("=" * 70)
    logger.info("Starting full pipeline run")

    # Full refresh: wipe and recreate the schema. This is what makes
    # re-running the pipeline safe — there's no "insert on top of old data"
    # step where duplicates could sneak in.
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    session = SASession(bind=engine)
    run_log = EtlRunLog(started_at=datetime.utcnow(), status="running")
    session.add(run_log)
    session.commit()

    try:
        raw = extract()
        tables = transform(raw)
        total_rows = load(session, tables)

        run_log.status = "success"
        run_log.finished_at = datetime.utcnow()
        run_log.rows_loaded = total_rows
        run_log.notes = f"Loaded {total_rows} rows across {len(tables)} source tables"
        session.commit()

        logger.info("Pipeline finished successfully: %d rows loaded", total_rows)
        return total_rows
    except Exception as exc:  # pragma: no cover - defensive path
        session.rollback()
        run_log.status = "failed"
        run_log.finished_at = datetime.utcnow()
        run_log.notes = str(exc)
        session.commit()
        logger.exception("Pipeline failed")
        raise
    finally:
        session.close()
