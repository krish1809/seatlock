"""Lost update. Both transactions read seat 1's version, add 1 in the application,
and write it back. If both commit, one increment is silently lost: the final
version is 1, not 2. (This is the read-modify-write the optimistic strategy avoids
by putting `version = <what I read>` in the UPDATE's WHERE clause.)"""
from runner import Step

READ = "SELECT version FROM event_seats WHERE event_id = 1 AND seat_id = 1"
WRITE = "UPDATE event_seats SET version = %s WHERE event_id = 1 AND seat_id = 1"


def steps(level):
    return [
        Step("T1", f"BEGIN ISOLATION LEVEL {level}"),
        Step("T2", f"BEGIN ISOLATION LEVEL {level}"),
        Step("T1", READ, key="t1_read"),
        Step("T2", READ, key="t2_read"),
        Step("T1", lambda ctx: (WRITE, (ctx["t1_read"]["rows"][0][0] + 1,)), note="write t1_read + 1"),
        Step("T2", lambda ctx: (WRITE, (ctx["t2_read"]["rows"][0][0] + 1,)), note="write t2_read + 1"),
        Step("T1", "COMMIT"),
        Step("T2", "COMMIT", key="t2_commit"),
    ]


def judge(ctx, monitor) -> bool:
    """Anomaly if T2 committed and the final version shows only one increment."""
    final = monitor.execute(READ).fetchone()[0]
    t2_committed = ctx["t2_commit"]["ok"] and ctx["t2_commit"]["status"] == "COMMIT"
    return t2_committed and final == ctx["t1_read"]["rows"][0][0] + 1
