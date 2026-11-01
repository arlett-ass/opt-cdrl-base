# ADR-008: Paginación y evaluación del rendimiento de consultas

**Estado:** Aceptado técnicamente tras la validación local descrita abajo; pendiente de revisión e integración del equipo.

**Fecha:** 31 de octubre de 2026

**Participantes:** Víctor (paginación y pruebas), Angelica (benchmark y análisis), David (integración, ADR y evidencia). Revisión técnica de David: 1 de noviembre de 2026; contraste de `src/m08/pagination.py`, sus pruebas y `src/m08/benchmark.py` con las muestras del JSON.

## 1. Contexto

En el proyecto CDRL se necesita consultar información almacenada en DynamoDB sin recuperar necesariamente todos los documentos en una sola operación. La implementación existente en M05 permite obtener los documentos de un tipo de evento, mientras que en M08 se incorpora `query_by_type_page()` para recuperar resultados por páginas mediante el cursor nativo de DynamoDB.

`query_by_type()` acumula todas las páginas del GSI y ordena posteriormente por `(timestamp, eventId)`. El consumidor recibe una lista completa, por lo que no puede solicitar una página independiente con esa API. El problema de M08 es permitir entrega progresiva y medir su costo frente a recuperar todo; no se presupone una mejora en el tiempo total.

Para evaluar esta alternativa, se desarrolló un benchmark que compara la consulta completa, la recuperación de la primera página y el recorrido paginado completo. La prueba utiliza 10,000 documentos sintéticos del tipo `telemetry.reading`, un tamaño de página de 20 documentos y 100 repeticiones por escenario, con una ejecución de calentamiento por escenario.

## 2. Decisión

Se conserva la paginación mediante el cursor nativo de DynamoDB para permitir que los resultados se recuperen progresivamente, reutilizando el GSI `type-timestamp-index` de M05 sin alterar su API de consulta completa.

La implementación debe mantener la compatibilidad con la consulta existente de M05 y validar la integridad del recorrido para detectar documentos omitidos o duplicados. También se comprueba que los cursores puedan serializarse y recuperarse como JSON, como sucedería al enviarlos entre solicitudes de un cliente.

La paginación se considera una estrategia para entregar resultados por partes, no una garantía de que recuperar el conjunto completo sea más rápido que realizar una consulta completa.

El índice utilizado tiene clave de partición `type`, clave de orden `timestamp` y proyección `ALL`. Se conserva también `source-timestamp-index` (`source`, `timestamp`); la tabla mantiene `PAY_PER_REQUEST`. No se modificaron índices, por lo que ninguna diferencia medida se atribuye a un índice nuevo.

Cada llamada paginada realiza un `Query` con `Limit`, recibe `LastEvaluatedKey` y la conserva como `ExclusiveStartKey` de la siguiente llamada. No utiliza `Scan`, offset ni ordenamiento posterior. El retorno contiene `items` y `next_cursor`; termina cuando el cursor es nulo. El tamaño permitido es de 1 a 1000 y representa un máximo por llamada. El cursor JSON conserva versión, filtros normalizados y clave nativa; un cursor o tamaño inválido genera un error controlado antes de consultar. M05 mantiene su retorno de lista completa, evitando cambios en sus consumidores.

## 3. Opciones consideradas

**Opción 1. Mantener la consulta completa.**

Conservar la implementación existente que recupera todos los documentos. Esta alternativa mantiene el comportamiento actual, pero no permite entregar los resultados progresivamente por páginas.

**Opción 2. Incorporar paginación con cursor nativo.**

Recuperar una cantidad limitada de documentos por consulta y utilizar el cursor para continuar el recorrido. Esta alternativa facilita la entrega progresiva de resultados, aunque puede aumentar el tiempo total cuando se necesitan todos los documentos.

**Opción 3. Evaluar cambios adicionales en los índices.**

Analizar si los índices existentes responden adecuadamente a los patrones de consulta del proyecto. Cualquier cambio debe justificarse mediante pruebas específicas, considerando también el costo de almacenamiento y escritura.

**Opción 4. Simular offset.**

Se descarta para este patrón: requiere leer y descartar los elementos anteriores y no produce una fotografía consistente ante inserciones. El cursor nativo permite continuar desde la clave evaluada sin simular posiciones numéricas.

| Alternativa | Ventaja | Costo o limitación | Resolución |
|---|---|---|---|
| Consulta completa | Menor tiempo medido para recuperar los 10,000 documentos | Acumula todos los resultados antes de devolverlos | Se conserva como baseline y para consumidores que necesitan todo |
| Cursor nativo | Entrega progresiva y continuación por clave, sin descartar páginas previas | Estado del cursor, más solicitudes para recorrer todo y ausencia de snapshot | Elegida para la nueva API |
| Índice alternativo | Podría responder a otro filtro u ofrecer un orden compuesto | Mayor mantenimiento, escritura y almacenamiento; exige mediciones adicionales | No implementado ni medido en M08 |
| Offset simulado | Permitiría expresar una posición numérica | Lee y descarta resultados; no resuelve concurrencia | Descartado sin implementar un experimento innecesario |

