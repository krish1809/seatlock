"""Read-only queries: events and their seats."""
from app.db import transaction

# The availability query (measured in bench/index_study.py, guarded in tests).
# It filters on status = 'AVAILABLE' only. A seat whose hold expired shows up
# here once the expiry sweeper resets it (app/services/expiry.py). Writes never
# depend on that: every hold strategy treats an expired hold as free itself.
AVAILABLE_SEATS_SQL = """
SELECT es.seat_id, s.section, s.row_label, s.seat_no, es.price
FROM event_seats AS es
JOIN seats AS s ON s.id = es.seat_id
WHERE es.event_id = %s AND es.status = 'AVAILABLE'
ORDER BY es.seat_id
"""

ALL_SEATS_SQL = """
SELECT es.seat_id, s.section, s.row_label, s.seat_no, es.price, es.status
FROM event_seats AS es
JOIN seats AS s ON s.id = es.seat_id
WHERE es.event_id = %s
ORDER BY es.seat_id
"""


def list_events() -> list[dict]:
    with transaction() as conn:
        return conn.execute("SELECT id, venue_id, name, starts_at FROM events ORDER BY id").fetchall()


def list_seats(event_id: int, available_only: bool) -> list[dict] | None:
    """Seats of one event, or None if the event does not exist."""
    with transaction() as conn:
        if conn.execute("SELECT 1 FROM events WHERE id = %s", (event_id,)).fetchone() is None:
            return None
        sql = AVAILABLE_SEATS_SQL if available_only else ALL_SEATS_SQL
        return conn.execute(sql, (event_id,)).fetchall()
