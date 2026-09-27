# ADR-004 Selección de almacenamiento NoSQL para CDRL

## Estado

Propuesto. Están desarrollados el workload, el evento canónico, los escenarios de carga y el análisis de las cuatro alternativas consideradas: Document, Graph, Column y Object Store. También se definieron criterios, pesos, supuestos comunes de escala, consistencia, costo y fallos, junto con hipótesis falsables y propuestas de puntuación.

La decisión final del equipo permanece pendiente del cálculo reproducible de la matriz, su validación mediante pruebas y la generación de la evidencia M04. Este documento todavía no declara una alternativa ganadora ni una entrega M04 verificada.

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

## Criterios y escala propuestos

Los pesos de la guía se conservan como propuesta previa al cálculo: consultas 30 %, escala/ingestión 25 %, consistencia 15 %, costo 15 %, fallos/disponibilidad 10 % y complejidad operativa 5 %. Suman 100 %. Consultas y escala reciben mayor peso por el acceso repetido a eventos y su acumulación; consistencia protege el contrato; costo y operación evitan valorar capacidades sin su mantenimiento.

Escala: 1 ajuste muy bajo, 2 bajo, 3 aceptable con adaptaciones, 4 alto con limitaciones identificadas, 5 alto y demostrado para el escenario completo. En complejidad, mayor puntuación significa menor esfuerzo. En costo, mayor puntuación significa menor costo total para garantías equivalentes. Los pesos deben acordarse para las cuatro alternativas antes del cálculo final.

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

Para evaluar la alternativa Column/Wide-column se utiliza Amazon DynamoDB como implementación de referencia basada en partición y ordenamiento por clave, aprovechando que DynamoDB Local ya forma parte de la infraestructura del proyecto. DynamoDB se clasifica específicamente como una base NoSQL key-value/document, por lo que sus resultados no se generalizan automáticamente a motores wide-column clásicos como Cassandra. En esta evaluación se estudian únicamente las propiedades de particionamiento, ordenamiento temporal y patrones de acceso relevantes para el CDRL. Su presencia previa en `docker-compose.yml` no constituye evidencia a favor de su selección ni implica que sea la alternativa ganadora.

Para las lecturas de telemetría se propone inicialmente una clave primaria compuesta por `device_id` como partition key y `recorded_at_us` como sort key. Esta organización se deriva del workload existente: Q1, Q2 y Q3 acceden a las lecturas principalmente mediante un dispositivo concreto y una dimensión temporal.

Los elementos de telemetría conservarían `reading_id`, `device_id`, `recorded_at_us`, `received_at_us`, `temperature_c`, `humidity_pct` y `co2_ppm`. La combinación lógica `(device_id, recorded_at_us)` debe continuar siendo única. La precisión temporal y decimal debe seguir las mismas decisiones declaradas en el evento canónico para evitar cambiar el contrato existente.

La clave propuesta es un diseño inicial para evaluación, no una decisión definitiva. Debe comprobarse frente a todos los patrones Q1–Q5 y ante distribuciones uniformes y sesgadas de tráfico. Los accesos que no estén alineados con la clave primaria pueden requerir índices secundarios, estructuras adicionales o composición con los metadatos que permanecen en PostgreSQL.

### Resolución de consultas

| Consulta | Estrategia propuesta | Costo o limitación |
| --- | --- | --- |
| Q1 | Ejecutar una consulta sobre `device_id` y acotar `recorded_at_us` al intervalo inclusivo solicitado, conservando el orden temporal. | El patrón coincide con la clave compuesta propuesta. El costo continúa dependiendo de la cantidad de elementos evaluados y devueltos; debe verificarse con la carga declarada. |
| Q2 | Consultar la partición del dispositivo en orden temporal descendente y limitar el resultado a una lectura. | El acceso está alineado con dispositivo y tiempo, pero debe conservarse la semántica de ausencia de resultados y el desempate requerido por el contrato actual. |
| Q3 | Consultar primero el dispositivo y rango temporal y después calcular `COUNT`, `AVG`, `MIN` y `MAX` sobre las lecturas correspondientes o utilizar agregados mantenidos explícitamente. | La clave facilita seleccionar el intervalo, pero no convierte las agregaciones en operaciones constantes; cualquier estructura de agregados introduce escrituras y consistencia adicionales. |
| Q4 | Mantener los metadatos de dispositivos en PostgreSQL o definir un acceso secundario por `location_id` si se decide duplicarlos en el modelo NoSQL. | `location_id` no pertenece a la clave primaria propuesta. Un índice o copia adicional aumenta almacenamiento, escrituras y necesidades de sincronización. |
| Q5 | Obtener eventos recientes mediante una estructura temporal adicional o consultar candidatos de las particiones correspondientes y componerlos con el estado y ubicación actuales de los dispositivos antes de ordenar y aplicar el límite global. | La partición por dispositivo no resuelve por sí sola una consulta temporal global. No debe aplicarse el límite antes de filtrar dispositivos activos ni asumirse que una copia de metadatos está inmediatamente sincronizada. |

