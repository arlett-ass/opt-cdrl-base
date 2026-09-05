# Contribución individual — Nicolás David Juarez Mendoza

## Integrante

* Nombre: Nicolás David Juarez Mendoza
* Rama de trabajo: `feat/data-contract-david`
* Área principal: análisis y diseño del contrato de datos
* Hito: M01 — Contrato de datos y entorno reproducible

## Objetivo de la contribución

Definir una propuesta clara, documentada y verificable para almacenar telemetría ambiental IoT en PostgreSQL.

El diseño servirá como fuente para que Víctor Manuel Jiménez Suarez implemente las migraciones y el seed, y para que Angelica Arlett Santiago Serrano implemente las pruebas automáticas y la generación de artefactos.

## Tareas asignadas

1. Analizar los requisitos de M01.
2. Identificar las entidades de telemetría.
3. Definir el contrato de datos.
4. Definir las tablas.
5. Definir las columnas y sus tipos.
6. Definir las llaves primarias y foráneas.
7. Definir las restricciones.
8. Crear la estructura inicial de `db/`.
9. Documentar la contribución individual.

## Trabajo realizado

### Análisis de requisitos

Se analizaron las indicaciones de M01 y se identificaron los siguientes requisitos principales:

* Base de datos relacional compatible con cloud.
* Migraciones reproducibles e idempotentes.
* Seed con datos completamente sintéticos.
* Un caso normal.
* Dos casos límite.
* Un fallo declarado.
* Resultado legible por una máquina.
* Evidencia técnica en formato JSON.
* Automatización mediante Make.
* Ejecución local mediante Docker Compose.
* Uso de AWS Academy Learner Lab cuando esté habilitado.
* Prohibición de almacenar credenciales, tokens, datos personales y cadenas de conexión reales.
* Entrega de la URL del repositorio, tag final, SHA exacto, salida de `make verify` y archivo de evidencia.

El análisis fue documentado en:

```text
docs/M01-requirements.md
```

### Selección del contexto

Se seleccionó un escenario genérico de telemetría ambiental IoT.

Las métricas definidas son:

* Temperatura en grados Celsius.
* Humedad relativa en porcentaje.
* Concentración de CO2 en partes por millón.

Todos los datos utilizados para el seed, las pruebas y las evidencias serán completamente sintéticos.

### Entidades identificadas

Se definieron tres entidades principales:

1. `locations`
2. `devices`
3. `telemetry_readings`

Las relaciones definidas son:

* Una ubicación puede tener varios dispositivos.
* Cada dispositivo debe pertenecer a una ubicación existente.
* Un dispositivo puede generar múltiples lecturas.
* Cada lectura debe pertenecer a un dispositivo existente.

La cardinalidad general es:

```text
locations 1 ───── N devices 1 ───── N telemetry_readings
```

### Contrato definido

Se establecieron los siguientes elementos del contrato:

* Campos obligatorios.
* Tipos de datos de PostgreSQL.
* Llaves primarias.
* Llaves foráneas.
* Relaciones entre entidades.
* Rangos ambientales.
* Rangos geográficos.
* Estados permitidos para los dispositivos.
* Reglas de unicidad.
* Reglas para las fechas.
* Integridad referencial.
* Reglas para rechazar información inválida.
* Índices para apoyar las consultas y relaciones.

La decisión fue documentada en:

```text
docs/ADR-001-data-contract.md
```

### Tablas y columnas

Se definieron las siguientes tablas:

* `locations`
* `devices`
* `telemetry_readings`

Cada tabla incluye, cuando corresponde:

* Llave primaria.
* Columnas obligatorias.
* Tipos de datos.
* Valores predeterminados.
* Restricciones.
* Llaves foráneas.
* Reglas de unicidad.
* Índices.

### Llaves primarias y foráneas

Se definieron las siguientes llaves primarias:

* `locations.id`
* `devices.id`
* `telemetry_readings.id`

Se definieron las siguientes llaves foráneas:

* `devices.location_id` referencia `locations.id`.
* `telemetry_readings.device_id` referencia `devices.id`.

Las relaciones utilizan:

* `ON UPDATE CASCADE`
* `ON DELETE RESTRICT`

`ON UPDATE CASCADE` permite mantener actualizadas las referencias relacionadas.

