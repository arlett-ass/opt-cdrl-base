# ADR-002 — Modelo Relacional Operativo, Invariantes y Consultas Parametrizadas

## Estado

Aceptado.

## Contexto

El hito M02 continúa el contrato de telemetría ambiental definido durante M01 ya que en la primera entrega se establecieron las entidades "locations", "devices" y "telemetry_readings", junto con sus llaves primarias, llaves foráneas, restricciones "CHECK", valores únicos y un seed sintético reproducible. Entonces para esta segunda entrega el objetivo es comprobar que ese modelo puede utilizarse de forma operativa y que las relaciones y restricciones definidas realmente protegen la integridad de los datos.

Además, se requiere demostrar consultas parametrizadas, casos de consulta normal y vacía, valores límite, un fallo declarado, migraciones idempotentes y resultados machine-readable que permitan verificar automáticamente el comportamiento de la solución. La implementación debía conservar compatibilidad con el contrato definido durante M01 y evitar cambios destructivos sobre las tablas o datos existentes.

## Decisión

### Conservación del modelo relacional de M01

Mantuvimos las tres entidades establecidas durante M01:

locations -> devices -> telemetry_readings

No fue necesario crear nuevas tablas porque las relaciones necesarias para M02 ya se encontraban representadas mediante llaves primarias y foráneas.

-locations: representa los lugares donde se encuentran instalados los dispositivos.
-devices: representa cada dispositivo de telemetría y mantiene una relación con una ubicación existente.
-telemetry_readings: almacena las lecturas producidas por cada dispositivo.

En M02 aprovechamos estas relaciones y comprobar mediante pruebas que las restricciones definidas realmente rechazan estados inválidos.

### Migración del modelo operativo

La migración correspondiente a M02 se encuentra en en la ruta de db/migrations/002_relational_model.sql entonces la migración conserva las tablas y registros existentes y agrega la vista "public.v_telemetry_context" y esta vista relaciona las lecturas de telemetría con la información del dispositivo y con su ubicación actual.

La vista permite obtener en una sola consulta información como:
-identificador de la lectura
-dispositivo
-código y nombre del dispositivo
-estado del dispositivo
-ubicación
-coordenadas
-fecha de registro y recepción
-temperatura
-humedad
-concentración de CO2

Se utilizó "CREATE OR REPLACE VIEW" para que la definición de la vista pueda repetirse sin necesitar eliminarla previamente. La vista representa la ubicación actual asociada al dispositivo y no un historial de cambios de ubicación. Esta característica se documentó directamente mediante un comentario en PostgreSQL. También se agregaron comentarios a las restricciones principales para documentar su propósito dentro del modelo.

### Invariantes del modelo

Decidimos comprobar directamente las reglas que protegen la integridad de los datos.

-La restricción `uq_telemetry_device_recorded_at` evita que un mismo dispositivo tenga dos lecturas registradas en el mismo instante.
-La llave foránea `fk_telemetry_readings_device` garantiza que toda lectura pertenezca a un dispositivo existente.
-La columna `device_id` mantiene la regla `NOT NULL`, por lo que una lectura no puede existir sin estar relacionada con un dispositivo.
-La restricción `ck_telemetry_timestamp_order` exige que `received_at` sea igual o posterior a `recorded_at`.
-Las llaves foráneas también evitan eliminar un dispositivo que todavía conserva lecturas y eliminar una ubicación que todavía conserva dispositivos.

Estas reglas se mantienen directamente en PostgreSQL para que la integridad del contrato no dependa solamente del código Python.

### Vista relacional

Se agregó "v_telemetry_context" para representar de forma directa la relación entre:

telemetry_readings -> devices -> locations

La vista utiliza `INNER JOIN` porque una lectura válida necesariamente debe pertenecer a un dispositivo y ese dispositivo debe pertenecer a una ubicación existente. Decidimos no duplicar dentro de `telemetry_readings` información como el código del dispositivo, nombre de la ubicación o coordenadas, ya que esos valores ya pertenecen a sus respectivas entidades y duplicarlos produciría redundancia.

### Consultas parametrizadas

Las consultas de M02 se encuentran en la ruta db/queries/telemetry.py y decidimos mantener el SQL fijo y enviar los valores mediante parámetros de `psycopg2`. De esta forma, los valores utilizados por el usuario no se concatenan directamente dentro de las instrucciones SQL.

Las consultas implementadas son:

-readings_between: obtiene las lecturas de un dispositivo dentro de un intervalo temporal inclusivo.
-latest_reading: obtiene la lectura más reciente de un dispositivo.
-reading_statistics: calcula cantidad de lecturas y valores promedio, mínimo y máximo.
-devices_at_location: obtiene los dispositivos asociados a una ubicación.
-recent_active_readings: obtiene lecturas recientes únicamente de dispositivos actualmente activos.

Los identificadores se validan como enteros positivos compatibles con `BIGINT`.
Los intervalos temporales deben utilizar fechas con zona horaria y la fecha inicial no puede ser posterior a la fecha final. El límite utilizado por `recent_active_readings` debe encontrarse entre 1 y 1000.

### Demostración de consultas

Se creó db/queries/demo.py pues su propósito es ejecutar las consultas parametrizadas sobre información existente y generar un resultado machine-readable. La demostración incluye resultados normales y también una ventana temporal sin registros para mostrar el comportamiento de una consulta vacía.

