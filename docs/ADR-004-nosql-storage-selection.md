# ADR-004 Selección de almacenamiento NoSQL para CDRL

## Estado

Aceptado.

La matriz ponderada reproducible de M04 fue completada y validada mediante pruebas automatizadas. Con los pesos definidos para consultas, escala/ingestión, consistencia, costo, fallos/disponibilidad y complejidad operativa, la alternativa Document, representada por MongoDB, obtuvo la mayor puntuación con 3.95/5. Apache Cassandra obtuvo 3.80/5, mientras que Neo4j y Amazon S3 obtuvieron 2.90/5. La decisión no presenta empate ni criterios pendientes.

## Contexto

CDRL registra telemetría ambiental. M01 definió locations, devices y telemetry_readings con restricciones de integridad; M02 agregó consultas parametrizadas y v_telemetry_context; M03 incorporó roles, mínimo privilegio y secretos externos al repositorio.

M04 compara Document, Graph, Column/Wide-column y Object para los eventos del proyecto. PostgreSQL y las entregas anteriores se conservan. DynamoDB Local ya disponible no constituye una decisión de arquitectura.

Base inspeccionada: development, commit `4cacc1d2ece95ce885f0bf9dd191f1c89d970b09`. Los comportamientos descritos como existentes provienen de R1–R4. Las cargas, modelos NoSQL y puntuaciones son propuestas de evaluación; no son resultados de un benchmark.

## Workload CDRL

### Consultas existentes

| ID | Función en R1 | Semántica que debe conservarse | Patrón de acceso |
| --- | --- | --- | --- |
| Q1 | readings_between | Dispositivo concreto; intervalo inclusivo [start, end]; orden ascendente por recorded_at e id; lista vacía si no hay datos. | Igualdad por dispositivo, rango y orden temporal. |
| Q2 | latest_reading | Orden descendente por recorded_at e id; un resultado o None. | Último evento de un dispositivo. |
| Q3 | reading_statistics | COUNT y AVG/MIN/MAX de temperatura, humedad y CO2; intervalo inclusivo; COUNT=0 y agregados None sin lecturas. | Rango por dispositivo y agregación. |
| Q4 | devices_at_location | Dispositivos de cualquier estado en una ubicación; orden por id. | Metadatos filtrados por ubicación. |
| Q5 | recent_active_readings | Intervalo inclusivo; dispositivos actualmente activos; orden descendente por recorded_at y reading_id; límite 20 por defecto, permitido entre 1 y 1000. | Eventos temporales globales y metadatos actuales relacionados. |

R1 acepta identificadores enteros positivos dentro del rango BIGINT y exige fechas con zona horaria. Un intervalo invertido es inválido; start=end es válido. El límite de Q5 es global, no por dispositivo. Q5 devuelve ubicación, pero no recibe un filtro location_id.

Q1–Q3 muestran que dispositivo y tiempo son dimensiones centrales. Q4 y Q5 exigen conservar acceso a metadatos. La existencia de relaciones no demuestra por sí sola que se necesiten recorridos de grafos de profundidad variable: las consultas actuales utilizan relaciones directas.

### Estado actual y relaciones

R3 une cada lectura con su dispositivo y la ubicación actual de este. No representa historial de movimientos. Cambiar el estado de un dispositivo puede cambiar qué lecturas aparecen en Q5; cambiar su ubicación cambia el contexto mostrado para sus lecturas anteriores.

Por ello, copiar status y location_id en cada evento sin mantenerlos actualizados no reproduce Q5. Las alternativas deben consultar metadatos actuales, sincronizarlos con garantías declaradas o justificar un cambio de contrato. En una arquitectura híbrida, los metadatos pueden seguir siendo autoridad de PostgreSQL; cualquier copia NoSQL necesita una política de sincronización. Una transacción dentro de un motor no vuelve atómica una escritura entre PostgreSQL y otro motor.

### Escrituras y contrato

Se modela la llegada de nuevas lecturas de dispositivos existentes. R2 impide duplicar `(device_id, recorded_at)`, recibir antes de medir y registrar métricas fuera de rango. Esas invariantes deben conservarse aunque cambie el almacenamiento. La frecuencia de escritura y consulta no está medida en el repositorio.

## Evento canónico

| Campo | Tipo de origen | Regla |
| --- | --- | --- |
| id | BIGINT identity | Identificador técnico único; conservar como reading_id si se reproducen las salidas actuales. |
| device_id | BIGINT | Obligatorio y asociado a un dispositivo existente. |
| recorded_at | TIMESTAMPTZ | Obligatorio; instante de la medición. |
| received_at | TIMESTAMPTZ | Obligatorio; por defecto CURRENT_TIMESTAMP; recorded_at <= received_at. |
| temperature_c | NUMERIC(5,2) | Obligatorio; entre -50.00 y 80.00 inclusive. |
| humidity_pct | NUMERIC(5,2) | Obligatorio; entre 0.00 y 100.00 inclusive. |
| co2_ppm | NUMERIC(8,2) | Obligatorio; entre 0.00 y 10000.00 inclusive. |

La clave natural del evento es dispositivo e instante, no el instante aislado. Dos dispositivos pueden medir al mismo tiempo. Un reintento idéntico no debe producir una segunda lectura; un conflicto con valores diferentes necesita rechazo o una política explícita, no una sobrescritura silenciosa.

Ejemplo sintético conceptual, no un formato de importación de un motor:

```json
{
  "reading_id": 1001,
  "device_id": 42,
  "recorded_at": "2026-09-25T12:00:00.123456Z",
  "received_at": "2026-09-25T12:00:01.000000Z",
  "temperature_c": "23.45",
  "humidity_pct": "51.20",
  "co2_ppm": "650.00"
}
```

Las cadenas decimales del ejemplo evitan confundir la representación de intercambio con un float binario. Para índices temporales se propone normalizar a UTC y conservar microsegundos mediante un entero de 64 bits desde epoch, validando su rango. No se debe truncar silenciosamente la precisión temporal del origen.

Para agregaciones exactas puede utilizarse Decimal128 en MongoDB o enteros escalados por 100 para las métricas en ambos modelos. AVG requiere convertir SUM/COUNT con aritmética decimal y reproducir el tratamiento de conjuntos vacíos. El redondeo final debe definirse en el adaptador. Son decisiones de diseño pendientes de implementación, no validaciones ya ejecutadas.

## Escenarios y supuestos de carga

Se propone una lectura por dispositivo cada 60 segundos y operación continua. Un día tiene 1440 intervalos de un minuto; el mes de comparación tiene 30 días.

| Escenario | Dispositivos | Eventos/día | Eventos/30 días | Escrituras/s promedio |
| --- | ---: | ---: | ---: | ---: |
| Inicial | 100 | 144000 | 4320000 | 1.67 |
| Crecimiento | 1000 | 1440000 | 43200000 | 16.67 |
| Expansión | 10000 | 14400000 | 432000000 | 166.67 |

Estos escenarios son propuestos, no medidos. El promedio no representa el pico: si todos los dispositivos envían durante el mismo segundo, expansión genera una ráfaga de 10000 eventos. Se propone evaluar distribución uniforme y sincronizada, y un dispositivo que genere 10 % del tráfico para explorar concentración.

Para hacer repetible una evaluación futura se propone además:

- Retención operativa de 30 días y análisis separado del archivo histórico.
- Q1: últimas 24 horas; Q2: última lectura; Q3: últimos 7 días; Q4: ubicación seleccionada; Q5: última hora, límite 20 y evaluación adicional con 1000.
- Mezcla de solicitudes de lectura Q1/Q2/Q3/Q4/Q5: 30/30/20/10/10 %, respectivamente; no representa frecuencia observada.
- Carga base de 10 solicitudes/s y sensibilidad a 100 solicitudes/s, con concurrencia máxima de 20 clientes. Registrar throughput logrado y latencias; no asumir que se alcanzan.
- Usar el mismo conjunto sintético, distribución de dispositivos y ventanas en cada alternativa. Separar tiempo de carga, calentamiento y medición.

Para estimar almacenamiento lógico se propone sensibilidad de 256, 512 y 1024 bytes/evento, no tamaños medidos. A 512 bytes, expansión supone 221.184 GB decimales por 30 días antes de índices, relaciones, réplicas, logs y respaldos. Angélica deberá utilizar estos mismos supuestos o documentar los cambios acordados para las cuatro familias.

## Criterios y escala utilizados

La matriz final utiliza los pesos definidos por la guía: consultas 30 %, escala/ingestión 25 %, consistencia 15 %, costo 15 %, fallos/disponibilidad 10 % y complejidad operativa 5 %. En conjunto suman 100 %.

Consultas y escala reciben el mayor peso por el acceso repetido a eventos y su acumulación. Consistencia protege el contrato del evento; costo y operación permiten comparar las capacidades sin ignorar los recursos y mantenimiento necesarios.

