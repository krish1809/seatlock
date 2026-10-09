"""Optimistic: read without locking, then write only if nothing changed.

How it prevents double booking: every UPDATE of event_seats bumps `version`.
We read each seat's version and check it is free, then run
UPDATE ... WHERE version = <the version we read>. If another transaction changed
the row in between, the version no longer matches, zero rows are updated, and
we know we lost the race. (If that other transaction has not committed yet, our
UPDATE waits for its row lock, then re-checks the WHERE against the committed
row, sees the new version, and matches nothing.)

Why the WHERE has no `status = 'AVAILABLE'`: a seat whose hold expired is free
but still says HELD. The version check alone proves the row is exactly as we
read it, including the status and held_until we just checked.

Cost: no waiting during the read, but a lost race is only discovered at write
time and the whole multi-seat transaction is rolled back. Under heavy contention
most attempts lose. Seats are updated in ascending seat_id order (the order of
seat_ids), so the row locks taken by the UPDATEs cannot deadlock.
"""
from app.strategies.base import HoldResult, HoldStrategy, hold_seconds


class OptimisticStrategy(HoldStrategy):
    name = "optimistic"

    def hold(self, conn, event_id, seat_ids, user_id):
        rows = conn.execute(
            """
            SELECT seat_id, version
            FROM event_seats
            WHERE event_id = %s AND seat_id = ANY(%s)
              AND (status = 'AVAILABLE' OR (status = 'HELD' AND held_until < now()))
            """,
            (event_id, seat_ids),
        ).fetchall()
        versions = {r["seat_id"]: r["version"] for r in rows}
        unavailable = [s for s in seat_ids if s not in versions]
        if unavailable:
            return HoldResult(success=False, unavailable=unavailable)

        held_until = None
        for seat_id in seat_ids:
            row = conn.execute(
                """
                UPDATE event_seats
                SET status = 'HELD', held_by = %s,
                    held_until = now() + %s * interval '1 second',
                    version = version + 1
                WHERE event_id = %s AND seat_id = %s AND version = %s
                RETURNING held_until
                """,
                (user_id, hold_seconds(), event_id, seat_id, versions[seat_id]),
            ).fetchone()
            if row is None:
                # Someone changed this seat after we read it: we lost the race.
                return HoldResult(success=False, unavailable=[seat_id])
            held_until = row["held_until"]
        return HoldResult(success=True, held=seat_ids, held_until=held_until)
