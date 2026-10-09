"""Print the README's result tables as Markdown, computed from bench/results/*.csv.

Each strategy/client cell is the median of the repeated runs (failed runs are
left out and counted). Run it and paste the output; never edit numbers by hand.

Usage: python bench/summary.py   (or `make summary`)
"""
import csv
import statistics
from collections import defaultdict
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
STRATEGIES = ["naive", "pessimistic", "optimistic", "conditional", "serializable"]


def read(name):
    path = RESULTS / name
    return list(csv.DictReader(path.open())) if path.exists() else []


def med(values):
    return statistics.median(values) if values else None


def show(v, digits=0):
    if v is None:
        return "TODO"
    return f"{v:,.{digits}f}"


def group(rows, *keys):
    out = defaultdict(list)
    for r in rows:
        out[tuple(r[k] for k in keys)].append(r)
    return out


def ok(rows):
    return [r for r in rows if r.get("status", "ok") == "ok"]


def retry_rate(r):
    attempts = int(r["holds_won"]) + int(r["holds_lost"]) + int(r["holds_error"])
    return 100 * (int(r["retries_40001"]) + int(r["retries_40P01"])) / attempts if attempts else 0


def strategy_table(bench, oversell, clients="200"):
    by = group([r for r in bench if r["workload"] == "hot" and r["clients"] == clients], "strategy")
    over = group([r for r in oversell if r["clients"] == clients], "strategy")
    mix = group([r for r in bench if r["workload"] == "mix" and r["clients"] == clients], "strategy")
    print(f"Hot-seat workload, {clients} clients (median of runs; mix = realistic workload, same clients)\n")
    print("| Strategy | Double-booked holds per run | Hold req/s | Hold p50 ms | Hold p99 ms "
          "| Retries per 100 holds | Gave up (409) per run | Mix req/s | Mix p99 ms | Runs ok |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for s in STRATEGIES:
        rows, all_rows = ok(by.get((s,), [])), by.get((s,), [])
        m_rows = ok(mix.get((s,), []))
        aborts = [int(r["aborts_40001"]) + int(r["aborts_40P01"]) for r in rows]
        print(f"| {s} | {show(med([int(r['overlapping_holds']) for r in over.get((s,), [])]))} "
              f"| {show(med([float(r['hold_rps']) for r in rows]))} "
              f"| {show(med([float(r['hold_p50_ms']) for r in rows]))} "
              f"| {show(med([float(r['hold_p99_ms']) for r in rows]))} "
              f"| {show(med([retry_rate(r) for r in rows]), 2)} "
              f"| {show(med(aborts))} "
              f"| {show(med([float(r['rps']) for r in m_rows]))} "
              f"| {show(med([float(r['p99_ms']) for r in m_rows]))} "
              f"| {len(rows)}/{len(all_rows)} hot, {len(m_rows)}/{len(mix.get((s,), []))} mix |")
    print()


def oversell_table(oversell):
    print("Double bookings over every hot-seat run (bench/results/oversell.csv)\n")
    print("| Strategy | Runs | Runs with a double booking | Double-booked holds, total | "
          "Seat holds (api count), total | DB versions match api count |")
    print("| --- | ---: | ---: | ---: | ---: | --- |")
    for s, rows in sorted(group(oversell, "strategy").items(), key=lambda kv: STRATEGIES.index(kv[0][0])):
        bad = sum(int(r["overlapping_holds"]) > 0 for r in rows)
        total = sum(int(r["overlapping_holds"]) for r in rows)
        holds = sum(int(r["api_seat_holds"]) for r in rows)
        match = all(r["db_matches_api"] == "True" for r in rows)
        print(f"| {s[0]} | {len(rows)} | {bad} | {total:,} | {holds:,} | {'all runs' if match else 'NO'} |")
    print()


def throughput_table(bench, workload):
    by = group(ok([r for r in bench if r["workload"] == workload]), "strategy", "clients")
    clients = sorted({int(r["clients"]) for r in bench}, key=int)
    print(f"Requests/s by client count, {workload} workload (median of runs)\n")
    print("| Strategy | " + " | ".join(f"{c} clients" for c in clients) + " |")
    print("| --- |" + " ---: |" * len(clients))
    for s in STRATEGIES:
        cells = [show(med([float(r["rps"]) for r in by.get((s, str(c)), [])])) for c in clients]
        print(f"| {s} | " + " | ".join(cells) + " |")
    print()


def pool_table(pool):
    if not pool:
        return
    by = group(ok(pool), "pool_size")
    print(f"Pool study: {pool[0]['strategy']}, realistic mix, {pool[0]['clients']} clients (median of runs)\n")
    print("| Pool size | Req/s | p50 ms | p99 ms | Runs ok |")
    print("| ---: | ---: | ---: | ---: | --- |")
    for size in sorted({r["pool_size"] for r in pool}, key=int):
        rows = by.get((size,), [])
        print(f"| {size} | {show(med([float(r['rps']) for r in rows]))} | {show(med([float(r['p50_ms']) for r in rows]))} "
              f"| {show(med([float(r['p99_ms']) for r in rows]))} | {len(rows)}/{sum(r['pool_size'] == size for r in pool)} |")
    print()


def cpu_table():
    """Median CPU% per container, sampled 40 s into each run (raw/*/docker_stats.csv)."""
    samples = defaultdict(lambda: defaultdict(list))
    for path in RESULTS.glob("raw/*/*/*/docker_stats.csv"):
        workload = path.parts[-4]
        for line in path.read_text().splitlines():
            name, cpu, _ = line.split(",", 2)
            role = "locust" if "-run-" in name else name.split("-")[1]
            samples[workload][role].append(float(cpu.rstrip("%")))
    if not samples:
        return
    print("Container CPU 40 s into each run, median over all runs (100% = one core)\n")
    print("| Workload | api | postgres | locust |")
    print("| --- | ---: | ---: | ---: |")
    for workload, roles in sorted(samples.items()):
        print(f"| {workload} | " + " | ".join(f"{med(roles[r]):.0f}%" if roles[r] else "TODO"
                                         for r in ("api", "postgres", "locust")) + " |")
    print()


if __name__ == "__main__":
    bench, oversell = read("benchmark.csv"), read("oversell.csv")
    if bench:
        strategy_table(bench, oversell)
        oversell_table(oversell)
        throughput_table(bench, "hot")
        throughput_table(bench, "mix")
        cpu_table()
    pool_table(read("pool_study.csv"))