### Particionamiento, hot partitions y throughput

La evaluación utilizará los mismos escenarios de carga ya definidos para las demás alternativas: 100, 1,000 y 10,000 dispositivos, con una lectura por dispositivo cada 60 segundos. Esto corresponde a 1.67, 16.67 y 166.67 escrituras por segundo en promedio, respectivamente. También se evaluará el caso sincronizado en el que los 10,000 dispositivos del escenario de expansión transmitan dentro del mismo segundo.

Usar `device_id` como dimensión de partición permite distribuir dispositivos diferentes entre claves distintas, pero no garantiza por sí solo una distribución uniforme de carga. Debe evaluarse tanto tráfico uniforme como tráfico sesgado, incluyendo el escenario propuesto en el que un dispositivo produce el 10 % de los eventos.

Una hot partition se considerará un riesgo cuando una clave o conjunto reducido de claves concentre una proporción desmedida del throughput. Si las mediciones muestran concentración que limita la ingestión, deberán evaluarse estrategias como particionamiento temporal o write sharding, considerando que aumentar la dispersión también puede hacer más costosas las consultas que necesitan reconstruir el historial completo de un dispositivo.

El throughput se registrará como eventos escritos y solicitudes atendidas por segundo bajo el mismo dataset, ventanas y concurrencia definidos para las demás alternativas. No se inferirá rendimiento únicamente a partir de límites documentados del servicio; los límites sirven para diseñar la prueba, mientras que la capacidad efectiva del modelo CDRL requiere medición.

### Consistencia e invariantes

La alternativa Column debe preservar el contrato del evento aunque no utilice restricciones relacionales de PostgreSQL. La aplicación o el adaptador deberá validar rangos de métricas, `recorded_at <= received_at`, precisión temporal y asociación con un dispositivo válido.

La unicidad lógica `(device_id, recorded_at_us)` debe impedir que un reintento idéntico produzca una segunda lectura. Se propone evaluar escrituras condicionales para rechazar la creación cuando ya exista el elemento correspondiente; un conflicto con valores diferentes no debe sobrescribirse silenciosamente.

Para consultas que requieran lectura posterior a escritura se deberá declarar el nivel de consistencia utilizado. DynamoDB permite lecturas eventualmente consistentes y lecturas fuertemente consistentes sobre la tabla y los índices secundarios locales; los índices secundarios globales ofrecen lecturas eventualmente consistentes. Por ello, si Q4 o Q5 dependen de un GSI o de metadatos duplicados, debe documentarse el posible intervalo de propagación y comprobar que la semántica aceptada por CDRL no se altere.

Las transacciones disponibles dentro de DynamoDB no vuelven atómica una operación distribuida entre DynamoDB y PostgreSQL. Si PostgreSQL continúa siendo autoridad para dispositivos y ubicaciones, cualquier sincronización entre ambos almacenamientos debe declarar su política de actualización, reintentos y tratamiento de inconsistencias temporales.

### Costo y fallos

El costo de Column no se estimará únicamente por almacenamiento. Para mantener una comparación equivalente se incluirán capacidad o solicitudes de lectura y escritura, almacenamiento de eventos, índices secundarios, replicación o durabilidad incluida por el servicio, respaldos, transferencia y esfuerzo operativo. Los índices adicionales necesarios para patrones como Q4 o Q5 deben contabilizarse porque agregan almacenamiento y actividad de escritura.

La valoración monetaria utilizará posteriormente el mismo horizonte de 30 días, volumen de eventos, tamaño lógico por evento, región y garantías definidos para las demás alternativas. Hasta fijar esos parámetros y una modalidad concreta de despliegue no se afirmará que Column sea más barato o más caro.

Como escenarios de fallo se evaluarán al menos: reintento de una escritura cuya respuesta se perdió, indisponibilidad temporal del servicio, lectura posterior a una escritura confirmada y retraso de una estructura secundaria respecto de la tabla principal. Un reintento no debe crear un duplicado lógico; una escritura no confirmada no debe suponerse persistida; y una consulta que dependa de consistencia eventual debe documentar la degradación aceptada.

