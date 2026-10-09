"""Confirm and cancel bookings. Each public function is one short transaction.

Lock order on every path: the booking row first, then event_seats rows in
ascending seat_id order. Holds lock only event_seats, in the same order, so no
two of these transactions can wait on each other in a cycle.
"""
from app.db import transaction, with_retries
from app.errors import Conflict, NotFound


@with_retries
def confirm(user_id: int, event_id: int, seat_ids: list[int], idempotency_key: str) -> tuple[dict, bool]:
    """Turn the user's held seats into a booking.

    Returns (booking, created). created is False when an earlier request with
    the same idempotency key already made the booking; nothing changes then.
    """
    seat_ids = sorted(set(seat_ids))
    with transaction() as conn:
        row = conn.execute(
            """
            INSERT INTO bookings (user_id, event_id, idempotency_key)
            VALUES (%s, %s, %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
            """,
            (user_id, event_id, idempotency_key),
        ).fetchone()
        if row is None:
            # The key was used before. If that first request is still running,
            # the INSERT above waited for it to finish; it committed, so its
            # booking is visible to this next statement (READ COMMITTED).
            return _load(conn, "idempotency_key", idempotency_key), False

        booking_id = row["id"]
        _lock_and_check_holds(conn, user_id, event_id, seat_ids)
        _insert_items(conn, booking_id, event_id, seat_ids)
        _mark_booked(conn, event_id, seat_ids)
        return _load(conn, "id", booking_id), True


def _lock_and_check_holds(conn, user_id, event_id, seat_ids):
    # FOR UPDATE: from here until commit nobody (holds, the expiry sweeper,
    # another confirm) can change these seats under us.
    rows = conn.execute(
        """
        SELECT seat_id, status, held_by, held_until > now() AS hold_active
        FROM event_seats
        WHERE event_id = %s AND seat_id = ANY(%s)
        ORDER BY seat_id
        FOR UPDATE
        """,
        (event_id, seat_ids),
    ).fetchall()
    mine = {r["seat_id"] for r in rows
            if r["status"] == "HELD" and r["held_by"] == user_id and r["hold_active"]}
    not_mine = [s for s in seat_ids if s not in mine]
    if not_mine:
        # Raising inside the transaction rolls back the booking INSERT too.
        raise Conflict("seats are not held by this user, or the hold has expired", not_mine)


def _insert_items(conn, booking_id, event_id, seat_ids):
    # Copies the current price: the booking keeps it even if the price changes later.
    conn.execute(
        """
        INSERT INTO booking_items (booking_id, event_id, seat_id, price)
        SELECT %s, event_id, seat_id, price
        FROM event_seats
        WHERE event_id = %s AND seat_id = ANY(%s)
        """,
        (booking_id, event_id, seat_ids),
    )


def _mark_booked(conn, event_id, seat_ids):
    conn.execute(
        """
        UPDATE event_seats
        SET status = 'BOOKED', held_by = NULL, held_until = NULL, version = version + 1
        WHERE event_id = %s AND seat_id = ANY(%s)
        """,
        (event_id, seat_ids),
    )


@with_retries
def cancel(booking_id: int) -> dict:
    """Cancel a whole booking and make its seats AVAILABLE again.

    Cancelling an already cancelled booking changes nothing and returns it.
    """
    with transaction() as conn:
        # Locks the booking row, so two cancels of the same booking serialize.
        row = conn.execute(
            "UPDATE bookings SET status = 'CANCELLED' WHERE id = %s AND status = 'CONFIRMED' RETURNING event_id",
            (booking_id,),
        ).fetchone()
        if row is None:
            booking = _load(conn, "id", booking_id)
            if booking is None:
                raise NotFound()
            return booking

        event_id = row["event_id"]
        items = conn.execute(
            "UPDATE booking_items SET cancelled_at = now() WHERE booking_id = %s AND cancelled_at IS NULL RETURNING seat_id",
            (booking_id,),
        ).fetchall()
        seat_ids = sorted(r["seat_id"] for r in items)
        # Lock the seats in ascending order first, like every other path.
        conn.execute(
            "SELECT 1 FROM event_seats WHERE event_id = %s AND seat_id = ANY(%s) ORDER BY seat_id FOR UPDATE",
            (event_id, seat_ids),
        )
        conn.execute(
            """
            UPDATE event_seats
            SET status = 'AVAILABLE', version = version + 1
            WHERE event_id = %s AND seat_id = ANY(%s) AND status = 'BOOKED'
            """,
            (event_id, seat_ids),
        )
        return _load(conn, "id", booking_id)


# Only these two lookup columns are allowed; the column name is never user input.
_LOAD_SQL = {
    "id": "SELECT id, user_id, event_id, status, idempotency_key, created_at FROM bookings WHERE id = %s",
    "idempotency_key": "SELECT id, user_id, event_id, status, idempotency_key, created_at FROM bookings WHERE idempotency_key = %s",
}


def _load(conn, column: str, value) -> dict | None:
    booking = conn.execute(_LOAD_SQL[column], (value,)).fetchone()
    if booking is None:
        return None
    booking["seats"] = conn.execute(
        "SELECT seat_id, price, cancelled_at FROM booking_items WHERE booking_id = %s ORDER BY seat_id",
        (booking["id"],),
    ).fetchall()
    return booking
