"""Naive: read, decide in Python, then write. INTENTIONALLY BROKEN. Do not fix.

This is the baseline that demonstrates the double-booking race.

At READ COMMITTED the SELECT takes no lock. Two transactions can both read a
seat as free and both decide to hold it. The UPDATE does not re-check the
status, so the second UPDATE waits for the first one's row lock, then goes
ahead and overwrites it. Both callers are told they hold the seat.
"""
from app.strategies.base import HoldResult, HoldStrategy, mark_held


class NaiveStrategy(HoldStrategy):
    name = "naive"

    def hold(self, conn, event_id, seat_ids, user_id):
        rows = conn.execute(
            """
            SELECT seat_id
            FROM event_seats
            WHERE event_id = %s AND seat_id = ANY(%s)
              AND (status = 'AVAILABLE' OR (status = 'HELD' AND held_until < now()))
            """,
            (event_id, seat_ids),
        ).fetchall()
        free = {r["seat_id"] for r in rows}
        unavailable = [s for s in seat_ids if s not in free]
        if unavailable:
            return HoldResult(success=False, unavailable=unavailable)

        # THE RACE WINDOW: another transaction can hold these seats right here,
        # and mark_held's UPDATE does not re-check the status, so it will not notice.
        held_until = mark_held(conn, event_id, seat_ids, user_id)
        return HoldResult(success=True, held=seat_ids, held_until=held_until)
