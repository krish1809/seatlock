"""A retried confirm (same Idempotency-Key) never creates a second booking."""
import threading

from app.services import bookings
from app.services.holds import hold_seats

SEATS = [10, 11]


def hold_for_user_1():
    assert hold_seats(1, SEATS, user_id=1).success


def count(db, table):
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_same_key_twice_in_sequence(db):
    hold_for_user_1()

    first, created_first = bookings.confirm(1, 1, SEATS, "key-seq")
    second, created_second = bookings.confirm(1, 1, SEATS, "key-seq")

    assert (created_first, created_second) == (True, False)
    assert first["id"] == second["id"]
    assert count(db, "bookings") == 1
    assert count(db, "booking_items") == 2


def test_same_key_ten_times_in_parallel(db):
    hold_for_user_1()
    barrier = threading.Barrier(10)
    results = [None] * 10

    def worker(i):
        barrier.wait()
        try:
            results[i] = bookings.confirm(1, 1, SEATS, "key-par")
        except Exception as e:
            results[i] = e

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert [r for r in results if isinstance(r, Exception)] == []
    assert sum(created for _, created in results) == 1
    assert len({booking["id"] for booking, _ in results}) == 1
    assert count(db, "bookings") == 1
    assert count(db, "booking_items") == 2


def test_replay_over_http_returns_200_with_the_same_booking(api):
    hold_for_user_1()
    body = {"user_id": 1, "event_id": 1, "seat_ids": SEATS}
    headers = {"Idempotency-Key": "key-http"}

    status1, booking1 = api("POST", "/bookings", body, headers)
    status2, booking2 = api("POST", "/bookings", body, headers)

    assert (status1, status2) == (201, 200)
    assert booking1["id"] == booking2["id"]


def test_missing_idempotency_key_is_rejected(api):
    status, _ = api("POST", "/bookings", {"user_id": 1, "event_id": 1, "seat_ids": SEATS})
    assert status == 422


def test_reused_key_with_different_seats_returns_the_original_booking(db):
    """The key wins and the new body is ignored (docs/design-decisions.md, Idempotency)."""
    hold_for_user_1()
    assert hold_seats(1, [20], user_id=1).success

    first, _ = bookings.confirm(1, 1, SEATS, "key-reused")
    second, created = bookings.confirm(1, 1, [20], "key-reused")

    assert not created and second["id"] == first["id"]
    assert [s["seat_id"] for s in second["seats"]] == SEATS
    assert db.execute("SELECT status FROM event_seats WHERE event_id = 1 AND seat_id = 20").fetchone()[0] == "HELD"
