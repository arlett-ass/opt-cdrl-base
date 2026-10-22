# ADR-007 — Migración versionada y compatibilidad documental

## Estado y alcance

Propuesto. Este documento registra el aporte de Víctor para M07: validación
versionada y migración explícita por documento. La entrega M07 del equipo
queda pendiente de integrar la compatibilidad de consumidores de Angélica y
el rollback, verificador y evidencia de David.

Este aporte se construye sobre M06, sin modificar su implementación ni
redefinir el contrato de M05. No declara completa la integración M07 ni
presenta resultados de pruebas que todavía no hayan sido ejecutadas.

## Contexto

La tabla DynamoDB de eventos, `cdrl_events`, ya admite documentos de
telemetría v1 y v2 mediante M06. Ambas versiones representan los mismos datos
de negocio. La diferencia está en la ubicación de las tres mediciones.

Los consumidores no necesariamente adoptan la versión nueva al mismo tiempo.
La migración debe permitir convivencia temporal, conservar los índices y
evitar que una lectura seguida de una escritura reemplace un cambio
concurrente. Repetir una migración ya aplicada tampoco debe producir otra
escritura.

El validador original `src/m05/event_contract.py` acepta únicamente v1. La
existencia de validación v1/v2 en M06 no convierte automáticamente a los
consumidores M05 en lectores de v2.

## Contratos existentes que se conservan

Los documentos contienen exactamente estas propiedades superiores:

| Propiedad | Invariante compartida por v1 y v2 |
| --- | --- |
| `eventId` | Identidad determinista `telemetry#{deviceId}#{microsegundos_UTC_desde_epoch}`. |
| `type` | `telemetry.reading`. |
| `source` | `device-{deviceId}`. |
| `timestamp` | Instante de la lectura con zona, normalizado a UTC y seis decimales. |
| `payload` | Identificadores, recepción y mediciones según la versión. |
| `metadata` | Objeto que contiene únicamente `schemaVersion`. |

La forma exacta de `payload` depende de la versión:

| Versión | Propiedades exactas de `payload` | Mediciones |
| --- | --- | --- |
| v1 | `readingId`, `deviceId`, `receivedAt`, `temperatureC`, `humidityPct`, `co2Ppm` | Directamente en `payload`. |
| v2 | `readingId`, `deviceId`, `receivedAt`, `measurements` | `measurements` contiene exactamente `temperatureC`, `humidityPct`, `co2Ppm`. |

`readingId` y `deviceId` son enteros positivos dentro del rango BIGINT.
`receivedAt` se normaliza a UTC y no puede preceder a `timestamp`. Las
mediciones mantienen los límites de M05: temperatura entre -50 y 80,
humedad entre 0 y 100, y CO2 entre 0 y 10000. Se normalizan como `Decimal`
exacto con dos decimales; se rechazan `float`, booleanos y valores que
requieran pérdida de precisión.

`metadata.schemaVersion` admite únicamente 1 o 2. La lectura de enteros
representados por `Decimal` de DynamoDB se conserva. Una versión no
soportada se rechaza explícitamente. Los campos desconocidos y las formas
incompletas también se rechazan usando los validadores existentes.

## Decisión — Reutilizar M06 y separar cálculo de persistencia

`src/m07/versioning.py` expone:

- `SUPPORTED_SCHEMA_VERSIONS`, con las versiones existentes `(1, 2)`;
- `TARGET_SCHEMA_VERSION = 2`;
- `validate_document(document)`, que devuelve un documento nuevo validado y
  normalizado mediante `validate_versioned_event()` de M06;
- `get_schema_version(document)`, que valida el documento y devuelve su
  versión;
- los errores canónicos de validación de M06, para que los consumidores no
  necesiten interpretar mensajes ni mantener excepciones duplicadas.

`EventValidationError`, heredado de M05 y exportado también por M07, es la
excepción base para capturar todos los errores de contrato. Los errores de
versión de M06 son subclases de ella; algunos errores de datos se originan
directamente en el validador M05.

`src/m07/migration.py` ofrece dos operaciones:

### Conversión pura

