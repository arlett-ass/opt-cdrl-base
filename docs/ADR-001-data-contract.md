# ADR-001 — Contrato de datos de telemetría ambiental IoT

## Estado

Propuesto para revisión y aceptación de los tres integrantes:

* Nicolás David Juarez Mendoza.
* Víctor Manuel Jiménez Suarez.
* Angelica Arlett Santiago Serrano.

## Contexto

El hito M01 requiere definir un contrato de datos de telemetría y levantar una base de datos relacional compatible con un entorno cloud.

El contrato debe ser suficientemente preciso para que las migraciones, el seed sintético y las pruebas automáticas puedan desarrollarse sin interpretaciones diferentes entre los integrantes.

Para mantener un alcance pequeño, claro y verificable, se utilizará un escenario de monitoreo ambiental IoT con datos completamente sintéticos.

## Objetivo de la decisión

Este documento define:

* Las entidades que forman el sistema.
* Las tablas de PostgreSQL.
* Las columnas y sus tipos de datos.
* Las llaves primarias y foráneas.
* Las relaciones entre entidades.
* Las restricciones de integridad.
* Las reglas para aceptar o rechazar información.
* Las decisiones que deberán respetar las migraciones.
* Las reglas que deberá respetar el seed.
* Los casos que deberán comprobar las pruebas automáticas.

## Decisión

Se utilizará PostgreSQL como sistema gestor de base de datos relacional.

El modelo estará compuesto por tres entidades:

1. Ubicaciones.
2. Dispositivos.
3. Lecturas de telemetría.

Los nombres de las tablas serán:

* `locations`
* `devices`
* `telemetry_readings`

## Relación entre entidades

Una ubicación puede contener varios dispositivos y cada dispositivo puede generar múltiples lecturas ambientales.

```text
locations 1 ───── N devices 1 ───── N telemetry_readings
```

Las relaciones serán:

* Una ubicación puede tener muchos dispositivos.
* Cada dispositivo pertenece a una sola ubicación.
* Un dispositivo puede generar muchas lecturas.
* Cada lectura pertenece a un solo dispositivo.

## Entidad 1: `locations`

Representa el lugar físico sintético donde se instala uno o más dispositivos IoT.

No se almacenarán domicilios particulares ni información personal. Las ubicaciones utilizadas en el seed serán completamente ficticias.

| Columna         | Tipo PostgreSQL                       | Requerido | Regla                              |
| --------------- | ------------------------------------- | --------: | ---------------------------------- |
| `id`            | `BIGINT GENERATED ALWAYS AS IDENTITY` |        Sí | Llave primaria                     |
| `location_code` | `VARCHAR(50)`                         |        Sí | Código único y no vacío            |
| `name`          | `VARCHAR(120)`                        |        Sí | No puede estar vacío               |
| `latitude`      | `NUMERIC(9,6)`                        |        Sí | Valor entre `-90` y `90`           |
| `longitude`     | `NUMERIC(9,6)`                        |        Sí | Valor entre `-180` y `180`         |
| `created_at`    | `TIMESTAMPTZ`                         |        Sí | Predeterminado `CURRENT_TIMESTAMP` |

### Reglas de `locations`

* `id` identifica internamente cada ubicación.
* `id` será generado automáticamente por PostgreSQL.
* `location_code` permite identificar una ubicación mediante un código externo.
* `location_code` no puede repetirse.
* `location_code` no puede estar vacío ni contener únicamente espacios.
* `name` no puede ser nulo.
* `name` no puede estar vacío ni contener únicamente espacios.
* `latitude` debe estar entre `-90` y `90`, incluidos ambos extremos.
* `longitude` debe estar entre `-180` y `180`, incluidos ambos extremos.
* `created_at` se genera automáticamente cuando se crea el registro.

## Entidad 2: `devices`

Representa un dispositivo IoT instalado en una ubicación.

| Columna        | Tipo PostgreSQL                       | Requerido | Regla                                |
| -------------- | ------------------------------------- | --------: | ------------------------------------ |
| `id`           | `BIGINT GENERATED ALWAYS AS IDENTITY` |        Sí | Llave primaria                       |
| `location_id`  | `BIGINT`                              |        Sí | FK hacia `locations.id`              |
| `device_code`  | `VARCHAR(64)`                         |        Sí | Código único y no vacío              |
| `name`         | `VARCHAR(100)`                        |        Sí | No puede estar vacío                 |
| `status`       | `VARCHAR(20)`                         |        Sí | `active`, `inactive` o `maintenance` |
| `installed_at` | `TIMESTAMPTZ`                         |        Sí | Fecha de instalación                 |
| `created_at`   | `TIMESTAMPTZ`                         |        Sí | Predeterminado `CURRENT_TIMESTAMP`   |