La escala de puntuación utilizada es de 1 a 5:

- 1: ajuste muy bajo.
- 2: ajuste bajo.
- 3: ajuste aceptable con adaptaciones.
- 4: ajuste alto con limitaciones identificadas.
- 5: ajuste alto y demostrado para el escenario completo.

En complejidad operativa, una puntuación mayor representa menor esfuerzo operativo. En costo, una puntuación mayor representa menor costo total para proporcionar garantías equivalentes.

Los pesos y puntuaciones fueron incorporados a `src/m04/storage_matrix.json` y utilizados por el cálculo reproducible de M04.

## Alternativa Document

### Modelo de referencia

Se utiliza MongoDB como representante concreto, sin atribuir automáticamente sus capacidades a toda la familia. Se propone una colección regular de lecturas con un documento por evento, y metadatos de dispositivos y ubicaciones separados. No se presupone una colección time-series, cuyas restricciones deben evaluarse por separado.

El documento contiene reading_id, device_id, recorded_at_us, received_at_us y métricas decimales o escaladas. Un índice compuesto comienza por device_id y continúa por recorded_at_us para acceso por igualdad y rango [D1]. Un índice único sobre esa pareja reproduce la unicidad; si se distribuye la colección, debe comprobarse su compatibilidad con la shard key [D2].

BSON Date representa milisegundos; por eso la propuesta utiliza microsegundos enteros para no colapsar dos instantes distintos del contrato. BSON también dispone de enteros de 64 bits y Decimal128 [D3]. No debe convertirse BIGINT a un Number de JavaScript sin verificar pérdida de precisión.

### Resolución de consultas

| Consulta | Estrategia propuesta | Costo o limitación |
| --- | --- | --- |
| Q1 | Filtrar device_id y rango inclusivo recorded_at_us; ordenar ascendente; adaptar campos de salida. | Verificar plan y cobertura; devolver muchos eventos mantiene costo proporcional a resultados. |
| Q2 | Mismo dispositivo, orden temporal descendente y un resultado. | Conservar None si no hay eventos y reading_id en la respuesta. |
| Q3 | Filtrar primero, luego COUNT/SUM/MIN/MAX y cálculo decimal de AVG. | El índice no vuelve constante el costo de agregar todas las lecturas seleccionadas. |
| Q4 | Consultar dispositivos por location_id; índice de metadatos y orden por id. | Los eventos solos no resuelven esta consulta. |
| Q5 | Seleccionar eventos temporales y resolver dispositivo/ubicación actuales, filtrar activos, ordenar globalmente y después limitar. | Requiere composición con metadatos; no aplicar límite antes de filtrar activos. Un índice global temporal es candidato adicional, no reemplazado por el índice por dispositivo. |

Si Q5 usa PostgreSQL como autoridad, el adaptador debe obtener candidatos adicionales hasta completar el límite o agotar el intervalo. Si usa copias de metadatos, debe declarar y comprobar su actualización. No basta con traer 20 eventos y eliminar los inactivos.

### Escala, consistencia, costo y fallos

MongoDB permite distribuir datos con sharding; una clave alineada con accesos ayuda a dirigir consultas, mientras accesos sin esa clave pueden consultar múltiples shards [D4]. Se propone evaluar dispositivo y partición temporal como dimensiones, sin aprobar aún una clave. El dispositivo caliente, el índice único y Q5 global condicionan el diseño.

Para lectura posterior a escritura se propone evaluar sesiones causales con readConcern y writeConcern majority, respetando las condiciones documentadas [D5]. Esto no equivale a aislamiento global ni resuelve sincronización entre motores.

El costo debe incluir documentos, índices, réplicas, almacenamiento, cómputo, respaldo, transferencia y administración. El sharding añade componentes y operación; no se demuestra ahorro monetario por el nombre de la tecnología. Ante pérdida del primario, un replica set necesita recuperación/elección; no se promete disponibilidad continua ni RTO medido [D6].

## Alternativa Graph

### Modelo de referencia

Se utiliza Neo4j como representante. El modelo conceptual es:

```text
(Location)<-[:LOCATED_AT]-(Device)-[:EMITTED]->(Reading)
```

Device conserva el estado y la relación con la ubicación actual. Reading contiene reading_id, device_id, recorded_at_us, received_at_us y métricas escaladas. Se conserva device_id como propiedad del evento para facilitar acceso indexado; su igualdad con el dispositivo conectado debe comprobarse al escribir.

Cada evento crea un nodo Reading y una relación EMITTED. Esto introduce elementos adicionales que se deben medir; no permite afirmar cuántos bytes o cuánto dinero costará sin medición. La escritura del nodo y relación debe ser atómica y debe imponer la unicidad del evento mediante una restricción adecuada a la edición/version elegida o una clave canónica única sin ambigüedad.

### Resolución de consultas

| Consulta | Estrategia propuesta | Costo o limitación |
| --- | --- | --- |
| Q1 | Buscar Reading por device_id y recorded_at_us mediante índice compuesto de rango; ordenar. | No asumir que recorrer todas las relaciones de un dispositivo será eficiente para cualquier ventana. |
| Q2 | Buscar lecturas indexadas del dispositivo, ordenar descendente y limitar a una. | Revisar el plan; una relación no proporciona automáticamente orden temporal. |
| Q3 | Filtrar lecturas por dispositivo/tiempo y agregar métricas. | Convertir correctamente escala decimal y conjuntos vacíos. |
| Q4 | Obtener Location y sus dispositivos relacionados, de cualquier estado, ordenados por id. | Las relaciones representan directamente esta necesidad. |
| Q5 | Filtrar lecturas por intervalo y recorrer hacia Device/Location actuales; filtrar active, ordenar globalmente y limitar. | Necesita coherencia de los metadatos y plan apropiado para rango, filtros y orden. |

Neo4j dispone de índices de rango y compuestos. Su uso depende de las propiedades y predicados de la consulta; debe revisarse con EXPLAIN/PROFILE [G1]. No se descarta Graph por una supuesta incapacidad de consultar fechas.

### Escala, consistencia, costo y fallos

En el modelo de clúster estándar descrito por G2, una base tiene un writer elegido entre sus primaries; las copias secundarias aportan escalado de lecturas. Añadir réplicas no demuestra escalado lineal de escrituras de esa base. Otras arquitecturas o capacidades requieren evaluación propia; no se generaliza esta limitación a todos los grafos.

Neo4j ofrece transacciones ACID; la documentación describe read committed como aislamiento predeterminado [G3]. La consistencia causal entre sesiones requiere gestionar bookmarks [G4]. ACID no significa automáticamente serialización de todas las lecturas ni consistencia con PostgreSQL.

El costo incorpora nodos, relaciones, índices, réplicas, recursos, backups y edición/licencia aplicable. El modelo estándar de tres primaries puede conservar escritura ante pérdida de uno mientras los dos restantes mantengan comunicación; perder el quorum impide nuevas escrituras [G2]. Este es respaldo documental, no una prueba ejecutada en CDRL.

## Alternativa Column / Wide-column

### Modelo de referencia

Para evaluar la alternativa Column/Wide-column se utiliza Apache Cassandra como implementación de referencia. Cassandra es una base de datos NoSQL distribuida con un modelo wide-column particionado. DynamoDB Local permanece disponible en la infraestructura del proyecto, pero no se utiliza como representante de esta familia ni constituye evidencia a favor de la selección.

Para las lecturas de telemetría se propone una tabla orientada a consultas por dispositivo y tiempo con una clave primaria equivalente a:

```sql
PRIMARY KEY ((device_id), recorded_at_us)
```

`device_id` actúa como partition key y `recorded_at_us` como clustering column. Esta organización se deriva del workload existente: Q1, Q2 y Q3 acceden principalmente a las lecturas de un dispositivo concreto y una dimensión temporal.

Las filas conservarían `reading_id`, `device_id`, `recorded_at_us`, `received_at_us`, `temperature_c`, `humidity_pct` y `co2_ppm`. La combinación `(device_id, recorded_at_us)` identifica lógicamente una lectura. `reading_id` permanece como identificador técnico del evento y no sustituye esa clave. La precisión temporal y decimal debe conservar las decisiones del evento canónico para evitar modificar el contrato existente.

La clave propuesta es un diseño para evaluación, no una decisión definitiva. Debe comprobarse frente a Q1–Q5 y ante distribuciones uniformes y sesgadas de tráfico. Los accesos no alineados con la clave primaria pueden requerir tablas adicionales, índices o composición con los metadatos que permanecen en PostgreSQL.

### Resolución de consultas

