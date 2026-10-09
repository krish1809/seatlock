"""Write skew. Rule: at least one seat in section VIP of event 1 must stay AVAILABLE
for walk-ins. Setup leaves exactly 2 VIP seats available (1 and 2). Each
transaction counts the available VIP seats, sees 2, decides holding one is
allowed, and holds a *different* seat. Neither write touches the row the other
wrote, so no row lock conflicts, yet together they leave 0 available: the rule
is broken although each transaction checked it."""
from runner import Step

SETUP_SQL = """
UPDATE event_seats SET status = 'BOOKED'
WHERE event_id = 1 AND seat_id BETWEEN 3 AND 50
"""

COUNT = """
SELECT count(*)
FROM event_seats AS es
JOIN seats AS s ON s.id = es.seat_id
WHERE es.event_id = 1 AND s.section = 'VIP' AND es.status = 'AVAILABLE'
"""
HOLD = """
UPDATE event_seats
SET status = 'HELD', held_by = %s, held_until = now() + interval '5 minutes', version = version + 1
WHERE event_id = 1 AND seat_id = %s
"""
NOOP = "SELECT 'rule check failed: not holding'"


def hold_if_allowed(count_key, user_id, seat_id):
    def build(ctx):
        available = ctx[count_key]["rows"][0][0]
        # The application-level rule check: holding one must leave at least one.
        return (HOLD, (user_id, seat_id)) if available >= 2 else (NOOP, ())
    return build


def steps(level):
    return [
        Step("T1", f"BEGIN ISOLATION LEVEL {level}"),
        Step("T2", f"BEGIN ISOLATION LEVEL {level}"),
        Step("T1", COUNT, key="t1_count"),
        Step("T2", COUNT, key="t2_count"),
        Step("T1", hold_if_allowed("t1_count", 1, 1), note="if count >= 2, hold seat 1"),
        Step("T2", hold_if_allowed("t2_count", 2, 2), note="if count >= 2, hold seat 2"),
        Step("T1", "COMMIT"),
        Step("T2", "COMMIT"),
    ]


def judge(ctx, monitor) -> bool:
    """Anomaly if the rule is broken in the committed data."""
    return monitor.execute(COUNT).fetchone()[0] == 0
