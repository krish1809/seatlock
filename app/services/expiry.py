"""Release expired holds: one UPDATE, and a background timer that runs it.

Correctness never depends on this sweeper: every hold strategy already treats
an expired hold as free. The sweeper only resets the rows so the availability
listing (status = 'AVAILABLE') shows them again.
"""
import logging
import os
import threading

from app.db import transaction

log = logging.getLogger("seatlock.expiry")

# SKIP LOCKED: a locked row belongs to a transaction that is holding or
# confirming that seat right now. The sweeper skips it instead of waiting, so
# it never blocks a request and can never take part in a deadlock. Anything
# skipped is picked up on the next run if it is still expired.
EXPIRE_SQL = """
WITH expired AS (
    SELECT event_id, seat_id
    FROM event_seats
    WHERE status = 'HELD' AND held_until < now()
    ORDER BY event_id, seat_id
    FOR UPDATE SKIP LOCKED
)
UPDATE event_seats AS es
SET status = 'AVAILABLE', held_by = NULL, held_until = NULL, version = es.version + 1
FROM expired
WHERE es.event_id = expired.event_id AND es.seat_id = expired.seat_id
"""


def expire_holds() -> int:
    """Release every expired hold; returns how many seats were released."""
    with transaction() as conn:
        return conn.execute(EXPIRE_SQL).rowcount


def start_sweeper() -> threading.Event | None:
    """Run expire_holds every EXPIRY_SWEEP_SECONDS in a daemon thread.

    Returns an Event; set it to stop the thread. 0 disables the sweeper.
    """
    interval = float(os.environ.get("EXPIRY_SWEEP_SECONDS", "5"))
    if interval <= 0:
        return None
    stop = threading.Event()

    def run():
        # Event.wait returns False on timeout and True once stop is set.
        while not stop.wait(interval):
            try:
                expire_holds()
            except Exception:
                log.exception("expiry sweep failed; will retry next interval")

    threading.Thread(target=run, name="expiry-sweeper", daemon=True).start()
    return stop