`migrate_document(document)` reutiliza `migrate_v1_to_v2()` de M06. No lee ni
escribe en DynamoDB y no modifica el argumento. Un documento v1 se convierte
a v2, mientras uno v2 produce una copia normalizada equivalente.

Se conservan `eventId`, `type`, `source`, `timestamp`, `readingId`, `deviceId`,
`receivedAt` y los valores exactos de las tres mediciones. La normalización
de fechas y números sigue el contrato existente. No se calculan nuevas
identidades ni valores de negocio.

### Migración de un evento almacenado

`migrate_event(event_id, table=None)` utiliza la tabla M05 configurada o el
recurso `Table` recibido explícitamente. Su resultado tiene este contrato:

| Campo | Significado |
| --- | --- |
| `event` | Documento v2 validado y normalizado. |
| `previousEvent` | Copia independiente de la imagen cruda leída antes de decidir la operación. |
| `changed` | `True` únicamente cuando esta llamada realizó la escritura de migración. |
| `fromVersion` | Versión validada del documento leído: 1 o 2. |
| `toVersion` | Versión destino, siempre 2. |

`previousEvent` es un resultado volátil en memoria para que las otras partes
del equipo puedan decidir cómo conservar y proteger la imagen anterior. No
se inserta dentro del evento, no se añade automáticamente al audit log y no
constituye un backup durable.

El procedimiento es:

1. Validar el identificador y realizar `GetItem` con `ConsistentRead=True`.
2. Conservar una copia independiente de la imagen cruda y validar el evento
   con M06.
3. Si es v2, devolver `changed=False`, `fromVersion=2`, `toVersion=2` y no
   ejecutar `PutItem`.
4. Si es v1, calcular la representación v2 mediante la función pura.
5. Ejecutar un `PutItem` condicionado a que la identidad todavía exista y a
   que `metadata`, `payload`, `type`, `source` y `timestamp` sigan siendo
   iguales al snapshot crudo leído.
6. Devolver `changed=True` solo después de que DynamoDB acepte la escritura.

La condición compara los valores crudos leídos, no la representación
normalizada. Además de detectar una versión cambiada, evita sobrescribir
una modificación del contenido que mantenga `schemaVersion = 1`.

La ausencia del evento se informa con
`VersionedEventNotFoundError`. Un fallo de la condición se informa con
`ConcurrentSchemaMigrationError`; ambas excepciones se reutilizan de M06.
Los demás errores de AWS se propagan. No hay reintentos automáticos ni
sobrescritura incondicional después de un conflicto.

## Compatibilidad y activación de la migración

Los campos de las claves permanecen arriba. Por tanto, la migración conserva
la PK `eventId` y los GSIs `type-timestamp-index` y
`source-timestamp-index`, sin crear otra tabla de eventos.

La convivencia v1/v2 permite migrar eventos seleccionados y conservar otros
en v1. No hay actualización masiva ni migración implícita durante una
lectura.

Angélica debe integrar el adaptador de compatibilidad **antes de activar la
migración para consumidores que esperan v1**. El adaptador debe reconocer la
versión persistida y entregar a cada consumidor una representación que
pueda interpretar, manteniendo identidad y datos. El validador M05 sin ese
adaptador seguirá rechazando v2. No debe afirmarse que el despliegue de esta
parte por sí solo garantiza compatibilidad de todos los consumidores.

El resultado de `migrate_event()` permite a la integración de auditoría
distinguir un cambio real de un no-op mediante `changed`, sin otra lectura
para decidir si esta llamada escribió. La política y persistencia de esa
auditoría pertenecen a la integración del equipo.

## Rollback y límites operacionales

Este aporte no implementa un rollback nuevo. David debe definir la
conservación segura del snapshot, la autorización de la operación, las
condiciones que evitan sobrescribir cambios posteriores y la verificación
del resultado antes de ofrecer una reversión.

La protección de concurrencia es por documento y compara únicamente los
campos admitidos por el contrato. No es una transacción de un lote ni una
transacción atómica entre el evento y su auditoría. Una operación posterior
puede fallar después de que la migración del evento haya terminado; la
integración debe documentar y resolver ese caso sin asumir atomicidad.

