"""Turn one Locust run directory into one CSV row.

Reads RUN_DIR/locust_stats.csv (written by Locust, measured part of the run only)
and RUN_DIR/metrics.json (the api's /metrics counters after the run).

Usage: python bench/record_run.py RUN_DIR OUT_CSV key=value ...      (a finished run)
       python bench/record_run.py --failed OUT_CSV key=value ...     (a run that failed)
       python bench/record_run.py --invalid RUN_DIR OUT_CSV key=value ...
           (measured, but not comparable, e.g. the laptop lost AC power: the
            numbers are kept as evidence and every summary and chart skips them)
A row with the same key=value labels as an existing row replaces it, so a
re-run overwrites the earlier attempt instead of adding a duplicate.
"""
import csv
import json
import sys
from pathlib import Path

FIELDS = ["status", "requests", "failures", "rps", "p50_ms", "p95_ms", "p99_ms",
          "hold_requests", "hold_rps", "hold_p50_ms", "hold_p95_ms", "hold_p99_ms",
          "holds_won", "holds_lost", "holds_error",
          "retries_40001", "retries_40P01", "aborts_40001", "aborts_40P01"]


def parse(run_dir: Path) -> dict:
    with (run_dir / "locust_stats.csv").open() as f:
        stats = {r["Name"]: r for r in csv.DictReader(f)}
    total = stats["Aggregated"]
    hold = next((r for name, r in stats.items() if name.startswith("hold")), None)
    counters = json.loads((run_dir / "metrics.json").read_text())["counters"]
    row = {
        "status": "ok",
        "requests": total["Request Count"], "failures": total["Failure Count"],
        "rps": round(float(total["Requests/s"]), 2),
        "p50_ms": total["50%"], "p95_ms": total["95%"], "p99_ms": total["99%"],
    }
    if hold:
        row.update({"hold_requests": hold["Request Count"], "hold_rps": round(float(hold["Requests/s"]), 2),
                    "hold_p50_ms": hold["50%"], "hold_p95_ms": hold["95%"], "hold_p99_ms": hold["99%"]})
    for key in ["holds.won", "holds.lost", "holds.error", "retries.40001", "retries.40P01",
                "aborts.40001", "aborts.40P01"]:
        row[key.replace(".", "_")] = counters.get(key, 0)
    return row


def main(argv):
    if argv[0] == "--failed":
        out, labels = Path(argv[1]), argv[2:]
        row = {"status": "failed"}
    else:
        status = "ok"
        if argv[0] == "--invalid":
            status, argv = "invalid", argv[1:]
        run_dir, out, labels = Path(argv[0]), Path(argv[1]), argv[2:]
        row = {**parse(run_dir), "status": status}
    label_values = dict(pair.split("=", 1) for pair in labels)
    fields = list(label_values) + FIELDS
    rows = []
    if out.exists():
        with out.open() as f:
            rows = [r for r in csv.DictReader(f)
                    if any(r.get(k) != v for k, v in label_values.items())]
    rows.append({**label_values, **row})
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, restval="")
        writer.writeheader()
        writer.writerows(rows)
    print({**label_values, **row})


if __name__ == "__main__":
    main(sys.argv[1:])
