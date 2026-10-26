# E-Commerce Order-to-Delivery Data Warehouse & Analytics Pipeline

A small but real ETL pipeline that turns raw, messy e-commerce export files
into a proper relational data warehouse, plus a dashboard on top of it.
Built to demonstrate the "boring but essential" data engineering skills
that show up in almost every Data Analyst / Data Scientist job posting:
**SQL, database schema design, SQLAlchemy, and ETL pipeline construction.**

## What this project demonstrates

| Skill | Where |
|---|---|
| pandas data cleaning | `src/etl.py` (`transform()`) |
| SQLAlchemy ORM schema design (star schema) | `src/models.py` |
| ETL pipeline construction (extract/transform/load) | `src/etl.py`, `run_pipeline.py` |
| SQL: joins, CTEs, window functions | `sql/*.sql` |
| Automated testing of a data pipeline | `tests/test_etl.py` |
| Dashboarding on top of a warehouse | `dashboard/app.py` |

## The data

[Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
— ~100,000 real orders placed at multiple marketplaces in Brazil between
2016 and 2018, split across 8 relational CSV files (customers, orders,
order items, payments, reviews, products, sellers, category translations).
It's genuinely messy: missing delivery dates, orders that were never
delivered, products with missing category names — exactly the kind of data
you'd actually be handed at a job, not a pre-cleaned Kaggle-competition
dataset.

## Architecture

```
data/raw/*.csv  --extract-->  pandas DataFrames  --transform-->  star schema
                                                                  DataFrames
                                                                       |
                                                                    load
                                                                       v
                                                          SQLite (db/ecommerce.db)
                                                          via SQLAlchemy ORM
                                                                       |
                                              +------------------------+------------------------+
                                              |                                                 |
                                   sql/*.sql analytical queries                      dashboard/app.py
                                   (RFM, delivery, revenue, categories)              (Streamlit)
```

The database is a **star schema**: dimension tables (`dim_customer`,
`dim_seller`, `dim_product`, `dim_date`) hold descriptive attributes, and
fact tables (`fact_order`, `fact_order_item`, `fact_payment`,
`fact_review`) hold the numeric business events, linked to dimensions by
integer surrogate keys. Full reasoning for this design is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Quickstart

```bash
# 1. install dependencies
pip install -r requirements.txt

# 2. download the raw dataset into data/raw/ (not committed to the repo —
#    see scripts/fetch_data.py for why, and for the manual/Kaggle alternative)
python scripts/fetch_data.py

# 3. build the warehouse (reads data/raw/*.csv, writes db/ecommerce.db)
python run_pipeline.py

# 4. explore the results
streamlit run dashboard/app.py

# 5. run the test suite
pytest
```

The pipeline defaults to a local SQLite file — no database server to
install. To point it at Postgres instead, set one environment variable:

```bash
export DATABASE_URL="postgresql+psycopg2://user:password@localhost:5432/ecommerce"
python run_pipeline.py
```

## Project structure

```
ecommerce-data-warehouse/
├── scripts/fetch_data.py  downloads the raw CSVs into data/raw/ (run this first)
├── data/raw/           raw source CSVs live here once fetched (not modified by the pipeline)
├── db/                 the built SQLite database lives here
├── src/
│   ├── db.py            database connection/engine setup
│   ├── models.py         SQLAlchemy ORM models = the star schema
│   └── etl.py            extract() / transform() / load() functions
├── sql/                 four analytical queries, each with an explanatory comment header
├── tests/               pytest suite: schema integrity + idempotency checks
├── dashboard/app.py      Streamlit dashboard (reads sql/*.sql, not its own logic)
├── docs/
│   └── ARCHITECTURE.md   design decisions, explained
├── run_pipeline.py       single entrypoint: run the whole ETL
└── requirements.txt
```

## Sample insight

Running `sql/02_delivery_performance.sql` against the built warehouse
shows Alagoas (AL) has both the highest late-delivery rate (~24%) and one
of the shorter average delays when late — worth flagging to a logistics
team as a "frequent but small" delay pattern rather than a rare
catastrophic one. That's the kind of one-line business insight this
warehouse is built to surface quickly.

## Attribution

Dataset: Olist Store, made available on Kaggle under a CC BY-NC-SA 4.0
license. This project uses it purely for educational/portfolio purposes.

## Author

**Dr. Paul Kwaku Larbi Anderson**, Data Scientist & Social Scientist
[LinkedIn](https://www.linkedin.com/in/paul-kl-anderson) · [GitHub](https://github.com/Pakanderson)
