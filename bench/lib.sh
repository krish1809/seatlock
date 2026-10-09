# Shared steps for run_all.sh and pool_study.sh (sourced, not run).
# Every step runs in the foreground, one after the other; only the CPU sampler
# runs beside Locust.

RESULTS=bench/results

# A laptop on battery throttles its CPU: on 2026-10-09 unplugging halved the api's
# throughput mid-benchmark (bench/results/INVALID_RUNS.md). Runs on battery are
# therefore refused, and a run that loses AC power is recorded as invalid.
on_mains_power() {  # true on AC power, or on a machine with no mains supply listed (desktop)
    local found=0 f
    for f in /sys/class/power_supply/*; do
        [ "$(cat "$f/type" 2>/dev/null)" = Mains ] || continue
        found=1
        [ "$(cat "$f/online" 2>/dev/null)" = 1 ] && return 0
    done
    [ $found -eq 0 ]
}

require_mains_power() {
    on_mains_power || [ "${ALLOW_BATTERY:-0}" = 1 ] && return 0
    echo "!!! not on AC power: results would not be comparable. Plug in, or set ALLOW_BATTERY=1."
    exit 1
}

power_held() {  # dir: AC power at the mid-run sample and now
    [ "${ALLOW_BATTERY:-0}" = 1 ] || { [ "$(cat "$1/power.txt" 2>/dev/null)" = ac ] && on_mains_power; }
}

reset_and_start_api() {  # VAR=value ... : reseed small data, recreate the api with these settings
    make -s seed >/dev/null &&
        env "$@" docker compose up -d --force-recreate --wait api >/dev/null 2>&1
}

sample_cpu() {  # dir: CPU and memory of the SeatLock containers, and the power source, 40 s into the run
    sleep 40
    docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}}" \
        $(docker ps -q --filter "name=seatlock") >"$1/docker_stats.csv"
    if on_mains_power; then echo ac; else echo battery; fi >"$1/power.txt"
}

run_locust() {  # dir user_class clients [extra docker compose run args]
    local dir=$1 user_class=$2 clients=$3
    shift 3
    sample_cpu "$dir" &
    local sampler=$!
    docker compose run --rm --no-deps "$@" api \
        locust -f bench/locustfile.py "$user_class" --headless \
        -u "$clients" -r "$clients" --run-time 70s --host http://api:8000 \
        --csv "$dir/locust" --only-summary --loglevel WARNING --exit-code-on-error 0 \
        >"$dir/locust.log" 2>&1
    local status=$?
    wait "$sampler"
    [ $status -eq 0 ] && curl -sf "localhost:$API_PORT/metrics" >"$dir/metrics.json"
}

record_run() {  # dir csv labels...
    local dir=$1 csv=$2
    shift 2
    docker compose run --rm --no-deps api python bench/record_run.py "$dir" "$RESULTS/$csv" "$@" 2>/dev/null | tail -1
}

record_invalid() {  # dir csv labels...: measured, but AC power was lost
    local dir=$1 csv=$2
    shift 2
    echo "!!! AC power lost during the run, recorded as invalid: $*"
    docker compose run --rm --no-deps api python bench/record_run.py --invalid "$dir" "$RESULTS/$csv" "$@" \
        >/dev/null 2>&1
}

record_failure() {  # csv labels...
    local csv=$1
    shift
    echo "!!! run failed: $*"
    docker compose run --rm --no-deps api python bench/record_run.py --failed "$RESULTS/$csv" "$@" >/dev/null 2>&1
}

verify_oversell() {  # dir strategy clients repeat
    docker compose run --rm --no-deps -e HOLD_SECONDS api python bench/verify_oversell.py "$@" 2>/dev/null | tail -1
}

restore_defaults() {  # leave the api as configured in .env, with fresh small data
    make -s seed >/dev/null
    docker compose up -d --force-recreate --wait api >/dev/null 2>&1
}
