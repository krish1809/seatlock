#!/usr/bin/env bash
# Pool study: one strategy (pessimistic, the one that holds row locks while it
# works), the realistic mix at 200 clients, pool sizes 5, 20, 50 and 100.
#
# Usage: bench/pool_study.sh        Output: bench/results/pool_study.csv (committed),
#                                           bench/results/raw/pool/ (local, not committed)
set -uo pipefail
cd "$(dirname "$0")/.."
source .env
source bench/lib.sh

POOL_SIZES=${POOL_SIZES:-"5 20 50 100"}
REPEATS=${REPEATS:-3}
CLIENTS=200
STRATEGY=pessimistic

for pool in $POOL_SIZES; do
    for repeat in $(seq 1 "$REPEATS"); do
        dir=$RESULTS/raw/pool/p${pool}_r${repeat}
        labels="pool_size=$pool strategy=$STRATEGY clients=$CLIENTS repeat=$repeat"
        require_mains_power  # before touching $dir: never delete a valid earlier run
        rm -rf "$dir" && mkdir -p "$dir"
        echo "=== $(date +%H:%M:%S) $labels"
        if ! { reset_and_start_api HOLD_STRATEGY=$STRATEGY HOLD_SECONDS=2 DB_POOL_SIZE="$pool" &&
               run_locust "$dir" RealisticUser $CLIENTS; }; then
            record_failure pool_study.csv $labels
        elif ! power_held "$dir"; then
            record_invalid "$dir" pool_study.csv $labels
        elif ! record_run "$dir" pool_study.csv $labels; then
            record_failure pool_study.csv $labels
        fi
    done
done

restore_defaults
echo "done: $RESULTS/pool_study.csv"
