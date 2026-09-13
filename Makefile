.PHONY: setup verify run queries verify-queries

PYTHON ?= python

setup:
	@mkdir -p artifacts evidence docs db/migrations db/seed src tests
	@test -f .env.example
	@echo "CDRL starter base preparada. Configura .env localmente cuando corresponda."

verify:
	@bash scripts/verify_base.sh

run:
	@docker compose up

# M02: ejecutar después de levantar PostgreSQL y aplicar rebuild.py.
queries:
	@$(PYTHON) -m db.queries.demo

verify-queries:
	@$(PYTHON) -m pytest tests/test_m02_queries_victor.py -q --json-report --json-report-file=artifacts/m02-query-tests.json
