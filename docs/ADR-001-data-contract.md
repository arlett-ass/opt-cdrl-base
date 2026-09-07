# ADR-001 — Selección de Stack Tecnológico y Contrato de Telemetría Ambiental

## Estado

Aceptado.

## Contexto

El hito M01 requiere convertir la base inicial de CDRL en un contrato de datos ejecutable, utilizando una base relacional compatible con un entorno cloud, migraciones reproducibles, un seed sintético y pruebas automáticas.

Además de definir las tablas, se necesitaba decidir qué tipo de telemetría se utilizaría como referencia, qué motor de base de datos sería adecuado y qué lenguaje permitiría automatizar de forma sencilla la creación, carga y validación de los datos.

La solución debía poder reproducirse entre los integrantes del equipo sin depender de configuraciones personales y conservar compatibilidad con AWS Academy Learner Lab cuando los servicios necesarios se encuentren habilitados.

## Decisión

### Telemetría ambiental
Se decidió utilizar telemetría ambiental IoT, representada mediante temperatura, humedad y concentración de CO2.

Se eligió este tipo de telemetría porque permite trabajar con datos numéricos sencillos de interpretar, pero al mismo tiempo suficientes para definir un contrato con reglas reales de validación además se adapta de manera natural a un modelo IoT formado por ubicaciones, dispositivos y lecturas, por lo que permite representar relaciones entre entidades sin introducir información personal o sensible.

Por ejemplo, una humedad no puede superar el 100 %, una temperatura debe mantenerse dentro del rango establecido por el contrato y una concentración de CO2 también necesita límites definidos.

El contrato quedó organizado de la siguiente forma:

```text
locations
    ↓
devices
    ↓
telemetry_readings
```

Una ubicación puede tener varios dispositivos y cada dispositivo puede producir múltiples lecturas.

### Contrato relacional
Se decidió dividir la información en tres entidades para evitar duplicar datos y mantener una estructura clara.

`locations` contiene la información del lugar donde se encuentran los dispositivos.
`devices` representa cada sensor o dispositivo IoT y mantiene una relación con su ubicación.
`telemetry_readings` almacena las mediciones ambientales generadas por cada dispositivo.

El contrato incluye restricciones directamente en PostgreSQL para que las reglas no dependan únicamente de una aplicación externa.

Entre las principales reglas se encuentran:

Temperatura: -50.00 °C a 80.00 °C
Humedad:      0.00 % a 100.00 %
CO2:          0.00 ppm a 10000.00 ppm
Latitud:     -90 a 90
Longitud:   -180 a 180

### PostgreSQL
Se seleccionó PostgreSQL porque el modelo necesita relaciones claras entre ubicaciones, dispositivos y lecturas, además de llaves primarias, llaves foráneas, restricciones `CHECK`, valores únicos, índices y transacciones, lo que permite representar todas las reglas directamente en el esquema.

Además de que puede utilizarse localmente mediante Docker y posteriormente mantenerse en un entorno cloud compatible sin rediseñar el contrato.

### Entorno reproducible con Docker Compose
Se implementó Docker Compose como respaldo reproducible para PostgreSQL y la principal razón fue evitar que la solución dependa de la versión de PostgreSQL, usuarios, puertos o configuraciones instaladas personalmente en cada computadora.

Entonces el contenedor permite que el equipo utilice el mismo motor y una configuración equivalente y asi también facilita reconstruir el entorno desde cero durante las pruebas.

AWS Academy Learner Lab continúa siendo el entorno cloud definido por la asignatura cuando los servicios requeridos se encuentren disponibles.

### Lenguaje Python
Se seleccionó Paython porque además de la capacidad de procesamiento de datos y su facilidad de lectura y la también permite resolver dentro de un mismo entorno las necesidades principales del hito como la conexión con PostgreSQL, la ejecución de migraciones, la carga del seed, el manejo de transacciones, las pruebas automáticas y la generación de resultados JSON