DynamoDB Local sirve para desarrollo y pruebas locales, pero no demuestra por sí mismo disponibilidad, replicación ni comportamiento de fallos del servicio administrado. Por ello, las capacidades documentadas y los resultados de un prototipo local deberán distinguirse explícitamente.

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
- para servicios AWS, utilizar Mexico (Central), `mx-central-1`, cuando el servicio evaluado esté disponible y la modalidad analizada sea comparable; A la fecha de esta evaluación, DynamoDB, Amazon S3 y MongoDB Atlas sobre AWS documentan disponibilidad en `mx-central-1`. Neo4j Aura documenta Mexico Central para determinados tiers. La disponibilidad y modalidad deberán volver a verificarse si la estimación se repite posteriormente.
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

La comparación utiliza servicios administrados como referencia cuando existe una modalidad comparable. Para AWS se prioriza `mx-central-1` (Mexico Central). MongoDB Atlas dispone de despliegues dedicados sobre AWS en esa región; DynamoDB y Amazon S3 también están disponibles en ella. Neo4j Aura dispone de Mexico Central en determinados niveles de servicio, por lo que cualquier comparación deberá registrar explícitamente el tier utilizado.

Las tecnologías poseen modelos de facturación diferentes. Document y Graph requieren capacidad de base de datos suficiente para mantener los datos operacionales, índices y procesamiento de consultas; Column puede facturar almacenamiento y actividad de lectura/escritura según la modalidad; Object Store factura principalmente almacenamiento, solicitudes y servicios adicionales de procesamiento. Por ello, comparar únicamente USD por GB produciría una conclusión inválida.

Para cada alternativa se contabilizarán los componentes que realmente sean necesarios para satisfacer Q1–Q5. Si una alternativa necesita índices secundarios, capacidad adicional, un catálogo, un motor de consulta o sincronización con PostgreSQL, estos componentes no se considerarán gratuitos.

Las puntuaciones siguientes son relativas al diseño CDRL y deberán revisarse si una medición, cotización o benchmark posterior contradice sus supuestos. No deben interpretarse como una afirmación general de que una tecnología siempre sea más barata que otra.

| Alternativa | Componentes relevantes para CDRL | Riesgo de costo |
| --- | --- | --- |
| Document / MongoDB | cluster operacional, almacenamiento de documentos, índices, replicación/alta disponibilidad, backups, transferencia y operación | El crecimiento de eventos e índices exige dimensionar capacidad del cluster; Q1–Q5 se resuelven mayoritariamente dentro del mismo motor. |
| Graph / Neo4j | capacidad del cluster, nodos, relaciones, índices, almacenamiento, backups y operación | El modelo agrega relaciones y estructuras que el workload directo dispositivo-tiempo no explota intensivamente; la capacidad necesaria debe medirse antes de fijar una factura. |
| Column / DynamoDB | almacenamiento, escrituras, lecturas, índices secundarios, backups y transferencia | El modelo se alinea con Q1/Q2, pero estructuras adicionales para Q4/Q5 aumentan almacenamiento y actividad de escritura/lectura. |
| Object / S3 | almacenamiento de objetos, solicitudes, transferencia, lifecycle y procesamiento/catálogo adicional | El almacenamiento histórico puede ser económico, pero reproducir Q1–Q5 operacionalmente requiere componentes adicionales que deben contabilizarse. |

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
| H14 | La unicidad lógica `(device_id, recorded_at_us)` puede conservarse en Column frente a reintentos. | Insertar un evento, repetir exactamente su clave y comprobar que no aparece una segunda lectura; rechazar si el reintento produce un duplicado lógico. |
| H15 | Object Store puede conservar el histórico sin pérdida ni duplicación lógica durante reintentos del proceso de archivado. | Ejecutar una exportación, interrumpirla en puntos controlados y repetirla; rechazar si faltan eventos o aparecen duplicados lógicos en el dataset resultante. |
| H16 | Una organización de objetos por tiempo y dispositivo reduce los datos considerados por Q1/Q3 históricos respecto de recorrer todo el archivo. | Ejecutar las consultas históricas sobre diferentes ventanas y registrar objetos/bytes procesados; rechazar si una consulta selectiva necesita procesar el histórico completo. |
| H17 | Object Store puro tiene menor ajuste operacional para Q2/Q5 que para conservación y análisis histórico. | Implementar o describir los componentes mínimos necesarios para Q2/Q5 y registrar si requieren catálogo, índice, motor de consulta o metadata externa; refutar si Object Store por sí solo satisface las consultas con las garantías declaradas. |
| H18 | El modelo común permite comparar costos de las cuatro alternativas sin cambiar carga, retención ni garantías. | Aplicar el mismo escenario, horizonte y componentes de costo a Document, Graph, Column y Object; rechazar cualquier puntuación cuyo cálculo omita componentes relevantes o utilice garantías diferentes. |

