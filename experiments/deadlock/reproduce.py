"""Reproduce a deadlock, print PostgreSQL's full error, then count them at scale.

Part 1: T1 locks seat A then B, T2 locks B then A. A barrier makes sure both
hold their first lock before either asks for the second, so the cycle is
guaranteed: each waits for a lock the other holds. Postgres detects the cycle
and aborts one of them with SQLSTATE 40P01.

Part 2: 1,000 random opposing pairs with no barrier between the two locks, so
whether each pair deadlocks depends on timing. Counts the 40P01 errors.

Usage: python experiments/deadlock/reproduce.py   (or `make deadlock`)
"""
import sys
import threading
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).parent))
from common import EVENT_ID, LOCK_SQL, connect, random_pairs, record, reseed, run_pairs  # noqa: E402

SEAT_A, SEAT_B = 1, 2


def forced_deadlock():
    both_hold_first_lock = threading.Barrier(2)
    errors = []

    def txn(name, first, second):
        with connect() as conn:  # default deadlock_timeout (1s), as in production
            conn.execute(LOCK_SQL, (EVENT_ID, first))
            print(f"{name}: locked seat {first}, now asking for seat {second}")
            both_hold_first_lock.wait()
            try:
                conn.execute(LOCK_SQL, (EVENT_ID, second))
                conn.commit()
                print(f"{name}: got seat {second} and committed (the other one was the victim)")
            except psycopg.Error as e:
                errors.append((name, e))
                conn.rollback()

    threads = [threading.Thread(target=txn, args=("T1", SEAT_A, SEAT_B)),
               threading.Thread(target=txn, args=("T2", SEAT_B, SEAT_A))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for name, e in errors:
        d = e.diag
        print(f"\n{name} was aborted. The full error from PostgreSQL:\n")
        print(f"ERROR:  {d.message_primary}")
        print(f"DETAIL:  {d.message_detail}")
        print(f"HINT:  {d.message_hint}")
        print(f"CONTEXT:  {d.context}")
        print(f"SQLSTATE: {e.sqlstate}")


if __name__ == "__main__":
    reseed()
    print("== Part 1: one forced deadlock ==")
    forced_deadlock()

    print("\n== Part 2: 1,000 random opposing pairs, unordered locking ==")
    result = run_pairs(random_pairs(1000), ordered=False)
    print(result)
    record("unordered", result)
