"""Pessimistic: lock the rows first, then check, then write.

How it prevents double booking: SELECT ... FOR UPDATE takes a row lock on each
requested seat before its status is used. A second transaction asking for the
same seat blocks on that lock until the first one commits. At READ COMMITTED it
then gets the newest version of the row (status HELD), so the check fails and it
backs off. Nobody can change a locked row between our check and our UPDATE.

Cost: contending transactions wait in line, each holding a pooled connection
while it waits; a hot seat is served one transaction at a time. ORDER BY seat_id
makes the locks be taken in ascending seat_id order (the LockRows step runs after
the sort), so two multi-seat holds can never deadlock each other.
"""
from app.strategies.base import HoldResult, HoldStrategy, mark_held


class PessimisticStrategy(HoldStrategy):
    name = "pessimistic"

    def hold(self, conn, event_id, seat_ids, user_id):
        rows = conn.execute(
            """
            SELECT seat_id,
                   (status = 'AVAILABLE' OR (status = 'HELD' AND held_until < now())) AS free
            FROM event_seats
            WHERE event_id = %s AND seat_id = ANY(%s)
            ORDER BY seat_id
            FOR UPDATE
            """,
            (event_id, seat_ids),
        ).fetchall()
        free = {r["seat_id"] for r in rows if r["free"]}
        unavailable = [s for s in seat_ids if s not in free]
        if unavailable:
            return HoldResult(success=False, unavailable=unavailable)

        # Safe: we hold the row locks, so the status we just checked cannot change.
        held_until = mark_held(conn, event_id, seat_ids, user_id)
        return HoldResult(success=True, held=seat_ids, held_until=held_until)
