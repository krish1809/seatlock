"""Many threads race for the same seats at the same instant.

A threading.Barrier releases all threads together, and every thread has its
own pooled connection (DB_POOL_SIZE >= N in conftest), so the transactions
really overlap inside Postgres.
"""
import threading

from app.services.holds import hold_seats
from app.strategies.base import HoldResult

N = 50
EVENT_ID = 1


def race(strategy: str, seats_for_thread) -> list:
    """Run N concurrent holds; thread i holds seats_for_thread(i) as user i+1."""
    barrier = threading.Barrier(N)
    results = [None] * N

    def worker(i):
        barrier.wait()
        try:
            results[i] = hold_seats(EVENT_ID, seats_for_thread(i), user_id=i + 1, strategy_name=strategy)
        except Exception as e:  # recorded, not raised: a thread error must not hide the count
            results[i] = e

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def winners(results) -> list[HoldResult]:
    return [r for r in results if isinstance(r, HoldResult) and r.success]


def test_naive_race_demonstration(db):
    """Expected demonstration of the bug, not a correctness check.

    Reported as XFAIL with the count when more than one thread won the seat.
    It can pass by luck if the threads happen not to overlap.
    """
    import pytest

    results = race("naive", lambda i: [1])
    won = winners(results)
    assert won, "at least one thread must get the seat"
    holder = db.execute("SELECT held_by FROM event_seats WHERE event_id = 1 AND seat_id = 1").fetchone()[0]
    if len(won) > 1:
        pytest.xfail(f"naive race: {len(won)} of {N} threads were told they hold seat 1; "
                     f"the row says user {holder}")
