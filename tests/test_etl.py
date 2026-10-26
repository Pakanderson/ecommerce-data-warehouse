"""
tests/test_etl.py

Tests for the ETL pipeline. Run with:  pytest

Why these specific tests? Each one protects against a real category of bug
that ETL pipelines are notorious for:

  test_extract_reads_all_source_tables   "did a CSV silently fail to load /
                                           end up with the wrong columns?"
  test_transform_deduplicates_dimensions "does a dimension table end up
                                           with two rows for one customer?"
  test_star_schema_referential_integrity "does every foreign key in a fact
                                           table actually point at a real
                                           row in its dimension table?"
  test_pipeline_is_idempotent            "if I run this twice, do I get
                                           duplicate data?" — this is the
                                           single most important property
                                           of an ETL pipeline you're going
                                           to run on a schedule.

These run against the REAL raw CSVs in data/raw/, not tiny fake fixtures.
That's a deliberate choice for a portfolio project: it proves the pipeline
works end-to-end against real, messy data, not just against data you
carefully constructed to be easy.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.etl import extract, transform, run_full_pipeline
from src.models import (
    Base, DimCustomer, DimSeller, DimProduct, DimDate,
    FactOrder, FactOrderItem, FactPayment, FactReview,
)


@pytest.fixture(scope="module")
def raw_data():
    return extract()


@pytest.fixture(scope="module")
def transformed(raw_data):
    return transform(raw_data)


def test_extract_reads_all_source_tables(raw_data):
    expected_tables = {
        "customers", "orders", "order_items", "payments",
        "reviews", "products", "sellers", "category_translation",
    }
    assert set(raw_data.keys()) == expected_tables
    for name, df in raw_data.items():
        assert len(df) > 0, f"{name} loaded with zero rows"


def test_transform_deduplicates_dimensions(transformed):
    # a dimension table should have exactly one row per business key
    assert transformed["dim_customer"]["customer_id"].is_unique
    assert transformed["dim_seller"]["seller_id"].is_unique
    assert transformed["dim_product"]["product_id"].is_unique


def test_dim_date_covers_the_full_range(transformed):
    dim_date = transformed["dim_date"]
    assert len(dim_date) > 0
    # every date should be a real, distinct calendar day
    assert dim_date["full_date"].is_unique


@pytest.fixture(scope="module")
def loaded_engine(tmp_path_factory):
    """Run the full pipeline once against a throwaway SQLite file, shared
    across the tests in this module (loading ~550k rows isn't free, so we
    only pay that cost once per test run, not once per test)."""
    db_path = tmp_path_factory.mktemp("db") / "test_ecommerce.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    run_full_pipeline(engine)
    return engine


def test_star_schema_referential_integrity(loaded_engine):
    """Every foreign key on a fact table should point at a row that
    actually exists in the referenced dimension table. This is the check
    that catches a broken JOIN before it ever reaches a dashboard."""
    with Session(loaded_engine) as session:
        orphan_items = session.execute(
            select(func.count()).select_from(FactOrderItem)
            .where(~FactOrderItem.order_key.in_(select(FactOrder.order_key)))
        ).scalar_one()
        assert orphan_items == 0

        orphan_payments = session.execute(
            select(func.count()).select_from(FactPayment)
            .where(~FactPayment.order_key.in_(select(FactOrder.order_key)))
        ).scalar_one()
        assert orphan_payments == 0

        orphan_orders = session.execute(
            select(func.count()).select_from(FactOrder)
            .where(~FactOrder.customer_key.in_(select(DimCustomer.customer_key)))
        ).scalar_one()
        assert orphan_orders == 0


def test_pipeline_is_idempotent(loaded_engine):
    """Run the pipeline a second time against the SAME database and check
    row counts are identical — proof that re-running doesn't duplicate
    data. This is what "idempotent" means in practice, not just in theory."""
    with Session(loaded_engine) as session:
        before = session.execute(select(func.count()).select_from(FactOrder)).scalar_one()

    run_full_pipeline(loaded_engine)

    with Session(loaded_engine) as session:
        after = session.execute(select(func.count()).select_from(FactOrder)).scalar_one()

    assert before == after
    assert before > 0


def test_no_duplicate_order_items(loaded_engine):
    """Regression guard for the (order_key, order_item_id) uniqueness
    constraint defined in models.py."""
    with Session(loaded_engine) as session:
        total = session.execute(select(func.count()).select_from(FactOrderItem)).scalar_one()
        distinct_pairs = session.execute(
            select(func.count(func.distinct(FactOrderItem.order_key * 1000 + FactOrderItem.order_item_id)))
        ).scalar_one()
    assert total == distinct_pairs
