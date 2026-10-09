"""Hold service: picks the strategy and owns the transaction around it."""
import os

import psycopg

from app.db import transaction, with_retries
from app.strategies.base import HoldResult, HoldStrategy, hold_seconds
from app.strategies.conditional import ConditionalStrategy
from app.strategies.naive import NaiveStrategy
from app.strategies.optimistic import OptimisticStrategy
from app.strategies.pessimistic import PessimisticStrategy
from app.strategies.serializable import SerializableStrategy

STRATEGIES: dict[str, HoldStrategy] = {
    s.name: s
    for s in [NaiveStrategy(), PessimisticStrategy(), OptimisticStrategy(),
              ConditionalStrategy(), SerializableStrategy()]
}


def get_strategy(name: str | None = None) -> HoldStrategy:
    name = name or os.environ.get("HOLD_STRATEGY", "pessimistic")
    if name not in STRATEGIES:
        raise ValueError(f"unknown HOLD_STRATEGY {name!r}, expected one of {sorted(STRATEGIES)}")
    return STRATEGIES[name]


def hold_seats(event_id: int, seat_ids: list[int], user_id: int, strategy_name: str | None = None) -> HoldResult:
    strategy = get_strategy(strategy_name)
    # Ascending seat_id is the single lock order every code path uses, so two
    # multi-seat transactions can never wait on each other in a cycle (deadlock).
    return _attempt(strategy, event_id, sorted(set(seat_ids)), user_id)


@with_retries
def _attempt(strategy: HoldStrategy, event_id: int, seat_ids: list[int], user_id: int) -> HoldResult:
    # One attempt = one fresh transaction, so a retry starts from a new snapshot.
    with transaction(strategy.isolation_level) as conn:
        result = strategy.hold(conn, event_id, seat_ids, user_id)
        if not result.success:
            # All-or-nothing: undo any seats this attempt already changed.
            # psycopg.Rollback ends the transaction block with ROLLBACK and is
            # swallowed by it, so execution continues after the `with`.
            raise psycopg.Rollback()
    return result


# Best available: take the first `count` free seats of a section that nobody is
# locking right now. SKIP LOCKED skips rows another transaction has locked
# instead of waiting for them, so concurrent "best available" requests spread
# over different seats rather than queueing behind each other. ORDER BY seat_id
# keeps the lock order ascending, as everywhere else.
BEST_AVAILABLE_SQL = """
WITH picked AS (
    SELECT es.event_id, es.seat_id
    FROM event_seats AS es
    JOIN seats AS s ON s.id = es.seat_id
    WHERE es.event_id = %s AND s.section = %s
      AND (es.status = 'AVAILABLE' OR (es.status = 'HELD' AND es.held_until < now()))
    ORDER BY es.seat_id
    LIMIT %s
    FOR UPDATE OF es SKIP LOCKED
)
UPDATE event_seats AS es
SET status = 'HELD', held_by = %s,
    held_until = now() + %s * interval '1 second',
    version = es.version + 1
FROM picked
WHERE es.event_id = picked.event_id AND es.seat_id = picked.seat_id
RETURNING es.seat_id, es.held_until
"""


@with_retries
def hold_best_available(event_id: int, section: str, count: int, user_id: int) -> HoldResult:
    with transaction() as conn:
        rows = conn.execute(BEST_AVAILABLE_SQL, (event_id, section, count, user_id, hold_seconds())).fetchall()
        if len(rows) < count:
            raise psycopg.Rollback()  # not enough free seats: hold none of them
    if len(rows) < count:
        return HoldResult(success=False)
    seat_ids = sorted(r["seat_id"] for r in rows)
    return HoldResult(success=True, held=seat_ids, held_until=rows[0]["held_until"])
