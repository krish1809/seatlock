"""Shared code for the deadlock experiments.

Runs against DATABASE_URL (the dev database) and reseeds it with seed_small.sql.
Run inside the api container: `make deadlock`.
"""
import csv
import os
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]
RESULTS_CSV = ROOT / "bench" / "results" / "deadlocks.csv"
EVENT_ID = 1
SEATS = range(1, 201)  # event 1 has seats 1-200 in the small seed

# Postgres only checks for a deadlock after a transaction has waited this long
# (default 1s). A lower value makes 1,000 pairs finish in seconds instead of
# minutes; it changes how fast a deadlock is detected, not whether it happens.
DEADLOCK_TIMEOUT_MS = 100

LOCK_SQL = "SELECT 1 FROM event_seats WHERE event_id = %s AND seat_id = %s FOR UPDATE"


def connect(**kwargs) -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"], **kwargs)


def reseed():
    with connect(autocommit=True) as conn, conn.transaction():
        conn.execute((ROOT / "db" / "seed" / "seed_small.sql").read_text())


def random_pairs(n: int, seed: int = 42) -> list[tuple[int, int]]:
    """n pairs of two distinct seats. The same seed gives the same pairs."""
    rng = random.Random(seed)
    return [tuple(rng.sample(SEATS, 2)) for _ in range(n)]


def run_pairs(pairs, ordered: bool) -> dict:
    """For each (a, b): T1 locks a then b while T2 locks b then a, at the same time.

    ordered=True sorts each transaction's seats first, so both lock the lower
    seat_id first. Returns counts of 40P01 (deadlock_detected) errors.
    """
    start = threading.Barrier(2)
    done = threading.Barrier(2)
    deadlocks = [0, 0]

    def worker(idx):
        with connect() as conn:
            conn.execute(f"SET deadlock_timeout = {DEADLOCK_TIMEOUT_MS}")
            conn.commit()
            for a, b in pairs:
                seats = [a, b] if idx == 0 else [b, a]  # opposite orders
                if ordered:
                    seats.sort()
                start.wait()  # both transactions begin together
                try:
                    for seat in seats:
                        conn.execute(LOCK_SQL, (EVENT_ID, seat))
                    conn.commit()
                except psycopg.errors.DeadlockDetected:
                    deadlocks[idx] += 1
                    conn.rollback()
                done.wait()  # next pair only once both are finished

    t0 = time.monotonic()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return {"pairs": len(pairs), "deadlocks_40P01": sum(deadlocks), "elapsed_s": round(time.monotonic() - t0, 2)}


def record(variant: str, result: dict):
    """Write or replace this variant's row in bench/results/deadlocks.csv."""
    fields = ["variant", "pairs", "deadlocks_40P01", "deadlock_timeout_ms", "elapsed_s", "recorded_at"]
    rows = []
    if RESULTS_CSV.exists():
        with RESULTS_CSV.open() as f:
            rows = [r for r in csv.DictReader(f) if r["variant"] != variant]
    rows.append({"variant": variant, **result, "deadlock_timeout_ms": DEADLOCK_TIMEOUT_MS,
                 "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    rows.sort(key=lambda r: r["variant"])
    with RESULTS_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
