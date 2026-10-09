"""Failure cases end in a clean HTTP error, never a hang or a stuck transaction."""
import psycopg

from app.db import pool

from conftest import TEST_URL


def stuck_transactions(db) -> int:
    return db.execute(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname = current_database() AND state LIKE 'idle in transaction%%' AND pid <> pg_backend_pid()"
    ).fetchone()[0]


def test_lock_timeout_is_a_clean_409(api, db, monkeypatch):
    monkeypatch.setenv("HOLD_STRATEGY", "pessimistic")  # waits for the row lock
    with psycopg.connect(TEST_URL) as other:
        other.execute("SELECT 1 FROM event_seats WHERE event_id = 1 AND seat_id = 1 FOR UPDATE")

        status, body = api("POST", "/events/1/holds", {"user_id": 1, "seat_ids": [1]})

        other.rollback()
    assert status == 409 and body["sqlstate"] == "55P03"  # lock_not_available, after LOCK_TIMEOUT_MS
    assert stuck_transactions(db) == 0


def test_pool_exhaustion_is_a_clean_503_and_recovers(api, db):
    borrowed = [pool.getconn() for _ in range(pool.max_size)]  # every pooled connection is busy
    try:
        status, body = api("GET", "/events/1/seats")  # waits DB_POOL_TIMEOUT_S, then gives up
    finally:
        for conn in borrowed:
            pool.putconn(conn)

    assert status == 503 and body["detail"] == "no database connection available"
    assert stuck_transactions(db) == 0
    status, _ = api("GET", "/events/1/seats")
    assert status == 200  # the pool recovers once connections come back


def test_availability_query_uses_the_partial_index(db):
    """Performance guard: the listing query must be able to use idx_event_seats_available.

    The small seed has every seat AVAILABLE, where any plan is cheap. Book most
    of event 1 first (about the 70% of the large seed) so the index is selective,
    as it is in production-sized data.
    """
    from app.services.events import AVAILABLE_SEATS_SQL

    db.execute("UPDATE event_seats SET status = 'BOOKED' WHERE seat_id % 4 <> 0")
    db.execute("ANALYZE event_seats")
    plan = "\n".join(r[0] for r in db.execute("EXPLAIN " + AVAILABLE_SEATS_SQL, (1,)).fetchall())
    assert "idx_event_seats_available" in plan, plan
