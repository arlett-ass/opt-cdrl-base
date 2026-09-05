# Base de datos — CDRL M01

## Propósito

Este directorio contiene el contrato, las migraciones y el seed de la base de datos relacional de telemetría ambiental IoT.

PostgreSQL será el sistema gestor de base de datos.

Docker Compose se utilizará como entorno local reproducible y AWS Academy Learner Lab podrá utilizarse cuando esté habilitado.

## Estructura

* `schema/`: contrato relacional definido inicialmente por Nicolás David Juarez Mendoza y sujeto a revisión del equipo.
* `migrations/`: migraciones reproducibles creadas por Víctor Manuel Jiménez Suarez.
* `seed/`: datos sintéticos e idempotentes creados por Víctor Manuel Jiménez Suarez.

La estructura esperada es:

```text
db/
├── README.md
├── schema/
│   └── telemetry-contract.sql
├── migrations/
└── seed/
```

## Contrato fuente

El archivo principal de diseño es:

```text
db/schema/telemetry-contract.sql
```

Este archivo define:

* Las tablas.
* Las columnas.
* Los tipos de datos.
* Las llaves primarias.
* Las llaves foráneas.
* Las restricciones.
* Los índices.
* Las relaciones entre entidades.

Víctor Manuel Jiménez Suarez deberá utilizarlo como referencia para crear las migraciones.

No deberán cambiarse nombres, tipos, relaciones o restricciones sin:

1. Comunicarlo al equipo.
2. Revisar el impacto.
3. Actualizar `docs/ADR-001-data-contract.md`.
4. Actualizar `db/schema/telemetry-contract.sql`.
5. Actualizar las migraciones.
6. Actualizar las pruebas afectadas.

## Entidades

El contrato contiene tres entidades principales:

### `locations`

Representa las ubicaciones donde se instalan los dispositivos ambientales.

### `devices`

Representa los dispositivos IoT relacionados con una ubicación.

### `telemetry_readings`

Representa las lecturas ambientales generadas por los dispositivos.

## Orden de las entidades

Las tablas deberán crearse en el siguiente orden:

1. `locations`
2. `devices`
3. `telemetry_readings`

El orden es necesario porque:

* `devices` depende de `locations`.
* `telemetry_readings` depende de `devices`.

## Relaciones

Las relaciones del contrato son:

* `devices.location_id` referencia `locations.id`.
* `telemetry_readings.device_id` referencia `devices.id`.

La cardinalidad es:

```text
locations 1 ───── N devices 1 ───── N telemetry_readings
```

Ambas llaves foráneas utilizan:

* `ON UPDATE CASCADE`
* `ON DELETE RESTRICT`

`ON UPDATE CASCADE` mantiene actualizadas las referencias cuando cambia una llave relacionada.

`ON DELETE RESTRICT` evita eliminar una ubicación que todavía tiene dispositivos o un dispositivo que todavía tiene lecturas.

## Migraciones

Las migraciones deberán:

* Estar versionadas.
* Ejecutarse en un orden definido.
* Crear la base desde cero.
* Crear las tablas en el orden de dependencia.
* Crear las llaves primarias y foráneas.
* Crear las restricciones del contrato.
* Crear los índices necesarios.
* Registrar cuáles migraciones ya fueron aplicadas.
* Evitar volver a aplicar una migración registrada.
* No duplicar tablas, restricciones ni índices.
* Fallar claramente si una operación no puede completarse.
* Utilizar transacciones cuando corresponda.
* Ser compatibles con PostgreSQL local y cloud.
* Poder comprobarse mediante los comandos Make del proyecto.

Las migraciones no deberán contener:

* Contraseñas reales.
* Tokens.
* Credenciales de AWS.
* Direcciones específicas de una computadora.
* Cadenas de conexión reales.
* Información de producción.

## Seed sintético

El seed deberá crear información ficticia para:

* Ubicaciones.
* Dispositivos.
* Lecturas de telemetría.

El seed deberá respetar el siguiente orden:

1. Insertar ubicaciones.
2. Insertar dispositivos relacionados con ubicaciones existentes.
3. Insertar lecturas relacionadas con dispositivos existentes.

También deberá:

* Utilizar códigos únicos.
* Respetar todos los rangos del contrato.
* Poder ejecutarse más de una vez.
* Evitar registros duplicados.
* No utilizar datos personales.
* No representar dispositivos reales.
* No depender de información externa.
* Producir el mismo estado esperado después de ejecutarse nuevamente.

## Datos ambientales

Cada lectura incluirá:

* Temperatura en grados Celsius.
* Humedad relativa en porcentaje.
* Concentración de CO2 en partes por millón.
* Fecha y hora de medición.
* Fecha y hora de recepción.
* Dispositivo relacionado.

Las fechas y horas deberán almacenarse con zona horaria.

## Rangos válidos

Los rangos definidos en el contrato son:

| Dato        | Valor mínimo |   Valor máximo |
| ----------- | -----------: | -------------: |
| Temperatura |  `-50.00 °C` |     `80.00 °C` |
| Humedad     |     `0.00 %` |     `100.00 %` |
| CO2         |   `0.00 ppm` | `10000.00 ppm` |
| Latitud     |        `-90` |           `90` |
| Longitud    |       `-180` |          `180` |

Los valores ubicados exactamente en los extremos deberán aceptarse.

Los valores menores o mayores que los rangos definidos deberán ser rechazados por PostgreSQL.

## Restricciones principales

El esquema deberá comprobar como mínimo:

