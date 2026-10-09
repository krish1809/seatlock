"""Hold expiry, with a 1-second hold duration set through HOLD_SECONDS."""
import time

import psycopg
import pytest

from app.errors import Conflict
from app.services import bookings, expiry
from app.services.holds import hold_seats

from conftest import TEST_URL

CORRECT = ["pessimistic", "optimistic", "conditional", "serializable"]


@pytest.fixture(autouse=True)
def one_second_holds(monkeypatch):
    monkeypatch.setenv("HOLD_SECONDS", "1")


def wait_for_expiry():
    time.sleep(1.2)


def seat_row(db, seat_id):
    return db.execute(
        "SELECT status, held_by, held_until, version FROM event_seats WHERE event_id = 1 AND seat_id = %s",
        (seat_id,),
    ).fetchone()


def test_sweeper_releases_expired_holds(db):
    assert hold_seats(1, [1, 2], user_id=1).success
    assert expiry.expire_holds() == 0  # not expired yet

    wait_for_expiry()

    assert expiry.expire_holds() == 2
    assert seat_row(db, 1)[:3] == ("AVAILABLE", None, None)


@pytest.mark.parametrize("strategy", CORRECT)
def test_expired_hold_can_be_taken_by_another_user(strategy, db):
    assert hold_seats(1, [1], user_id=1, strategy_name=strategy).success
    assert not hold_seats(1, [1], user_id=2, strategy_name=strategy).success  # still held

    wait_for_expiry()  # no sweeper run: the strategy itself must see the hold as expired

    assert hold_seats(1, [1], user_id=2, strategy_name=strategy).success
    assert seat_row(db, 1)[:2] == ("HELD", 2)


def test_confirm_rejects_an_expired_hold(db):
    assert hold_seats(1, [1], user_id=1).success
    wait_for_expiry()

    with pytest.raises(Conflict) as exc:
        bookings.confirm(1, 1, [1], "key-expired")

    assert exc.value.seat_ids == [1]
    assert db.execute("SELECT count(*) FROM bookings").fetchone()[0] == 0  # booking insert rolled back


def test_sweeper_skips_rows_locked_by_another_transaction(db):
    assert hold_seats(1, [1, 2], user_id=1).success
    wait_for_expiry()

    with psycopg.connect(TEST_URL) as other:
        other.execute("SELECT 1 FROM event_seats WHERE event_id = 1 AND seat_id = 1 FOR UPDATE")
        started = time.monotonic()
        released = expiry.expire_holds()  # must not wait for seat 1's lock
        elapsed = time.monotonic() - started
        other.rollback()

    assert released == 1  # seat 2 only
    assert elapsed < 1.0
    assert seat_row(db, 1)[0] == "HELD" and seat_row(db, 2)[0] == "AVAILABLE"
