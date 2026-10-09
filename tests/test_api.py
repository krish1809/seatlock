"""The full booking flow over HTTP, and the error mapping."""


def test_hold_confirm_replay_cancel(api, db):
    status, hold = api("POST", "/events/1/holds", {"user_id": 3, "seat_ids": [7, 5]})
    assert status == 201 and hold["seat_ids"] == [5, 7]

    body = {"user_id": 3, "event_id": 1, "seat_ids": [5, 7]}
    status, booking = api("POST", "/bookings", body, {"Idempotency-Key": "flow-1"})
    assert status == 201 and booking["status"] == "CONFIRMED"
    assert [s["seat_id"] for s in booking["seats"]] == [5, 7]

    status, replay = api("POST", "/bookings", body, {"Idempotency-Key": "flow-1"})
    assert status == 200 and replay["id"] == booking["id"]

    status, cancelled = api("DELETE", f"/bookings/{booking['id']}")
    assert status == 200 and cancelled["status"] == "CANCELLED"
    assert all(s["cancelled_at"] for s in cancelled["seats"])
    statuses = db.execute(
        "SELECT status FROM event_seats WHERE event_id = 1 AND seat_id IN (5, 7)"
    ).fetchall()
    assert statuses == [("AVAILABLE",), ("AVAILABLE",)]

    status, again = api("DELETE", f"/bookings/{booking['id']}")
    assert status == 200 and again["status"] == "CANCELLED"  # cancelling twice changes nothing


def test_seats_rebookable_after_cancel(api):
    api("POST", "/events/1/holds", {"user_id": 3, "seat_ids": [5]})
    _, booking = api("POST", "/bookings", {"user_id": 3, "event_id": 1, "seat_ids": [5]}, {"Idempotency-Key": "a"})
    api("DELETE", f"/bookings/{booking['id']}")

    status, _ = api("POST", "/events/1/holds", {"user_id": 4, "seat_ids": [5]})
    assert status == 201
    status, _ = api("POST", "/bookings", {"user_id": 4, "event_id": 1, "seat_ids": [5]}, {"Idempotency-Key": "b"})
    assert status == 201


def test_confirm_seats_not_held_by_user_is_409(api):
    api("POST", "/events/1/holds", {"user_id": 3, "seat_ids": [5]})
    status, body = api("POST", "/bookings", {"user_id": 4, "event_id": 1, "seat_ids": [5]}, {"Idempotency-Key": "x"})
    assert status == 409 and body["seat_ids"] == [5]


def test_unknown_user_is_400_foreign_key_violation(api):
    status, body = api("POST", "/events/1/holds", {"user_id": 9999, "seat_ids": [5]})
    assert status == 400 and body["sqlstate"] == "23503"


def test_cancel_unknown_booking_is_404(api):
    status, _ = api("DELETE", "/bookings/424242")
    assert status == 404


def test_admin_expire_holds(api):
    status, body = api("POST", "/admin/expire-holds")
    assert status == 200 and body == {"released": 0}
