# ADR-008: Paginación y evaluación del rendimiento de consultas

**Estado:** Propuesto

**Fecha:** 31 de octubre de 2026

## 1. Contexto

En el proyecto CDRL se necesita consultar información almacenada en DynamoDB sin recuperar necesariamente todos los documentos en una sola operación. La implementación existente en M05 permite obtener los documentos de un tipo de evento, mientras que en M08 se incorpora `query_by_type_page()` para recuperar resultados por páginas mediante el cursor nativo de DynamoDB.

Para evaluar esta alternativa, se desarrolló un benchmark que compara la consulta completa, la recuperación de la primera página y el recorrido paginado completo. La prueba utiliza 10,000 documentos sintéticos del tipo `telemetry.reading`, un tamaño de página de 20 documentos y 100 repeticiones por escenario, con una ejecución de calentamiento por escenario.

## 2. Decisión propuesta

Se propone conservar la paginación mediante el cursor nativo de DynamoDB para permitir que los resultados se recuperen progresivamente.

La implementación debe mantener la compatibilidad con la consulta existente de M05 y validar la integridad del recorrido para detectar documentos omitidos o duplicados. También se comprueba que los cursores puedan serializarse y recuperarse como JSON, como sucedería al enviarlos entre solicitudes de un cliente.

La paginación se considera una estrategia para entregar resultados por partes, no una garantía de que recuperar el conjunto completo sea más rápido que realizar una consulta completa.

## 3. Opciones consideradas

**Opción 1. Mantener la consulta completa.**

Conservar la implementación existente que recupera todos los documentos. Esta alternativa mantiene el comportamiento actual, pero no permite entregar los resultados progresivamente por páginas.

**Opción 2. Incorporar paginación con cursor nativo.**

Recuperar una cantidad limitada de documentos por consulta y utilizar el cursor para continuar el recorrido. Esta alternativa facilita la entrega progresiva de resultados, aunque puede aumentar el tiempo total cuando se necesitan todos los documentos.

**Opción 3. Evaluar cambios adicionales en los índices.**

Analizar si los índices existentes responden adecuadamente a los patrones de consulta del proyecto. Cualquier cambio debe justificarse mediante pruebas específicas, considerando también el costo de almacenamiento y escritura.

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

Aunque los 10,000 documentos se recuperaron sin omisiones ni duplicados, la consulta vacía representa una operación adicional que debe revisarse. Se documenta como un hallazgo de rendimiento y queda pendiente confirmar si puede evitarse sin comprometer la continuidad del recorrido ni la integridad de los resultados.

## 6. Consecuencias

La paginación permite entregar resultados progresivamente y puede ser útil en interfaces que muestran resultados por páginas o en procesos que consumen información de manera incremental.

Sin embargo, si se necesita recuperar todo el conjunto, las consultas adicionales pueden aumentar el tiempo total. El tamaño de página y la estrategia de consulta deben seleccionarse según las necesidades del sistema.

La implementación debe conservar las validaciones de integridad y detección de cursores repetidos. Además, el comportamiento observado de la consulta vacía debe revisarse antes de considerar optimizado el recorrido completo.

## 7. Limitaciones

Los resultados corresponden a una prueba local con datos sintéticos y DynamoDB Local. No representan una garantía del rendimiento en producción.

Los tiempos pueden variar según el equipo, la carga del sistema, la configuración y las características de los datos. La paginación mediante cursor tampoco garantiza por sí sola una vista inmutable de los datos cuando estos cambian durante el recorrido.

La evaluación específica de cambios en los índices y el comportamiento ante modificaciones concurrentes quedan pendientes de pruebas adicionales.

## 8. Evidencia y seguimiento

Los resultados se registran en `artifacts/m08-pagination-benchmark.json`. La implementación de la paginación y del benchmark se encuentra en `src/m08/pagination.py` y `src/m08/benchmark.py`.

Antes de aceptar este ADR, el equipo deberá revisar el comportamiento de la consulta vacía, integrar las pruebas correspondientes y confirmar si se requieren ajustes adicionales en la implementación o en los índices.