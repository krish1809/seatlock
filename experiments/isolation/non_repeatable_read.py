"""Non-repeatable read. T1 reads seat 1's status twice in one transaction. Between
the two reads, T2 books the seat and commits. The anomaly is T1 getting two
different answers to the same question inside one transaction."""
from runner import Step

READ = "SELECT status FROM event_seats WHERE event_id = 1 AND seat_id = 1"


def steps(level):
    return [
        Step("T1", f"BEGIN ISOLATION LEVEL {level}"),
        Step("T1", READ, key="first_read"),
        Step("T2", f"BEGIN ISOLATION LEVEL {level}"),
        Step("T2", "UPDATE event_seats SET status = 'BOOKED', version = version + 1 "
                   "WHERE event_id = 1 AND seat_id = 1"),
        Step("T2", "COMMIT"),
        Step("T1", READ, key="second_read"),
        Step("T1", "COMMIT"),
    ]


def judge(ctx, monitor) -> bool:
    return ctx["first_read"]["rows"] != ctx["second_read"]["rows"]
