"""Best available uses FOR UPDATE SKIP LOCKED: it skips locked seats instead of waiting."""
import time

import psycopg

from app.services.holds import hold_best_available

from conftest import TEST_URL


def test_takes_the_first_free_seats_of_the_section():
    result = hold_best_available(1, "LOWER", 2, user_id=1)
    assert result.success and result.held == [51, 52]  # LOWER starts at seat 51 in the small seed


def test_skips_seats_locked_by_another_transaction_without_waiting(db):
    with psycopg.connect(TEST_URL) as other:
        # An open transaction holds row locks on the first two VIP seats.
        other.execute("SELECT 1 FROM event_seats WHERE event_id = 1 AND seat_id IN (1, 2) FOR UPDATE")

        started = time.monotonic()
        result = hold_best_available(1, "VIP", 2, user_id=1)
        elapsed = time.monotonic() - started

        other.rollback()

    assert result.success and result.held == [3, 4]
    assert elapsed < 0.5  # well under lock_timeout: it never waited for seats 1 and 2


def test_all_or_nothing_when_not_enough_seats(db):
    db.execute("UPDATE event_seats SET status = 'BOOKED' WHERE event_id = 1 AND seat_id BETWEEN 1 AND 49")

    result = hold_best_available(1, "VIP", 2, user_id=1)  # only seat 50 is left

    assert not result.success
    assert db.execute("SELECT status FROM event_seats WHERE event_id = 1 AND seat_id = 50").fetchone()[0] == "AVAILABLE"


def test_endpoint(api):
    status, body = api("POST", "/events/1/holds/best-available", {"user_id": 1, "count": 3, "section": "UPPER"})
    assert status == 201 and body["seat_ids"] == [101, 102, 103]
