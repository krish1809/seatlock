"""Each test attempts one invalid write and asserts the exact SQLSTATE.

23514 = check_violation, 23505 = unique_violation. These prove the database
itself rejects bad data, independent of any application code.
"""
import psycopg
import pytest


def sqlstate_of(db, sql, params=()):
    with pytest.raises(psycopg.Error) as exc:
        db.execute(sql, params)
    return exc.value.sqlstate


def create_booking(db, key, user_id=1, event_id=1):
    return db.execute(
        "INSERT INTO bookings (user_id, event_id, idempotency_key) VALUES (%s, %s, %s) RETURNING id",
        (user_id, event_id, key),
    ).fetchone()[0]


def add_item(db, booking_id, event_id=1, seat_id=1, price=150):
    db.execute(
        "INSERT INTO booking_items (booking_id, event_id, seat_id, price) VALUES (%s, %s, %s, %s)",
        (booking_id, event_id, seat_id, price),
    )


def test_invalid_status_rejected(db):
    sql = "UPDATE event_seats SET status = 'SOLD' WHERE event_id = 1 AND seat_id = 1"
    assert sqlstate_of(db, sql) == "23514"


def test_negative_price_rejected(db):
    sql = "UPDATE event_seats SET price = -1 WHERE event_id = 1 AND seat_id = 1"
    assert sqlstate_of(db, sql) == "23514"


def test_held_without_held_until_rejected(db):
    sql = """UPDATE event_seats SET status = 'HELD', held_by = 1, held_until = NULL
             WHERE event_id = 1 AND seat_id = 1"""
    assert sqlstate_of(db, sql) == "23514"


def test_hold_fields_on_available_seat_rejected(db):
    sql = """UPDATE event_seats SET held_by = 1, held_until = now()
             WHERE event_id = 1 AND seat_id = 1"""
    assert sqlstate_of(db, sql) == "23514"


def test_duplicate_seat_in_venue_rejected(db):
    # Seat 1 is venue 1, VIP, row A, seat 1 in the small seed.
    sql = "INSERT INTO seats (venue_id, section, row_label, seat_no) VALUES (1, 'VIP', 'A', 1)"
    assert sqlstate_of(db, sql) == "23505"


def test_duplicate_idempotency_key_rejected(db):
    create_booking(db, "key-1")
    sql = "INSERT INTO bookings (user_id, event_id, idempotency_key) VALUES (2, 1, 'key-1')"
    assert sqlstate_of(db, sql) == "23505"


def test_two_active_items_for_same_seat_rejected(db):
    first = create_booking(db, "key-1", user_id=1)
    second = create_booking(db, "key-2", user_id=2)
    add_item(db, first, seat_id=1)
    with pytest.raises(psycopg.Error) as exc:
        add_item(db, second, seat_id=1)
    assert exc.value.sqlstate == "23505"


def test_seat_can_be_rebooked_after_cancellation(db):
    first = create_booking(db, "key-1", user_id=1)
    second = create_booking(db, "key-2", user_id=2)
    add_item(db, first, seat_id=1)
    db.execute("UPDATE booking_items SET cancelled_at = now() WHERE booking_id = %s", (first,))

    add_item(db, second, seat_id=1)  # must not raise: the partial index ignores cancelled items

    active = db.execute(
        "SELECT booking_id FROM booking_items WHERE event_id = 1 AND seat_id = 1 AND cancelled_at IS NULL"
    ).fetchall()
    assert active == [(second,)]
