# ADR-006 — Evolución versionada, auditoría segura y recuperación de eventos

## Estado

Aceptado después de completar satisfactoriamente la integración de evolución,
auditoría y recuperación y ejecutar `make verify` con M01-M06 correctamente.

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

## Decisión — Auditoría segura (aporte de Angélica)

Las migraciones de esquema v1 → v2 que produzcan un cambio real deben dejar
una traza de auditoría independiente del documento de negocio.

La auditoría se almacena en una tabla DynamoDB separada denominada
`cdrl_audit_log`, configurable mediante la variable no secreta
`DYNAMODB_AUDIT_TABLE`.

La tabla utiliza `auditId` como única partition key y su preparación es
idempotente.

Cada registro conserva únicamente la información necesaria para explicar
qué operación ocurrió:

- `auditId`
- `eventId`
- `actorId`
- `action`
- `entity`
- `timestamp`
- `traceId`
- `result`
- `reason`
- `fromVersion`
- `toVersion`
- `changedFields`

`traceId` permite relacionar el registro de auditoría con una ejecución
concreta sin almacenar credenciales ni datos personales.

No se almacenan copias completas de los documentos antes o después de la
migración. `changedFields` registra únicamente los nombres de los campos
afectados, evitando copiar valores de negocio innecesarios.

Antes de persistir contexto adicional se aplica sanitización recursiva.
Las claves sensibles, incluyendo `password`, `token`, `secret`,
`authorization`, `credentials`, `apiKey` y `connectionString`, conservan
únicamente el valor `[REDACTED]`.

Los fixtures utilizan exclusivamente valores sintéticos y no representan
credenciales reales.

El `auditId` de una migración se construye de forma determinista a partir de
la acción, `eventId`, versión origen y versión destino.

La escritura usa la condición:

`attribute_not_exists(auditId)`

Esto impide almacenar nuevamente un registro equivalente si la operación es
reintentada.

`migrate_event_with_audit()` primero consulta la versión actual del evento.
Solo una transición real de v1 a v2 produce auditoría.

Si el evento ya se encuentra en v2, la operación se considera un no-op y no
genera un segundo registro.

### Consecuencias de auditoría

La decisión permite contestar quién ejecutó la operación, qué acción se
realizó, sobre qué entidad, cuándo ocurrió, a qué ejecución pertenece mediante
`traceId` y cuál fue su resultado.

La auditoría queda separada de los documentos de negocio y no expone secretos
simulados.

Los reintentos no generan registros duplicados.

Se añade una segunda tabla DynamoDB que debe prepararse antes de ejecutar
operaciones auditadas.

La implementación actual no pretende reemplazar un sistema centralizado de
observabilidad o SIEM.

La actualización del documento y la escritura del audit log se realizan como
operaciones separadas. Si en el futuro se necesita atomicidad estricta entre
ambas, deberá evaluarse una estrategia transaccional.

### Autoría técnica de este aporte

Angélica Arlett Santiago Serrano:

`src/m06/audit_store.py`

`src/m06/audited_operations.py`

`tests/fixtures/m06_audit_cases.json`

`tests/test_m06_audit.py`
## Decisión — Recuperación controlada y medición (aporte de David)

La recuperación de M06 utiliza exclusivamente fixtures sintéticos conocidos.
No se realiza recuperación sobre eventos reales ni sobre documentos ajenos al
conjunto de `eventId` declarado en el fixture.

`load_recovery_fixture()` carga el documento JSON y
`validate_recovery_fixture()` valida completamente todos los eventos antes de
que ocurra cualquier escritura.

La validación reutiliza el contrato versionado de M06, por lo que pueden
recuperarse documentos válidos con `metadata.schemaVersion` 1 o 2. Una versión
no soportada provoca un fallo antes de comenzar la restauración.

`restore_fixture()` realiza un preflight de todos los `eventId` esperados:

- un evento ausente queda pendiente de restauración;
- un evento existente y equivalente se contabiliza como `skipped`;
- un evento existente con el mismo `eventId` pero contenido distinto se
  considera un conflicto y no se sobrescribe.

Los eventos ausentes se escriben mediante una condición
`attribute_not_exists(eventId)` para evitar sobrescrituras silenciosas ante
cambios concurrentes.

Al finalizar se vuelve a consultar cada elemento y se compara su contenido
normalizado con el fixture.

La medición de recuperación registra:

- `expectedCount`;
- `restoredCount`;
- `skippedCount`;
- `verifiedCount`;
- `durationMs`;
- `integrityPassed`.

`durationMs` se obtiene mediante `time.perf_counter()`.

La prueba normal provoca deliberadamente la pérdida de un único evento
sintético, confirma su ausencia y ejecuta recovery. El resultado esperado es
tres eventos verificados, uno restaurado y dos omitidos por encontrarse ya
correctos.

El fallo declarado modifica un fixture para utilizar una `schemaVersion` no
soportada. La validación completa ocurre antes de las escrituras, por lo que
ningún documento queda restaurado parcialmente.

### Verificación integrada

`scripts/verify_m06.sh` comprueba las dependencias y fixtures, la conexión con
DynamoDB, prepara de forma idempotente `cdrl_events` y `cdrl_audit_log`,
ejecuta las pruebas M06 y realiza una demostración real de evolución,
auditoría y recuperación.

El verifier genera
`artifacts/m06-evolution-audit-recovery-results.json` a partir de la ejecución
real. El artifact contiene los resultados de evolución, auditoría, recovery y
las pruebas automatizadas.

### Consecuencias de recovery

La estrategia permite demostrar recuperación de forma repetible sin afectar
datos ajenos a M06.

La prevalidación evita restauraciones parciales ocasionadas por fixtures
inválidos.

La escritura condicional evita reemplazar silenciosamente un evento creado por
otro proceso durante recovery.

El procedimiento no pretende sustituir una solución completa de backup y
disaster recovery para producción. Su alcance es demostrar una recuperación
controlada, verificable y medible sobre datos sintéticos.

### Autoría técnica de este aporte

Nicolás David Juárez Mendoza:

`src/m06/recovery.py`

`tests/fixtures/m06_recovery_fixture.json`

`tests/test_m06_recovery.py`

`scripts/verify_m06.sh`

`evidence/m06-evolution-audit-recovery.json`

Integración final del ADR-006 y del flujo de verificación M06.