H1/H2 no exigen un índice para consultas que devuelven casi todo el dataset: un escaneo puede ser una elección razonable en ese caso. H5 no valida por sí sola latencia ni capacidad; H8 no promete un tiempo de recuperación específico.

## Propuestas de puntuación de las alternativas

Estas son valoraciones de diseño para discusión, respaldadas por fuentes e hipótesis, no puntuaciones de rendimiento observado. El equipo debe aceptar la escala y los pesos antes de integrarlas. No se calculan totales parciales como si constituyeran la decisión final.

| Criterio | Document | Graph | Justificación y trazabilidad |
| --- | ---: | ---: | --- |
| Consultas | 4 | 3 | Document ofrece acceso directo por evento/dispositivo/tiempo, con composición adicional para Q5. Graph cubre relaciones de Q4/Q5, pero Q1–Q3 siguen requiriendo índices y agregación. D1, G1, R1; H1–H4. La diferencia es ajuste estructural, no latencia medida. |
| Escala/ingestión | 4 | 3 | Document dispone de distribución por shard key; exige diseño de claves y control de sesgo. Graph estándar permite escalar lecturas, pero la escritura por base depende del writer. D4, G2; H5/H6. No implica incapacidad de Graph para los escenarios propuestos. |
| Consistencia | 4 | 4 | Ambos disponen de mecanismos para operaciones y lecturas causalmente relacionadas; requieren configuración y validación de invariantes. D5, G3/G4; H3/H4/H7. La integración con PostgreSQL queda como riesgo compartido. |
| Costo | 3 | 2 | Document requiere capacidad e índices para el workload operacional, pero sus estructuras corresponden directamente a los patrones evaluados. Graph añade nodos, relaciones y capacidad de grafo para un workload predominantemente directo dispositivo-tiempo; la valoración es relativa al CDRL y deberá revisarse con dimensionamiento medido. H9/H10/H18. |
| Fallos/disponibilidad | 4 | 4 | Las topologías replicadas documentadas ofrecen recuperación bajo condiciones; se necesita conservar quorum y comprobar confirmaciones/reintentos. D6, G2; H8. No se asigna 5 porque no se probó el escenario. |
| Complejidad operativa | 3 | 2 | Document requiere índices, validación y metadatos coherentes. Graph añade nodos/relaciones por evento, consistencia de referencias duplicadas y adaptación numérica. Inferencia de los modelos; H10. Revisar la diferencia si Graph simplifica suficientemente Q5. |

El criterio de costo se integró mediante el modelo operativo común definido en este ADR. Las puntuaciones propuestas utilizan el mismo horizonte, workload, retención, componentes de costo y garantías para las cuatro alternativas. David deberá conservar estos valores y supuestos en la matriz reproducible, salvo que el equipo acuerde y documente una modificación respaldada por nueva evidencia.

### Propuestas de puntuación Column y Object

Estas valoraciones utilizan la misma escala 1–5 definida para Document y Graph. Representan ajuste arquitectónico respaldado por documentación, supuestos comunes e hipótesis falsables; no representan resultados de rendimiento medido. Las puntuaciones de costo utilizan el modelo comparativo común definido en este ADR y deberán revisarse si mediciones o cotizaciones posteriores contradicen sus supuestos.

