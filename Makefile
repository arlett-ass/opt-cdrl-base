.PHONY: setup verify run queries

PYTHON ?= python

#Prepara la infraestructura, migraciones y datos desde el repositorio
setup:
	@PYTHON="$(PYTHON)" bash scripts/setup.sh

#Ejecuta las verificaciones integradas usando el mismo entorno
verify:
	@PYTHON="$(PYTHON)" bash scripts/verify_all.sh

#Mantiene los servicios disponibles para uso manual
run:
	@docker compose up

#Demuestra las consultas parametrizadas de la entrega de m02
queries:
	@$(PYTHON) -m db.queries.demo