La imagen anterior en memoria desaparece si finaliza el proceso o se pierde
su resultado. Por ello no se presenta como mecanismo de recuperación
durable. La repetición sobre v2 no vuelve a escribir ni aporta una imagen
v1 histórica: `previousEvent` corresponde a lo que esa llamada leyó.

Los módulos, verificadores y fixtures de M01–M06 deben conservar su
comportamiento. Integrar M07 en el flujo general y generar su reporte y
evidencia quedan pendientes del aporte correspondiente del equipo.

## Alternativas consideradas

| Alternativa | Motivo para descartarla |
| --- | --- |
| Introducir v3 para M07 | M07 puede demostrar migración y compatibilidad con las versiones ya existentes; v3 añadiría otro contrato sin necesidad. |
| Duplicar las reglas de validación de M06 | Permitiría divergencias de identidad, precisión y formas aceptadas entre entregas. |
| Escribir sin condición, o condicionar solo a la existencia | Podría sobrescribir contenido modificado después de la lectura. |
| Condicionar únicamente a la versión v1 | No detecta un cambio concurrente del contenido que conserve v1. |
| Migración masiva destructiva al iniciar | Impediría controlar la convivencia de versiones y aumentaría el alcance de un fallo. |

## Verificación del aporte

La validación del aporte se ejecuta desde la raíz del repositorio:

```sh
python -m pytest tests/test_m07_migration.py -q
```

El conjunto cubre coexistencia v1/v2, conservación de identidad y
valores, conversión pura sin mutaciones, idempotencia sin una segunda
escritura, errores de versión y documento inválido, ausencia y conflictos
concurrentes. En particular, debe comprobar cambios de contenido que
conserven v1, además de cambios de versión y borrados concurrentes.

Para detectar regresiones de la base reutilizada, se compara con las pruebas
M06 sin modificarlas:

```sh
python -m pytest tests/test_m06_evolution.py tests/test_m06_audit.py tests/test_m06_recovery.py -q
```

Las pruebas M07 usan un doble de `Table` que evalúa la condición contra el
estado almacenado. Ese resultado se distingue de las comprobaciones contra
un servicio real.

### Resultado individual del 21 de octubre de 2026

- **36 de 36 pruebas M07 aprobadas.** Incluyen conversión normal, reejecución
  sin escritura, coexistencia, límites, rechazo de datos inválidos y carreras.
- **5 de 5 pruebas M06 aprobadas** junto con M07: evolución, auditoría y
  recuperación. El total combinado fue **41 de 41**.
- **9 comprobaciones adicionales aprobadas contra DynamoDB Local en Docker
  dentro de WSL**: migración normal conservando datos e imagen anterior,
  reejecución sin escritura, convivencia con v1, v2 inicial sin escritura,
  comparación de imagen cruda, cambio concurrente dentro de v1, cambio
  concurrente a v2, borrado concurrente y versión desconocida sin escritura.
  Se utilizó una tabla sintética separada y se eliminó al terminar.

La ejecución combinada usó Python 3.14.4, pytest 9.1.1 y boto3 1.42.0;
Docker Engine 29.7.2 para el servicio local. La ejecución unitaria también
pasó en Python 3.12.14 en Windows.

Estos son resultados del aporte individual. La comprobación adicional y sus
reportes se conservaron en el entorno de trabajo; la integración de David
debe convertir la demostración en parte del verificador reproducible del
repositorio y generar el artifact/evidence oficial M07. Todavía no se ha
ejecutado ni declarado completo un flujo integrado M01–M07.

## Autoría y pendientes del equipo

- **Víctor:** `src/m07/versioning.py`, `src/m07/migration.py`, fixture de
  documentos versionados M07, `tests/test_m07_migration.py` y esta decisión.
- **Angélica:** adaptación y comprobación de compatibilidad entre los
  consumidores y las versiones persistidas.
- **David:** rollback controlado, integración del verificador, reportes y
  evidencia M07.

La aceptación final requiere revisar los aportes juntos, ejecutar el flujo
integrado y registrar resultados reales asociados al commit entregado.
