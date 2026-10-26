"""
models.py — the database schema, defined as Python classes.

This is a "star schema": one set of small, descriptive DIMENSION tables
(who's the customer, what's the product, when did this happen) surrounding
a set of FACT tables that hold the actual business events (an order was
placed, an item was paid for, a review was left) and mostly just contain
numbers and foreign keys pointing back at the dimensions.

Why bother with this shape instead of one giant flat table?
1. No repeated data: a customer's city is stored once in dim_customer,
   not once per order line. That's what "normalization" means in practice.
2. Fast, intuitive analytical queries: "revenue by state" is just a JOIN
   from fact_order_items to dim_customer on customer_key, then GROUP BY
   state. This is exactly the shape every BI tool (Tableau, Power BI,
   Looker) expects to sit on top of.
3. It's the industry-standard vocabulary. If you can point at this file
   and say "dimension table", "fact table", "surrogate key", "grain",
   interviewers will recognize you've done this before for real.

Vocabulary you should be comfortable explaining out loud:
- Surrogate key: the auto-incrementing integer primary key (e.g.
  `customer_key`) that WE invented for our warehouse. It is NOT the same
  as the `customer_id` string that came from the source system — that's
  the "business key" / "natural key". We keep both: the surrogate key is
  what foreign keys point at (fast integer joins), the business key is
  what lets us trace a row back to the original CSV.
- Grain: the "one row = one ___" definition of a fact table. Getting the
  grain right is the single most important decision in a warehouse design.
  Here: fact_orders is one row per ORDER; fact_order_items is one row per
  ORDER LINE ITEM (an order with 3 products has 3 rows in this table).
"""

from datetime import date, datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Date,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ---------------------------------------------------------------------------
# DIMENSION TABLES — the "who / what / when" that facts refer to
# ---------------------------------------------------------------------------

class DimCustomer(Base):
    """One row per customer who placed at least one order."""
    __tablename__ = "dim_customer"

    customer_key = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String, unique=True, nullable=False)  # business key from source
    customer_unique_id = Column(String, nullable=False)  # Olist's "real person" id
    zip_code_prefix = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)

    orders = relationship("FactOrder", back_populates="customer")


class DimSeller(Base):
    """One row per seller/merchant on the marketplace."""
    __tablename__ = "dim_seller"

    seller_key = Column(Integer, primary_key=True, autoincrement=True)
    seller_id = Column(String, unique=True, nullable=False)
    zip_code_prefix = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)


class DimProduct(Base):
    """One row per product SKU."""
    __tablename__ = "dim_product"

    product_key = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(String, unique=True, nullable=False)
    category_name_english = Column(String, nullable=True)
    weight_g = Column(Float, nullable=True)
    length_cm = Column(Float, nullable=True)
    height_cm = Column(Float, nullable=True)
    width_cm = Column(Float, nullable=True)
    photos_qty = Column(Integer, nullable=True)


class DimDate(Base):
    """
    One row per calendar day that appears anywhere in the data.

    A date dimension looks like overkill until you need "sales by day of
    week" or "sales by quarter" — with a date dimension that's a plain
    GROUP BY on a column instead of date arithmetic buried inside every
    query. It's a very standard warehouse pattern.
    """
    __tablename__ = "dim_date"

    date_key = Column(Integer, primary_key=True)  # YYYYMMDD as an int, e.g. 20180115
    full_date = Column(Date, nullable=False, unique=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    day = Column(Integer, nullable=False)
    quarter = Column(Integer, nullable=False)
    day_of_week = Column(String, nullable=False)  # 'Monday', 'Tuesday', ...
    is_weekend = Column(Integer, nullable=False)  # 0/1 (SQLite has no real boolean)

    @staticmethod
    def key_for(d: date) -> int:
        return int(d.strftime("%Y%m%d"))

    @staticmethod
    def build(d: date) -> "DimDate":
        return DimDate(
            date_key=DimDate.key_for(d),
            full_date=d,
            year=d.year,
            month=d.month,
            day=d.day,
            quarter=(d.month - 1) // 3 + 1,
            day_of_week=d.strftime("%A"),
            is_weekend=1 if d.weekday() >= 5 else 0,
        )


# ---------------------------------------------------------------------------
# FACT TABLES — the actual business events, mostly numbers + foreign keys
# ---------------------------------------------------------------------------

class FactOrder(Base):
    """
    Grain: ONE ROW PER ORDER.

    Holds the order lifecycle timestamps and status — the things that are
    true about the order as a whole, not about any individual item in it.
    """
    __tablename__ = "fact_order"

    order_key = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String, unique=True, nullable=False)
    customer_key = Column(Integer, ForeignKey("dim_customer.customer_key"), nullable=False)
    purchase_date_key = Column(Integer, ForeignKey("dim_date.date_key"), nullable=True)

    order_status = Column(String, nullable=False)
    order_purchase_timestamp = Column(DateTime, nullable=True)
    order_approved_at = Column(DateTime, nullable=True)
    order_delivered_carrier_date = Column(DateTime, nullable=True)
    order_delivered_customer_date = Column(DateTime, nullable=True)
    order_estimated_delivery_date = Column(DateTime, nullable=True)

    customer = relationship("DimCustomer", back_populates="orders")
    items = relationship("FactOrderItem", back_populates="order")
    payments = relationship("FactPayment", back_populates="order")
    reviews = relationship("FactReview", back_populates="order")

    # SQLite (and most databases) only auto-index PRIMARY KEY / UNIQUE
    # columns. Foreign key columns you actually JOIN or filter on need an
    # explicit index, or every join through them is a full table scan.
    # These two indexes are exactly the columns fact_order gets joined/
    # filtered on in the analytical queries under sql/.
    __table_args__ = (
        Index("ix_fact_order_customer_key", "customer_key"),
        Index("ix_fact_order_purchase_date_key", "purchase_date_key"),
    )


