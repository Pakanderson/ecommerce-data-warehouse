#!/usr/bin/env python3
"""
run_pipeline.py — the single command that builds the whole warehouse.

Usage:
    python run_pipeline.py

That's it. It will:
  1. connect to the database (SQLite by default — see src/db.py)
  2. drop and recreate every table
  3. extract the raw CSVs, transform them into the star schema, load them
  4. print a summary

This is the file you'd point a scheduler (cron, Airflow, Prefect — see the
companion supply-chain-pipeline project for an orchestrated version of this
same idea) at to run the pipeline on a schedule.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.db import get_engine, DATABASE_URL
from src.etl import run_full_pipeline


def main() -> None:
    print(f"Target database: {DATABASE_URL}")
    engine = get_engine()
    total_rows = run_full_pipeline(engine)
    print(f"\nDone. {total_rows:,} rows loaded into the warehouse.")
    print("Try: sqlite3 db/ecommerce.db  (or open it with any SQLite browser)")
    print("Or run the dashboard: streamlit run dashboard/app.py")


if __name__ == "__main__":
    main()
