# ADR-005 — Implementar el almacén documental CDRL con DynamoDB

## Estado

Aceptado.

La decisión fue validada mediante la verificación integrada del repositorio.
`make verify` completó correctamente los módulos M02, M03, M04 y M05; las
cuatro pruebas obligatorias de M05 finalizaron con 4/4 aprobadas.

## Contexto

### Antecedente M04

En M04 el equipo evaluó distintas familias NoSQL para el workload CDRL y
seleccionó la familia documental como la alternativa con mejor ajuste.

MongoDB se utilizó como representante de la familia Document durante la
comparación de M04. Para M05 se requiere implementar un almacén documental
operativo y reproducible.

El entorno académico permite utilizar AWS Academy cuando está disponible y
DynamoDB Local mediante Docker Compose como respaldo. Por esta razón, M05
implementa concretamente el almacén mediante DynamoDB sin contradecir la
decisión de familia documental tomada en ADR-004.

### Requisitos de M05

El almacén debe:

- aceptar únicamente documentos que cumplan el contrato del evento;
- rechazar documentos inválidos antes de persistirlos;
- detectar intentos de creación duplicada;
- manejar explícitamente eventos inexistentes;
- soportar operaciones Create, Read, Update y Delete;
- utilizar índices declarados para consultas temporales;
- evitar `Scan` como solución para los patrones de acceso principales;
- utilizar fixtures sintéticos;
- configurarse mediante variables de entorno;
- ser reproducible tanto en DynamoDB Local como en AWS Academy;
- producir pruebas y evidencia machine-readable.

### Evento documental

Los eventos CDRL se representan con la estructura:

- `eventId`
- `type`
- `source`
- `timestamp`
- `payload`
- `metadata`

El tipo implementado actualmente es:

`telemetry.reading`

El `payload` contiene:

- `readingId`
- `deviceId`
- `receivedAt`
- `temperatureC`
- `humidityPct`
- `co2Ppm`

`metadata` contiene la versión del esquema mediante `schemaVersion`.

La identidad lógica del evento se construye de manera determinística a partir
de `deviceId` y el timestamp normalizado. Esto permite que un reintento del
mismo evento genere el mismo `eventId` y pueda detectarse como duplicado.

### Validación

Antes de persistir un documento se verifica:

- presencia exacta de los campos definidos por el contrato;
- `eventId` consistente con `deviceId` y `timestamp`;
- `type` igual a `telemetry.reading`;
- `source` consistente con `deviceId`;
- timestamps válidos y normalizados a UTC;
- `receivedAt >= timestamp`;
- identificadores enteros positivos;
- `schemaVersion == 1`;
- temperatura dentro de `[-50, 80]`;
- humedad dentro de `[0, 100]`;
- CO2 dentro de `[0, 10000]`.

Los valores numéricos se normalizan mediante `Decimal` antes de almacenarse.

### Patrones de acceso

M05 necesita resolver tres patrones principales:

1. obtener un evento exacto por `eventId`;
2. consultar eventos por `type` dentro de un rango temporal;
3. consultar eventos por `source` dentro de un rango temporal.

Las consultas temporales utilizan rangos inclusivos y los resultados se
ordenan de forma determinista por `timestamp` y `eventId`.

### Restricciones de infraestructura y seguridad

La implementación conserva la infraestructura existente del repositorio.

No se modifican para M05:

- `docker-compose.yml`;
- `rebuild.py`;
- `.github/workflows/cdrl-feedback.yml`;
- `scripts/verify_base.sh`;
- `scripts/verify_m02.sh`;
- `scripts/verify_m03.sh`;
- `scripts/verify_m04.sh`.

No se almacenan credenciales, tokens, datos personales ni cadenas de conexión
en el repositorio.

## Decisión

### Motor y modos de ejecución

Se implementa M05 con DynamoDB.

Se soportan dos modos:

- AWS Academy DynamoDB para el entorno cloud cuando el laboratorio esté
  habilitado;
- DynamoDB Local mediante Docker Compose para desarrollo local y CI.

La selección del modo y parámetros de conexión se realiza mediante variables
de entorno.

### Tabla y clave primaria

La tabla utilizada es:

`cdrl_events`

La clave primaria es:

- Partition Key: `eventId`

Esto permite recuperar un evento exacto mediante `GetItem`.

### Índices

Se declaran exactamente dos Global Secondary Indexes.

#### `type-timestamp-index`

- Partition Key: `type`
- Sort Key: `timestamp`

Soporta:

`type + rango temporal`

#### `source-timestamp-index`

- Partition Key: `source`
- Sort Key: `timestamp`

Soporta:

`source + rango temporal`

Las consultas principales se ejecutan mediante `GetItem` y `Query`.

No se utiliza `Scan` para resolver los patrones de acceso declarados en este
ADR.

### Creación

`create_event(event)` valida primero el documento.

La inserción usa:

`attribute_not_exists(eventId)`

para impedir que un segundo intento con la misma identidad sobrescriba
silenciosamente el evento existente.

Cuando ocurre un duplicado se genera `DuplicateEventError`.