* Que los códigos requeridos no estén vacíos.
* Que los códigos únicos no se repitan.
* Que cada dispositivo pertenezca a una ubicación existente.
* Que cada lectura pertenezca a un dispositivo existente.
* Que el estado de un dispositivo contenga un valor permitido.
* Que la temperatura permanezca dentro de su rango.
* Que la humedad permanezca dentro de su rango.
* Que la concentración de CO2 permanezca dentro de su rango.
* Que la latitud y la longitud permanezcan dentro de sus rangos.
* Que la fecha de medición no sea posterior a la fecha de recepción.
* Que un dispositivo no registre dos lecturas con la misma fecha de medición.

## Pruebas esperadas

El contrato permite implementar las siguientes pruebas:

### Caso normal

Registrar una lectura con:

* Temperatura: `24.00 °C`.
* Humedad: `50.00 %`.
* CO2: `500.00 ppm`.

Resultado esperado: PostgreSQL acepta y almacena la lectura.

### Caso límite inferior

Registrar una lectura con:

* Humedad: `0.00 %`.

Resultado esperado: PostgreSQL acepta el valor porque corresponde al límite inferior permitido.

### Caso límite superior

Registrar una lectura con:

* Humedad: `100.00 %`.

Resultado esperado: PostgreSQL acepta el valor porque corresponde al límite superior permitido.

### Fallo declarado

Intentar registrar una lectura con:

* Humedad: `101.00 %`.

Resultado esperado: PostgreSQL rechaza el registro porque supera el límite permitido.

La prueba del fallo declarado será exitosa cuando el registro inválido sea rechazado de la manera esperada.

## Idempotencia

La idempotencia significa que ejecutar nuevamente las migraciones y el seed deberá conservar el mismo estado esperado sin generar duplicados ni errores por objetos ya procesados.

Para las migraciones se deberá:

* Mantener un registro de versiones aplicadas.
* Ejecutar únicamente las migraciones pendientes.
* Evitar repetir cambios ya registrados.
* Utilizar transacciones cuando corresponda.

Para el seed se deberá:

* Utilizar identificadores naturales o códigos únicos.
* Controlar conflictos.
* Insertar solamente los datos faltantes.
* Evitar duplicar ubicaciones, dispositivos o lecturas.

La estrategia exacta será implementada por Víctor Manuel Jiménez Suarez y revisada por todo el equipo.

## Variables de entorno

La configuración de PostgreSQL se obtendrá mediante variables de entorno.

Los nombres de las variables y los valores públicos de ejemplo estarán documentados en `.env.example`.

El archivo `.env` local:

* No deberá incluirse en Git.
* No deberá compartirse mediante capturas.
* No deberá contener credenciales de AWS.
* No deberá contener datos de producción.
* No deberá incluirse en los artefactos o evidencias.
* No deberá compartirse entre integrantes mediante el repositorio.

## Responsabilidades

### Nicolás David Juarez Mendoza

* Analizar los requisitos de M01.
* Definir el contrato relacional.
* Definir entidades, tablas y columnas.
* Definir tipos de datos.
* Definir llaves primarias y foráneas.
* Definir restricciones.
* Crear la estructura inicial de `db/`.
* Documentar el diseño y su contribución.

### Víctor Manuel Jiménez Suarez

* Convertir el contrato en migraciones.
* Garantizar la reproducibilidad de las migraciones.
* Implementar la estrategia de idempotencia.
* Crear el seed sintético.
* Probar la creación de la base desde cero.
* Comprobar la ejecución repetida del seed.
* Documentar su contribución.

### Angelica Arlett Santiago Serrano

* Crear el caso normal.
* Crear el primer caso límite.
* Crear el segundo caso límite.
* Crear el fallo declarado.
* Automatizar las pruebas.
* Comprobar las restricciones.
* Integrar las pruebas con `make verify`.
* Generar los artefactos.
* Documentar su contribución.

La asignación anterior indica quién lidera cada parte, pero los tres integrantes deberán revisar el resultado final.

## Revisión conjunta

Nicolás David Juarez Mendoza, Víctor Manuel Jiménez Suarez y Angelica Arlett Santiago Serrano deberán revisar:

* El contrato SQL.
* La representación de la telemetría.
* Las relaciones.
* Las cardinalidades.
* Los tipos de datos.
* Las llaves primarias.
* Las llaves foráneas.
* Las restricciones.
* Los rangos permitidos.
* Las migraciones.
* El seed.
* Las pruebas.
* Los comandos Make.
* Los artefactos.
* La evidencia.
* La ausencia de secretos.

Cualquier modificación al esquema deberá actualizar:

1. `docs/ADR-001-data-contract.md`.
2. `db/schema/telemetry-contract.sql`.
3. Las migraciones correspondientes.
4. El seed, cuando resulte afectado.
5. Las pruebas afectadas.
6. La documentación relacionada.

## Integración final

Al finalizar M01, los tres integrantes deberán comprobar conjuntamente:

```bash
make setup
make verify
make run
```

La integración se considerará completa cuando:

* PostgreSQL pueda levantarse correctamente.
* Las migraciones creen la base desde cero.
* Una segunda ejecución no dañe la base.
* El seed se cargue sin generar duplicados.
* Las cuatro pruebas produzcan los resultados esperados.
* `make verify` termine sin errores.
* Se genere un resultado legible por una máquina dentro de `artifacts/`.
* `evidence/m01-data-contract.json` contenga información válida.
* No existan secretos en el repositorio.
* El tag `week-01-final` corresponda al SHA entregado.