### Reglas de `devices`

* `id` identifica internamente cada dispositivo.
* `id` será generado automáticamente por PostgreSQL.
* `location_id` relaciona el dispositivo con una ubicación existente.
* `location_id` es obligatorio.
* `device_code` no puede repetirse.
* `device_code` no puede estar vacío ni contener únicamente espacios.
* `name` no puede ser nulo.
* `name` no puede estar vacío ni contener únicamente espacios.
* `status` solo acepta los valores autorizados por el contrato.
* `installed_at` debe incluir fecha, hora y zona horaria.
* `created_at` se genera automáticamente.
* No se podrá eliminar una ubicación mientras tenga dispositivos relacionados.

## Entidad 3: `telemetry_readings`

Representa una lectura ambiental producida por un dispositivo IoT.

Cada registro contendrá las tres métricas definidas para M01:

* Temperatura.
* Humedad relativa.
* Concentración de dióxido de carbono.

| Columna         | Tipo PostgreSQL                       | Requerido | Regla                              |
| --------------- | ------------------------------------- | --------: | ---------------------------------- |
| `id`            | `BIGINT GENERATED ALWAYS AS IDENTITY` |        Sí | Llave primaria                     |
| `device_id`     | `BIGINT`                              |        Sí | FK hacia `devices.id`              |
| `recorded_at`   | `TIMESTAMPTZ`                         |        Sí | Momento de la medición             |
| `received_at`   | `TIMESTAMPTZ`                         |        Sí | Predeterminado `CURRENT_TIMESTAMP` |
| `temperature_c` | `NUMERIC(5,2)`                        |        Sí | Entre `-50.00` y `80.00`           |
| `humidity_pct`  | `NUMERIC(5,2)`                        |        Sí | Entre `0.00` y `100.00`            |
| `co2_ppm`       | `NUMERIC(8,2)`                        |        Sí | Entre `0.00` y `10000.00`          |

### Reglas de `telemetry_readings`

* Cada lectura debe pertenecer a un dispositivo existente.
* `device_id` es obligatorio.
* Las tres métricas son obligatorias.
* Los valores deben respetar los rangos definidos.
* `recorded_at` indica cuándo el dispositivo realizó la medición.
* `received_at` indica cuándo la plataforma recibió la información.
* `received_at` utilizará `CURRENT_TIMESTAMP` como valor predeterminado.
* `recorded_at` no puede ser posterior a `received_at`.
* Un dispositivo no puede tener dos lecturas registradas en el mismo instante.
* No se podrá eliminar un dispositivo mientras tenga lecturas relacionadas.

## Llaves primarias

Las llaves primarias serán:

* `locations.id`
* `devices.id`
* `telemetry_readings.id`

Se utilizará `BIGINT GENERATED ALWAYS AS IDENTITY` porque PostgreSQL puede generar los identificadores automáticamente.

Esta decisión evita depender de extensiones adicionales y facilita la creación reproducible del esquema.

El seed no deberá depender de identificadores numéricos escritos manualmente. Deberá utilizar códigos únicos y consultar los identificadores generados por PostgreSQL cuando necesite crear relaciones.

## Llaves foráneas

### Relación entre `locations` y `devices`

La relación será:

```text
devices.location_id → locations.id
```

Reglas:

* `location_id` será obligatorio.
* La ubicación debe existir antes de registrar un dispositivo.
* Se utilizará `ON UPDATE CASCADE`.
* Se utilizará `ON DELETE RESTRICT`.

### Relación entre `devices` y `telemetry_readings`

La relación será:

```text
telemetry_readings.device_id → devices.id
```

Reglas:

* `device_id` será obligatorio.
* El dispositivo debe existir antes de registrar una lectura.
* Se utilizará `ON UPDATE CASCADE`.
* Se utilizará `ON DELETE RESTRICT`.

## Restricciones de unicidad

Se definirán las siguientes restricciones:

* `locations.location_code` será único.
* `devices.device_code` será único.
* La combinación de `device_id` y `recorded_at` será única.

La última restricción evita registrar dos veces una lectura del mismo dispositivo en el mismo instante.

Las restricciones de unicidad también servirán como apoyo para implementar un seed idempotente.

## Restricciones de texto

Los siguientes campos no podrán estar vacíos ni contener únicamente espacios:

* `locations.location_code`
* `locations.name`
* `devices.device_code`
* `devices.name`

La validación se realizará mediante `BTRIM` dentro de restricciones `CHECK`.