Además mediante `psycopg2` Python permite comunicarse directamente con PostgreSQL y controlar operaciones como `commit` y `rollback`. Esto es útil en las pruebas porque los registros utilizados para validar un escenario pueden crearse temporalmente y revertirse al finalizar sin modificar permanentemente el estado de la base.

También se utiliza `pytest`, que permite expresar de manera sencilla los casos normal, límite y de fallo solicitados por el hito.

### Migraciones e idempotencia
La migración inicial se encuentra en: db/migrations/001_schema.sql

Se decidió evitar la estrategia de eliminar y volver a crear las tablas en cada ejecución, ya que esto destruiría el estado existente y no representaría correctamente una migración versionada. Por lo que se implementó "schema_migrations" para registrar las migraciones que ya fueron aplicadas asi de esta manera, `rebuild.py` puede comprobar si una migración ya existe antes de ejecutarla nuevamente.

### Seed sintético
El estado definido para el seed es:
- 3 locations
- 5 devices
- 50 telemetry_readings

No se utilizaron datos reales ni información personal y se evitó utilizar valores aleatorios porque producirían resultados diferentes entre ejecuciones y dificultarían demostrar la reproducibilidad.

### Pruebas automáticas
Las pruebas se implementaron con `pytest` tomando como referencia las restricciones definidas en el contrato. Se utilizaron cuatro escenarios:

- Caso normal: 24.00 °C / 50.00 % / 500.00 ppm
- Caso límite inferior: temperatura = -50.00 °C
- Caso límite superior: CO2 = 10000.00 ppm
- Fallo declarado: humedad = 100.05 %

La prueba del fallo se considera correcta cuando PostgreSQL rechaza el valor mediante la restricción de humedad. Además de que los escenarios utilizan transacciones y `ROLLBACK`, por lo que los datos de prueba no modifican permanentemente el seed.

El resultado obtenido fue 4 passed y la base conservó:
- 3 locations
- 5 devices
- 50 telemetry_readings

El resultado machine-readable de las pruebas se almacena en: artifacts/m01-tests.json

## Opciones consideradas

### PostgreSQL instalado directamente en cada equipo
Se consideró utilizar la instalación personal de PostgreSQL de cada integrante pero se descartó como entorno principal porque las versiones, usuarios, puertos y configuraciones pueden ser diferentes y Docker Compose ofrece un entorno más fácil de reproducir.

### Seed con información aleatoria
Se consideró generar datos diferentes en cada ejecución pero se descartó porque dificultaría comprobar si el estado de la base realmente se mantiene estable y se prefirió un conjunto pequeño de información conocida y sintética.

### Eliminar y recrear las tablas
Se consideró reconstruir completamente las tablas cada vez que se ejecutara el proceso aunque simplificaba inicialmente la creación desde cero, también eliminaba información existente y se decidió registrar las migraciones aplicadas y ejecutar solamente las pendientes.

## Consecuencias

La solución permite tener un contrato que no solamente describe los datos, sino que también puede validar automáticamente si estos cumplen las reglas establecidas.

- El uso de PostgreSQL permite mantener la integridad de las relaciones y de los valores almacenados.
- Docker Compose reduce diferencias entre los entornos de los integrantes y facilita reconstruir la base.
- Python permite automatizar migraciones, seed y pruebas sin depender de procesos manuales.
- El seed determinista permite comprobar que múltiples ejecuciones mantienen el mismo resultado.

Como consecuencia, el proyecto incorpora algunos elementos adicionales como "schema_migrations", dependencias de Python y scripts de reconstrucción, pero estos elementos permiten obtener una solución más reproducible y fácil de verificar.

## Resultado
La decisión fue validada comprobando que:
- la base puede construirse desde cero
- la migración queda registrada
- una migración aplicada no vuelve a ejecutarse
- el seed mantiene 3 locations
- el seed mantiene 5 devices
- el seed mantiene 50 telemetry_readings
- una segunda ejecución no duplica los datos
- las cuatro pruebas automáticas son aprobadas
- las pruebas no modifican permanentemente el seed
- el artifact JSON es válido