Se acepta la opción de cursor porque el consumidor puede detenerse tras la página que necesita. Si requiere inmediatamente todos los documentos, la consulta completa fue más rápida en el experimento. Esta decisión depende del patrón de consumo; no declara que la paginación sea universalmente superior.

## 4. Resultados del benchmark

La prueba se ejecutó con Python 3.14.4, Linux sobre WSL2, boto3 1.42.0 y DynamoDB Local.

El conjunto de prueba contiene 10,000 documentos confirmados, con 100 fuentes distintas. Se realizaron 100 repeticiones por escenario y una ejecución de calentamiento por escenario. El tamaño de página utilizado fue de 20 documentos.

| Escenario | Documentos por resultado | p50 (ms) | p95 (ms) |
|---|---:|---:|---:|
| Consulta completa (línea base) | 10,000 | 794.441 | 970.462 |
| Recuperación de primera página | 20 | 4.794 | 6.338 |
| Recorrido paginado completo | 10,000 | 3,000.671 | 3,186.263 |

La primera página presentó una mediana de 4.794 ms, lo que demuestra que es posible comenzar a recibir resultados sin esperar a que termine la recuperación de los 10,000 documentos.

El recorrido paginado completo presentó una mediana de 3,000.671 ms, aproximadamente un 277.71 % mayor que la mediana de la consulta completa. Esto refleja el costo de realizar múltiples consultas secuenciales para recuperar el conjunto completo.

La comparación entre la primera página y la consulta completa no representa dos operaciones equivalentes, ya que recuperan cantidades diferentes de documentos. Por esta razón, los tiempos se presentan por separado.

El p50 es la mediana y el p95 se calcula por interpolación lineal sobre las muestras individuales ordenadas. La comparación equivalente para recuperación total es baseline completo frente a recorrido paginado completo, con los mismos datos, filtros y entorno. La primera página se informa aparte como latencia inicial. La carga y la espera de propagación del índice se registran separadamente; el calentamiento no se incluye en las 100 repeticiones medidas.

## 5. Comportamiento de las páginas

En las 100 repeticiones del recorrido completo se registraron 501 consultas por recorrido: 500 páginas con documentos y una consulta adicional que devolvió una página vacía.

Aunque los 10,000 documentos se recuperaron sin omisiones ni duplicados, la consulta vacía representa una operación adicional. `LastEvaluatedKey` permite continuar, pero no garantiza que queden coincidencias. El consumidor termina al recibir un cursor nulo; no se elimina una consulta por suponer que una página llena es la última. Se conserva el hallazgo y no se introduce una optimización adicional sin evidencia que la justifique.

Son 501 peticiones, no 501 páginas con datos. La última petición vacía no constituye una página omitida ni un error de integridad: las validaciones recuperaron los 10,000 IDs esperados. Es el comportamiento de terminación observado en este benchmark, no una obligación de todos los diseños de DynamoDB ni una prueba de optimalidad. Su posible optimización queda pendiente de revisión y debe conservar la correcta detección del final.

## 6. Consecuencias

La paginación permite entregar resultados progresivamente y puede ser útil en interfaces que muestran resultados por páginas o en procesos que consumen información de manera incremental.

Sin embargo, si se necesita recuperar todo el conjunto, las consultas adicionales pueden aumentar el tiempo total. El tamaño de página y la estrategia de consulta deben seleccionarse según las necesidades del sistema.

Las pruebas y el benchmark conservan las validaciones de integridad y detección de cursores repetidos. No se declara optimizado el tiempo de recuperar todo el conjunto. El cursor añade contexto y validación, pero no es un token firmado ni garantiza autenticidad.

El intercambio aceptado es recuperación progresiva a cambio de administrar el cursor y asumir mayor latencia acumulada al recorrer todo. El consumidor debe mantener los mismos filtros y tabla al continuar. El mantenimiento incluye las pruebas de contrato, compatibilidad M05 y tratamiento de errores; nuevas garantías de orden o consistencia requerirían otra decisión y mediciones nuevas. No se estiman unidades de lectura ni costos monetarios a partir del conteo de peticiones.

## 7. Limitaciones

Los resultados corresponden a una prueba local con datos sintéticos y DynamoDB Local. No representan una garantía del rendimiento en producción.

Los tiempos pueden variar según el equipo, la carga del sistema, la configuración y las características de los datos. La paginación mediante cursor tampoco garantiza por sí sola una vista inmutable de los datos cuando estos cambian durante el recorrido.

El GSI tiene consistencia eventual. Tras esperar su propagación, la prueba de inserciones demuestra que un evento anterior al cursor no se relee y uno posterior puede aparecer: no existe snapshot del conjunto original. Los empates de timestamp mantienen el orden real del índice sin prometer un desempate global por `eventId`. La integridad sin omisiones se verifica sobre datos sin cambios durante el recorrido; no se extiende esa garantía a modificaciones concurrentes arbitrarias.

No se midieron índices alternativos ni costos de AWS. Cambiar índices queda fuera de esta integración y requeriría justificar almacenamiento, escritura y patrón de acceso.

## 8. Evidencia y seguimiento

