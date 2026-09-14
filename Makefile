.PHONY: setup verify run queries

PYTHON ?= python

setup:
	@mkdir -p artifacts evidence docs db/migrations db/seed src tests
	@test -f .env.example
	@echo "CDRL starter base preparada. Configura .env localmente cuando corresponda."

verify:
	@bash scripts/verify_base.sh
	@PYTHON="$(PYTHON)" bash scripts/verify_m02.sh

run:
	@docker compose up

# M02: ejecutar después de levantar PostgreSQL y aplicar rebuild.py.
queries:
	@$(PYTHON) -m db.queries.demo