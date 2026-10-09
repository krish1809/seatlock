"""Index study for the availability query on event_seats.

For the data currently loaded (one tier: run after `make seed-large`) and each of
three index configurations:
  none     only the primary key (event_id, seat_id)
  plain    index on (event_id, status)
  partial  index on (event_id) WHERE status = 'AVAILABLE'
it creates the index, runs ANALYZE, runs the availability query
(app/services/events.py) for 20 random events with EXPLAIN (ANALYZE, BUFFERS,
FORMAT JSON), discards the first 3 runs, and records medians. It also saves one
human-readable plan per configuration to docs/explain-plans/.

Usage: python bench/index_study.py --tier 1M     (`make index-study` runs both tiers)
"""
import argparse
import csv
import os
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.services.events import AVAILABLE_SEATS_SQL  # noqa: E402

RESULTS_CSV = ROOT / "bench" / "results" / "index_study.csv"
PLANS_DIR = ROOT / "docs" / "explain-plans"
EVENTS_PER_CONFIG = 20
DISCARD_FIRST = 3

CONFIGS = {
    "none": None,
    "plain": "CREATE INDEX idx_study_plain ON event_seats (event_id, status)",
    "partial": "CREATE INDEX idx_study_partial ON event_seats (event_id) WHERE status = 'AVAILABLE'",
}
INDEX_NAME = {"plain": "idx_study_plain", "partial": "idx_study_partial"}
# Indexes from 002_indexes.sql that would interfere with the "none" baseline.
PRODUCTION_INDEXES = ["idx_event_seats_available", "idx_event_seats_held_until"]


def drop_indexes(conn):
    for name in [*INDEX_NAME.values(), *PRODUCTION_INDEXES]:
        conn.execute(f"DROP INDEX IF EXISTS {name}")  # names are constants above


def find_scan(node):
    """The plan node that reads event_seats, and a label like 'Index Scan using x'."""
    if node.get("Relation Name") == "event_seats":
        index = node.get("Index Name") or next(
            (c.get("Index Name") for c in node.get("Plans", []) if c.get("Index Name")), None)
        return node, node["Node Type"] + (f" using {index}" if index else "")
    for child in node.get("Plans", []):
        found = find_scan(child)
        if found:
            return found
    return None


def buffers(node) -> int:
    return node.get("Shared Hit Blocks", 0) + node.get("Shared Read Blocks", 0)


def measure(conn, event_ids) -> dict:
    runs = []
    for event_id in event_ids:
        plan = conn.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + AVAILABLE_SEATS_SQL,
                            (event_id,)).fetchone()[0][0]
        scan, label = find_scan(plan["Plan"])
        runs.append({"exec_ms": plan["Execution Time"], "buffers": buffers(plan["Plan"]),
                     "scan_buffers": buffers(scan), "scan_ms": scan["Actual Total Time"],
                     "rows": plan["Plan"]["Actual Rows"], "scan": label})
    kept = runs[DISCARD_FIRST:]  # the first runs warm the cache
    return {
        "scan_node": kept[-1]["scan"],
        "median_execution_ms": round(statistics.median(r["exec_ms"] for r in kept), 3),
        "median_scan_ms": round(statistics.median(r["scan_ms"] for r in kept), 3),
        "median_shared_buffers": statistics.median(r["buffers"] for r in kept),
        "median_scan_buffers": statistics.median(r["scan_buffers"] for r in kept),
        "median_rows": statistics.median(r["rows"] for r in kept),
        "runs_measured": len(kept),
    }


def save_plan(conn, tier, config, event_id):
    lines = [r[0] for r in conn.execute("EXPLAIN (ANALYZE, BUFFERS) " + AVAILABLE_SEATS_SQL, (event_id,)).fetchall()]
    header = [
        f"-- tier {tier}, index config '{config}', event_id {event_id}",
        f"-- recorded {datetime.now(timezone.utc).isoformat(timespec='seconds')} by bench/index_study.py",
        "-- EXPLAIN (ANALYZE, BUFFERS) " + " ".join(AVAILABLE_SEATS_SQL.split()).replace("%s", str(event_id)),
        "",
    ]
    (PLANS_DIR / f"{tier}_{config}.txt").write_text("\n".join(header + lines) + "\n")


def write_rows(new_rows):
    rows = []
    if RESULTS_CSV.exists():
        with RESULTS_CSV.open() as f:
            keys = {(r["tier"], r["config"]) for r in new_rows}
            rows = [r for r in csv.DictReader(f) if (r["tier"], r["config"]) not in keys]
    rows += new_rows
    rows.sort(key=lambda r: (r["event_seats_rows"] if isinstance(r["event_seats_rows"], int) else int(r["event_seats_rows"]),
                             list(CONFIGS).index(r["config"])))
    with RESULTS_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(new_rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", required=True, help="label for this data size, e.g. 1M or 10M")
    tier = parser.parse_args().tier

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        total = conn.execute("SELECT count(*) FROM event_seats").fetchone()[0]
        all_events = [r[0] for r in conn.execute("SELECT id FROM events ORDER BY id")]
        event_ids = random.Random(42).sample(all_events, min(EVENTS_PER_CONFIG, len(all_events)))
        print(f"tier {tier}: {total} event_seats rows, {len(all_events)} events")

        rows = []
        for config, ddl in CONFIGS.items():
            drop_indexes(conn)
            if ddl:
                conn.execute(ddl)
            conn.execute("ANALYZE event_seats")
            size = conn.execute("SELECT pg_relation_size(%s)", (INDEX_NAME[config],)).fetchone()[0] if ddl else 0
            result = measure(conn, event_ids)
            save_plan(conn, tier, config, event_ids[-1])
            row = {"tier": tier, "event_seats_rows": total, "config": config, "index_size_bytes": size, **result}
            print(row)
            rows.append(row)
        drop_indexes(conn)

        # Put back the production indexes if migration 002 is already applied.
        applied = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE filename = '002_indexes.sql'").fetchone()
        if applied:
            conn.execute((ROOT / "db" / "migrations" / "002_indexes.sql").read_text())
            conn.execute("ANALYZE event_seats")
            print("restored the indexes from 002_indexes.sql")
    write_rows(rows)


if __name__ == "__main__":
    main()
