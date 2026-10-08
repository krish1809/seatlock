"""Shared fixtures.

Tests run against the real Postgres container, but in their own database
(seatlock_test), so `make test` never wipes the dev data that experiments and
benchmarks use. The database is recreated and migrated once per test session,
and reseeded with seed_small.sql before every test.
"""
import os
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parent.parent
SEED_SMALL = (ROOT / "db" / "seed" / "seed_small.sql").read_text()
TEST_DB = "seatlock_test"

# Must run before anything imports `app`: app/db.py reads DATABASE_URL at import.
ADMIN_URL = os.environ["DATABASE_URL"]
os.environ["DATABASE_URL"] = make_conninfo(ADMIN_URL, dbname=TEST_DB)
TEST_URL = os.environ["DATABASE_URL"]
# Enough pooled connections for 50 threads to run their transactions at once.
os.environ["DB_POOL_SIZE"] = "55"


@pytest.fixture(scope="session", autouse=True)
def test_database():
    # CREATE/DROP DATABASE cannot run inside a transaction, hence autocommit.
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DB}")

    from db.migrate import migrate
    migrate(TEST_URL)

    from app.db import pool
    pool.open(wait=True, timeout=10)
    yield
    pool.close()


@pytest.fixture(autouse=True)
def reset_data():
    """Reseed before every test so each one starts from the same known state."""
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        # Fail fast instead of hanging if an earlier test leaked a lock.
        conn.execute("SET lock_timeout = '5s'")
        with conn.transaction():
            conn.execute(SEED_SMALL)


@pytest.fixture
def db():
    """A plain autocommit connection: every statement is its own transaction."""
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        yield conn
