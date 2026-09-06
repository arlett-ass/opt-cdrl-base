# Contribución individual — Víctor Manuel Jiménez Suárez

## Integrante

* Nombre: Víctor Manuel Jiménez Suárez
* Rama de trabajo: `feat/migrations-seed-victor`
* Área principal: Implementación de migraciones, automatización e inyección de datos sintéticos
* Hito: M01 — Contrato de datos y entorno reproducible

## Objetivo de la contribución

Materializar el contrato de datos diseñado por el equipo en una base de datos PostgreSQL mediante migraciones automatizadas e idempotentes, y garantizar un entorno de pruebas robusto mediante la inyección de datos completamente sintéticos.

El entorno generado servirá como base sólida para que Angelica Arlett Santiago Serrano ejecute los casos de prueba y genere los artefactos del hito.

## Tareas asignadas

1. Tomar el esquema del integrante Nicolas David (Contrato de datos).
2. Crear migraciones SQL.
3. Hacer las migraciones reproducibles/idempotentes.
4. Crear seed sintético utilizando Python.
5. Probar la creación de la base de datos desde cero.
6. Probar la carga del seed sintético.
7. Documentar la contribución individual.

## Trabajo realizado

### Migraciones e Idempotencia

Se tomó como base el diseño relacional propuesto en `db/schema/telemetry-contract.sql` y se transformó en una migración oficial y ejecutable. 

Para cumplir con el requisito de reproducibilidad, se implementó una estrategia de idempotencia agresiva al inicio del script SQL. Se utilizó el comando `DROP TABLE IF EXISTS ... CASCADE` para garantizar que la base de datos pueda destruirse y reconstruirse desde cero sin generar conflictos ni errores de dependencias previas.

Las tablas creadas respetan estrictamente las restricciones del contrato original:
* `locations`
* `devices`
* `telemetry_readings`

### Seed Sintético

Se desarrolló un script en Python (`seed.py`) utilizando la librería `Faker` y el conector `psycopg2` para poblar las tablas con datos falsos pero realistas.

El script fue programado para respetar rigurosamente los límites físicos y matemáticos establecidos en el contrato de datos:
* Generación de coordenadas válidas para las ubicaciones.
* Asignación aleatoria de estados permitidos para los sensores (`active`, `inactive`, `maintenance`).
* Generación de lecturas de temperatura, humedad y CO2 dentro de los rangos ambientales permitidos.
* Cálculo lógico de fechas para asegurar que el registro (`recorded_at`) sea siempre anterior a la recepción (`received_at`).

### Automatización y Pruebas

Para validar los puntos 5 y 6 de las tareas asignadas, se diseñó un script orquestador en la raíz del proyecto (`rebuild.py`). Este archivo centraliza la automatización del entorno local conectándose al contenedor de PostgreSQL expuesto por Docker Compose.

El flujo automatizado y probado consiste en:
1. Establecer conexión con la base de datos.
2. Ejecutar la migración inicial garantizando limpieza previa.
3. Llamar al script de inyección de datos (Seed).
4. Confirmar la transacción completa.

## Archivos creados

Durante esta contribución se crearon los siguientes archivos:

* `db/migrations/001_schema.sql`
* `db/seed/seed.py`
* `rebuild.py`
* `docs/contributions/victor-suarez.md`

## Traspaso hacia Angelica Arlett Santiago Serrano

Angelica Arlett Santiago Serrano ahora cuenta con un entorno de base de datos PostgreSQL vivo, reproducible y poblado con datos sintéticos.

Para su etapa de pruebas automatizadas, podrá levantar el entorno en cualquier momento ejecutando el contenedor local y corriendo el script `rebuild.py`. Esto le garantizará un escenario limpio cada vez que necesite ejecutar sus aserciones sobre los casos normales, los casos límite y el fallo declarado acordados en el contrato.

## Estado de la contribución

La migración, el seed y el script de orquestación se encuentran terminados, probados y documentados dentro de la rama:

```text
feat/migrations-seed-victor