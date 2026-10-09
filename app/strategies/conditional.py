"""Conditional: one UPDATE that only matches free seats. No prior read.

How it prevents double booking: the "is it free?" check is in the UPDATE's
WHERE clause, and Postgres evaluates it while holding the row lock. If two
transactions target the same seat, the second blocks on the first one's row
lock. At READ COMMITTED, once the first commits, Postgres re-evaluates the WHERE
against the newest row version (status HELD, hold not expired), the row no
longer matches, and it is skipped. RETURNING says which seats we actually got;
if fewer came back than we asked for, the transaction is rolled back.

Lock order: a plain UPDATE locks rows in whatever order its plan visits them.
With an index scan on the primary key that is ascending seat_id, but after
002_indexes.sql the planner switched to a bitmap heap scan, which visits rows
in physical order (tests/test_concurrency.py caught this). So the CTE locks the
requested rows first, ORDER BY seat_id, and the UPDATE only touches rows it
already holds: ascending order no matter which plan is chosen.

Cost: one statement and one round trip, and the check runs under the lock. A
requested seat that is not free is still locked briefly until the rollback.
"""
from app.strategies.base import HoldResult, HoldStrategy, hold_seconds

HOLD_IF_FREE_SQL = """
WITH locked AS (
    SELECT seat_id
    FROM event_seats
    WHERE event_id = %(event_id)s AND seat_id = ANY(%(seat_ids)s)
    ORDER BY seat_id
    FOR UPDATE
)
UPDATE event_seats AS es
SET status = 'HELD', held_by = %(user_id)s,
    held_until = now() + %(seconds)s * interval '1 second',
    version = es.version + 1
FROM locked
WHERE es.event_id = %(event_id)s AND es.seat_id = locked.seat_id
  AND (es.status = 'AVAILABLE' OR (es.status = 'HELD' AND es.held_until < now()))
RETURNING es.seat_id, es.held_until
"""


class ConditionalStrategy(HoldStrategy):
    name = "conditional"

    def hold(self, conn, event_id, seat_ids, user_id):
        params = {"event_id": event_id, "seat_ids": seat_ids, "user_id": user_id, "seconds": hold_seconds()}
        rows = conn.execute(HOLD_IF_FREE_SQL, params).fetchall()
        got = {r["seat_id"] for r in rows}
        if len(got) < len(seat_ids):
            return HoldResult(success=False, unavailable=[s for s in seat_ids if s not in got])
        return HoldResult(success=True, held=seat_ids, held_until=rows[0]["held_until"])
