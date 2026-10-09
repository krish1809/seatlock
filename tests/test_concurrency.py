"""Many threads race for the same seats at the same instant.

A threading.Barrier releases all threads together, and every thread has its
own pooled connection (DB_POOL_SIZE >= N in conftest), so the transactions
really overlap inside Postgres.
"""
import random
import threading

import pytest

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
    results = race("naive", lambda i: [1])
    won = winners(results)
    assert won, "at least one thread must get the seat"
    holder = db.execute("SELECT held_by FROM event_seats WHERE event_id = 1 AND seat_id = 1").fetchone()[0]
    if len(won) > 1:
        pytest.xfail(f"naive race: {len(won)} of {N} threads were told they hold seat 1; "
                     f"the row says user {holder}")


# ---- correct strategies -------------------------------------------------

CORRECT = ["pessimistic", "optimistic", "conditional", "serializable"]


@pytest.mark.parametrize("strategy", CORRECT)
def test_exactly_one_of_50_wins_a_seat(strategy, db):
    results = race(strategy, lambda i: [1])

    errors = [r for r in results if isinstance(r, Exception)]
    assert errors == []
    won = [i for i, r in enumerate(results) if r.success]
    assert len(won) == 1
    holder = db.execute("SELECT held_by FROM event_seats WHERE event_id = 1 AND seat_id = 1").fetchone()[0]
    assert holder == won[0] + 1  # the row agrees with the one thread told it won


@pytest.mark.parametrize("strategy", CORRECT)
def test_three_seat_holds_are_all_or_nothing_under_contention(strategy, db):
    # Every thread asks for 3 of the seats 1-6, in a shuffled order, so the
    # requests overlap heavily and arrive in opposite orders.
    def seats_for(i):
        return random.Random(i).sample(range(1, 7), 3)

    results = race(strategy, seats_for)

    assert [r for r in results if isinstance(r, Exception)] == []
    held_rows = dict(db.execute(
        "SELECT seat_id, held_by FROM event_seats WHERE event_id = 1 AND status = 'HELD'"
    ).fetchall())
    winners_seats = {i + 1: set(seats_for(i)) for i, r in enumerate(results) if r.success}
    assert winners_seats, "someone must win"
    # Each winner holds all 3 of its seats, and nobody else holds anything.
    expected = {seat: user for user, seats in winners_seats.items() for seat in seats}
    assert held_rows == expected
    assert len(expected) == 3 * len(winners_seats)  # winners' seat sets are disjoint


@pytest.mark.parametrize("strategy", CORRECT)
def test_failed_multi_seat_hold_changes_nothing(strategy, db):
    assert hold_seats(EVENT_ID, [2], user_id=1, strategy_name=strategy).success

    result = hold_seats(EVENT_ID, [3, 2, 1], user_id=2, strategy_name=strategy)

    assert not result.success and result.unavailable == [2]
    rows = db.execute(
        "SELECT seat_id, status, held_by, version FROM event_seats WHERE event_id = 1 AND seat_id IN (1, 3) ORDER BY seat_id"
    ).fetchall()
    assert rows == [(1, "AVAILABLE", None, 0), (3, "AVAILABLE", None, 0)]  # rolled back, untouched


def test_conditional_update_locks_rows_in_seat_id_order(db):
    """The conditional hold must lock rows in ascending seat_id, whatever the plan.

    The rows are locked by a LockRows node; its input must be sorted by seat_id
    (a Sort, or an index scan on the primary key, which returns that order).
    """
    from app.strategies.conditional import HOLD_IF_FREE_SQL

    params = {"event_id": 1, "seat_ids": [5, 2, 9], "user_id": 1, "seconds": 300}
    plan = db.execute("EXPLAIN (FORMAT JSON, VERBOSE) " + HOLD_IF_FREE_SQL, params).fetchone()[0][0]["Plan"]

    def nodes(node):
        yield node
        for child in node.get("Plans", []):
            yield from nodes(child)

    lock_rows = [n for n in nodes(plan) if n["Node Type"] == "LockRows"]
    assert len(lock_rows) == 1
    feeder = lock_rows[0]["Plans"][0]
    ordered_by_sort = feeder["Node Type"] == "Sort" and feeder["Sort Key"] == ["event_seats.seat_id"]
    ordered_by_pk = feeder["Node Type"] == "Index Scan" and feeder["Index Name"] == "event_seats_pkey"
    assert ordered_by_sort or ordered_by_pk, feeder