| Consulta | Estrategia propuesta | Costo o limitación |
| --- | --- | --- |
| Q1 | Consultar la partición de `device_id` y restringir `recorded_at_us` al intervalo inclusivo solicitado, conservando el orden temporal. | El patrón coincide con partition key y clustering column. El trabajo continúa dependiendo del número de filas del intervalo. |
| Q2 | Consultar la partición del dispositivo en orden temporal descendente y limitar el resultado a una lectura. | El acceso está alineado con dispositivo y tiempo. Debe conservarse la semántica de ausencia de resultados. |
| Q3 | Seleccionar primero las filas del dispositivo y rango temporal y calcular las estadísticas en la aplicación o mediante agregados explícitos. | La clave facilita localizar el intervalo, pero la agregación continúa dependiendo de las filas consideradas. Una tabla de agregados añade escrituras y requisitos de consistencia. |
| Q4 | Mantener dispositivos y ubicaciones en PostgreSQL o crear una tabla orientada a consulta por `location_id` si se decide duplicar esos metadatos. | `location_id` no forma parte de la primary key de telemetría. La duplicación introduce almacenamiento y sincronización adicionales. |
| Q5 | Crear una estructura adicional orientada a eventos recientes, posiblemente mediante buckets temporales, o consultar candidatos y combinarlos con estado y ubicación actuales desde PostgreSQL. | La partición por dispositivo no resuelve por sí sola una consulta temporal global. El límite debe aplicarse después de filtrar los dispositivos activos. |

No se propone utilizar `ALLOW FILTERING` como sustituto de un modelo orientado a consultas para Q4 o Q5. Si esos patrones requieren acceso directo desde Cassandra, deberán diseñarse tablas adicionales con claves adecuadas o componerse explícitamente con PostgreSQL.

### Particionamiento, concentración y throughput

La evaluación conservará los escenarios comunes de 100, 1,000 y 10,000 dispositivos, con una lectura por dispositivo cada 60 segundos. Esto corresponde a aproximadamente 1.67, 16.67 y 166.67 escrituras por segundo en promedio.

También se evaluará la ráfaga sincronizada de 10,000 eventos dentro del mismo segundo y el escenario sesgado donde un dispositivo produce el 10 % del tráfico.

Usar `device_id` como partition key distribuye dispositivos diferentes entre particiones, pero no garantiza por sí solo una distribución uniforme del throughput. Un dispositivo excepcionalmente activo concentra sus escrituras sobre una misma partición lógica.

Con una lectura por minuto durante 30 días, cada dispositivo produciría 43,200 lecturas durante la retención operacional propuesta. Con un tamaño lógico de referencia de 512 bytes por evento, esto equivale aproximadamente a 22.1 MB lógicos por dispositivo antes de replicación, índices, metadata, compresión y demás overhead físico.

Si el tamaño o actividad de una partición resulta problemático, deberá evaluarse una estrategia con bucket temporal, por ejemplo:

```text
((device_id, day_bucket), recorded_at_us)
```

Esta alternativa limita el tamaño de cada partición, pero obliga a consultar varias particiones cuando una ventana cruza diferentes buckets. No se adoptará sin evidencia obtenida con el workload propuesto.

El throughput se registrará utilizando el mismo dataset, ventanas y concurrencia de las demás alternativas. Las capacidades documentadas de Cassandra no se presentarán como rendimiento medido del CDRL.

### Consistencia e invariantes

La alternativa Column debe preservar el contrato del evento aunque no utilice restricciones relacionales de PostgreSQL. La aplicación o adaptador deberá validar rangos de métricas, `recorded_at <= received_at`, precisión temporal y asociación con un dispositivo válido.

En Cassandra una escritura normal sobre una primary key existente tiene semántica de upsert. Cuando sea necesario rechazar explícitamente una creación cuya clave `(device_id, recorded_at_us)` ya existe, se evaluará una escritura condicional:

```sql
INSERT ... IF NOT EXISTS
```

Esta operación utiliza una lightweight transaction y requiere coordinación adicional, por lo que deberá medirse su impacto. No debe suponerse que un `INSERT` ordinario reproduce el rechazo de unicidad de PostgreSQL.

Para operaciones que necesiten lectura posterior a escritura deberá declararse el consistency level utilizado. Cassandra ofrece niveles configurables como `ONE`, `QUORUM`, `ALL` y `LOCAL_QUORUM`. La configuración seleccionada deberá relacionarse con el replication factor y con la garantía requerida por el CDRL.

Las garantías internas de Cassandra no vuelven atómica una operación distribuida entre Cassandra y PostgreSQL. Si PostgreSQL permanece como autoridad de dispositivos y ubicaciones, cualquier copia de `status` o `location_id` debe declarar su política de sincronización, actualización y reintentos.

### Costo y fallos

El costo de Column no se estimará únicamente mediante almacenamiento. La comparación deberá considerar nodos o capacidad de cómputo, almacenamiento de datos, replication factor, tablas o índices adicionales, respaldos, transferencia, monitoreo y esfuerzo operativo.

Si se evalúa una oferta administrada compatible con Cassandra, deberán contabilizarse sus componentes facturables necesarios para proporcionar garantías equivalentes. Si se evalúa Cassandra autogestionado, deberán contabilizarse explícitamente los recursos de infraestructura y operación necesarios; la ausencia de una licencia comercial no equivale a costo total cero.

La valoración utilizará el mismo horizonte de 30 días, volumen de eventos, tamaños lógicos y garantías de las demás alternativas. Hasta completar una estimación reproducible no se afirmará que Cassandra sea más barata o más cara que las demás alternativas.

Los escenarios de fallo incluirán reintento de una escritura cuya respuesta se perdió, indisponibilidad temporal de una réplica, lectura posterior a una escritura confirmada, pérdida temporal de un miembro y recuperación y convergencia de réplicas.

La evaluación deberá registrar replication factor, consistency level y política de reparación. Por ejemplo, con replication factor 3 y `LOCAL_QUORUM`, la disponibilidad efectiva depende de que pueda alcanzarse el número de réplicas requerido por ese nivel; no se generalizará una garantía sin declarar la topología evaluada.

Cuando una réplica está temporalmente indisponible, Cassandra puede conservar hints para intentar reproducir posteriormente las mutaciones pendientes. Hinted handoff no sustituye los procesos de repair necesarios para asegurar la convergencia de réplicas.

## Alternativa Object Store

### Modelo de referencia

Se utiliza Amazon S3 como representante concreto de la familia Object Store. El objetivo no es asumir que un almacenamiento de objetos reemplaza directamente una base operacional, sino evaluar si resulta apropiado para los eventos del CDRL y distinguir entre consultas frecuentes sobre datos recientes y conservación de históricos.

En un modelo de objetos, las lecturas de telemetría podrían agruparse en archivos por intervalos temporales y organizarse mediante prefijos derivados de dimensiones como fecha y dispositivo. Por ejemplo, un esquema conceptual podría utilizar rutas como `telemetry/year=2026/month=09/day=26/device_id=42/`, sin asumir que esta estructura constituye un índice equivalente al de una base de datos.

Para históricos se propone evaluar formatos orientados a análisis como Parquet, además de formatos simples de intercambio cuando sean necesarios. Agrupar múltiples eventos en objetos evita crear necesariamente un objeto independiente por cada lectura y permite separar la retención operacional de 30 días del archivo histórico.

El Object Store no se considerará automáticamente sustituto del almacenamiento operacional. Las consultas Q1–Q5 deben analizarse considerando que localizar, filtrar, agregar y relacionar información dentro de objetos puede requerir un motor de consulta, catálogo, índices externos o procesamiento adicional.

### Consulta operacional frente a archivo histórico

Para esta comparación se distinguen dos niveles de almacenamiento. La retención operacional corresponde a los eventos recientes que deben satisfacer directamente Q1–Q5 con los patrones y límites declarados. El histórico corresponde a eventos que ya no necesitan el mismo nivel de acceso inmediato, pero deben conservarse para análisis posterior, auditoría, procesamiento por lotes o reconstrucción de datasets.

La retención operacional propuesta previamente es de 30 días. Al finalizar ese periodo, una arquitectura híbrida podría conservar eventos históricos en Object Store sin exigir que este reproduzca por sí solo todas las características del almacenamiento operacional.

Esta separación evita evaluar Object Store únicamente por una función para la cual no fue diseñado el modelo propuesto. Sin embargo, para que pueda competir como almacén principal de eventos, deberá demostrar que Q1–Q5 pueden resolverse con las garantías y costos requeridos sin depender de componentes adicionales que cambien sustancialmente la arquitectura evaluada.

### Resolución de consultas