## Estados permitidos

El estado de un dispositivo solo podrá contener uno de los siguientes valores:

* `active`
* `inactive`
* `maintenance`

Cualquier otro valor deberá ser rechazado por PostgreSQL.

El valor predeterminado será:

```text
active
```

## Rangos ambientales

| Métrica            | Valor mínimo | Valor máximo | Unidad            |
| ------------------ | -----------: | -----------: | ----------------- |
| Temperatura        |     `-50.00` |      `80.00` | Grados Celsius    |
| Humedad relativa   |       `0.00` |     `100.00` | Porcentaje        |
| Dióxido de carbono |       `0.00` |   `10000.00` | Partes por millón |

Los valores mínimos y máximos se consideran válidos porque forman parte de los casos límite del contrato.

Los valores inferiores o superiores a estos rangos deberán ser rechazados por PostgreSQL.

## Rangos geográficos

| Coordenada | Valor mínimo | Valor máximo |
| ---------- | -----------: | -----------: |
| Latitud    |        `-90` |         `90` |
| Longitud   |       `-180` |        `180` |

Los valores mínimos y máximos se consideran válidos.

Estos rangos evitan almacenar coordenadas geográficas inválidas.

## Fechas y zona horaria

Todas las fechas se almacenarán utilizando `TIMESTAMPTZ`.

Esto permite conservar correctamente la referencia temporal cuando el proyecto se ejecute en diferentes zonas horarias o en un entorno cloud.

Las fechas principales serán:

* `installed_at`: momento de instalación del dispositivo.
* `recorded_at`: momento en que se realizó la medición.
* `received_at`: momento en que la plataforma recibió la lectura.
* `created_at`: momento de creación del registro.

La siguiente regla deberá cumplirse:

```text
recorded_at <= received_at
```

Una medición con fecha posterior a la fecha de recepción deberá ser rechazada.

## Contrato de una lectura válida

Una lectura se considerará válida cuando cumpla todas las condiciones siguientes:

1. Pertenece a un dispositivo existente.
2. Incluye temperatura, humedad y CO2.
3. La temperatura está entre `-50.00` y `80.00 °C`.
4. La humedad está entre `0.00` y `100.00 %`.
5. El CO2 está entre `0.00` y `10000.00 ppm`.
6. Incluye una fecha de medición con zona horaria.
7. La fecha de medición no es posterior a la fecha de recepción.
8. No duplica una lectura del mismo dispositivo en el mismo instante.
9. Ningún campo obligatorio contiene un valor nulo.

## Datos que deben rechazarse

PostgreSQL deberá rechazar:

* Lecturas asociadas con dispositivos inexistentes.
* Dispositivos asociados con ubicaciones inexistentes.
* Humedad menor que `0.00`.
* Humedad mayor que `100.00`.
* Temperatura menor que `-50.00`.
* Temperatura mayor que `80.00`.
* CO2 menor que `0.00`.
* CO2 mayor que `10000.00`.
* Estados de dispositivo diferentes de los autorizados.
* Lecturas duplicadas.
* Columnas obligatorias con valor nulo.
* Nombres o códigos vacíos.
* Nombres o códigos formados únicamente por espacios.
* Coordenadas geográficas fuera de rango.
* Mediciones con fecha posterior a la fecha de recepción.

## Estrategia de índices

Se utilizarán índices para facilitar:

* La búsqueda de dispositivos por ubicación.
* La búsqueda de lecturas por dispositivo y fecha.
* La consulta de lecturas por fecha de medición.

Los índices explícitos serán:

* `idx_devices_location_id` sobre `devices.location_id`.
* `idx_telemetry_recorded_at` sobre `telemetry_readings.recorded_at`.

La restricción única sobre:

```text
telemetry_readings(device_id, recorded_at)
```

creará automáticamente un índice único compuesto en PostgreSQL. Por esa razón no se creará otro índice idéntico, ya que sería redundante.

## Orden de creación

Las tablas deberán crearse en el siguiente orden:

1. `locations`
2. `devices`
3. `telemetry_readings`

Este orden deberá respetarse porque:

* `devices` depende de `locations`.
* `telemetry_readings` depende de `devices`.

## Compatibilidad con cloud

El contrato utiliza características estándar de PostgreSQL.

No dependerá de:

* Rutas locales.
* Usuarios específicos del sistema operativo.
* Direcciones IP fijas.
* Extensiones adicionales de PostgreSQL.
* Credenciales incluidas en el código.
* Información proveniente de ambientes de producción.

La configuración de la base de datos se obtendrá mediante variables de entorno.

El mismo modelo deberá poder utilizarse en:

* PostgreSQL ejecutado mediante Docker Compose.
* PostgreSQL disponible en AWS Academy Learner Lab, cuando esté habilitado.

## Seguridad

El repositorio no almacenará:

* Contraseñas reales.
* Tokens.
* Datos personales.
* Cadenas de conexión reales.
* Credenciales de AWS.
* Información de dispositivos reales.
* Datos provenientes de ambientes de producción.

El archivo `.env.example` solamente contendrá valores públicos, sintéticos o marcadores de posición.

El archivo `.env` deberá mantenerse fuera de Git y no deberá incluirse en capturas, artefactos o evidencias.

## Reproducibilidad

Víctor Manuel Jiménez Suarez convertirá este contrato en migraciones ordenadas y versionadas.

Las migraciones deberán:

* Crear la base desde cero.
* Aplicarse siempre en el mismo orden.
* Registrar cuáles migraciones fueron ejecutadas.
* Ejecutar únicamente las migraciones pendientes.
* Evitar duplicar objetos.
* Utilizar transacciones cuando corresponda.
* Fallar claramente cuando una operación no pueda completarse.
* Producir el mismo esquema final esperado.

El seed deberá:

* Utilizar datos completamente sintéticos.
* Respetar las llaves foráneas.
* Respetar todas las restricciones.
* Utilizar códigos únicos.
* Poder ejecutarse varias veces sin duplicar registros.
* Producir el mismo estado esperado después de cada ejecución.

## Casos de prueba derivados del contrato

Angelica Arlett Santiago Serrano podrá utilizar los siguientes casos como base para las pruebas automáticas.

### Caso normal

Datos:

* Temperatura: `24.00 °C`
* Humedad: `50.00 %`
* CO2: `500.00 ppm`

Resultado esperado: PostgreSQL acepta y almacena la lectura.

### Caso límite 1

Datos:

* Temperatura: `24.00 °C`
* Humedad: `0.00 %`
* CO2: `500.00 ppm`

Resultado esperado: PostgreSQL acepta la lectura porque la humedad corresponde al límite inferior permitido.

### Caso límite 2

Datos:

* Temperatura: `24.00 °C`
* Humedad: `100.00 %`
* CO2: `500.00 ppm`

Resultado esperado: PostgreSQL acepta la lectura porque la humedad corresponde al límite superior permitido.

### Fallo declarado

Datos:

* Temperatura: `24.00 °C`
* Humedad: `101.00 %`
* CO2: `500.00 ppm`

Resultado esperado: PostgreSQL rechaza la lectura porque la humedad supera el límite permitido.

La prueba del fallo declarado deberá considerarse exitosa cuando confirme que PostgreSQL rechazó correctamente la información inválida.

## Alternativas consideradas

### Almacenar todas las métricas en JSON

Se consideró almacenar las métricas ambientales dentro de una columna JSON.

Se descartó porque dificultaría aplicar tipos, campos obligatorios y restricciones directamente desde PostgreSQL.

También complicaría las consultas y las pruebas de los rangos definidos.

### Utilizar un modelo EAV

Se consideró almacenar cada métrica como una combinación de entidad, atributo y valor.

Se descartó para M01 porque las tres métricas son conocidas y un modelo EAV agregaría complejidad innecesaria.

Además, dificultaría aplicar diferentes rangos y tipos a cada métrica.

### Utilizar únicamente una base NoSQL

Se descartó porque el objetivo de M01 solicita levantar una base de datos relacional.

El proyecto inicial puede incluir otros servicios de respaldo, pero el contrato evaluado en este ADR corresponde a PostgreSQL.

### Utilizar UUID como llave primaria

Se consideró utilizar UUID como llave primaria.

Se eligió `BIGINT GENERATED ALWAYS AS IDENTITY` para:

* Simplificar el esquema.
* Evitar extensiones adicionales.
* Facilitar la lectura de las relaciones.
* Mantener un alcance adecuado para M01.

UUID podría evaluarse nuevamente si un hito futuro requiere generación distribuida de identificadores.

## Consecuencias positivas

* El contrato es pequeño y fácil de comprobar.
* Las relaciones son claras.
* PostgreSQL valida los datos desde la base.
* Los casos normales y límite son sencillos de automatizar.
* El esquema es compatible con un entorno local y cloud.
* Las migraciones pueden crearse directamente a partir del contrato.
* La integridad no depende solamente del código de aplicación.
* El seed puede utilizar códigos únicos para evitar duplicados.
* Los errores de datos pueden detectarse directamente en PostgreSQL.

## Consecuencias negativas