`ON DELETE RESTRICT` evita eliminar ubicaciones que todavía tengan dispositivos o dispositivos que todavía tengan lecturas.

### Restricciones definidas

Se incluyeron restricciones para:

* Códigos únicos.
* Campos obligatorios.
* Campos de texto no vacíos.
* Estados permitidos para los dispositivos.
* Rangos de temperatura.
* Rangos de humedad.
* Rangos de CO2.
* Rangos de latitud.
* Rangos de longitud.
* Orden lógico entre la fecha de medición y la fecha de recepción.
* Prevención de lecturas duplicadas para un mismo dispositivo y momento.
* Integridad referencial entre ubicaciones, dispositivos y lecturas.

Los rangos ambientales definidos son:

| Dato        | Valor mínimo |   Valor máximo |
| ----------- | -----------: | -------------: |
| Temperatura |  `-50.00 °C` |     `80.00 °C` |
| Humedad     |     `0.00 %` |     `100.00 %` |
| CO2         |   `0.00 ppm` | `10000.00 ppm` |
| Latitud     |        `-90` |           `90` |
| Longitud    |       `-180` |          `180` |

### Estructura inicial de `db/`

Se creó el archivo:

```text
db/schema/telemetry-contract.sql
```

Este archivo contiene el contrato SQL que Víctor Manuel Jiménez Suarez utilizará como referencia para crear las migraciones.

También se creó:

```text
db/README.md
```

Este documento explica:

* La estructura del directorio.
* El orden de creación de las tablas.
* Las relaciones.
* Las restricciones.
* Los rangos permitidos.
* La estrategia esperada de idempotencia.
* El traspaso hacia las migraciones.
* El traspaso hacia el seed.
* Los casos de prueba esperados.
* Las responsabilidades de los integrantes.

### ADR de Python

Se colaboró en la propuesta inicial del ADR para utilizar Python como lenguaje principal de automatización de M01.

El documento se encuentra en:

```text
docs/ADR-002-python.md
```

El ADR explica:

* Por qué se propone utilizar Python.
* Qué necesidades de M01 cubre.
* Qué herramientas podrán utilizarse.
* Qué alternativas fueron consideradas.
* Por qué se descartaron las alternativas.
* Las consecuencias positivas y negativas.
* Las reglas de implementación.
* La necesidad de aprobación conjunta.

La decisión deberá ser revisada y aceptada por:

* Nicolás David Juarez Mendoza.
* Víctor Manuel Jiménez Suarez.
* Angelica Arlett Santiago Serrano.

## Archivos creados

Durante esta contribución se crearon los siguientes archivos:

* `docs/M01-requirements.md`
* `docs/ADR-001-data-contract.md`
* `docs/ADR-002-python.md`
* `db/README.md`
* `db/schema/telemetry-contract.sql`
* `docs/contributions/nicolas-david.md`
* `.gitattributes`

El archivo `.gitattributes` se agregó para mantener finales de línea compatibles con Linux en scripts, archivos Python, SQL, YAML y el Makefile.

## Decisiones principales

Las principales decisiones propuestas fueron:

* Utilizar PostgreSQL como base de datos relacional.
* Utilizar Python para automatización, pruebas y evidencia.
* Utilizar tres entidades relacionadas.
* Utilizar `BIGINT GENERATED ALWAYS AS IDENTITY` para las llaves primarias.
* Utilizar `TIMESTAMPTZ` para las fechas y horas.
* Utilizar `NUMERIC` para las mediciones ambientales.
* Aplicar las restricciones directamente desde PostgreSQL.
* Mantener las migraciones como archivos versionados.
* Evitar modelos JSON o EAV para el alcance de M01.
* Utilizar datos completamente sintéticos.
* No almacenar credenciales ni información personal.
* Utilizar variables de entorno para la configuración.
* Utilizar Docker Compose como respaldo local reproducible.

## Casos de prueba derivados del contrato

El contrato permite implementar los siguientes casos:

### Caso normal

* Temperatura: `24.00 °C`
* Humedad: `50.00 %`
* CO2: `500.00 ppm`

Resultado esperado: PostgreSQL acepta y almacena la lectura.

### Caso límite inferior