| Consulta | Estrategia propuesta | Costo o limitación |
| --- | --- | --- |
| Q1 | Localizar los objetos correspondientes al dispositivo y periodo mediante una organización por prefijos/particiones y procesar únicamente los archivos relevantes. | La organización física puede reducir los objetos considerados, pero Object Store no proporciona por sí solo un índice operacional equivalente a `device_id + recorded_at`; el filtrado fino puede requerir lectura de archivos o un motor de consulta adicional. |
| Q2 | Identificar el objeto o partición temporal más reciente del dispositivo y obtener la última lectura contenida en él. | Requiere conocer qué objeto contiene el evento más reciente o mantener metadata/índice adicional. No es un acceso natural de objeto individual si múltiples eventos se agrupan por archivo. |
| Q3 | Procesar los archivos del dispositivo y rango para calcular `COUNT`, `AVG`, `MIN` y `MAX`, preferentemente mediante un formato analítico y un motor capaz de aprovechar particiones y metadata. | Tiene buen ajuste para análisis por lotes e históricos, pero la latencia y cantidad de datos leídos deben medirse; el motor de consulta adicional forma parte del costo de la solución. |
| Q4 | Mantener dispositivos y ubicaciones en PostgreSQL o exportar datasets de metadatos cuando el análisis histórico lo requiera. | Object Store no sustituye naturalmente las consultas operacionales de metadatos actuales por ubicación. |
| Q5 | Combinar eventos recientes con el estado y ubicación actuales, ordenar globalmente y aplicar el límite después del filtro. | Como consulta operacional frecuente tiene bajo ajuste en un Object Store puro; requeriría metadata actual y procesamiento o índices externos. Utilizar un motor adicional debe contabilizarse como parte de la arquitectura y no atribuirse al Object Store por sí solo. |

### Escala, particionamiento y crecimiento

Object Store se evaluará con los mismos escenarios de 4.32 millones, 43.2 millones y 432 millones de eventos por 30 días. La unidad física de almacenamiento no será necesariamente un objeto por evento. Se evaluará la agrupación de eventos en archivos de tamaño controlado para evitar que el número de solicitudes y objetos pequeños crezca en la misma proporción que el número de lecturas.

La organización por prefijos y particiones lógicas deberá permitir limitar el conjunto de objetos considerado para consultas históricas por dispositivo y tiempo. La elección de granularidad representa un compromiso: archivos demasiado grandes aumentan la cantidad de datos procesados para ventanas pequeñas, mientras que archivos demasiado pequeños incrementan el número de objetos, solicitudes y metadata operacional.

Para la comparación se mantendrán las sensibilidades de 256, 512 y 1024 bytes lógicos por evento ya declaradas, pero el tamaño físico del archivo deberá medirse después de serialización, compresión y metadata. No se asumirá que el tamaño lógico del evento equivale al almacenamiento facturable.

El crecimiento histórico se evaluará separadamente del throughput operacional. Object Store puede absorber grandes volúmenes de objetos, pero esa capacidad no demuestra que Q1–Q5 mantengan una latencia adecuada. Escalabilidad de almacenamiento y eficiencia de consulta son criterios relacionados pero diferentes.

### Consistencia e invariantes

La conservación de eventos en Object Store no elimina las invariantes del contrato CDRL. Antes de generar un objeto histórico, los eventos deben haber sido validados respecto de rangos, precisión temporal, relación entre `recorded_at` y `received_at` y unicidad lógica.

Amazon S3 ofrece consistencia fuerte de lectura después de escritura para operaciones sobre objetos. Sin embargo, esta garantía no resuelve por sí sola la consistencia entre PostgreSQL, un almacenamiento operacional y el archivo histórico. Si los eventos se exportan posteriormente al Object Store, debe definirse cómo se identifica qué eventos ya fueron archivados, cómo se manejan reintentos y cómo se evita duplicar u omitir información.

Los objetos históricos deben considerarse derivados de una fuente operacional autoritativa hasta que el proceso de archivado declare una política diferente. Una consulta histórica que combine eventos archivados con metadatos actuales deberá reconocer que ambos representan momentos o fuentes distintas y evitar presentar esa combinación como una única transacción atómica.

### Costo y fallos

El costo de Object Store se evaluará considerando almacenamiento por volumen y clase, solicitudes de escritura, lectura y listado, recuperación cuando corresponda, transferencia, lifecycle, respaldos o replicación adicional y los motores de consulta o catálogos necesarios para satisfacer los casos evaluados. No se considerará únicamente el precio por GB.

Para el histórico se utilizará el mismo horizonte temporal y volumen lógico que las demás alternativas. Si se aplican políticas de lifecycle hacia clases de almacenamiento de menor costo, también deberán contabilizarse sus restricciones de acceso y recuperación; reducir el costo de almacenamiento puede aumentar latencia o cargos cuando los datos vuelven a consultarse.

Entre los escenarios de fallo se evaluarán exportaciones interrumpidas, reintentos del mismo lote, creación satisfactoria del objeto seguida de un fallo antes de registrar su estado y ausencia temporal de uno de los componentes utilizados para consultar el histórico. El proceso deberá ser idempotente o disponer de una estrategia equivalente que evite pérdida y duplicación lógica de eventos.

El Object Store puede reducir la necesidad de mantener históricos completos en almacenamiento operacional de mayor costo, pero esta afirmación deberá comprobarse mediante el modelo común de costos. No se asignará una puntuación alta de costo únicamente por asumir que el almacenamiento de objetos es barato.

## Supuestos comunes de evaluación operativa

Las cuatro alternativas se evaluarán bajo los mismos escenarios, horizonte temporal y requisitos funcionales. El propósito es evitar favorecer una tecnología mediante cargas, retenciones o garantías diferentes.

### Escala y crecimiento

Se conservan los tres escenarios definidos previamente: Inicial con 100 dispositivos, Crecimiento con 1,000 dispositivos y Expansión con 10,000 dispositivos. Cada dispositivo genera una lectura cada 60 segundos durante operación continua.

Esto produce 144,000, 1,440,000 y 14,400,000 eventos por día respectivamente, equivalentes a 4.32 millones, 43.2 millones y 432 millones de eventos durante un periodo de 30 días.

La evaluación distinguirá throughput promedio de carga pico. En Expansión el promedio corresponde a 166.67 eventos por segundo, pero también se analizará una ráfaga sincronizada de hasta 10,000 eventos dentro del mismo segundo y un escenario sesgado donde un dispositivo genera el 10 % del tráfico.

Para almacenamiento se conservará la sensibilidad de 256, 512 y 1024 bytes lógicos por evento. Estos valores no representan tamaño físico medido: índices, relaciones, metadata, compresión, replicación, logs y respaldos deberán contabilizarse según cada alternativa.

### Modelo común de costo

El criterio de costo comparará el costo total necesario para satisfacer el mismo workload y garantías, no únicamente el precio nominal de almacenamiento de cada tecnología.

Se utilizará como modelo común:

`C_total = C_compute + C_storage + C_backup + C_transfer + C_license + C_operations`

Cuando un servicio facture directamente solicitudes de lectura o escritura, estas se incorporarán como una dimensión adicional o dentro del componente operativo correspondiente, evitando contabilizar dos veces recursos ya incluidos en otra tarifa.

Para hacer comparables las estimaciones se fijan los siguientes supuestos:

- horizonte de comparación: 30 días;
- cargas: escenarios Inicial, Crecimiento y Expansión ya declarados;
- retención operacional: 30 días;
- tamaños lógicos: 256, 512 y 1024 bytes por evento;
- mismo conjunto de consultas Q1–Q5 y mezcla de lectura declarada;
- misma expectativa de durabilidad y recuperación;
- precios consultados en una fecha explícita;
- precios expresados inicialmente en USD antes de cualquier conversión monetaria;
- para servicios AWS, utilizar Mexico (Central), `mx-central-1`, cuando el servicio evaluado esté disponible y la modalidad analizada sea comparable; para Amazon S3 y servicios desplegados directamente sobre infraestructura AWS se priorizará esa región. Para MongoDB Atlas y Neo4j Aura deberá registrarse explícitamente la región y modalidad realmente utilizada en la estimación. Si Apache Cassandra se evalúa de forma autogestionada sobre AWS, se utilizará infraestructura de una región disponible y se documentarán cómputo, almacenamiento, replicación y respaldos por separado. La disponibilidad regional y los precios deberán volver a verificarse si la estimación se repite posteriormente.
- si una alternativa no dispone de una oferta equivalente en esa región, deberá declararse la región utilizada y tratar la diferencia como una limitación de la comparación.

No se utilizarán créditos educativos, promociones, Free Tier ni descuentos temporales para determinar qué alternativa obtiene mejor puntuación, porque no representan el costo normal y reproducible de operación.

La ubicación del proyecto es Tehuacán, Puebla, México. Esta ubicación sirve como contexto para justificar una región cercana y analizar latencia, residencia y transferencia, pero los precios de servicios cloud se determinan por la región y modalidad del proveedor, no por la ciudad desde la que accede el usuario.

### Convención monetaria

Las estimaciones monetarias se expresarán primero en USD mensuales y antes de impuestos. Si se presenta posteriormente una conversión a MXN, se documentarán la fuente y fecha del tipo de cambio utilizado. Los impuestos, créditos académicos, promociones y descuentos temporales se reportarán separadamente y no modificarán la puntuación base.

