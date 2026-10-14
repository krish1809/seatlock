#!/usr/bin/env bash
# Strategy benchmark: every HOLD_STRATEGY x client count x workload, 3 repeats.
#
# Each run: reset data (small seed), restart the api with that strategy, run
# Locust headless for 70 s (10 s warm-up, then 60 s measured), save the api's
# /metrics, and for the hot-seat workload count double bookings.
#
# Usage: bench/run_all.sh                      (all, about 3 hours)
#        STRATEGIES="naive conditional" CLIENTS="50" REPEATS=1 WORKLOADS=hot bench/run_all.sh
# Outputs: bench/results/benchmark.csv, bench/results/oversell.csv (committed), and the
#          per-run working files in bench/results/raw/ (local, not committed)
set -uo pipefail
cd "$(dirname "$0")/.."
source .env
source bench/lib.sh

STRATEGIES=${STRATEGIES:-"naive pessimistic optimistic conditional serializable"}
CLIENTS=${CLIENTS:-"10 50 100 200"}
REPEATS=${REPEATS:-3}
WORKLOADS=${WORKLOADS:-"hot mix"}
export HOLD_SECONDS=2         # short holds keep seats churning for the whole run

declare -A USER_CLASS=([hot]=HotSeatUser [mix]=RealisticUser)
# Hot-seat runs turn the sweeper off so that every write to a hot seat is a hold
# (verify_oversell.py compares versions with the api's count). Holds still
# expire: every strategy treats an expired hold as free by itself.
declare -A SWEEP=([hot]=0 [mix]=5)

run_one() {  # workload strategy clients repeat
    local workload=$1 strategy=$2 clients=$3 repeat=$4
    local dir=$RESULTS/raw/$workload/$strategy/c${clients}_r${repeat}
    local labels="workload=$workload strategy=$strategy clients=$clients repeat=$repeat"
    require_mains_power  # before touching $dir: never delete a valid earlier run
    rm -rf "$dir" && mkdir -p "$dir"
    echo "=== $(date +%H:%M:%S) $labels"
    if ! reset_and_start_api HOLD_STRATEGY="$strategy" EXPIRY_SWEEP_SECONDS="${SWEEP[$workload]}"; then
        record_failure benchmark.csv $labels
        return
    fi
    if ! run_locust "$dir" "${USER_CLASS[$workload]}" "$clients" -e HOLD_LOG="/app/$dir/holds.jsonl"; then
        record_failure benchmark.csv $labels
    elif ! power_held "$dir"; then
        record_invalid "$dir" benchmark.csv $labels
    elif ! { record_run "$dir" benchmark.csv $labels &&
             { [ "$workload" != hot ] || verify_oversell "$dir" "$strategy" "$clients" "$repeat"; }; }; then
        record_failure benchmark.csv $labels
    fi
}

for workload in $WORKLOADS; do
    for strategy in $STRATEGIES; do
        for clients in $CLIENTS; do
            for repeat in $(seq 1 "$REPEATS"); do
                run_one "$workload" "$strategy" "$clients" "$repeat"
            done
        done
    done
done

restore_defaults
echo "done: $RESULTS/benchmark.csv, $RESULTS/oversell.csv"