### Lectura

`get_event(event_id)` utiliza `GetItem` sobre la PK `eventId`.

Cuando el evento no existe devuelve `None`.

### Actualización

`update_event(event_id, changes)`:

1. obtiene el documento actual;
2. combina los cambios parciales;
3. valida nuevamente el documento completo;
4. escribe únicamente si `eventId` continúa existiendo.

La condición:

`attribute_exists(eventId)`

evita un upsert accidental.

Cuando el evento requerido no existe se genera `EventNotFoundError`.

### Eliminación

`delete_event(event_id)` utiliza `DeleteItem` con `ReturnValues="ALL_OLD"`.

Devuelve:

- `True` cuando el evento existía y fue eliminado;
- `False` cuando el evento ya estaba ausente.

La repetición de la eliminación no crea ni corrompe estado, por lo que la
operación tiene comportamiento idempotente.

### Consultas

`query_by_type(type, start, end)` utiliza:

`type-timestamp-index`

`query_by_source(source, start, end)` utiliza:

`source-timestamp-index`

Ambas operaciones:

- utilizan `Query`;
- consumen la paginación mediante `LastEvaluatedKey`;
- usan rangos temporales inclusivos;
- devuelven orden determinista por `timestamp` y `eventId`.

### Infraestructura idempotente

`table_setup.py` crea `cdrl_events` cuando no existe.

Si la tabla ya existe, verifica que la estructura esperada esté presente en
lugar de crear una segunda tabla.

Por lo tanto, repetir el setup no duplica infraestructura.

### Pruebas y evidencia

M05 define exactamente cuatro escenarios automatizados:

1. `test_document_store_normal_flow`
   - Create
   - Read
   - Update
   - Delete
   - consulta por `type-timestamp-index`
   - consulta por `source-timestamp-index`

2. `test_duplicate_event_is_rejected`
   - verifica que un segundo Create con el mismo `eventId` sea rechazado.

3. `test_missing_event_is_handled`
   - Read devuelve ausencia;
   - Update no crea un evento inexistente;
   - Delete de un id ausente devuelve `False`.

4. `test_invalid_document_is_rejected`
   - un documento inválido es rechazado antes de persistirse.

`scripts/verify_m05.sh` valida infraestructura, ejecuta estas cuatro pruebas y
genera:

`artifacts/m05-document-store-results.json`

La evidencia final se registra en:

`evidence/m05-document-store.json`

### Autoría técnica

La implementación se realizó de forma secuencial mediante ramas y Pull
Requests.

**Víctor Manuel Jiménez Suárez**

Responsable de:

- contrato documental;
- validación del evento;
- configuración del cliente DynamoDB;
- creación idempotente de tabla;
- definición de GSIs;
- fixtures sintéticos.

**Angélica Arlett Santiago Serrano**

Responsable de:

- Create;
- Read;
- Update;
- Delete;
- manejo de duplicado y ausencia;
- consulta por `type-timestamp-index`;
- consulta por `source-timestamp-index`;
- paginación y orden determinista.

**Nicolás David Juárez Mendoza**

Responsable de:

- pruebas automatizadas M05;
- `scripts/verify_m05.sh`;
- generación y validación del artifact;
- evidencia M05;
- integración mínima en `Makefile`;
- consolidación de ADR-005;
- validación final de la entrega.

## Consecuencias

### Beneficios

La implementación proporciona:

- validación explícita antes de persistir;
- detección controlada de duplicados;
- ausencia manejada de forma explícita;
- CRUD reproducible;
- infraestructura idempotente;
- consultas dirigidas mediante índices;
- ejecución local sin depender permanentemente de AWS;
- posibilidad de ejecutar el mismo contrato sobre AWS Academy;
- pruebas y resultados machine-readable.

### Trade-offs y riesgos

Los GSIs de DynamoDB tienen consistencia eventual, por lo que una consulta
sobre un índice puede tardar brevemente en reflejar una escritura reciente.

Los tests contemplan esta característica mediante una espera limitada al
validar consultas indexadas.

La actualización actual reemplaza el documento completo después de combinar y
validar los cambios. La condición de existencia impide upsert accidental, pero
no implementa control de versiones para actualizaciones concurrentes.

La elección de índices depende directamente de los patrones de acceso
declarados. Nuevas consultas pueden requerir nuevos índices o una revisión del
modelo.

### Limitaciones

La implementación actual se concentra en eventos `telemetry.reading` con
`schemaVersion` 1.

No se implementan consultas generales mediante `Scan`.

No se implementa control optimista de concurrencia mediante versionado del
documento.

Las pruebas locales utilizan DynamoDB Local y fixtures sintéticos.

### Trabajo futuro

Como evolución se puede considerar:

- versionado adicional del contrato;
- nuevos tipos de evento;
- control optimista de concurrencia;
- TTL para eventos con política de retención;
- métricas de capacidad y consumo;
- pruebas automatizadas adicionales sobre AWS Academy;
- evaluación de nuevos GSIs únicamente cuando aparezcan nuevos patrones de
  acceso justificados.