La comparación busca estimar diferencias arquitectónicas reproducibles, no predecir una factura exacta. Los precios de proveedores y tipos de cambio pueden modificarse después de la fecha de evaluación.

### Interpretación del criterio de costo

La escala de costo conservará el significado general de la matriz: una puntuación mayor representa menor costo total para proporcionar garantías equivalentes.

- 1: costo relativo muy alto o requiere componentes adicionales importantes para satisfacer el workload.
- 2: costo alto frente a las demás alternativas bajo los mismos supuestos.
- 3: costo intermedio o diferencias insuficientes para considerarlo claramente favorable o desfavorable.
- 4: costo bajo con las garantías requeridas y sin omitir componentes relevantes.
- 5: costo muy bajo respaldado por una estimación reproducible para el escenario completo.

Una puntuación 3 no se utilizará como sustituto de información faltante. Si todavía no existe evidencia suficiente, el valor permanecerá `Por determinar` hasta completar la estimación.

### Evaluación comparativa de costo

La puntuación de costo no representa una cotización contractual ni una factura exacta. Representa el costo relativo esperado de satisfacer el workload CDRL bajo los mismos supuestos de volumen, retención, consultas y garantías.

La comparación utiliza servicios administrados como referencia cuando existe una modalidad comparable. Para servicios AWS se prioriza `mx-central-1` (Mexico Central) cuando la modalidad necesaria esté disponible. MongoDB Atlas y Neo4j Aura se evaluarán con el tier, proveedor cloud y región explícitamente declarados. Apache Cassandra se evaluará como despliegue autogestionado y deberá incluir los recursos necesarios para replicación, almacenamiento, respaldos y operación. Amazon S3 se evaluará con su modelo de cobro por almacenamiento, solicitudes y componentes adicionales requeridos para satisfacer Q1–Q5.

Las tecnologías poseen modelos de facturación diferentes. Document y Graph requieren capacidad de base de datos suficiente para mantener los datos operacionales, índices y procesamiento de consultas; Column/Cassandra requiere contabilizar cómputo, almacenamiento, replicación, respaldos y operación según la modalidad de despliegue; Object Store factura principalmente almacenamiento, solicitudes y servicios adicionales de procesamiento. Por ello, comparar únicamente USD por GB produciría una conclusión inválida.

Para cada alternativa se contabilizarán los componentes que realmente sean necesarios para satisfacer Q1–Q5. Si una alternativa necesita índices secundarios, capacidad adicional, un catálogo, un motor de consulta o sincronización con PostgreSQL, estos componentes no se considerarán gratuitos.

Las puntuaciones siguientes son relativas al diseño CDRL y deberán revisarse si una medición, cotización o benchmark posterior contradice sus supuestos. No deben interpretarse como una afirmación general de que una tecnología siempre sea más barata que otra.

| Alternativa | Componentes relevantes para CDRL | Riesgo de costo |
| --- | --- | --- |
| Document / MongoDB | cluster operacional, almacenamiento de documentos, índices, replicación/alta disponibilidad, backups, transferencia y operación | El crecimiento de eventos e índices exige dimensionar capacidad del cluster; Q1–Q5 se resuelven mayoritariamente dentro del mismo motor. |
| Graph / Neo4j | capacidad del cluster, nodos, relaciones, índices, almacenamiento, backups y operación | El modelo agrega relaciones y estructuras que el workload directo dispositivo-tiempo no explota intensivamente; la capacidad necesaria debe medirse antes de fijar una factura. |
| Column / Apache Cassandra | nodos de cómputo, almacenamiento, replication factor, tablas o índices adicionales, backups, transferencia, monitoreo y operación | El modelo se alinea con Q1/Q2, pero Q4/Q5 pueden requerir tablas adicionales o composición con PostgreSQL. En un despliegue autogestionado deben contabilizarse explícitamente infraestructura, replicación y esfuerzo operativo. |
| Object / S3 | almacenamiento de objetos, solicitudes, transferencia, lifecycle y procesamiento/catálogo adicional | El almacenamiento histórico puede ser económico, pero reproducir Q1–Q5 operacionalmente requiere componentes adicionales que deben contabilizarse. |

#### Estimación reproducible de referencia

Para evitar comparar únicamente precios mínimos de entrada, se toma como referencia el escenario Expansión con 10,000 dispositivos, 432,000,000 eventos durante 30 días y 512 bytes lógicos por evento. Esto representa 221.184 GB lógicos antes de índices, relaciones, replicación, logs, compresión y respaldos.

La estimación no pretende constituir una cotización contractual ni demostrar capacidad mediante benchmark. Su objetivo es proporcionar una base reproducible para comparar el orden de magnitud del costo y los componentes necesarios para satisfacer el mismo workload.

Para las alternativas cuyo proveedor factura por hora se utiliza un mes de referencia de 30 días, equivalente a 720 horas. Los precios consultados corresponden al 27 de septiembre de 2026. Cuando el proveedor publica precios dependientes de región, configuración o consumo, esa condición se conserva explícitamente como una limitación de la estimación.

| Alternativa | Configuración de referencia | Costo de referencia | Observaciones |
| --- | --- | ---: | --- |
| Document / MongoDB Atlas | Atlas Dedicated sobre AWS. Se utiliza M30 como referencia de capacidad: 8 GB RAM, 2 vCPU y rango configurable de almacenamiento de hasta 512 GB. | M30 base: aproximadamente USD 388/mes a USD 0.54/h. La documentación de Atlas ejemplifica aproximadamente USD 468/mes cuando M30 se configura con 200 GB de almacenamiento. | El escenario Expansión representa 221.184 GB lógicos antes de índices y overhead, por lo que ni el precio base ni el ejemplo de 200 GB deben interpretarse como una cotización completa del escenario. Atlas factura capacidad personalizada de almacenamiento, backups y transferencia adicional según configuración y región. |
| Graph / Neo4j AuraDB | AuraDB Professional dimensionado por memoria y almacenamiento. Se utiliza como referencia la configuración de 64 GB RAM, 12 CPU y 128 GB de almacenamiento. | USD 5.76/h, equivalentes a USD 4,204.80/mes. | Los 128 GB incluidos son inferiores a los 221.184 GB lógicos del escenario Expansión y todavía no contemplan el overhead propio de nodos, relaciones e índices. Para tamaños superiores puede ser necesario utilizar AuraDB Business Critical u otra configuración de mayor capacidad, incrementando el costo. |
| Column / Apache Cassandra | Clúster autogestionado de tres nodos EC2 `m6i.xlarge` utilizado únicamente como configuración reproducible de costeo, con replication factor 3 y 300 GB de almacenamiento gp3 por nodo. | Cómputo: `3 × USD 0.192/h × 720 h = USD 414.72/mes`. Almacenamiento: `3 × 300 GB × USD 0.08/GB-mes = USD 72.00/mes`. Piso de infraestructura: aproximadamente USD 486.72/mes. | Los precios utilizados corresponden a referencias publicadas para `us-east-1`. El cálculo no demuestra mediante benchmark que `m6i.xlarge` sea el dimensionamiento definitivo para CDRL. Tampoco incluye snapshots, transferencia, monitoreo ni esfuerzo operativo, por lo que USD 486.72 constituye un piso reproducible de infraestructura y no una factura completa. |
| Object / Amazon S3 + Athena | Amazon S3 Standard para almacenar eventos agrupados en objetos y Amazon Athena como componente de consulta de referencia para representar el procesamiento necesario para Q1–Q5. | S3 Standard: `221.184 GB × USD 0.023/GB-mes ≈ USD 5.09/mes` de almacenamiento lógico. Con la carga base de 10 solicitudes/s durante 30 días se obtienen 25,920,000 consultas. Con el mínimo facturable de 10 MB por consulta en Athena, el piso teórico representa 259.2 TB procesados y aproximadamente USD 1,296/mes a USD 5/TB. | El costo aislado de S3 es bajo, pero no representa por sí mismo una solución operacional equivalente para Q1–Q5. El cálculo de Athena representa un piso teórico basado en el mínimo facturable por consulta. Compresión, particionamiento y formatos columnares pueden reducir los bytes realmente escaneados cuando una consulta supera ese mínimo, mientras que catálogos, índices, transferencia u otros servicios adicionales también deben contabilizarse si forman parte de la solución. |

##### Cálculos reproducibles

**MongoDB Atlas**

La documentación pública de MongoDB indica que un clúster M30 sobre AWS tiene un precio base de aproximadamente USD 0.54 por hora:

```text
USD 0.54/h × 24 h/día × 30 días = USD 388.80/mes
```

MongoDB también documenta un ejemplo donde M30 con 200 GB de almacenamiento aumenta aproximadamente a USD 0.65 por hora:

