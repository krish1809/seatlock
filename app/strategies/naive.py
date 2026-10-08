"""Naive: read, decide in Python, then write. INTENTIONALLY BROKEN. Do not fix.

This is the baseline that demonstrates the double-booking race.

At READ COMMITTED the SELECT takes no lock. Two transactions can both read a
seat as free and both decide to hold it. The UPDATE does not re-check the
status, so the second UPDATE waits for the first one's row lock, then goes
ahead and overwrites it. Both callers are told they hold the seat.
"""
from app.strategies.base import HoldResult, HoldStrategy, hold_seconds


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
        # and the UPDATE below will not notice.
        row = conn.execute(
            """
            UPDATE event_seats
            SET status = 'HELD', held_by = %s,
                held_until = now() + %s * interval '1 second',
                version = version + 1
            WHERE event_id = %s AND seat_id = ANY(%s)
            RETURNING held_until
            """,
            (user_id, hold_seconds(), event_id, seat_ids),
        ).fetchone()
        return HoldResult(success=True, held=seat_ids, held_until=row["held_until"])