Los resultados se registran en `artifacts/m08-pagination-benchmark.json`. La implementación de la paginación y del benchmark se encuentra en `src/m08/pagination.py` y `src/m08/benchmark.py`.

## 9. Validación de integración — David

`bash scripts/verify_m08.sh` ejecuta las pruebas existentes y exige que todas terminen aprobadas, sin omisiones ni xfail. Comprueba los escenarios normal, vacío, página corta, cursor/tamaño inválido, recorrido íntegro, cursor JSON, timestamps repetidos, inserciones y documentos v1/v2. Resultado local: **71 pruebas aprobadas** con Python 3.14.8 y DynamoDB Local.

El verificador valida las muestras almacenadas del benchmark: entorno, filtros, dataset completo, calentamiento, repeticiones, conteos, p50/p95, extremos, páginas y comparación porcentual. Recalcula las métricas con tolerancia de 0.002 ms por el redondeo de las muestras. No ejecuta de nuevo el benchmark ni presenta las mediciones WSL2 de Angélica como mediciones de esta máquina.

La integración se ejecuta después de M07 en `scripts/verify_all.sh`; no requiere cambios en Makefile ni CI, que ya utilizan `make verify`. El único artifact M08 conservado es `artifacts/m08-pagination-benchmark.json`, generado por el benchmark. El reporte JSON de pytest es temporal y se elimina al salir del verificador. `evidence/m08-pagination-index-performance.json` resume el commit probado, los comandos, los resultados y la referencia al benchmark; no duplica sus muestras.

| Criterio | Prueba existente de Víctor en `tests/test_m08_pagination.py` |
|---|---|
| Normal e integridad | `test_real_traversal_has_no_duplicates_or_omissions_and_preserves_m05` (tamaños 1, 2 y 20) |
| Límite 1: sin coincidencias | `test_real_empty_range_has_no_next_cursor` |
| Límite 2: menos de una página | `test_real_fewer_items_than_page_size_returns_the_available_documents` |
| Fallo declarado | `test_invalid_cursor_is_a_controlled_error_before_query` y `test_invalid_page_size_is_rejected_before_query` |
| Continuidad JSON | `test_json_cursor_continues_with_exact_native_key_and_normalized_filters` |
| Inserción entre páginas | `test_real_insertions_before_and_after_the_cursor_demonstrate_no_snapshot` |
| Timestamps repetidos | `test_real_equal_timestamps_continue_without_claiming_an_event_id_tiebreak` |

David integra y exige esos escenarios aprobados; no duplica las pruebas de paginación. El benchmark se comprueba recalculando sus percentiles, conteos y metodología. Las 71 pruebas incluyen parametrizaciones; el número excede el mínimo de cuatro escenarios solicitado sin cambiar sus criterios.

En este entorno administrado fue necesario seleccionar para las ejecuciones locales un archivo de configuración AWS sin credenciales, conservando el perfil de bloqueo inyectado. DynamoDB Local recibe únicamente los valores sintéticos definidos por el cliente existente. Esto no es un requisito de AWS Academy ni una modificación de la aplicación.

La aceptación técnica documenta estas garantías limitadas; no equivale a aprobación del docente, integración remota ni publicación del tag final.

## 10. Reproducción y condiciones de revisión

Desde la raíz del repositorio, con las dependencias instaladas y la configuración local cargada, ejecutar `make setup && make verify && make run`. La verificación valida el benchmark conservado; volver a ejecutar el módulo `src.m08.benchmark` es un experimento separado que sobrescribe el JSON con nuevas mediciones y exige actualizar el análisis. Consultar `python -m src.m08.benchmark --help` para sus opciones.

Revisar esta decisión si se exige snapshot consistente, desempate único de timestamps, otro patrón de filtros o si mediciones equivalentes justifican un índice alternativo. Cualquier cambio debe preservar o versionar el contrato M05 y volver a medir bajo las mismas condiciones. El dataset actual varía fuentes y timestamps, pero utiliza un solo tipo (`telemetry.reading`); no demuestra rendimiento entre múltiples tipos ni de índices alternativos.

## 11. Trazabilidad y cierre por PR

El verificador imprime `git rev-parse --verify HEAD^{commit}` y comprueba con `git diff --quiet HEAD -- <fuentes M08>` si las fuentes coinciden con ese commit. Si existen cambios locales lo advierte y no presenta HEAD como identificación completa de lo ejecutado. No obtiene un SHA del benchmark ni copia el SHA de un tag anterior. Tampoco sobrescribe evidence en cada prueba.

El flujo acordado es rama de David → PR a `development` → validación del conjunto de los tres integrantes → PR a `main` → validación del commit integrado → tag semanal M08. El tag es una referencia a un commit, no una propiedad de una rama. No se declara final antes de la integración y validación.

`commitSha` en evidence identifica un commit efectivamente probado. Registrar ese resultado requiere un commit posterior de evidencia; un archivo no puede contener el hash de su propio commit porque modificarlo cambiaría ese hash. El tag final y su SHA se registran en la entrega externa, y la evidencia versionada conserva por separado el commit probado y la referencia semanal. No se vuelve a modificar evidence para intentar igualar recursivamente ambos hashes.
