"""Connection pool shared by the whole api process.

Each request borrows a connection for one short transaction and returns it.
"""
import os

from psycopg_pool import ConnectionPool

# Fixed size (min == max): all connections are opened at startup, so early
# requests never wait for a new connection to be established.
POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "10"))

# open=False: the pool is opened in the FastAPI lifespan (app/main.py), not at import.
pool = ConnectionPool(
    conninfo=os.environ["DATABASE_URL"],
    min_size=POOL_SIZE,
    max_size=POOL_SIZE,
    open=False,
)