El resultado se almacena en la ruta artifacts/m02-query-demo.json y los valores `NUMERIC` de PostgreSQL se serializan como texto para conservar exactamente su precisión decimal y los valores de fecha se representan utilizando formato ISO.

### Pruebas de invariantes

Se creó el archivo en tests/test_m02_invariants_david.py ya que este archivo contiene ocho pruebas relacionadas con la integridad del modelo y se comprueba que:

-una lectura duplicada sea rechazada
-una lectura asociada a un dispositivo inexistente sea rechazada
-una lectura sin `device_id` sea rechazada
-`received_at` anterior a `recorded_at` sea rechazado
-un dispositivo con lecturas no pueda eliminarse
-una ubicación con dispositivos no pueda eliminarse
-la vista relacional devuelva correctamente una lectura relacionada
-un dispositivo sin lecturas produzca un resultado vacío en la vista

Los fallos esperados se validan utilizando el tipo de excepción producido por PostgreSQL y el nombre de la restricción responsable.

### Pruebas de aceptación

Se creó el archivo en tests/test_m02_acceptance_angelica.py y las pruebas cubren los cuatro escenarios solicitados por el hito.

1. Caso normal: Se registra una lectura con 24.00 °C, 50.00 % de humedad y 500.00 ppm de CO2 y posteriormente se recupera mediante una consulta parametrizada.
2. Caso vacío: Se consulta un intervalo en el cual el dispositivo no tiene lecturas y se comprueba que el resultado sea una lista vacía.
3. Caso límite: Se comprueban los límites permitidos por el contrato:

Temperatura mínima: -50.00 °C
Temperatura máxima:  80.00 °C

Humedad mínima:       0.00 %
Humedad máxima:     100.00 %

CO2 mínimo:           0.00 ppm
CO2 máximo:       10000.00 ppm

4. Fallo declarado: Se intenta almacenar una humedad de 101.00 %, valor que se encuentra fuera del contrato.

La prueba se considera correcta cuando PostgreSQL rechaza el registro mediante la restricción `ck_telemetry_humidity` y el código SQLSTATE `23514`. Se utiliza un `SAVEPOINT` para recuperar la transacción después del fallo esperado y posteriormente comprobar que la lectura inválida no fue almacenada.

### Aislamiento de las pruebas

Los datos utilizados durante las pruebas de M02 se crean específicamente para cada ejecución.
Se utilizan códigos únicos para las ubicaciones y dispositivos de prueba y al finalizar se ejecuta `ROLLBACK`.
Esto evita modificar permanentemente el seed definido durante M01 y permite repetir las pruebas sin acumular información adicional.

### Verificación automatizada

Se creó el archivo en scripts/verify_m02.sh y el script comprueba la existencia de los archivos requeridos y posteriormente ejecuta las ocho pruebas de invariantes y las cuatro pruebas de aceptación.

También verifica específicamente que los cuatro escenarios requeridos por la actividad hayan sido ejecutados y aprobados. El resultado machine-readable se genera mediante `pytest-json-report` en artifacts/m02-relational-results.json

El archivo existente scripts/verify_base.sh se conserva sin modificaciones porque forma parte de la base proporcionada por el profesor. El objetivo `verify` del Makefile ejecuta primero la validación original del starter y posteriormente la validación correspondiente a M02.

## Opciones consideradas

### Duplicar datos dentro de telemetry_readings

Consideramos almacenar directamente en cada lectura información como el código del dispositivo y la ubicación, pero lo descartamos porque produciría redundancia y permitiría inconsistencias entre la lectura y las entidades relacionadas. Preferimos mantener la normalización del modelo y utilizar una vista para consultar el contexto completo.

### Eliminar y recrear objetos durante la migración

Descartamos eliminar tablas o registros para aplicar M02 porque podría destruir el estado existente de M01. La migración se diseñó como una extensión no destructiva y la vista utiliza `CREATE OR REPLACE VIEW`.

## Consecuencias

-La solución conserva compatibilidad con M01 y permite utilizar el modelo como una base relacional operativa.
-Las consultas parametrizadas permiten reutilizar las mismas operaciones con diferentes dispositivos, ubicaciones y periodos sin modificar el SQL.
-Las pruebas se ejecutan dentro de transacciones y no modifican permanentemente el seed.

## Resultado

La entrega M02 queda preparada para comprobar que:

-la migración `002_relational_model.sql` puede aplicarse sin eliminar el modelo anterior
-la vista `v_telemetry_context` relaciona correctamente lecturas, dispositivos y ubicaciones
-las restricciones rechazan duplicados y relaciones inválidas
-`NOT NULL` impide lecturas sin dispositivo
-el orden temporal entre registro y recepción se conserva
-las llaves foráneas impiden eliminar entidades que todavía tienen dependencias
-las consultas utilizan parámetros separados del SQL
-el caso normal devuelve la información esperada
-el caso vacío produce un resultado vacío válido
-los límites definidos por el contrato son aceptados
-el fallo declarado es rechazado por PostgreSQL
-las pruebas no modifican permanentemente el seed
-las ocho pruebas de invariantes y las cuatro pruebas de aceptación forman una validación M02 de 12 escenarios
-los resultados se conservan en archivos JSON dentro de artifacts/