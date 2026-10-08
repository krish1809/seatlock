"""Database access: the connection pool, short transactions, and retries."""
import functools
import logging
import os
import random
import time
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

log = logging.getLogger("seatlock.db")

POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "10"))
# How long a request waits for a free pooled connection before PoolTimeout.
POOL_TIMEOUT_S = float(os.environ.get("DB_POOL_TIMEOUT_S", "10"))
# Give up on a row lock after this long (SQLSTATE 55P03) instead of queueing
# behind a slow transaction indefinitely.
LOCK_TIMEOUT_MS = int(os.environ.get("LOCK_TIMEOUT_MS", "2000"))
# Upper bound on any single statement (SQLSTATE 57014).
STATEMENT_TIMEOUT_MS = int(os.environ.get("STATEMENT_TIMEOUT_MS", "5000"))

# Fixed size (min == max): all connections are opened at startup.
# open=False: opened in the FastAPI lifespan (app/main.py) or by the test fixtures.
pool = ConnectionPool(
    conninfo=os.environ["DATABASE_URL"],
    min_size=POOL_SIZE,
    max_size=POOL_SIZE,
    timeout=POOL_TIMEOUT_S,
    kwargs={
        # Startup options apply to every pooled connection with no extra round trip.
        "options": f"-c lock_timeout={LOCK_TIMEOUT_MS} -c statement_timeout={STATEMENT_TIMEOUT_MS}",
        "row_factory": dict_row,
    },
    open=False,
)

ISOLATION_LEVELS = {
    "READ COMMITTED": "SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
    "REPEATABLE READ": "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
    "SERIALIZABLE": "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE",
}


@contextmanager
def transaction(isolation_level=None):
    """Borrow a pooled connection and run exactly one transaction on it.

    Commits when the block finishes, rolls back when it raises. The connection
    goes back to the pool either way, so no transaction outlives a request.
    """
    with pool.connection() as conn:
        with conn.transaction():
            if isolation_level is not None:
                # SET TRANSACTION applies to this transaction only, so the level
                # never leaks to the next request that borrows this connection.
                conn.execute(ISOLATION_LEVELS[isolation_level])
            yield conn


RETRYABLE = {"40001", "40P01"}  # serialization_failure, deadlock_detected
MAX_RETRIES = 3
BACKOFF_BASE_S = 0.01


def with_retries(fn):
    """Re-run fn when Postgres aborts it with 40001 or 40P01, up to MAX_RETRIES times.

    Both errors mean "your transaction was rolled back; running it again may
    succeed". fn must open its own transaction so every attempt starts fresh.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        for attempt in range(MAX_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except psycopg.Error as e:
                if e.sqlstate not in RETRYABLE or attempt == MAX_RETRIES:
                    raise
                if e.sqlstate == "40P01":
                    log.warning("deadlock detected, retry %d: %s", attempt + 1, e)
                # Full jitter: sleep a random time up to an exponentially growing
                # cap, so transactions that just collided do not retry in lockstep.
                time.sleep(random.uniform(0, BACKOFF_BASE_S * 2 ** attempt))
    return wrapper
