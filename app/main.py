from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.db import pool
from app.services import events, holds


@asynccontextmanager
async def lifespan(app: FastAPI):
    # wait=True: if Postgres is unreachable, fail at startup instead of on the first request.
    pool.open(wait=True, timeout=10)
    yield
    pool.close()


app = FastAPI(title="SeatLock", lifespan=lifespan)


class HoldRequest(BaseModel):
    user_id: int
    seat_ids: list[int] = Field(min_length=1, max_length=6)


# Endpoints are plain `def`, not `async def`: FastAPI runs them in a worker
# thread, so blocking psycopg calls do not stall the event loop.
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
        raise HTTPException(404, "event not found")
    return seats


@app.post("/events/{event_id}/holds", status_code=201)
def create_hold(event_id: int, body: HoldRequest):
    result = holds.hold_seats(event_id, body.seat_ids, body.user_id)
    if not result.success:
        raise HTTPException(409, {"message": "seats not available", "seat_ids": result.unavailable})
    return {
        "event_id": event_id,
        "user_id": body.user_id,
        "seat_ids": result.held,
        "held_until": result.held_until,
        "strategy": holds.get_strategy().name,
    }
