# ADR-004: consultas parametrizadas con psycopg2

Estado: propuesto para integración de M02.

## Contexto

El esquema de David conserva locations, devices y telemetry_readings y agrega
v_telemetry_context. Se necesitan consultas reproducibles por dispositivo, fecha
y ubicación, con casos normal y vacío y resultados procesables automáticamente.

## Decisión

Usar SQL fijo en `db/queries/telemetry.py` y enviar todos los valores mediante el
segundo argumento de `cursor.execute`. Se reutiliza psycopg2, ya declarado por
el proyecto. RealDictCursor proporciona nombres de columnas en los resultados.

Validar IDs positivos BIGINT, fechas con zona horaria, inicio no posterior al fin
y límites de 1 a 1000. Usar intervalos inclusivos y orden determinista. Conservar
los agregados NULL cuando no hay filas. No convertir ausencia de datos en cero.

Reutilizar la vista para lecturas de dispositivos actualmente activos y el índice
UNIQUE existente para búsquedas por dispositivo y fecha. Reutilizar el seed
parametrizado de M01 como DML de demostración.

La CLI abre una transacción de solo lectura REPEATABLE READ para que sus consultas
vean una misma instantánea. Los métodos de consulta dejan las transacciones al
llamador. En JSON, Decimal se representa como cadena para evitar pérdida de precisión.

## Alternativas

Se descarta construir SQL con interpolación de entradas por riesgo de inyección
y errores de formato. Un ORM añadiría una dependencia sin ser necesario para estas
cinco consultas. Un índice adicional idéntico al UNIQUE duplicaría almacenamiento.

## Consecuencias

La API es pequeña y comprobable con PostgreSQL real. Sus consumidores deben
interpretar fechas ISO y cadenas decimales del JSON. El estado/ubicación de la vista
son actuales. La lista por rango no se pagina, suficiente para esta demo académica;
volúmenes grandes requerirán paginación. Las pruebas revierten los datos propios.
