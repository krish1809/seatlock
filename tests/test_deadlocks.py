"""Ordered locking: opposing multi-seat holds never deadlock.

Each pair: user A asks for seats [a, b, c] while user B asks for [c, b, a], at
the same moment. Without a global lock order this is the classic deadlock
(experiments/deadlock/ measured 822 deadlocks in 1,000 unordered pairs). The
hold service sorts seat ids, so it must produce zero 40P01, and therefore no
retries or give-ups for 40P01 in the api's counters.
"""
import random
import threading

import pytest

from app import metrics
from app.services.holds import hold_seats

PAIRS = 200
POOL = list(range(1, 7))  # few seats, so every pair overlaps


@pytest.mark.parametrize("strategy", ["pessimistic", "optimistic", "conditional", "serializable"])
def test_200_opposing_pairs_produce_no_deadlock(strategy, db):
    before = metrics.snapshot()
    rng = random.Random(7)
    barrier = threading.Barrier(2)
    errors = []

    def holder(seats, user_id):
        barrier.wait()
        try:
            hold_seats(1, seats, user_id, strategy_name=strategy)
        except Exception as e:
            errors.append(e)

    for _ in range(PAIRS):
        seats = rng.sample(POOL, 3)
        threads = [threading.Thread(target=holder, args=(seats, 1)),
                   threading.Thread(target=holder, args=(seats[::-1], 2))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        db.execute("UPDATE event_seats SET status = 'AVAILABLE', held_by = NULL, held_until = NULL "
                   "WHERE event_id = 1 AND seat_id = ANY(%s)", (POOL,))

    after = metrics.snapshot()
    deadlocks = sum(after.get(k, 0) - before.get(k, 0) for k in ("retries.40P01", "aborts.40P01"))
    assert deadlocks == 0
    assert [e for e in errors if getattr(e, "sqlstate", None) == "40P01"] == []
