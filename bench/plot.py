"""Draw the benchmark charts in docs/img/ from bench/results/*.csv.

Every point is the median of the repeated runs; failed runs are left out and
counted in the chart subtitle. Nothing is estimated: a missing CSV means its
charts are skipped.

Usage: python bench/plot.py   (or `make plot`)
"""
import csv
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "bench" / "results"
IMG = ROOT / "docs" / "img"

STRATEGIES = ["naive", "pessimistic", "optimistic", "conditional", "serializable"]
# Categorical slots 1-5 of the validated reference palette, fixed per strategy
# so a strategy has the same color in every chart.
COLOR = dict(zip(STRATEGIES, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]))
# Ordinal blue ramp (steps 250 / 450 / 650) for p50 < p95 < p99.
PERCENTILE_COLOR = {"p50": "#86b6ef", "p95": "#2a78d6", "p99": "#104281"}
SURFACE, INK, INK_2, MUTED, GRID, BASELINE = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": BASELINE, "axes.labelcolor": INK_2, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "axes.axisbelow": True,
    "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
    "axes.spines.left": False, "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "legend.frameon": False,
})


def read(name):
    path = RESULTS / name
    if not path.exists():
        print(f"skip: {path.relative_to(ROOT)} not found")
        return None
    with path.open() as f:
        return list(csv.DictReader(f))


def medians(rows, keys, value):
    """{key tuple: median of value over ok runs}, plus {key tuple: failed run count}."""
    values, failed = defaultdict(list), defaultdict(int)
    for r in rows:
        k = tuple(r[key] for key in keys)
        if r.get("status", "ok") != "ok":
            failed[k] += 1
        elif value_of(r, value) != "":
            values[k].append(float(value_of(r, value)))
    return {k: statistics.median(v) for k, v in values.items()}, failed


def value_of(row, value):
    if value == "retry_rate":
        attempts = sum(int(row[c]) for c in ("holds_won", "holds_lost", "holds_error"))
        retries = int(row["retries_40001"]) + int(row["retries_40P01"])
        return 100 * retries / attempts if attempts else 0
    return row[value]


def fmt(v):
    return f"{v:,.0f}" if v >= 10 or v == 0 else f"{v:.1f}"


