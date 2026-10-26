"""
dashboard/app.py — a Streamlit dashboard sitting on top of the warehouse.

Run it with:  streamlit run dashboard/app.py

This file deliberately does NOT recompute business logic in Python — every
number on this dashboard comes from running one of the .sql files in sql/
against the database. That's the point: the warehouse (built by
run_pipeline.py) is the single source of truth, and this dashboard is just
a thin presentation layer over it. Change a metric definition once, in the
SQL file, and both a data analyst querying the database directly AND this
dashboard see the same number.
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import get_engine

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

st.set_page_config(page_title="E-Commerce Data Warehouse", layout="wide")


@st.cache_resource
def get_conn():
    return get_engine()


@st.cache_data(ttl=600)
def run_sql(filename: str) -> pd.DataFrame:
    sql = (SQL_DIR / filename).read_text()
    return pd.read_sql(sql, get_conn())


st.title("📦 E-Commerce Order-to-Delivery Data Warehouse")
st.caption(
    "Built from the Olist Brazilian E-Commerce public dataset. "
    "Every chart below is powered directly by a SQL query in sql/ — "
    "see the expander under each chart to read the query that produced it."
)

try:
    monthly = run_sql("03_monthly_revenue_trend.sql")
except Exception as exc:
    st.error(
        "Could not read the warehouse database. Have you run "
        "`python run_pipeline.py` yet? \n\nDetails: " + str(exc)
    )
    st.stop()

tab_revenue, tab_delivery, tab_rfm, tab_categories = st.tabs(
    ["Revenue Trend", "Delivery Performance", "Customer Segments (RFM)", "Top Categories"]
)

# --- Revenue trend -----------------------------------------------------
with tab_revenue:
    st.subheader("Monthly revenue and month-over-month growth")
    monthly["period"] = monthly["year"].astype(str) + "-" + monthly["month"].astype(str).str.zfill(2)

    col1, col2, col3 = st.columns(3)
    col1.metric("Total revenue", f"R$ {monthly['revenue'].sum():,.0f}")
    col2.metric("Total orders", f"{monthly['orders'].sum():,.0f}")
    col3.metric("Avg order value", f"R$ {monthly['revenue'].sum() / monthly['orders'].sum():,.2f}")

    st.line_chart(monthly.set_index("period")["revenue"])
    st.bar_chart(monthly.set_index("period")["mom_growth_pct"])
    st.dataframe(monthly, width="stretch")
    with st.expander("SQL behind this tab"):
        st.code((SQL_DIR / "03_monthly_revenue_trend.sql").read_text(), language="sql")

# --- Delivery performance -----------------------------------------------
with tab_delivery:
    st.subheader("Late-delivery rate by state")
    delivery = run_sql("02_delivery_performance.sql")

    col1, col2 = st.columns(2)
    col1.metric("Worst state (late %)", delivery.iloc[0]["state"], f"{delivery.iloc[0]['late_pct']}%")
    col2.metric("Best state (late %)", delivery.iloc[-1]["state"], f"{delivery.iloc[-1]['late_pct']}%")

    st.bar_chart(delivery.set_index("state")["late_pct"])
    st.dataframe(delivery, width="stretch")
    with st.expander("SQL behind this tab"):
        st.code((SQL_DIR / "02_delivery_performance.sql").read_text(), language="sql")

# --- RFM segmentation -----------------------------------------------------
with tab_rfm:
    st.subheader("Customer segments (Recency / Frequency / Monetary)")
    rfm = run_sql("01_rfm_segmentation.sql")

    segment_counts = rfm["rfm_segment"].value_counts()
    st.bar_chart(segment_counts)

    segment_filter = st.selectbox("Filter by segment", ["All"] + sorted(rfm["rfm_segment"].unique().tolist()))
    shown = rfm if segment_filter == "All" else rfm[rfm["rfm_segment"] == segment_filter]
    st.dataframe(shown.head(200), width="stretch")
    with st.expander("SQL behind this tab"):
        st.code((SQL_DIR / "01_rfm_segmentation.sql").read_text(), language="sql")

# --- Top categories -----------------------------------------------------
with tab_categories:
    st.subheader("Best-selling product category per state")
    categories = run_sql("04_top_categories_by_state.sql")
    st.dataframe(categories, width="stretch")
    with st.expander("SQL behind this tab"):
        st.code((SQL_DIR / "04_top_categories_by_state.sql").read_text(), language="sql")

st.divider()
st.caption(
    "Data pipeline: raw CSVs -> pandas transform -> SQLAlchemy load -> "
    "SQLite star schema. See run_pipeline.py and src/etl.py."
)
