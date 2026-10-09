# All Python runs inside the api container, so the host only needs Docker and make.
COMPOSE := docker compose
RUN := $(COMPOSE) run --rm api

# .env is plain KEY=VALUE, so make can read it too (for the psql user and db name).
# If .env is missing, make creates it from the rule below before reading it.
include .env
PSQL := $(COMPOSE) exec -T postgres psql -v ON_ERROR_STOP=1 -q -U $(POSTGRES_USER) -d $(POSTGRES_DB)

.PHONY: up down migrate seed seed-large test bench deadlock isolation index-study pool-study plot summary env

# Created only if missing; edit .env afterwards to change ports or credentials.
.env:
	cp .env.example .env

up: .env
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

migrate:
	$(RUN) python db/migrate.py

seed:
	$(PSQL) --single-transaction < db/seed/seed_small.sql

# 10M event_seats rows at SCALE=1, 1M at SCALE=0.1. Manages its own transaction.
SCALE ?= 1
seed-large:
	$(PSQL) -v scale=$(SCALE) < db/seed/seed_large.sql

test:
	$(RUN) pytest

# Strategy benchmark, about 3 hours (bench/results/benchmark.csv, oversell.csv).
bench:
	bash bench/run_all.sh

pool-study:
	bash bench/pool_study.sh

plot:
	$(RUN) python bench/plot.py

# Markdown result tables for the README, computed from bench/results/*.csv.
summary:
	$(RUN) python bench/summary.py

env:
	bash bench/environment.sh

# Deadlock experiments (reseed the dev database). Writes bench/results/deadlocks.csv.
deadlock:
	$(RUN) python experiments/deadlock/reproduce.py
	$(RUN) python experiments/deadlock/fixed.py

# Isolation experiments (reseed the dev database). Writes docs/isolation-results.md.
isolation:
	$(RUN) python experiments/isolation/runner.py

# Index study at 1M and 10M rows (bench/results/index_study.csv, docs/explain-plans/).
# The api is stopped so its expiry sweeper cannot run during measurements.
index-study:
	$(COMPOSE) stop api
	$(MAKE) seed-large SCALE=0.1
	$(RUN) python bench/index_study.py --tier 1M
	$(MAKE) seed-large SCALE=1
	$(RUN) python bench/index_study.py --tier 10M
	$(MAKE) seed