```text
USD 0.65/h × 24 h/día × 30 días = USD 468.00/mes
```

Estos valores se utilizan únicamente como referencia porque el escenario CDRL contiene 221.184 GB lógicos antes de índices, journals, metadata y demás overhead físico.

**Neo4j AuraDB**

AuraDB Professional publica para 64 GB de memoria, 12 CPU y 128 GB de almacenamiento:

```text
USD 5.76/h × 730 h de referencia del proveedor = USD 4,204.80/mes
```

La capacidad incluida de 128 GB es inferior a los 221.184 GB lógicos del escenario Expansión. Por ello, USD 4,204.80 tampoco representa una cotización completa para almacenar todo el escenario CDRL; se utiliza como evidencia del orden de magnitud del costo y de la necesidad de una configuración superior.

**Apache Cassandra**

Para obtener una referencia reproducible de infraestructura se utiliza un clúster de tres nodos EC2 `m6i.xlarge`.

Cómputo:

```text
3 nodos × USD 0.192/h × 720 h
= USD 414.72/mes
```

Almacenamiento gp3:

```text
3 nodos × 300 GB × USD 0.08/GB-mes
= USD 72.00/mes
```

Piso estimado:

```text
USD 414.72 + USD 72.00
= USD 486.72/mes
```

El uso de 300 GB por nodo permite representar explícitamente el efecto de mantener copias distribuidas con replication factor 3, pero no sustituye una medición del tamaño físico real después de compresión, SSTables, compaction, índices, commit logs y respaldos.

**Amazon S3 y Athena**

Almacenamiento lógico de referencia en S3 Standard:

```text
221.184 GB × USD 0.023/GB-mes
≈ USD 5.09/mes
```

La carga base definida para la evaluación es de 10 solicitudes por segundo:

```text
10 consultas/s
× 60 s/min
× 60 min/h
× 24 h/día
× 30 días
= 25,920,000 consultas/mes
```

Athena factura por datos procesados y documenta un mínimo facturable de 10 MB por consulta. Utilizando únicamente ese mínimo:

```text
25,920,000 consultas
× 10 MB
= 259,200,000 MB
≈ 259.2 TB
```

Con una referencia de USD 5 por TB procesado:

```text
259.2 TB × USD 5/TB
= USD 1,296/mes
```

Este cálculo no afirma que todas las consultas de CDRL deban implementarse individualmente con Athena. Su propósito es demostrar que el precio de almacenamiento de S3 no puede utilizarse de forma aislada para representar el costo de una arquitectura que debe responder Q1–Q5 con la frecuencia operacional definida. Una arquitectura que introduzca caching, agregación, índices o un motor adicional deberá contabilizar también dichos componentes.

##### Puntuación relativa del criterio de costo

A partir de las estimaciones anteriores y de las limitaciones documentadas, se utiliza la siguiente valoración relativa para el workload CDRL:

| Alternativa | Puntuación de costo | Justificación |
| --- | ---: | --- |
| Document / MongoDB Atlas | 4 | Mantiene Q1–Q5 principalmente dentro de un único motor y presenta un costo de referencia menor que las alternativas con mayor sobrecosto estructural. Sin embargo, la capacidad física necesaria para Expansión todavía debe dimensionarse por encima del ejemplo de 200 GB, por lo que no recibe puntuación 5. |
| Graph / Neo4j AuraDB | 1 | La configuración de referencia de USD 4,204.80/mes todavía ofrece únicamente 128 GB de almacenamiento, menos que el volumen lógico del escenario Expansión, y una configuración mayor incrementaría el costo. |
| Column / Apache Cassandra | 3 | El piso reproducible de infraestructura es aproximadamente USD 486.72/mes antes de respaldos, transferencia, monitoreo y operación. Su costo es intermedio y depende del dimensionamiento y esfuerzo operativo del clúster autogestionado. |
| Object / Amazon S3 + Athena | 2 | S3 ofrece almacenamiento muy económico, pero satisfacer el workload operacional Q1–Q5 requiere procesamiento adicional. Bajo la carga base declarada, incluso el mínimo facturable de Athena genera un costo de consulta materialmente superior al costo de almacenamiento aislado. |

Ninguna alternativa recibe puntuación 5 porque la definición del criterio exige un costo muy bajo respaldado por una estimación reproducible para el escenario completo. Todas las alternativas conservan componentes, dimensionamientos o limitaciones que impiden realizar esa afirmación.

Estos puntajes representan exclusivamente la comparación del workload y los supuestos definidos para CDRL. No constituyen una afirmación general de que una tecnología sea siempre más barata que otra. Cambios en región, tamaño físico real, compresión, índices, patrón de consultas, frecuencia de lectura, modalidad administrada o precios del proveedor requieren recalcular este criterio.

### Escenarios comunes de fallo

Las cuatro alternativas se analizarán frente a los mismos escenarios de fallo para evitar atribuir disponibilidad a afirmaciones generales del proveedor.

F1 — Reintento de escritura: la escritura puede haberse confirmado internamente aunque la respuesta no llegue al cliente. El reintento no debe crear un segundo evento con la misma clave lógica `(device_id, recorded_at_us)`.

F2 — Indisponibilidad temporal: un nodo, servicio o componente requerido deja de responder durante un periodo limitado. Se documentará si la operación falla, se reintenta, se encola o continúa mediante otra réplica.

F3 — Lectura posterior a escritura: después de confirmar una escritura se ejecuta una consulta que debería poder observarla bajo la garantía declarada. Se documentará si la alternativa ofrece esa garantía y bajo qué configuración.

F4 — Pérdida de réplica o miembro: se analizará qué ocurre cuando un componente de una topología replicada deja de estar disponible y si las escrituras pueden continuar sin comprometer las confirmaciones ya realizadas.

F5 — Partición de red: se documentará qué compromiso adopta la configuración evaluada entre disponibilidad y consistencia cuando algunos componentes no pueden comunicarse.

F6 — Fallo entre almacenamientos: en una arquitectura donde PostgreSQL conserva metadatos y otro motor almacena eventos, se analizará el caso en que una operación se complete en un sistema y falle en el otro. No se asumirá atomicidad distribuida sin un mecanismo explícito.

No se asignará la máxima puntuación de disponibilidad únicamente porque la documentación indique replicación o alta disponibilidad. Una puntuación máxima requerirá evidencia suficiente para el escenario y configuración concretos evaluados.

### Requisitos comunes de consistencia

La evaluación no utilizará las etiquetas “fuerte”, “eventual” o “ACID” como puntuaciones por sí solas. Cada alternativa deberá relacionar sus garantías con comportamientos concretos del CDRL.

Como mínimo se evaluará:

1. preservación de la unicidad lógica `(device_id, recorded_at_us)`;
2. rechazo o tratamiento explícito de un reintento duplicado;
3. lectura posterior a escritura bajo la garantía declarada;
4. preservación de los rangos y reglas del evento canónico;
5. comportamiento de Q5 cuando el estado o ubicación de un dispositivo cambia;
6. consistencia entre el almacenamiento de eventos y PostgreSQL cuando ambos participen.

Una garantía interna de un motor no implica atomicidad entre motores diferentes. Si una solución utiliza copias de `status` o `location_id`, deberá declarar cuánto retraso acepta, cómo detecta actualizaciones y qué ocurre durante una sincronización fallida.

## Hipótesis falsables y método de comprobación

Ninguna hipótesis de esta tabla se presenta como medida. Puede incorporarse a la matriz como hipótesis identificada, junto con sus supuestos y criterio de refutación.

