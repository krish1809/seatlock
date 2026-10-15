# Runs marked invalid, and their re-run

On 2026-10-09 the laptop running the benchmark was unplugged at about 11:58:58 local time
(UTC+05:30) and finished the run on battery. On battery the CPU is throttled, so every
run measured after that moment is not comparable with the runs before it. Those runs were
marked `status = invalid` (summaries and charts skip that status) and their raw output was
moved to `bench/results/raw_invalid/` (local working files, not committed). On 2026-10-15 they
were re-run on AC power; the CSVs now hold the re-run results (last section).

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

## Re-run on 2026-10-15 (on AC power)

Before re-running, one calibration run repeated a configuration measured on 2026-10-09:
pessimistic, realistic mix, 200 clients, pool 10. It gave 474.18 requests/s; the three
original runs gave 475.02, 482.37 and 468.62 (`benchmark.csv`). The machine performed the same.
The application and benchmark code were unchanged since the benchmarked commit (no diff in
`app/`, `db/`, `bench/locustfile.py`, the Dockerfile, docker-compose.yml or requirements.txt).

Then these were run again, and every run recorded AC power at its 40-second sample and at its end:

```bash
STRATEGIES=serializable WORKLOADS=mix CLIENTS="50 100 200" bench/run_all.sh
bench/pool_study.sh
```

The re-runs replaced the invalid rows; `benchmark.csv` and `pool_study.csv` now contain no
`invalid` rows. Serializable at 50 clients was re-run as a full set of 3, including the
repeat that had been valid, so all three come from the same session.