* Humedad: `0.00 %`

Resultado esperado: PostgreSQL acepta el valor porque corresponde al límite inferior permitido.

### Caso límite superior

* Humedad: `100.00 %`

Resultado esperado: PostgreSQL acepta el valor porque corresponde al límite superior permitido.

### Fallo declarado

* Humedad: `101.00 %`

Resultado esperado: PostgreSQL rechaza el registro porque supera el límite permitido.

La prueba del fallo declarado deberá considerarse exitosa cuando la base de datos rechace correctamente el dato inválido.

## Traspaso hacia Víctor Manuel Jiménez Suarez

Víctor Manuel Jiménez Suarez deberá utilizar los siguientes archivos:

* `docs/M01-requirements.md`
* `docs/ADR-001-data-contract.md`
* `db/schema/telemetry-contract.sql`
* `db/README.md`

Con estos archivos podrá:

* Crear las migraciones.
* Definir el orden de ejecución.
* Registrar las migraciones aplicadas.
* Implementar la estrategia de idempotencia.
* Crear el seed sintético.
* Comprobar la creación de la base desde cero.
* Comprobar que el seed no genere duplicados.

No deberá cambiar nombres, tablas, columnas, tipos, relaciones o restricciones sin comunicarlo al equipo.

Si necesita modificar el contrato, el cambio deberá revisarse conjuntamente y reflejarse en:

1. `docs/ADR-001-data-contract.md`
2. `db/schema/telemetry-contract.sql`
3. Las migraciones.
4. El seed, cuando resulte afectado.
5. Las pruebas relacionadas.
6. La documentación correspondiente.

## Traspaso hacia Angelica Arlett Santiago Serrano

Angelica Arlett Santiago Serrano podrá utilizar los casos definidos en el contrato:

1. Caso normal con humedad de `50.00 %`.
2. Caso límite inferior con humedad de `0.00 %`.
3. Caso límite superior con humedad de `100.00 %`.
4. Fallo declarado con humedad de `101.00 %`.

Las pruebas deberán comprobar directamente las restricciones de PostgreSQL.

También deberá:

* Automatizar las cuatro pruebas.
* Integrarlas con `make verify`.
* Generar resultados dentro de `artifacts/`.
* Generar un resultado legible por una máquina.
* Comprobar el comportamiento esperado del fallo declarado.
* Documentar su contribución.

## Revisión pendiente

Antes de aceptar el contrato, Víctor Manuel Jiménez Suarez y Angelica Arlett Santiago Serrano deberán revisar junto con Nicolás David Juarez Mendoza:

* Si las entidades representan correctamente la telemetría.
* Si las relaciones tienen sentido.
* Si las cardinalidades son correctas.
* Si los tipos de datos son adecuados.
* Si las llaves primarias y foráneas están correctamente definidas.
* Si las restricciones corresponden al contrato.
* Si los rangos son apropiados.
* Si las migraciones pueden implementarse de manera reproducible.
* Si el seed puede ser idempotente.
* Si los casos de prueba pueden automatizarse.
* Si Python cubre las necesidades del hito.
* Si las alternativas del ADR fueron explicadas correctamente.

## Integración final compartida

Nicolás David Juarez Mendoza, Víctor Manuel Jiménez Suarez y Angelica Arlett Santiago Serrano deberán ejecutar y comprobar conjuntamente:

```bash
make setup
make verify
make run
```

También deberán revisar:

* El esquema final.
* Las migraciones.
* El seed.
* Las pruebas automáticas.
* Los artefactos.
* El archivo `evidence/m01-data-contract.json`.
* La ausencia de secretos.
* La documentación.
* El tag `week-01-final`.
* El SHA exacto de la entrega.
* La salida final de `make verify`.

La asignación de tareas indica quién lidera cada parte, pero no elimina la responsabilidad de los tres integrantes de revisar e integrar el resultado final.

## Estado de la contribución

La propuesta inicial del contrato y su documentación se encuentran completas dentro de la rama:

```text
feat/data-contract-david
```

La aceptación del contrato, las migraciones, el seed, las pruebas y la integración final permanecen pendientes de revisión y aprobación del equipo.

Después de la aprobación deberán actualizarse los estados de los ADR correspondientes antes de crear el tag final.
