from contextlib import asynccontextmanager
from typing import Literal

import psycopg
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout
from pydantic import BaseModel, Field

from app import metrics
from app.db import POOL_SIZE, pool
from app.errors import Conflict, NotFound
from app.services import bookings, events, expiry, holds


@asynccontextmanager
async def lifespan(app: FastAPI):
    # wait=True: if Postgres is unreachable, fail at startup instead of on the first request.
    pool.open(wait=True, timeout=10)
    stop_sweeper = expiry.start_sweeper()
    yield
    if stop_sweeper:
        stop_sweeper.set()
    pool.close()


app = FastAPI(title="SeatLock", lifespan=lifespan)


# ---- error mapping (README.md) --------------------------------------------

SQLSTATE_TO_HTTP = {
    "23505": 409,  # unique_violation, e.g. a second active booking for a seat
    "23514": 400,  # check_violation: a value the schema does not allow
    "23503": 400,  # foreign_key_violation: unknown user, event or seat
    "55P03": 409,  # lock_not_available: lock_timeout expired, the seat is busy
    "40001": 409,  # serialization_failure that persisted through 3 retries
    "40P01": 409,  # deadlock_detected that persisted through 3 retries
}


@app.exception_handler(psycopg.Error)
async def database_error(request: Request, exc: psycopg.Error):
    status = SQLSTATE_TO_HTTP.get(exc.sqlstate, 500)
    detail = exc.diag.message_primary if status != 500 else "database error"
    return JSONResponse(status_code=status, content={"detail": detail, "sqlstate": exc.sqlstate})


@app.exception_handler(PoolTimeout)
async def pool_exhausted(request: Request, exc: PoolTimeout):
    # Every pooled connection stayed busy for DB_POOL_TIMEOUT_S: shed load cleanly.
    return JSONResponse(status_code=503, content={"detail": "no database connection available"})


@app.exception_handler(Conflict)
async def conflict(request: Request, exc: Conflict):
    return JSONResponse(status_code=409, content={"detail": exc.message, "seat_ids": exc.seat_ids})


@app.exception_handler(NotFound)
async def not_found(request: Request, exc: NotFound):
    return JSONResponse(status_code=404, content={"detail": "not found"})


# ---- endpoints --------------------------------------------------------------
# Plain `def`, not `async def`: FastAPI runs them in a worker thread, so
# blocking psycopg calls do not stall the event loop.

class HoldRequest(BaseModel):
    user_id: int
    seat_ids: list[int] = Field(min_length=1, max_length=6)


class BestAvailableRequest(BaseModel):
    user_id: int
    count: int = Field(ge=1, le=6)
    section: str


class BookingRequest(BaseModel):
    user_id: int
    event_id: int
    seat_ids: list[int] = Field(min_length=1, max_length=6)


@app.get("/health")
def health():
    # pool.connection() commits on exit, so this is one short transaction.
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/events")
def list_events():
    return events.list_events()


@app.get("/events/{event_id}/seats")
def list_seats(event_id: int, status: Literal["available"] | None = None):
    seats = events.list_seats(event_id, available_only=status == "available")
    if seats is None:
        raise NotFound()
    return seats


@app.post("/events/{event_id}/holds", status_code=201)
def create_hold(event_id: int, body: HoldRequest):
    result = holds.hold_seats(event_id, body.seat_ids, body.user_id)
    if not result.success:
        raise Conflict("seats not available", result.unavailable)
    return {
        "event_id": event_id,
        "user_id": body.user_id,
        "seat_ids": result.held,
        "held_until": result.held_until,
        "strategy": holds.get_strategy().name,
    }


@app.post("/events/{event_id}/holds/best-available", status_code=201)
def create_best_available_hold(event_id: int, body: BestAvailableRequest):
    result = holds.hold_best_available(event_id, body.section, body.count, body.user_id)
    if not result.success:
        raise Conflict(f"fewer than {body.count} free seats in section {body.section}")
    return {
        "event_id": event_id,
        "user_id": body.user_id,
        "seat_ids": result.held,
        "held_until": result.held_until,
    }


@app.post("/bookings", status_code=201)
def create_booking(
    body: BookingRequest,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
):
    booking, created = bookings.confirm(body.user_id, body.event_id, body.seat_ids, idempotency_key)
    if not created:
        response.status_code = 200  # a replay of an earlier request: same booking, nothing new
    return booking


@app.delete("/bookings/{booking_id}")
def cancel_booking(booking_id: int):
    return bookings.cancel(booking_id)


@app.get("/metrics")
def get_metrics():
    """Counters since this process started: hold outcomes, retries and give-ups by SQLSTATE."""
    return {"strategy": holds.get_strategy().name, "pool_size": POOL_SIZE, "counters": metrics.snapshot()}


@app.post("/admin/expire-holds")
def expire_holds():
    return {"released": expiry.expire_holds()}
