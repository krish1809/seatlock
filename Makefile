# All Python runs inside the api container, so the host only needs Docker and make.
COMPOSE := docker compose
RUN := $(COMPOSE) run --rm api

.PHONY: up down migrate seed test bench

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
	@echo "seed: not implemented yet (Prompt 3)"

test:
	$(RUN) pytest

bench:
	@echo "bench: not implemented yet (Prompt 10)"
