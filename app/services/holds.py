"""Hold service: picks the strategy and owns the transaction around it."""
import os

import psycopg

from app.db import transaction, with_retries
from app.strategies.base import HoldResult, HoldStrategy
from app.strategies.naive import NaiveStrategy

STRATEGIES: dict[str, HoldStrategy] = {s.name: s for s in [NaiveStrategy()]}


def get_strategy(name: str | None = None) -> HoldStrategy:
    name = name or os.environ.get("HOLD_STRATEGY", "naive")
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