| Criterio | Column | Object | Justificación y trazabilidad |
| --- | ---: | ---: | --- |
| Consultas | 4 | 2 | Column se alinea directamente con Q1/Q2 mediante dispositivo y tiempo y permite seleccionar el intervalo de Q3, aunque Q4/Q5 requieren estructuras o composición adicionales. Object puede organizar históricos por dispositivo/tiempo, pero Q2/Q5 operacionales requieren procesamiento o metadata adicional. C1–C5, O1/O3; H11, H16/H17. |
| Escala/ingestión | 4 | 4 | Column permite distribuir eventos por claves, condicionado por la selección de partition key y tráfico sesgado. Object está diseñado para almacenar grandes volúmenes, aunque la escala de almacenamiento no demuestra eficiencia de Q1–Q5. C4, O1/O3; H12/H13/H16. |
| Consistencia | 4 | 3 | Column dispone de opciones de lectura fuerte para la tabla y mecanismos condicionales para proteger escrituras, con limitaciones de consistencia en estructuras secundarias. Object ofrece consistencia fuerte de objetos, pero conservar invariantes y sincronización con el almacenamiento operacional depende del proceso de archivado. C6–C8, O2; H14/H15. |
| Costo | 4 | 4 | Column evita mantener una topología de base autogestionada en la referencia administrada y permite asociar costo con almacenamiento y actividad, aunque Q4/Q5 pueden añadir índices y operaciones. Object presenta buen ajuste económico para archivo histórico, pero su puntuación no supone que pueda reemplazar gratuitamente el almacenamiento operacional; cualquier catálogo o motor de consulta adicional debe contabilizarse. H15–H18. |
| Fallos/disponibilidad | 4 | 4 | Ambos representantes documentan mecanismos administrados de disponibilidad y durabilidad, pero la comparación debe incluir reintentos, fallos parciales y componentes externos. No se asigna 5 sin evidencia específica del escenario CDRL. C6–C8, O1/O2; H14/H15. |
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
- No se desplegaron MongoDB, Neo4j ni servicios cloud administrados de DynamoDB o Amazon S3 para ejecutar benchmarks equivalentes; DynamoDB Local disponible en el entorno no demuestra las propiedades del servicio administrado. No se ejecutó la carga comparativa completa, no se midieron costos reales y no se simularon todos los escenarios de fallo. Las fuentes documentan capacidades y las hipótesis indican qué falta demostrar.
- Las fuentes oficiales current pueden cambiar. Un prototipo deberá fijar versión, edición, topología y configuración antes de validar las hipótesis.

## Integración pendiente del equipo

Víctor incorporó el workload, el evento canónico, los escenarios de carga y el análisis Document/Graph. Angélica incorporó el análisis Column/Object, los supuestos operativos comunes de escala, consistencia, costo y fallos, las hipótesis correspondientes y las propuestas de puntuación.

David deberá implementar la matriz reproducible, sus pruebas, `verify_m04.sh`, el artifact machine-readable y la integración mínima del Makefile. Con esos resultados, el equipo deberá revisar las puntuaciones, registrar la decisión final, completar las consecuencias y generar la evidencia M04.

La autoría individual se conserva mediante las ramas, commits y pull requests correspondientes. No se crea un ADR independiente por integrante.

## Resultado de esta revisión

Se identificaron cinco consultas reales, sus reglas de salida, el contrato del evento y escenarios comparables. Se analizaron las cuatro familias candidatas mediante representantes concretos y se definieron criterios, pesos, hipótesis falsables, supuestos comunes y propuestas de puntuación.

La selección final continúa abierta hasta ejecutar el cálculo reproducible de la matriz y revisar su resultado como equipo. El estado del ADR pasará de `Propuesto` a `Aceptado` únicamente cuando la decisión, sus consecuencias y la evidencia M04 estén completas.

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

- C1: [DynamoDB Core Components](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.CoreComponents.html).
- C2: [DynamoDB Query](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.html).
- C3: [DynamoDB Sort Key Best Practices](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-sort-keys.html).
- C4: [DynamoDB Partition Key Design](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-design.html).
- C5: [DynamoDB Secondary Indexes](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/SecondaryIndexes.html).
- C6: [DynamoDB Read Consistency](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html).
- C7: [DynamoDB Read and Write Operations](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/read-write-operations.html).
- C8: [DynamoDB Transactions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transactions.html).

### Object Store

- O1: [Amazon S3 — What is Amazon S3?](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html).
- O2: [Amazon S3 — Strong consistency](https://aws.amazon.com/s3/consistency/).
- O3: [Amazon S3 — Organizing objects using prefixes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-prefixes.html).
- O4: [Amazon S3 — Lifecycle management](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html).
- O5: [Amazon S3 — Storage classes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/storage-class-intro.html).
- O6: [Apache Parquet Documentation](https://parquet.apache.org/docs/).

### Costos y regiones

- K1: [AWS — DynamoDB endpoints and quotas](https://docs.aws.amazon.com/general/latest/gr/ddb.html).
- K2: [AWS — Amazon S3 endpoints and quotas](https://docs.aws.amazon.com/general/latest/gr/s3.html).
- K3: [MongoDB Atlas — Amazon Web Services regions](https://www.mongodb.com/docs/atlas/reference/amazon-aws/).
- K4: [MongoDB Atlas — Cloud Providers and Regions](https://www.mongodb.com/docs/atlas/cloud-providers-regions/).
- K5: [Neo4j Aura — Regions](https://neo4j.com/docs/aura/managing-instances/regions/).
- K6: [Neo4j — Pricing](https://neo4j.com/pricing/).