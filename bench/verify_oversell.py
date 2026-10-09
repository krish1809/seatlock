"""Count double bookings in one hot-seat run, from the Locust log and the database.

From the log: a seat is oversold when two successful hold responses for it
overlap in time. Each hold covers [held_until - HOLD_SECONDS, held_until], where
the start is the holding transaction's now(). A legitimate re-hold can only
start after the previous held_until, because every strategy requires
held_until < now() to take a held seat. Any overlap is a double booking.

From the database: the run has the expiry sweeper off, so every write to a hot
seat is a hold, and each bumps `version` by one. The sum of the hot seats'
versions must equal the number of seat holds the api reports in /metrics
(holds.won_seats). This checks the counting, not oversell by itself. The client
log can be a few holds short of the api: requests still in flight when Locust
stops are committed by the api but never logged (in_flight_at_stop).

Usage: python bench/verify_oversell.py RUN_DIR STRATEGY CLIENTS REPEAT
Appends a row to bench/results/oversell.csv.
"""
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "bench" / "results" / "oversell.csv"
HOT_EVENT, HOT_SEATS = 1, list(range(1, 51))


def main(run_dir: Path, strategy: str, clients: str, repeat: str):
    hold_seconds = float(os.environ["HOLD_SECONDS"])
    windows = defaultdict(list)  # seat_id -> [(start, end, user_id)]
    successes = 0
    for line in (run_dir / "holds.jsonl").read_text().splitlines():
        hold = json.loads(line)
        end = datetime.fromisoformat(hold["held_until"])
        for seat in hold["seat_ids"]:
            windows[seat].append((end - timedelta(seconds=hold_seconds), end, hold["user_id"]))
            successes += 1

    overlapping_holds, oversold_seats = 0, 0
    for seat, holds in windows.items():
        holds.sort()
        latest_end, seat_oversold = None, False
        for start, end, _ in holds:
            if latest_end is not None and start < latest_end:
                overlapping_holds += 1
                seat_oversold = True
            latest_end = end if latest_end is None else max(latest_end, end)
        oversold_seats += seat_oversold

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        version_total = conn.execute(
            "SELECT sum(version) FROM event_seats WHERE event_id = %s AND seat_id = ANY(%s)",
            (HOT_EVENT, HOT_SEATS)).fetchone()[0]

    api_seat_holds = json.loads((run_dir / "metrics.json").read_text())["counters"].get("holds.won_seats", 0)
    row = {"strategy": strategy, "clients": clients, "repeat": repeat,
           "logged_seat_holds": successes, "overlapping_holds": overlapping_holds,
           "oversold_seats": oversold_seats, "api_seat_holds": api_seat_holds,
           "db_version_total": version_total, "db_matches_api": version_total == api_seat_holds,
           "in_flight_at_stop": api_seat_holds - successes}
    new_file = not OUT.exists()
    with OUT.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        if new_file:
            writer.writeheader()
        writer.writerow(row)
    print(row)


if __name__ == "__main__":
    main(Path(sys.argv[1]), *sys.argv[2:5])
