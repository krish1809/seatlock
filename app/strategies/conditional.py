"""Conditional: one UPDATE that only matches free seats. No prior read.

How it prevents double booking: the "is it free?" check is in the UPDATE's
WHERE clause, and Postgres evaluates it while holding the row lock. If two
transactions target the same seat, the second blocks on the first one's row
lock. At READ COMMITTED, once the first commits, Postgres re-evaluates the WHERE
against the new row version (status HELD, hold not expired), the row no longer
matches, and it is skipped. RETURNING says which seats we actually got; if
fewer came back than we asked for, the transaction is rolled back.

Cost: the cheapest correct option, one statement and one round trip, and a
loser never sees stale data. Rows are locked in the order the plan visits them.
The plan is an index scan on the primary key (event_id, seat_id), which walks
the seat_id array in ascending order, the same lock order as everywhere else
(tests/test_concurrency.py checks the plan).
"""
from app.strategies.base import HoldResult, HoldStrategy, hold_seconds

HOLD_IF_FREE_SQL = """
UPDATE event_seats
SET status = 'HELD', held_by = %s,
    held_until = now() + %s * interval '1 second',
    version = version + 1
WHERE event_id = %s AND seat_id = ANY(%s)
  AND (status = 'AVAILABLE' OR (status = 'HELD' AND held_until < now()))
RETURNING seat_id, held_until
"""


class ConditionalStrategy(HoldStrategy):
    name = "conditional"

    def hold(self, conn, event_id, seat_ids, user_id):
        rows = conn.execute(HOLD_IF_FREE_SQL, (user_id, hold_seconds(), event_id, seat_ids)).fetchall()
        got = {r["seat_id"] for r in rows}
        if len(got) < len(seat_ids):
            return HoldResult(success=False, unavailable=[s for s in seat_ids if s not in got])
        return HoldResult(success=True, held=seat_ids, held_until=rows[0]["held_until"])
