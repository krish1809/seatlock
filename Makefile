# All Python runs inside the api container, so the host only needs Docker and make.
COMPOSE := docker compose
RUN := $(COMPOSE) run --rm api

# .env is plain KEY=VALUE, so make can read it too (for the psql user and db name).
# If .env is missing, make creates it from the rule below before reading it.
include .env
PSQL := $(COMPOSE) exec -T postgres psql -v ON_ERROR_STOP=1 -q -U $(POSTGRES_USER) -d $(POSTGRES_DB)

.PHONY: up down migrate seed test bench deadlock isolation

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

test:
	$(RUN) pytest

bench:
	@echo "bench: not implemented yet (Prompt 10)"

# Deadlock experiments (reseed the dev database). Writes bench/results/deadlocks.csv.
deadlock:
	$(RUN) python experiments/deadlock/reproduce.py
	$(RUN) python experiments/deadlock/fixed.py

# Isolation experiments (reseed the dev database). Writes docs/isolation-results.md.
isolation:
	$(RUN) python experiments/isolation/runner.py
