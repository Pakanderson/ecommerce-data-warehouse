"""
db.py — where the database "lives".

This is the one place in the whole project that knows the database connection
string. Every other module asks THIS file for an engine/session instead of
building its own connection string. That's a deliberate pattern: if you ever
want to swap SQLite for Postgres (which is exactly what a real company would
do when this project "graduates" from a laptop prototype to production), you
change ONE line here and nothing else in the codebase has to change.

How to explain this in an interview:
"I centralized the database configuration behind a single get_engine()
function so the rest of the pipeline is database-agnostic — it just asks
SQLAlchemy for a session and doesn't care if that session points at SQLite
or Postgres."
"""

import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Default: a SQLite file sitting in db/ecommerce.db. SQLite needs zero setup
# (no server to install/run), which is why it's the default for a portfolio
# project — anyone who clones the repo can run it immediately.
#
# To point this at Postgres instead (e.g. for a "production" deployment),
# set the DATABASE_URL environment variable, for example:
#   export DATABASE_URL="postgresql+psycopg2://user:password@localhost:5432/ecommerce"
# No code changes needed — that's the whole point of this file.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "db" / "ecommerce.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_SQLITE_PATH}"

DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def get_engine(echo: bool = False):
    """
    Create a SQLAlchemy Engine — the object that actually knows how to
    talk to the database (open connections, run SQL, etc.).

    echo=True is handy while developing: it prints every SQL statement
    SQLAlchemy sends to the database, which is a great way to *see* what
    the ORM is doing under the hood instead of trusting it blindly.
    """
    connect_args = {}
    if DATABASE_URL.startswith("sqlite"):
        # SQLite by default only allows the thread that created a connection
        # to use it. Streamlit and pytest both juggle threads, so we relax
        # that restriction. This is a SQLite-only quirk — Postgres doesn't
        # need this.
        connect_args = {"check_same_thread": False}
    return create_engine(DATABASE_URL, echo=echo, connect_args=connect_args)


def get_session_factory(engine=None) -> sessionmaker:
    """Return a sessionmaker bound to the given (or default) engine."""
    engine = engine or get_engine()
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session(engine=None) -> Session:
    """Convenience: get a single ready-to-use Session."""
    return get_session_factory(engine)()
