# ADR-008: Paginación y evaluación del rendimiento de consultas

**Estado:** Aceptado técnicamente tras la validación local descrita abajo; pendiente de revisión e integración del equipo.

**Fecha:** 31 de octubre de 2026

**Participantes:** Víctor (paginación y pruebas), Angelica (benchmark y análisis), David (integración, ADR y evidencia). Revisión técnica de David: 1 de noviembre de 2026; contraste de `src/m08/pagination.py`, sus pruebas y `src/m08/benchmark.py` con las muestras del JSON.

## 1. Contexto

En el proyecto CDRL se necesita consultar información almacenada en DynamoDB sin recuperar necesariamente todos los documentos en una sola operación. La implementación existente en M05 permite obtener los documentos de un tipo de evento, mientras que en M08 se incorpora `query_by_type_page()` para recuperar resultados por páginas mediante el cursor nativo de DynamoDB.

Para evaluar esta alternativa, se desarrolló un benchmark que compara la consulta completa, la recuperación de la primera página y el recorrido paginado completo. La prueba utiliza 10,000 documentos sintéticos del tipo `telemetry.reading`, un tamaño de página de 20 documentos y 100 repeticiones por escenario, con una ejecución de calentamiento por escenario.

## 2. Decisión

Se conserva la paginación mediante el cursor nativo de DynamoDB para permitir que los resultados se recuperen progresivamente, reutilizando el GSI `type-timestamp-index` de M05 sin alterar su API de consulta completa.

La implementación debe mantener la compatibilidad con la consulta existente de M05 y validar la integridad del recorrido para detectar documentos omitidos o duplicados. También se comprueba que los cursores puedan serializarse y recuperarse como JSON, como sucedería al enviarlos entre solicitudes de un cliente.

La paginación se considera una estrategia para entregar resultados por partes, no una garantía de que recuperar el conjunto completo sea más rápido que realizar una consulta completa.

## 3. Opciones consideradas

**Opción 1. Mantener la consulta completa.**

Conservar la implementación existente que recupera todos los documentos. Esta alternativa mantiene el comportamiento actual, pero no permite entregar los resultados progresivamente por páginas.

**Opción 2. Incorporar paginación con cursor nativo.**

Recuperar una cantidad limitada de documentos por consulta y utilizar el cursor para continuar el recorrido. Esta alternativa facilita la entrega progresiva de resultados, aunque puede aumentar el tiempo total cuando se necesitan todos los documentos.

**Opción 3. Evaluar cambios adicionales en los índices.**

Analizar si los índices existentes responden adecuadamente a los patrones de consulta del proyecto. Cualquier cambio debe justificarse mediante pruebas específicas, considerando también el costo de almacenamiento y escritura.

**Opción 4. Simular offset.**

Se descarta para este patrón: requiere leer y descartar los elementos anteriores y no produce una fotografía consistente ante inserciones. El cursor nativo permite continuar desde la clave evaluada sin simular posiciones numéricas.

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

## 5. Comportamiento de las páginas

En las 100 repeticiones del recorrido completo se registraron 501 consultas por recorrido: 500 páginas con documentos y una consulta adicional que devolvió una página vacía.

Aunque los 10,000 documentos se recuperaron sin omisiones ni duplicados, la consulta vacía representa una operación adicional. `LastEvaluatedKey` permite continuar, pero no garantiza que queden coincidencias. El consumidor termina al recibir un cursor nulo; no se elimina una consulta por suponer que una página llena es la última. Se conserva el hallazgo y no se introduce una optimización adicional sin evidencia que la justifique.

## 6. Consecuencias

La paginación permite entregar resultados progresivamente y puede ser útil en interfaces que muestran resultados por páginas o en procesos que consumen información de manera incremental.

Sin embargo, si se necesita recuperar todo el conjunto, las consultas adicionales pueden aumentar el tiempo total. El tamaño de página y la estrategia de consulta deben seleccionarse según las necesidades del sistema.

Las pruebas y el benchmark conservan las validaciones de integridad y detección de cursores repetidos. No se declara optimizado el tiempo de recuperar todo el conjunto. El cursor añade contexto y validación, pero no es un token firmado ni garantiza autenticidad.

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

La integración se ejecuta después de M07 en `scripts/verify_all.sh`; no requiere cambios en Makefile ni CI, que ya utilizan `make verify`. El resultado nuevo se escribe en `artifacts/m08-pagination-index-performance-results.json`, con referencia al reporte pytest y hashes de las fuentes probadas y del benchmark. `evidence/m08-pagination-index-performance.json` registra los comandos y sus resultados reales.

En este entorno administrado fue necesario seleccionar para las ejecuciones locales un archivo de configuración AWS sin credenciales, conservando el perfil de bloqueo inyectado. DynamoDB Local recibe únicamente los valores sintéticos definidos por el cliente existente. Esto no es un requisito de AWS Academy ni una modificación de la aplicación.

La aceptación técnica documenta estas garantías limitadas; no equivale a aprobación del docente, integración remota ni publicación del tag final.

## 10. Reproducción y condiciones de revisión

Desde la raíz del repositorio, con las dependencias instaladas y la configuración local cargada, ejecutar `make setup && make verify && make run`. La verificación valida el benchmark conservado; volver a ejecutar el módulo `src.m08.benchmark` es un experimento separado que sobrescribe el JSON con nuevas mediciones y exige actualizar el análisis. Consultar `python -m src.m08.benchmark --help` para sus opciones.

Revisar esta decisión si se exige snapshot consistente, desempate único de timestamps, otro patrón de filtros o si mediciones equivalentes justifican un índice alternativo. Cualquier cambio debe preservar o versionar el contrato M05 y volver a medir bajo las mismas condiciones. El dataset actual varía fuentes y timestamps, pero utiliza un solo tipo (`telemetry.reading`); no demuestra rendimiento entre múltiples tipos ni de índices alternativos.
