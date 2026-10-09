"""Atomicity: a failure halfway through a confirm leaves no trace."""
import pytest

from app.services import bookings
from app.services.holds import hold_seats


def test_failure_after_inserting_items_persists_nothing(db, monkeypatch):
    assert hold_seats(1, [1, 2], user_id=1).success

    def explode(conn, event_id, seat_ids):
        # By now the booking row and its items are inserted in this transaction.
        inserted = conn.execute("SELECT count(*) AS n FROM booking_items").fetchone()["n"]
        assert inserted == 2
        raise RuntimeError("injected failure")

    monkeypatch.setattr(bookings, "_mark_booked", explode)

    with pytest.raises(RuntimeError, match="injected failure"):
        bookings.confirm(1, 1, [1, 2], "key-atomic")

    assert db.execute("SELECT count(*) FROM bookings").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM booking_items").fetchone()[0] == 0
    seats = db.execute(
        "SELECT seat_id, status, held_by FROM event_seats WHERE event_id = 1 AND seat_id IN (1, 2) ORDER BY seat_id"
    ).fetchall()
    assert seats == [(1, "HELD", 1), (2, "HELD", 1)]  # still held, as before the confirm