def finish(fig, name, subtitle):
    fig.text(0.01, -0.01, subtitle, color=MUTED, fontsize=8, va="top")
    IMG.mkdir(parents=True, exist_ok=True)
    fig.savefig(IMG / name, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote docs/img/{name}")


def grouped_bars(ax, groups, series, value, color_of, label_values=True):
    """groups along x; within each group one bar per series; value(group, series) -> number or None."""
    width = 0.8 / len(series)
    for i, s in enumerate(series):
        xs, ys = [], []
        for g_i, g in enumerate(groups):
            v = value(g, s)
            if v is not None:
                xs.append(g_i - 0.4 + width * (i + 0.5))
                ys.append(v)
        bars = ax.bar(xs, ys, width, color=color_of(s), label=s, edgecolor=SURFACE, linewidth=1.5)
        if label_values:
            for b, y in zip(bars, ys):
                ax.annotate(fmt(y), (b.get_x() + b.get_width() / 2, y), xytext=(0, 2),
                            textcoords="offset points", ha="center", va="bottom", fontsize=7, color=INK_2)
    ax.set_xticks(range(len(groups)))
    ax.grid(axis="x", visible=False)


def failed_note(failed):
    n = sum(failed.values())
    return f"{n} failed or invalid run(s) excluded (bench/results/INVALID_RUNS.md)" if n else "no runs excluded"


def double_bookings(bench_rows, oversell):
    clients = sorted({int(r["clients"]) for r in oversell})
    med, _ = medians(oversell, ["strategy", "clients"], "overlapping_holds")
    _, failed = medians([r for r in bench_rows if r["workload"] == "hot"], ["strategy", "clients"], "rps")
    fig, ax = plt.subplots(figsize=(9, 4.2))
    grouped_bars(ax, [str(c) for c in clients], STRATEGIES,
                 lambda c, s: med.get((s, c)), COLOR.get)
    ax.set_xticklabels([f"{c} clients" for c in clients])
    ax.set_ylabel("double-booked holds per run")
    ax.set_title("Double bookings per strategy (hot-seat workload)", pad=30)
    ax.legend(ncols=5, loc="lower left", bbox_to_anchor=(0, 1.0))
    finish(fig, "double_bookings.png",
           "Successful holds whose time window overlapped another successful hold on the same seat. "
           f"Median of runs; source bench/results/oversell.csv; {failed_note(failed)}.")


def throughput(bench_rows):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    notes = []
    for ax, workload, title in zip(axes, ["hot", "mix"], ["Hot-seat contention", "Realistic mix (80% reads)"]):
        rows = [r for r in bench_rows if r["workload"] == workload]
        med, failed = medians(rows, ["strategy", "clients"], "rps")
        notes.append(f"{workload}: {failed_note(failed)}")
        for s in STRATEGIES:
            pts = sorted((int(c), v) for (st, c), v in med.items() if st == s)
            if not pts:
                continue
            xs, ys = zip(*pts)
            ax.plot(xs, ys, color=COLOR[s], linewidth=2, marker="o", markersize=5, label=s)
        ax.set_title(title, pad=30)
        ax.set_xlabel("concurrent clients")
        ax.set_ylabel("requests per second")
        ax.set_ylim(bottom=0)
        ax.set_xticks(sorted({int(r["clients"]) for r in rows}) or [0])
    axes[0].legend(ncols=5, loc="lower left", bbox_to_anchor=(0, 1.0))
    fig.tight_layout()
    finish(fig, "throughput.png", "Median requests/s over the 60 s measured window (exact values: README tables); "
           "source bench/results/benchmark.csv; "
           + "; ".join(notes) + ".")


def latency(bench_rows, clients="200"):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    notes = []
    for ax, workload, prefix, title in zip(axes, ["hot", "mix"], ["hold_", ""],
                                           ["Hold latency, hot seat", "All requests, realistic mix"]):
        rows = [r for r in bench_rows if r["workload"] == workload and r["clients"] == clients]
        meds = {p: medians(rows, ["strategy"], f"{prefix}{p}_ms")[0] for p in PERCENTILE_COLOR}
        notes.append(f"{workload}: {failed_note(medians(rows, ['strategy'], 'rps')[1])}")
        grouped_bars(ax, STRATEGIES, list(PERCENTILE_COLOR),
                     lambda s, p: meds[p].get((s,)), PERCENTILE_COLOR.get)
        for i, s in enumerate(STRATEGIES):
            if (s,) not in meds["p50"]:
                ax.annotate("no valid runs", (i, 0), xytext=(0, 4), textcoords="offset points",
                            ha="center", va="bottom", fontsize=8, color=MUTED, rotation=90)
        ax.set_xticklabels(STRATEGIES)
        ax.set_title(f"{title} ({clients} clients)")
        ax.set_ylabel("milliseconds")
    axes[0].legend(ncols=3, loc="upper left")
    fig.tight_layout()
    finish(fig, "latency.png", "Median of runs of Locust's p50/p95/p99; source bench/results/benchmark.csv; "
           + "; ".join(notes) + ".")


def retry_rate(bench_rows, clients="200"):
    rows = [r for r in bench_rows if r["workload"] == "hot" and r["clients"] == clients]
    med, failed = medians(rows, ["strategy"], "retry_rate")
    fig, ax = plt.subplots(figsize=(7, 3.8))
    vals = [med.get((s,), 0) for s in STRATEGIES]
    bars = ax.bar(STRATEGIES, vals, color=[COLOR[s] for s in STRATEGIES], width=0.6)
    for b, v in zip(bars, vals):
        ax.annotate(f"{v:.2f}", (b.get_x() + b.get_width() / 2, v), xytext=(0, 2),
                    textcoords="offset points", ha="center", fontsize=8, color=INK_2)
    ax.grid(axis="x", visible=False)
    ax.set_ylabel("retries per 100 hold requests")
    ax.set_ylim(bottom=0)
    ax.set_title(f"Retries on 40001/40P01, hot seat, {clients} clients")
    finish(fig, "retry_rate.png", "Retries counted by the api (/metrics) for the whole run; "
           f"source bench/results/benchmark.csv; {failed_note(failed)}.")


def deadlocks(rows):
    order = {"unordered": 0, "ordered": 1}
    rows = sorted(rows, key=lambda r: order.get(r["variant"], 9))
    labels = [f"{r['variant']} locking" for r in rows]
    vals = [int(r["deadlocks_40P01"]) for r in rows]
    fig, ax = plt.subplots(figsize=(6, 3.6))
    bars = ax.bar(labels, vals, color=COLOR["naive"], width=0.5)
    for b, v in zip(bars, vals):
        ax.annotate(str(v), (b.get_x() + b.get_width() / 2, v), xytext=(0, 2),
                    textcoords="offset points", ha="center", fontsize=9, color=INK_2)
    ax.grid(axis="x", visible=False)
    ax.set_ylabel("deadlocks (SQLSTATE 40P01)")
    ax.set_title(f"Deadlocks in {rows[0]['pairs']} opposing pairs")
    finish(fig, "deadlocks.png", "Source bench/results/deadlocks.csv (experiments/deadlock/).")


def pool_size(rows):
    if not any(r.get("status") == "ok" for r in rows):
        print("skip: pool_size.png, no valid pool study runs (see bench/results/INVALID_RUNS.md)")
        return
    sizes = sorted({int(r["pool_size"]) for r in rows})
    rps, failed = medians(rows, ["pool_size"], "rps")
    p99, _ = medians(rows, ["pool_size"], "p99_ms")
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    for ax, med, label, title in [(axes[0], rps, "requests per second", "Throughput"),
                                  (axes[1], p99, "p99 milliseconds", "p99 latency")]:
        ys = [med.get((str(s),)) for s in sizes]
        ax.plot(sizes, ys, color=COLOR["pessimistic"], linewidth=2, marker="o", markersize=5)
        for x, y in zip(sizes, ys):
            ax.annotate(fmt(y), (x, y), xytext=(0, 6), textcoords="offset points", ha="center",
                        fontsize=8, color=INK_2)
        ax.set_xticks(sizes)
        ax.set_xlabel("connection pool size")
        ax.set_ylabel(label)
        ax.set_ylim(bottom=0)
        ax.set_title(f"{title} vs pool size")
    fig.tight_layout()
    finish(fig, "pool_size.png", f"Pessimistic strategy, realistic mix, {rows[0]['clients']} clients. "
           f"Median of runs; source bench/results/pool_study.csv; {failed_note(failed)}.")


if __name__ == "__main__":
    bench, oversell = read("benchmark.csv"), read("oversell.csv")
    if bench and oversell:
        double_bookings(bench, oversell)
    if bench:
        throughput(bench)
        latency(bench)
        retry_rate(bench)
    if (rows := read("deadlocks.csv")):
        deadlocks(rows)
    if (rows := read("pool_study.csv")):
        pool_size(rows)