| ID | Hipótesis | Cómo comprobarla y cuándo rechazarla |
| --- | --- | --- |
| H1 | Document resuelve Q1/Q2 por acceso indexado sin escanear toda la colección en ventanas selectivas. | Examinar explain con estadísticas, índices y dataset registrados; rechazar si realiza escaneo global para esos casos. |
| H2 | Graph resuelve Q1/Q2 mediante índice sin expandir todas las lecturas del dispositivo. | Revisar PROFILE en un prototipo; rechazar si el trabajo sigue todo el historial para la ventana selectiva. |
| H3 | Ambos modelos conservan Q1–Q5. | Comparar con PostgreSQL sobre datos idénticos, conjuntos vacíos, límites temporales, empates entre dispositivos y cambio de estado/ubicación. Rechazar ante diferencia semántica o decimal. |
| H4 | Las claves propuestas preservan instantes separados por un microsegundo y rechazan un duplicado exacto. | Insertar dos instantes dentro del mismo milisegundo y luego repetir uno. Rechazar si colapsan los primeros o se acepta el duplicado. |
| H5 | La estrategia Document puede distribuir la carga sin concentrarla en una única partición global. | Registrar distribución y throughput en carga uniforme y sesgada; refutar la configuración si un shard recibe más del 50 % de escrituras con al menos cuatro shards y tráfico uniforme. El umbral es propuesto. |
| H6 | El modelo Graph estándar necesita dimensionar el writer para la ingestión de expansión. | Medir cola y throughput en 166.67 eventos/s sostenidos y ráfagas; evaluar si agregar lectores mejora realmente la escritura. No declarar insuficiencia sin medir. |
| H7 | La política de cada motor permite leer las escrituras confirmadas causalmente relacionadas. | Configurar sesiones/concerns o bookmarks; escribir y consultar tras confirmación. Refutar ante lectura obsoleta dentro de la garantía declarada. |
| H8 | La topología replicada recupera escrituras tras perder un miembro y conservar quorum. | Desconectar un miembro en entorno aislado; registrar interrupción, recuperación y eventos confirmados. Refutar ante pérdida de eventos confirmados bajo la política evaluada o ausencia de recuperación. |
| H9 | Ambos modelos admiten una estimación de costo reproducible para la misma carga y durabilidad. | Medir bytes por evento con índices y relaciones, dimensionar recursos y aplicar precios/edición/región fechados. Rechazar cualquier comparación que omita un componente o use garantías distintas. |
| H10 | Para las cinco consultas, Document necesita menos estructuras de aplicación que Graph sin omitir integridad. | Contar colecciones/etiquetas, relaciones, índices y validaciones de ambos diseños funcionalmente equivalentes. Refutar si el costo de composición de metadatos elimina esa ventaja. |
| H11 | Column resuelve Q1 y Q2 mediante acceso dirigido por `device_id` y rango/orden temporal sin recorrer todos los eventos del sistema. | Ejecutar Q1/Q2 sobre el mismo dataset y registrar operaciones y elementos evaluados; rechazar si el patrón requiere un scan global para ventanas selectivas. |
| H12 | La estrategia de partición de Column distribuye la ingestión cuando el tráfico entre dispositivos es uniforme. | Registrar distribución y throughput durante el escenario uniforme; rechazar la configuración si una fracción reducida de claves concentra de forma desproporcionada la carga sin que el workload lo justifique. |
| H13 | Un dispositivo que genera el 10 % del tráfico permite detectar y cuantificar riesgo de hot partition en Column. | Ejecutar la carga sesgada y comparar distribución, throttling y throughput con el escenario uniforme; rechazar la estrategia si la concentración impide satisfacer la carga declarada. |
| H14 | La unicidad lógica `(device_id, recorded_at_us)` puede conservarse en Column frente a reintentos. | Insertar un evento en Cassandra, repetir exactamente su primary key y comprobar la semántica de upsert. Después ejecutar una creación condicional con `IF NOT EXISTS` y verificar que la segunda creación no se aplique. | Cassandra utiliza upsert para escrituras ordinarias; cuando CDRL requiera semántica explícita de rechazo por existencia deberá utilizarse una lightweight transaction y medirse su costo de coordinación. |
| H15 | Object Store puede conservar el histórico sin pérdida ni duplicación lógica durante reintentos del proceso de archivado. | Ejecutar una exportación, interrumpirla en puntos controlados y repetirla; rechazar si faltan eventos o aparecen duplicados lógicos en el dataset resultante. |
| H16 | Una organización de objetos por tiempo y dispositivo reduce los datos considerados por Q1/Q3 históricos respecto de recorrer todo el archivo. | Ejecutar las consultas históricas sobre diferentes ventanas y registrar objetos/bytes procesados; rechazar si una consulta selectiva necesita procesar el histórico completo. |
| H17 | Object Store puro tiene menor ajuste operacional para Q2/Q5 que para conservación y análisis histórico. | Implementar o describir los componentes mínimos necesarios para Q2/Q5 y registrar si requieren catálogo, índice, motor de consulta o metadata externa; refutar si Object Store por sí solo satisface las consultas con las garantías declaradas. |
| H18 | El modelo común permite comparar costos de las cuatro alternativas sin cambiar carga, retención ni garantías. | Aplicar el mismo escenario, horizonte y componentes de costo a Document, Graph, Column y Object; rechazar cualquier puntuación cuyo cálculo omita componentes relevantes o utilice garantías diferentes. |

H1/H2 no exigen un índice para consultas que devuelven casi todo el dataset: un escaneo puede ser una elección razonable en ese caso. H5 no valida por sí sola latencia ni capacidad; H8 no promete un tiempo de recuperación específico.

## Puntuaciones finales de las alternativas

Las siguientes puntuaciones forman parte de la matriz reproducible final de M04. Se derivan del workload, las hipótesis, la documentación técnica, los supuestos comunes y la estimación de costo descritos en este ADR. No representan benchmarks de rendimiento observado, sino una valoración arquitectónica reproducible bajo los criterios y pesos establecidos.

### Puntuaciones finales de Column y Object

Estas valoraciones utilizan la misma escala 1–5 definida para Document y Graph. Representan ajuste arquitectónico respaldado por documentación, supuestos comunes e hipótesis falsables; no representan resultados de rendimiento medido. Las puntuaciones de costo utilizan el modelo comparativo común definido en este ADR y deberán revisarse si mediciones o cotizaciones posteriores contradicen sus supuestos.

| Criterio | Column | Object | Justificación y trazabilidad |
| --- | ---: | ---: | --- |
| Consultas | 4 | 2 | Column se alinea directamente con Q1/Q2 mediante dispositivo y tiempo y permite seleccionar el intervalo de Q3, aunque Q4/Q5 requieren estructuras o composición adicionales. Object puede organizar históricos por dispositivo/tiempo, pero Q2/Q5 operacionales requieren procesamiento o metadata adicional. C1–C5, O1/O3; H11, H16/H17. |
| Escala/ingestión | 4 | 4 | Column permite distribuir eventos por claves, condicionado por la selección de partition key y tráfico sesgado. Object está diseñado para almacenar grandes volúmenes, aunque la escala de almacenamiento no demuestra eficiencia de Q1–Q5. C4, O1/O3; H12/H13/H16. |
| Consistencia | 4 | 3 | Column/Cassandra permite configurar niveles de consistencia como `ONE`, `QUORUM`, `ALL` y `LOCAL_QUORUM`; la garantía efectiva depende del replication factor y del nivel seleccionado. Las creaciones que deban rechazar una clave existente requieren `IF NOT EXISTS` mediante lightweight transactions. Object/S3 ofrece garantías distintas y cualquier composición con metadatos externos debe evaluarse por separado. | C6, C7, O6 |
| Costo | 3 | 2 | Column/Cassandra presenta un piso reproducible de aproximadamente USD 486.72/mes para tres nodos EC2 y almacenamiento gp3, antes de respaldos, monitoreo, transferencia y operación. Object/S3 tiene almacenamiento aislado muy económico, pero satisfacer la carga operacional Q1–Q5 requiere procesamiento adicional; bajo la carga base declarada, el mínimo facturable utilizado para Athena produce un piso teórico de aproximadamente USD 1,296/mes. | H18, K1, K2, K3, K4 |
| Fallos/disponibilidad | 4 | 4 | Column/Cassandra utiliza replicación entre nodos y mecanismos como hinted handoff y repair para recuperación y convergencia; su tolerancia efectiva depende de la topología, replication factor y consistency level. Object/S3 posee mecanismos administrados distintos. La comparación debe mantener escenarios equivalentes de reintento, indisponibilidad y recuperación. | C1, C8, O7 |
| Complejidad operativa | 3 | 3 | Column exige diseñar claves, índices y sincronización de metadatos para Q4/Q5. Object simplifica conservación de históricos pero requiere procesos de archivado y componentes adicionales para reproducir consultas operacionales. Inferencia del diseño; H11–H17. |

### Modelo de costo asociado a H9 y H18

Usar `C_total = C_compute + C_storage + C_backup + C_transfer + C_license + C_operations` para el mismo mes, región, retención y garantías. En servicios que cobran por operaciones, añadir lecturas/escrituras facturables evitando duplicar partidas incluidas.

El almacenamiento físico debe medirse con documentos o nodos/relaciones e índices. Multiplicar por la replicación aplicable y sumar logs/respaldos sin contar dos veces capacidad ya incluida en una tarifa. Declarar horas de operación y su valoración, o separarlas explícitamente del costo monetario.

Puede mantenerse costo como hipótesis si se fijan tarifas y supuestos auditables; no debe inventarse un importe o afirmar que un motor es más barato sin ese cálculo.

## Alternativa candidata a descarte

Graph / Neo4j permanece como candidato principal a descarte antes del cálculo final de la matriz.

El motivo no es que el modelo graph sea técnicamente incapaz de almacenar la telemetría. Puede representar `Location`, `Device` y `Reading` y resolver los accesos evaluados. El problema es la correspondencia entre sus fortalezas y el workload real del CDRL: Q1–Q3 están dominadas por dispositivo y tiempo, Q4 utiliza una relación directa con ubicación y Q5 combina eventos recientes con metadatos actuales. Ninguna consulta actual exige recorridos variables o análisis intensivo de relaciones.

