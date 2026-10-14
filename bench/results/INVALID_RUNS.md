# Runs marked invalid

On 2026-10-09 the laptop running the benchmark was unplugged at about 11:58:58 local time
(UTC+05:30) and finished the run on battery. On battery the CPU is throttled, so every
run measured after that moment is not comparable with the runs before it. Those runs are
kept, with their numbers, as `status = invalid` in the CSVs, and their raw output was moved
to `bench/results/raw_invalid/` (local working files, not committed). `bench/summary.py`
and `bench/plot.py` leave them out.

## Evidence

1. **Battery log** (the upower charge history in `/var/lib/upower/`, read with awk):
   ```
   2026-10-09 10:03:46 100.000 charging
   2026-10-09 11:59:11 99.000 discharging
   ```
   The battery was full from 10:03:46; the first "discharging" entry is at 11:59:11.
   upower only logs when the percentage changes, so the plug was pulled shortly before.
2. **Throughput step inside one run.** Locust's per-second history of the run (local raw output),
   aggregated requests/s every 5 s: `11:58:40=536 11:58:45=533 11:58:50=507 11:58:55=540
   11:59:00=406 11:59:05=266 11:59:10=257 11:59:15=252`. The previous run of the same
   configuration (c50_r1) ended at 11:58:03 with a median of 504 requests/s and no step.
3. **Same configuration, before and after.** Pessimistic, realistic mix, 200 clients, pool 10:
   475, 482 and 469 requests/s on AC at 11:20-11:22 (`benchmark.csv`), and 254 requests/s
   when re-run on battery (run ended at 12:25:41; local raw output).
   The api container used about 150% CPU in both, so the same CPU share did half the work.
4. **Power state afterwards:** `/sys/class/power_supply/ACAD/online` = 0, `BAT1` discharging.

## Runs affected

| CSV | Runs | Why |
| --- | --- | --- |
| benchmark.csv | mix / serializable / 50 clients / repeats 2, 3 | unplugged during repeat 2 |
| benchmark.csv | mix / serializable / 100 clients / repeats 1-3 | on battery |
| benchmark.csv | mix / serializable / 200 clients / repeats 1-3 | on battery |
| pool_study.csv | all 12 runs | on battery |

All 60 hot-seat runs and the other 52 realistic-mix runs finished before 11:58:58.

## Re-running them (on AC power)

```bash
STRATEGIES=serializable WORKLOADS=mix CLIENTS="50 100 200" bench/run_all.sh   # about 12 min
bench/pool_study.sh                                                         # about 16 min
make plot && make summary
```

A re-run replaces the rows with the same labels. Since this incident the scripts refuse to
start on battery and record a run as invalid if AC power is missing at its 40-second
sample or at its end (`bench/lib.sh`).