class FactOrderItem(Base):
    """
    Grain: ONE ROW PER ORDER LINE ITEM.

    An order with three different products has three rows here. This is
    where price/freight live, and where product+seller performance
    analysis comes from.
    """
    __tablename__ = "fact_order_item"

    order_item_key = Column(Integer, primary_key=True, autoincrement=True)
    order_key = Column(Integer, ForeignKey("fact_order.order_key"), nullable=False)
    order_item_id = Column(Integer, nullable=False)  # position within the order (1, 2, 3...)
    product_key = Column(Integer, ForeignKey("dim_product.product_key"), nullable=True)
    seller_key = Column(Integer, ForeignKey("dim_seller.seller_key"), nullable=True)

    price = Column(Float, nullable=False)
    freight_value = Column(Float, nullable=False)
    shipping_limit_date = Column(DateTime, nullable=True)

    order = relationship("FactOrder", back_populates="items")

    __table_args__ = (
        UniqueConstraint("order_key", "order_item_id", name="uq_order_item"),
        Index("ix_fact_order_item_product_key", "product_key"),
        Index("ix_fact_order_item_seller_key", "seller_key"),
    )


class FactPayment(Base):
    """
    Grain: ONE ROW PER PAYMENT INSTALLMENT RECORD.

    A single order can be paid with more than one payment method/split
    (payment_sequential handles that), which is why this isn't just a
    column on fact_order.
    """
    __tablename__ = "fact_payment"

    payment_key = Column(Integer, primary_key=True, autoincrement=True)
    order_key = Column(Integer, ForeignKey("fact_order.order_key"), nullable=False)
    payment_sequential = Column(Integer, nullable=False)
    payment_type = Column(String, nullable=False)
    payment_installments = Column(Integer, nullable=False)
    payment_value = Column(Float, nullable=False)

    order = relationship("FactOrder", back_populates="payments")

    __table_args__ = (Index("ix_fact_payment_order_key", "order_key"),)


class FactReview(Base):
    """Grain: ONE ROW PER REVIEW."""
    __tablename__ = "fact_review"

    review_key = Column(Integer, primary_key=True, autoincrement=True)
    review_id = Column(String, unique=True, nullable=False)
    order_key = Column(Integer, ForeignKey("fact_order.order_key"), nullable=False)
    review_score = Column(Integer, nullable=False)
    review_creation_date = Column(DateTime, nullable=True)
    review_answer_timestamp = Column(DateTime, nullable=True)

    order = relationship("FactOrder", back_populates="reviews")

    __table_args__ = (Index("ix_fact_review_order_key", "order_key"),)


# ---------------------------------------------------------------------------
# CONTROL TABLE — bookkeeping for the pipeline itself, not business data.
# This is a very common real-world pattern: a small table where the ETL
# process records "I ran, here's what happened", so you (and re-runs) can
# check pipeline history instead of only trusting logs.
# ---------------------------------------------------------------------------

class EtlRunLog(Base):
    __tablename__ = "etl_run_log"

    run_key = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default="running")  # running / success / failed
    rows_loaded = Column(Integer, nullable=True)
    notes = Column(String, nullable=True)


ALL_TABLES = [
    DimCustomer, DimSeller, DimProduct, DimDate,
    FactOrder, FactOrderItem, FactPayment, FactReview,
    EtlRunLog,
]
