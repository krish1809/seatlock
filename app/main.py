from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    # wait=True: if Postgres is unreachable, fail at startup instead of on the first request.
    pool.open(wait=True, timeout=10)
    yield
    pool.close()


app = FastAPI(title="SeatLock", lifespan=lifespan)


# Plain `def`, not `async def`: FastAPI runs it in a worker thread, so the
# blocking psycopg call does not stall the event loop.
@app.get("/health")
def health():
    # pool.connection() commits on exit, so this is one short transaction.
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}
