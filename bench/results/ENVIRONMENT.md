# Benchmark environment

Collected by `bench/environment.sh` on 2026-10-09 04:05 UTC.

## Host

| Item | Value |
| --- | --- |
| CPU | 13th Gen Intel(R) Core(TM) i7-13620H |
| Logical CPUs | 16 |
| RAM | 15Gi total, 4.2Gi available at collection time |
| OS | Ubuntu 24.04.3 LTS, kernel 7.0.0-34-generic |
| Load average (1/5/15 min) | 2.51 1.88 1.35 |
| Other running containers | 2 (not part of SeatLock) |

## Docker

| Item | Value |
| --- | --- |
| Docker | 29.8.0 |
| Compose | 5.5.1 |
| CPUs / memory visible to Docker | 16 CPUs, 16473264128 bytes |
| postgres container limits | NanoCpus=0 Memory=0 (0 = no limit) |
| api container limits | NanoCpus=0 Memory=0 (0 = no limit) |

## PostgreSQL

| Setting | Value |
| --- | --- |
| version | PostgreSQL 18.6 (Debian 18.6-1.pgdg13+2) on x86_64-pc-linux-gnu, compiled by gcc (Debian 14.2.0-19) 14.2.0, 64-bit |
| max_connections | 200 |
| shared_buffers | 128MB |
| work_mem | 4MB |
| effective_cache_size | 4GB |
| deadlock_timeout | 1s |
| default_transaction_isolation | read committed |

## Application and load generator

| Item | Value |
| --- | --- |
| Python | Python 3.12.15 |
| Packages | fastapi==0.142.2 uvicorn==0.54.0 psycopg[binary]==3.3.6 psycopg-pool==3.3.3 pytest==9.1.1 locust==2.46.7 matplotlib==3.11.2  |
| SeatLock commit | fad1211 |
| api | 1 uvicorn process, FastAPI sync endpoints (default thread pool), pool size from DB_POOL_SIZE |
| Locust | runs in a container from the same image, on the same host, same Docker network |