* Agregar una nueva métrica requerirá una migración.
* `ON DELETE RESTRICT` impide eliminar registros que todavía tengan información relacionada.
* Los rangos ambientales podrían necesitar ajustes en futuros hitos.
* Cada lectura debe incluir las tres métricas definidas.
* La estructura no permite agregar métricas dinámicas sin modificar el esquema.
* El uso de identificadores generados requiere consultar los IDs antes de crear relaciones en el seed.

## Responsabilidades relacionadas

### Nicolás David Juarez Mendoza

* Analizar los requisitos de M01.
* Identificar las entidades.
* Definir el contrato.
* Definir tablas, columnas y tipos.
* Definir llaves primarias y foráneas.
* Definir restricciones.
* Crear la estructura inicial de `db/`.
* Documentar su contribución.

### Víctor Manuel Jiménez Suarez

* Convertir el contrato en migraciones.
* Garantizar la reproducibilidad e idempotencia.
* Crear el seed sintético.
* Probar la creación de la base desde cero.
* Probar la carga repetida del seed.
* Documentar su contribución.

### Angelica Arlett Santiago Serrano

* Diseñar el caso normal.
* Diseñar los dos casos límite.
* Diseñar el fallo declarado.
* Automatizar las pruebas.
* Integrar las pruebas con `make verify`.
* Generar los resultados dentro de `artifacts/`.
* Comprobar los comandos Make.
* Documentar su contribución.

La asignación anterior indica quién lidera cada parte, pero los tres integrantes deberán revisar el contrato y el resultado final.

## Revisión conjunta del contrato

Aunque Nicolás David Juarez Mendoza redacta la propuesta inicial, Nicolás David Juarez Mendoza, Víctor Manuel Jiménez Suarez y Angelica Arlett Santiago Serrano deberán revisar:

* Si el esquema representa correctamente la telemetría.
* Si las relaciones tienen sentido.
* Si las cardinalidades son correctas.
* Si los tipos de datos son adecuados.
* Si las llaves primarias y foráneas están correctamente definidas.
* Si las restricciones corresponden al contrato.
* Si los rangos son razonables.
* Si las migraciones pueden construirse a partir del esquema.
* Si las pruebas pueden comprobar las reglas definidas.
* Si el seed puede respetar las restricciones.
* Si la solución es compatible con PostgreSQL local y cloud.
* Si el contrato contiene información sensible.
* Si los comandos requeridos pueden ejecutarse de manera reproducible.

## Aprobación del contrato

| Integrante                       | Aspecto que debe validar                           | Estado    |
| -------------------------------- | -------------------------------------------------- | --------- |
| Nicolás David Juarez Mendoza     | Requisitos, entidades, tablas, tipos y contrato    | Pendiente |
| Víctor Manuel Jiménez Suarez     | Viabilidad de migraciones, idempotencia y seed     | Pendiente |
| Angelica Arlett Santiago Serrano | Viabilidad de pruebas, automatización y artefactos | Pendiente |

El estado de este ADR cambiará de `Propuesto` a `Aceptado` cuando los tres integrantes hayan revisado y aprobado el contrato.

Cuando se obtenga la aprobación deberán actualizarse:

* El estado general del ADR.
* El estado de cada integrante en la tabla.
* Las observaciones o modificaciones acordadas por el equipo.

## Integración final compartida

Al finalizar M01, Nicolás David Juarez Mendoza, Víctor Manuel Jiménez Suarez y Angelica Arlett Santiago Serrano deberán comprobar juntos:

```bash
make setup
make verify
make run
```

También deberán revisar:

* El esquema final.
* Las relaciones.
* Los tipos de datos.
* Las llaves primarias.
* Las llaves foráneas.
* Las restricciones.
* Las migraciones.
* El seed.
* Las pruebas automáticas.
* Los artefactos.
* El archivo `evidence/m01-data-contract.json`.
* La ausencia de secretos.
* El tag `week-01-final`.
* El SHA exacto entregado.
* La salida final de `make verify`.

## Resultado de la decisión

Este ADR será la fuente de referencia para las migraciones, el seed y las pruebas del hito M01.

Cualquier cambio posterior en nombres, columnas, tipos, relaciones o restricciones deberá:

1. Actualizarse en este documento.
2. Actualizarse en `db/schema/telemetry-contract.sql`.
3. Reflejarse en las migraciones.
4. Reflejarse en el seed cuando corresponda.
5. Reflejarse en las pruebas afectadas.
6. Comunicarse a los tres integrantes.
7. Revisarse antes de integrarse en la rama principal.

El contrato permanecerá en estado `Propuesto` hasta recibir la aprobación de los tres integrantes.
