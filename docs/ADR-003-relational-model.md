# ADR-003: Modelo relacional operativo de telemetría

## Estado

Propuesto para integración en M02.

## Contexto

El modelo de M01 contiene las tablas locations, devices y
telemetry_readings. M02 requiere demostrar sus relaciones,
la protección de invariantes y consultas parametrizadas.

Al revisar 001_schema.sql se identificó que las restricciones
necesarias ya estaban definidas. Se decidió conservarlas y
comprobar su comportamiento sin duplicarlas.

## Modelo y relaciones

- Una ubicación puede tener varios dispositivos.
- Cada dispositivo pertenece a una ubicación.
- Un dispositivo puede tener varias lecturas.
- Cada lectura pertenece a un dispositivo.

Cada tabla utiliza una clave primaria independiente.

Los datos de ubicación, dispositivo y lectura se almacenan
en sus respectivas tablas para evitar repetir sus atributos
en cada medición.

## Invariantes conservados

- Claves primarias únicas y no nulas.
- Códigos de ubicación y dispositivo únicos y no vacíos.
- Nombres de ubicación y dispositivo no vacíos.
- Campos obligatorios protegidos con NOT NULL.
- Latitud entre -90 y 90.
- Longitud entre -180 y 180.
- Temperatura entre -50 y 80 °C.
- Humedad entre 0 y 100 %.
- CO₂ entre 0 y 10000 ppm.
- Estados permitidos: active, inactive y maintenance.
- Una sola lectura por dispositivo e instante de registro.
- La recepción no puede ocurrir antes del registro.
- No se admiten referencias a ubicaciones o dispositivos inexistentes.
- No se pueden borrar ubicaciones con dispositivos ni dispositivos
  con lecturas, mediante ON DELETE RESTRICT.

Estas reglas se aplican en PostgreSQL, independientemente
del programa que escriba los datos.

## Decisión

Se agrega la migración 002_relational_model.sql, que crea
la vista public.v_telemetry_context mediante CREATE OR REPLACE VIEW
y documenta restricciones existentes mediante COMMENT ON.

La vista relaciona lecturas, dispositivos y ubicaciones con
INNER JOIN. No copia datos ni modifica registros existentes.

La vista muestra la ubicación y el estado actuales del dispositivo.
No representa el historial de movimientos o cambios de estado.

Las consultas sobre la vista pueden recibir valores mediante
parámetros del controlador psycopg2. La vista por sí sola no
sustituye la parametrización.

## Índices

Se reutiliza el índice creado por la restricción
UNIQUE (device_id, recorded_at), apropiado para búsquedas
por dispositivo y rango temporal.

Se conservan los índices existentes:

- idx_devices_location_id.
- idx_telemetry_recorded_at.

No se agrega otro índice idéntico al de la restricción UNIQUE.
No se realizaron mediciones de rendimiento con cargas grandes.

## Migraciones e idempotencia

001_schema.sql se conserva sin modificaciones.

rebuild.py registra las migraciones en schema_migrations
y omite las que ya fueron aplicadas.

Además de ese mecanismo, el SQL de 002 se ejecutó directamente
dos veces con ON_ERROR_STOP y --single-transaction.
Ambas ejecuciones finalizaron sin errores.

Después de repetir la migración se verificaron:

- 3 ubicaciones.
- 5 dispositivos.
- 50 lecturas.
- 50 filas en la vista.

Esta comprobación confirma que las cantidades se conservaron;
no constituye una comparación completa de todos los valores.

## Validación realizada

Se ejecutaron los archivos:

- tests/test_telemetry_contract.py.
- tests/test_m02_invariants_david.py.

Resultado observado: 12 pruebas aprobadas y 0 fallidas.

Cobertura comprobada:

- Inserción normal.
- Temperatura mínima permitida.
- CO₂ máximo permitido.
- Rechazo de humedad superior al máximo.
- Rechazo de lecturas duplicadas.
- Rechazo de dispositivo inexistente.
- Rechazo de device_id nulo.
- Rechazo de recepción anterior al registro.
- Rechazo de borrado de dispositivo con lecturas.
- Rechazo de borrado de ubicación con dispositivos.
- Consulta parametrizada de la vista con resultado.
- Consulta parametrizada de la vista sin lecturas.

Las pruebas revierten sus transacciones al terminar.
Las secuencias de identificadores pueden avanzar aunque
los registros insertados se reviertan.

Resultado machine-readable:
artifacts/m02-david-invariants.json.

## Alternativas descartadas

Duplicar las restricciones y el índice compuesto:
se descartó porque M01 ya los proporciona.

Validar únicamente desde Python:
se descartó porque no protege escrituras realizadas
directamente contra PostgreSQL.

Reconstruir las tablas borrando datos:
se descartó porque esta evolución no requiere eliminar
la información existente.

## Consecuencias y pendientes

Se obtiene una vista reutilizable del modelo relacionado
y pruebas adicionales de integridad sin cambiar el contrato M01.

La cobertura todavía no prueba todos los extremos de cada
restricción ni constituye la validación completa de M02.

La integración de las consultas del equipo, make verify,
make run y la evidencia final de M02 queda pendiente.