# ADR-006 — Evolución versionada, auditoría segura y recuperación de eventos

## Estado

Propuesto durante el desarrollo de M06. Esta contribución documenta la decisión
de versionado de Víctor; el ADR queda pendiente de integrar las decisiones de
auditoría y recuperación y de completar la verificación del equipo.

## Contexto

M05 almacena documentos de telemetría con `metadata.schemaVersion = 1`. Su
contrato coloca `temperatureC`, `humidityPct` y `co2Ppm` directamente dentro
de `payload`. Cambiar esa forma sin identificar la versión impediría validar y
leer documentos antiguos de manera segura.

La tabla `cdrl_events` utiliza `eventId` como clave primaria y los índices
`type-timestamp-index` y `source-timestamp-index` para consultas temporales. La
evolución debe conservar `eventId`, `type`, `source` y `timestamp` en el nivel
superior para mantener esas claves y los patrones de consulta de M05.

## Decisión — Versionado y compatibilidad (aporte de Víctor)

Se admite coexistencia de versiones v1 y v2 en la tabla de eventos existente.
La v1 mantiene el contrato M05. La v2 agrupa las tres métricas dentro de
`payload.measurements` y declara `metadata.schemaVersion = 2`.

La lectura y validación M06 reconoce ambas formas. Las reglas existentes de
identidad, tipo, origen, timestamps, identificadores y rangos de métricas se
reutilizan para ambas versiones. Una versión desconocida, como 999, se rechaza
con `UnsupportedSchemaVersionError`.

La conversión v1 → v2 es explícita, pura e idempotente. Conserva identidad y
datos de negocio; una entrada que ya es v2 produce un resultado equivalente
sin otra escritura. La persistencia M06 usa la misma tabla `cdrl_events` que
M05, y condiciona la escritura de migración a que el documento siga existiendo
con versión v1. No se crea una tabla de eventos nueva ni se modifican los GSIs.

### Consecuencias

- Los consumidores nuevos deben validar por `schemaVersion` antes de acceder
  a las métricas.
- Los datos v1 pueden seguir leyéndose mientras la migración se realiza de
  forma selectiva.
- El esquema común de claves conserva compatibilidad con los GSIs de M05.
- La normalización conserva los valores numéricos como `Decimal`, igual que el
  contrato M05 usado por boto3.

### Autoría técnica de este aporte

Víctor: `src/m06/__init__.py`, `src/m06/schema_evolution.py`,
`src/m06/versioned_store.py`, `tests/fixtures/m06_versioned_events.json` y
`tests/test_m06_evolution.py`.
