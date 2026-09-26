# ADR-004 Selección de almacenamiento NoSQL para CDRL

## Estado

Propuesto. Están desarrollados el workload, el evento canónico, los escenarios de carga y el análisis Document/Graph. La decisión de equipo requiere incorporar Column/Wide-column y Object, acordar los criterios y calcular la matriz completa. Este documento todavía no declara una alternativa ganadora ni una entrega M04 verificada.

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

H1/H2 no exigen un índice para consultas que devuelven casi todo el dataset: un escaneo puede ser una elección razonable en ese caso. H5 no valida por sí sola latencia ni capacidad; H8 no promete un tiempo de recuperación específico.

## Propuestas de puntuación Document y Graph

Estas son valoraciones de diseño para discusión, respaldadas por fuentes e hipótesis, no puntuaciones de rendimiento observado. El equipo debe aceptar la escala y los pesos antes de integrarlas. No se calculan totales parciales como si constituyeran la decisión final.

| Criterio | Document | Graph | Justificación y trazabilidad |
| --- | ---: | ---: | --- |
| Consultas | 4 | 3 | Document ofrece acceso directo por evento/dispositivo/tiempo, con composición adicional para Q5. Graph cubre relaciones de Q4/Q5, pero Q1–Q3 siguen requiriendo índices y agregación. D1, G1, R1; H1–H4. La diferencia es ajuste estructural, no latencia medida. |
| Escala/ingestión | 4 | 3 | Document dispone de distribución por shard key; exige diseño de claves y control de sesgo. Graph estándar permite escalar lecturas, pero la escritura por base depende del writer. D4, G2; H5/H6. No implica incapacidad de Graph para los escenarios propuestos. |
| Consistencia | 4 | 4 | Ambos disponen de mecanismos para operaciones y lecturas causalmente relacionadas; requieren configuración y validación de invariantes. D5, G3/G4; H3/H4/H7. La integración con PostgreSQL queda como riesgo compartido. |
| Costo | Por determinar | Por determinar | No existe cotización comparable, medición de tamaño ni despliegue definido. H9 establece cómo obtener evidencia. No se convierte falta de datos en una puntuación neutral arbitraria. |
| Fallos/disponibilidad | 4 | 4 | Las topologías replicadas documentadas ofrecen recuperación bajo condiciones; se necesita conservar quorum y comprobar confirmaciones/reintentos. D6, G2; H8. No se asigna 5 porque no se probó el escenario. |
| Complejidad operativa | 3 | 2 | Document requiere índices, validación y metadatos coherentes. Graph añade nodos/relaciones por evento, consistencia de referencias duplicadas y adaptación numérica. Inferencia de los modelos; H10. Revisar la diferencia si Graph simplifica suficientemente Q5. |

El costo pendiente pertenece a la comparación operativa común coordinada por Angélica. Antes de cerrar la matriz, deben incorporarse las dos puntuaciones de costo con H9 y las filas Column/Object. David no debe sustituir pendientes por cero, por 3 ni excluir el criterio y renormalizar pesos sin acuerdo documentado.

### Modelo de costo para completar H9

Usar `C_total = C_compute + C_storage + C_backup + C_transfer + C_license + C_operations` para el mismo mes, región, retención y garantías. En servicios que cobran por operaciones, añadir lecturas/escrituras facturables evitando duplicar partidas incluidas.

El almacenamiento físico debe medirse con documentos o nodos/relaciones e índices. Multiplicar por la replicación aplicable y sumar logs/respaldos sin contar dos veces capacidad ya incluida en una tarifa. Declarar horas de operación y su valoración, o separarlas explícitamente del costo monetario.

Puede mantenerse costo como hipótesis si se fijan tarifas y supuestos auditables; no debe inventarse un importe o afirmar que un motor es más barato sin ese cálculo.

## Alternativa candidata a descartar y condiciones de revisión

Graph es una candidata razonable a descartar como almacén principal de eventos si la matriz completa confirma que sus beneficios relacionales no compensan los costos operativos para Q1–Q5. La razón sería que el workload inspeccionado se centra en dispositivo/tiempo y agregados, y solo requiere relaciones directas de contexto.

Esta es una conclusión preliminar de adecuación, no el descarte final. Se revisaría si aparecen recorridos variables, análisis de dependencias, propagación de fallos entre dispositivos o resultados medidos que favorezcan Graph. El resultado tampoco convierte automáticamente a Document en ganador frente a Column/Object.

## Consecuencias y limitaciones

- El contrato existente permite comparar resultados y no solo características comerciales.
- Las propuestas exigen preservar unicidad, precisión y metadatos actuales; la flexibilidad no elimina esas obligaciones.
- Agregar un motor implica respaldos, seguridad, monitoreo y sincronización adicionales. Los roles PostgreSQL de M03 no configuran permisos del motor nuevo.
- No se levantaron MongoDB ni Neo4j, no se ejecutó carga, no se midieron costos y no se simularon fallos. Las fuentes documentan capacidades; las hipótesis indican qué falta demostrar.
- Las fuentes oficiales current pueden cambiar. Un prototipo deberá fijar versión, edición, topología y configuración antes de validar las hipótesis.

## Integración pendiente del equipo

Angélica incorporará Column/Wide-column, Object y el análisis operativo/costo común. David implementará la matriz reproducible, sus cuatro pruebas, verify_m04.sh, artifact y la integración mínima del Makefile. El equipo acordará puntuaciones, completará decisión, consecuencias finales y evidence.

La autoría del aporte se registrará con la rama `feat/m04-workload-document-graph-victor`, su commit y PR. No se crea un ADR independiente por integrante.

## Resultado de esta revisión

Se identificaron cinco consultas reales, sus reglas de salida, el contrato del evento, escenarios comparables, dos modelos candidatos y propuestas trazables de puntuación. La selección final continúa abierta hasta la integración del equipo; el estado del ADR pasará a Aceptado únicamente cuando la matriz y la justificación estén completas.

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
