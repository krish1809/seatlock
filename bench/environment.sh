#!/usr/bin/env bash
# Write bench/results/ENVIRONMENT.md: the machine and software the benchmarks ran on.
# Everything below is collected by commands, not typed in by hand.
set -uo pipefail
cd "$(dirname "$0")/.."
source .env
OUT=bench/results/ENVIRONMENT.md

psql_value() { docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "$1"; }

{
    echo "# Benchmark environment"
    echo
    echo "Collected by \`bench/environment.sh\` on $(date -u '+%Y-%m-%d %H:%M UTC')."
    echo
    echo "## Host"
    echo
    echo "| Item | Value |"
    echo "| --- | --- |"
    echo "| CPU | $(lscpu | sed -n 's/^Model name: *//p') |"
    echo "| Logical CPUs | $(nproc) |"
    echo "| RAM | $(free -h | awk '/^Mem:/ {print $2 " total, " $7 " available at collection time"}') |"
    echo "| OS | $(. /etc/os-release && echo "$PRETTY_NAME"), kernel $(uname -r) |"
    echo "| Load average (1/5/15 min) | $(cut -d' ' -f1-3 /proc/loadavg) |"
    echo "| Other running containers | $(( $(docker ps -q | wc -l) - $(docker compose ps -q | wc -l) )) (not part of SeatLock) |"
    echo
    echo "## Docker"
    echo
    echo "| Item | Value |"
    echo "| --- | --- |"
    echo "| Docker | $(docker version --format '{{.Server.Version}}') |"
    echo "| Compose | $(docker compose version --short) |"
    echo "| CPUs / memory visible to Docker | $(docker info --format '{{.NCPU}} CPUs, {{.MemTotal}} bytes') |"
    for svc in postgres api; do
        id=$(docker compose ps -q "$svc")
        echo "| $svc container limits | $(docker inspect --format 'NanoCpus={{.HostConfig.NanoCpus}} Memory={{.HostConfig.Memory}} (0 = no limit)' "$id") |"
    done
    echo
    echo "## PostgreSQL"
    echo
    echo "| Setting | Value |"
    echo "| --- | --- |"
    echo "| version | $(psql_value 'SELECT version()') |"
    for s in max_connections shared_buffers work_mem effective_cache_size deadlock_timeout default_transaction_isolation; do
        echo "| $s | $(psql_value "SHOW $s") |"
    done
    echo
    echo "## Application and load generator"
    echo
    echo "| Item | Value |"
    echo "| --- | --- |"
    echo "| Python | $(docker compose run --rm --no-deps api python --version 2>/dev/null) |"
    echo "| Packages | $(tr '\n' ' ' < requirements.txt) |"
    echo "| SeatLock commit | $(git rev-parse --short HEAD) |"
    echo "| api | 1 uvicorn process, FastAPI sync endpoints (default thread pool), pool size from DB_POOL_SIZE |"
    echo "| Locust | runs in a container from the same image, on the same host, same Docker network |"
} >"$OUT"
echo "wrote $OUT"