Por tanto, los nodos, relaciones y operación específica de un motor graph introducen estructuras cuyo beneficio no está demostrado para el workload actual. Esta conclusión continúa siendo provisional hasta calcular la matriz ponderada completa; no se descartará formalmente ninguna alternativa únicamente por esta apreciación cualitativa.

## Consecuencias y limitaciones

- El contrato existente permite comparar resultados y no solo características comerciales.
- Las propuestas exigen preservar unicidad, precisión y metadatos actuales; la flexibilidad no elimina esas obligaciones.
- Agregar un motor implica respaldos, seguridad, monitoreo y sincronización adicionales. Los roles PostgreSQL de M03 no configuran permisos del motor nuevo.
- No se desplegaron MongoDB, Neo4j, un clúster Apache Cassandra equivalente ni servicios cloud de Amazon S3 para ejecutar benchmarks equivalentes. DynamoDB Local permanece disponible en el `docker-compose.yml` del proyecto, pero no representa la alternativa Column/Wide-column evaluada y sus resultados no se utilizan como evidencia de rendimiento, disponibilidad o fallos de Cassandra.
- Las fuentes oficiales current pueden cambiar. Un prototipo deberá fijar versión, edición, topología y configuración antes de validar las hipótesis.

## Integración del equipo

Víctor incorporó el workload, el evento canónico, los escenarios de carga y el análisis Document/Graph. Angélica incorporó el análisis Column/Object, los supuestos de escala, costo, consistencia y fallos. David implementó la matriz reproducible, las pruebas automatizadas, `verify_m04.sh`, el artifact machine-readable y la integración mínima del Makefile.

La matriz final fue validada con cuatro escenarios automatizados: caso normal, valores límite 1 y 5, empate sin criterio de desempate inventado y fallo declarado cuando los pesos no suman 100. La ejecución de `scripts/verify_m04.sh` confirmó 4/4 pruebas aprobadas y generó `artifacts/m04-storage-selection-results.json` con `decision_status: complete`.

La autoría individual se conserva mediante las ramas, commits y pull requests correspondientes. No se crea un ADR independiente por integrante.

## Resultado de esta revisión

Se identificaron cinco consultas reales, sus reglas de salida, el contrato del evento y escenarios comparables. Se analizaron las cuatro familias candidatas mediante representantes concretos: MongoDB para Document, Neo4j para Graph, Apache Cassandra para Column/Wide-column y Amazon S3 para Object Store.

La matriz ponderada reproducible fue completada con los pesos definidos para consultas, escala/ingestión, consistencia, costo, fallos/disponibilidad y complejidad operativa. El cálculo produjo los siguientes resultados:

- Document / MongoDB: 3.95/5.
- Column / Apache Cassandra: 3.80/5.
- Graph / Neo4j: 2.90/5.
- Object / Amazon S3: 2.90/5.

La alternativa seleccionada para M04 es Document, representada por MongoDB, al obtener la mayor puntuación ponderada. No existe empate en primer lugar y no permanecen criterios pendientes.

Esta selección se limita al workload, pesos, hipótesis y evidencia documentados para CDRL. No implica que MongoDB sea universalmente superior a las demás alternativas. Si cambian los volúmenes, regiones, precios, garantías, patrones de consulta o requisitos operativos, la matriz deberá recalcularse.

## Fuentes

### Evidencia del repositorio

- R1: [Consultas parametrizadas](https://github.com/arlett-ass/opt-cdrl-base/blob/4cacc1d2ece95ce885f0bf9dd191f1c89d970b09/db/queries/telemetry.py).
- R2: [Contrato y restricciones M01](https://github.com/arlett-ass/opt-cdrl-base/blob/4cacc1d2ece95ce885f0bf9dd191f1c89d970b09/db/migrations/001_schema.sql).
- R3: [Vista y semántica de ubicación actual M02](https://github.com/arlett-ass/opt-cdrl-base/blob/4cacc1d2ece95ce885f0bf9dd191f1c89d970b09/db/migrations/002_relational_model.sql).
- R4: [Seguridad relacional M03](https://github.com/arlett-ass/opt-cdrl-base/blob/4cacc1d2ece95ce885f0bf9dd191f1c89d970b09/docs/ADR-003-relational-security.md).

### Documentación primaria de motores

- D1: [MongoDB Compound Indexes](https://www.mongodb.com/docs/manual/core/indexes/index-types/index-compound/).
- D2: [MongoDB Unique Indexes](https://www.mongodb.com/docs/manual/core/index-unique/).
- D3: [MongoDB BSON Types](https://www.mongodb.com/docs/manual/reference/bson-types/).
- D4: [MongoDB Sharding](https://www.mongodb.com/docs/manual/sharding/).
- D5: [MongoDB Read Isolation, Consistency, and Recency](https://www.mongodb.com/docs/manual/core/read-isolation-consistency-recency/).
- D6: [MongoDB Replication](https://www.mongodb.com/docs/manual/replication/).
- G1: [Neo4j Indexes and Query Performance](https://neo4j.com/docs/cypher-manual/current/indexes/search-performance-indexes/using-indexes/).
- G2: [Neo4j Clustering Architecture](https://neo4j.com/docs/operations-manual/current/clustering/introduction/).
- G3: [Neo4j Database Transactions](https://neo4j.com/docs/operations-manual/current/database-internals/transaction-management/).
- G4: [Neo4j Bookmarks](https://neo4j.com/docs/python-manual/current/bookmarks/).

### Column / Wide-column

- C1: [Apache Cassandra — Architecture Overview](https://cassandra.apache.org/doc/stable/cassandra/architecture/overview.html).
- C2: [Apache Cassandra — CREATE TABLE](https://cassandra.apache.org/doc/latest/cassandra/reference/cql-commands/create-table.html).
- C3: [Apache Cassandra — Data Manipulation](https://cassandra.apache.org/doc/stable/cassandra/developing/cql/dml.html).
- C4: [Apache Cassandra — Indexing Concepts](https://cassandra.apache.org/doc/latest/cassandra/developing/cql/indexing/indexing-concepts.html).
- C5: [Apache Cassandra — Storage-Attached Indexing](https://cassandra.apache.org/doc/latest/cassandra/developing/cql/indexing/sai/sai-overview.html).
- C6: [Apache Cassandra — Tunable Consistency](https://cassandra.apache.org/doc/stable/cassandra/architecture/dynamo.html).
- C7: [Apache Cassandra — Guarantees and Lightweight Transactions](https://cassandra.apache.org/doc/stable/cassandra/architecture/guarantees.html).
- C8: [Apache Cassandra — Hinted Handoff](https://cassandra.apache.org/doc/latest/cassandra/managing/operating/hints.html).

### Object Store

- O1: [Amazon S3 — What is Amazon S3?](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html).
- O2: [Amazon S3 — Strong consistency](https://aws.amazon.com/s3/consistency/).
- O3: [Amazon S3 — Organizing objects using prefixes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-prefixes.html).
- O4: [Amazon S3 — Lifecycle management](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html).
- O5: [Amazon S3 — Storage classes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/storage-class-intro.html).
- O6: [Apache Parquet Documentation](https://parquet.apache.org/docs/).
- O7: [Amazon S3 — Service Level Agreement](https://aws.amazon.com/s3/sla/).

### Costos y regiones

- K1: [AWS — Amazon EC2 On-Demand Pricing](https://aws.amazon.com/ec2/pricing/on-demand/).
- K2: [AWS — Amazon EBS Pricing](https://aws.amazon.com/ebs/pricing/).
- K3: [AWS — Amazon S3 Pricing](https://aws.amazon.com/s3/pricing/).
- K4: [AWS — Amazon Athena Pricing](https://aws.amazon.com/athena/pricing/).
- K5: [MongoDB — Atlas Pricing](https://www.mongodb.com/pricing).
- K6: [MongoDB — Atlas billing and invoice breakdown](https://www.mongodb.com/docs/atlas/billing/invoice-breakdown/).
- K7: [Neo4j — Aura Pricing](https://neo4j.com/pricing/).
- K8: [Neo4j — Aura billing dimensions](https://neo4j.com/docs/aura/billing/billing-dimensions/).
- K9: [AWS — Amazon S3 endpoints and quotas](https://docs.aws.amazon.com/general/latest/gr/s3.html).
- K10: [MongoDB Atlas — Amazon Web Services regions](https://www.mongodb.com/docs/atlas/reference/amazon-aws/).
- K11: [MongoDB Atlas — Cloud Providers and Regions](https://www.mongodb.com/docs/atlas/cloud-providers-regions/).
- K12: [Neo4j Aura — Regions](https://neo4j.com/docs/aura/managing-instances/regions/).