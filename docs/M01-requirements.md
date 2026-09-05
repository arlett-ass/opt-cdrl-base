# Análisis de requisitos — M01 Contrato de datos y entorno reproducible

## 1. Objetivo

Definir un contrato de datos para telemetría ambiental IoT y levantar una base de datos relacional compatible con un entorno cloud.

La solución deberá utilizar migraciones y datos semilla reproducibles. Además, deberá poder prepararse, verificarse y ejecutarse mediante los siguientes comandos:

```bash
make setup
make verify
make run
```

## 2. Alcance

El sistema almacenará información completamente sintética relacionada con:

* Ubicaciones monitoreadas.
* Dispositivos IoT instalados en cada ubicación.
* Lecturas ambientales generadas por los dispositivos.

Las métricas ambientales consideradas serán:

* Temperatura, expresada en grados Celsius.
* Humedad relativa, expresada como porcentaje.
* Concentración de dióxido de carbono, expresada en partes por millón.

La actividad se concentra en el diseño, creación, carga, validación y ejecución reproducible de la base de datos.

No se requiere:

* Autenticación de usuarios.
* Interfaz gráfica.
* Uso de información personal.
* Uso de dispositivos IoT reales.
* Almacenamiento de credenciales o conexiones reales dentro del repositorio.

## 3. Requisitos funcionales

### RF-01. Contrato de datos

El proyecto debe definir claramente:

* Entidades.
* Tablas.
* Columnas.
* Tipos de datos.
* Llaves primarias.
* Llaves foráneas.
* Relaciones.
* Restricciones de integridad.
* Reglas de validación.

El contrato deberá ser suficientemente preciso para que las migraciones, el seed y las pruebas automáticas puedan desarrollarse sin interpretaciones diferentes.

### RF-02. Entidades

El modelo estará compuesto inicialmente por tres entidades:

1. `locations`: representa las ubicaciones monitoreadas.
2. `devices`: representa los dispositivos IoT instalados.
3. `telemetry_readings`: representa las lecturas ambientales enviadas por los dispositivos.

### RF-03. Relaciones

Las relaciones esperadas son:

* Una ubicación puede contener varios dispositivos.
* Cada dispositivo debe pertenecer a una ubicación existente.
* Un dispositivo puede generar múltiples lecturas.
* Cada lectura debe pertenecer a un dispositivo existente.

La cardinalidad general será:

```text
locations 1 ───── N devices 1 ───── N telemetry_readings
```

### RF-04. Base de datos relacional

La información deberá almacenarse en PostgreSQL.

Las relaciones entre las entidades deberán implementarse mediante llaves primarias y foráneas, además de restricciones que protejan la integridad de los datos.

### RF-05. Migraciones

La base de datos deberá poder crearse desde cero mediante migraciones versionadas, reproducibles e idempotentes.

Las migraciones deberán:

* Crear las tablas en el orden correcto.
* Crear las llaves primarias y foráneas.
* Crear las restricciones definidas en el contrato.
* Crear los índices necesarios.
* Poder ejecutarse desde un entorno limpio.
* Evitar que una ejecución repetida dañe el estado de la base.

### RF-06. Seed sintético

El proyecto deberá incluir un seed con información completamente ficticia.

El seed deberá:

* Crear ubicaciones sintéticas.
* Crear dispositivos sintéticos asociados a ubicaciones existentes.
* Crear lecturas sintéticas asociadas a dispositivos existentes.
* Respetar todas las restricciones del contrato.
* Poder ejecutarse repetidamente sin duplicar registros.
* No contener datos personales ni información sensible.

### RF-07. Pruebas automáticas

El proyecto deberá implementar y automatizar al menos cuatro casos de prueba:

1. Un caso normal con datos válidos.
2. Un primer caso límite válido.
3. Un segundo caso límite válido.
4. Un fallo declarado con datos inválidos.

El caso normal deberá comprobar que una lectura válida puede almacenarse correctamente.

Los casos límite deberán comprobar el comportamiento del contrato en valores permitidos ubicados en los extremos de sus rangos.

El fallo declarado deberá comprobar que PostgreSQL rechaza correctamente un dato que viola alguna restricción del contrato.

La prueba del fallo declarado se considerará exitosa cuando la base de datos rechace el registro inválido de la manera esperada.

### RF-08. Automatización con Make

El repositorio deberá proporcionar los siguientes comandos:

#### `make setup`

Deberá preparar las dependencias o configuraciones locales necesarias para trabajar con el proyecto.

#### `make verify`

Deberá ejecutar las validaciones y pruebas automáticas del proyecto.

También deberá producir un resultado legible por una máquina dentro de `artifacts/`.

#### `make run`

Deberá levantar o ejecutar la solución completa, incluyendo la base de datos y los componentes necesarios.

La secuencia final requerida será:

```bash
make setup && make verify && make run
```

### RF-09. Resultado machine-readable

La verificación deberá generar al menos un archivo en formato JSON o XML dentro del directorio `artifacts/`.

Este resultado deberá indicar como mínimo:

* Estado general de la verificación.
* Casos ejecutados.
* Resultado de cada caso.
* Cantidad de pruebas exitosas.
* Cantidad de pruebas fallidas.
* Fecha o momento de ejecución, cuando corresponda.

### RF-10. Evidencia

El archivo `evidence/m01-data-contract.json` deberá contener la evidencia final de la actividad.

Deberá registrar como mínimo:

* Identificación del hito M01.
* Comandos ejecutados.
* Resultado de `make setup`.
* Resultado de `make verify`.
* Resultado de `make run`.
* Resultado de las pruebas.
* Ruta de los artefactos generados.
* Tag final.
* SHA exacto del commit entregado.
* Suposiciones.
* Limitaciones conocidas.

El archivo deberá contener JSON válido y ser legible por una máquina.

### RF-11. Documentación

El proyecto deberá incluir documentación dentro de `docs/` que explique:

* El análisis de requisitos.
* El contrato de datos.
* Las decisiones técnicas.
* La selección de Python.
* Las alternativas evaluadas.
* Las contribuciones de los integrantes.
* Las instrucciones de preparación, verificación y ejecución.

## 4. Requisitos no funcionales

### RNF-01. Reproducibilidad

Una persona deberá poder clonar el repositorio y preparar el proyecto sin realizar cambios manuales en la base de datos.

La estructura de la base, los datos sintéticos y las verificaciones deberán generarse mediante archivos versionados en Git.

### RNF-02. Idempotencia

Ejecutar nuevamente las migraciones y el seed no deberá:

* Duplicar información.
* Eliminar datos inesperadamente.
* Producir un esquema inconsistente.
* Dañar el estado de la base de datos.

### RNF-03. Compatibilidad con cloud

El diseño deberá utilizar características compatibles con PostgreSQL local y con un servicio PostgreSQL que pueda utilizarse desde AWS Academy Learner Lab, si dicho servicio está habilitado.

El desarrollo local utilizará Docker Compose como entorno de respaldo reproducible.

### RNF-04. Seguridad

El repositorio no deberá contener:

* Contraseñas reales.
* Tokens.
* Credenciales de AWS.
* Datos personales.
* Cadenas de conexión reales.
* Archivos `.env` con información sensible.
* Llaves privadas.

Los valores de ejemplo públicos deberán documentarse en `.env.example`.

El archivo `.env` local deberá permanecer excluido mediante `.gitignore`.

### RNF-05. Trazabilidad

Los cambios de cada integrante deberán poder identificarse mediante:

* Ramas.
* Commits.
* Pull requests.
* Historial de Git.
* Documentos de contribución.

### RNF-06. Portabilidad

La solución deberá poder ejecutarse en un equipo diferente mediante instrucciones claras y dependencias declaradas.

No deberá depender de configuraciones manuales que solo existan en el equipo de un integrante.

## 5. Entorno de ejecución

Los entornos contemplados son:

### AWS Academy Learner Lab

Se utilizará cuando esté habilitado y permita ejecutar los recursos necesarios.

No deberán guardarse credenciales de AWS dentro del repositorio.

### Docker Compose

Se utilizará como entorno local reproducible y como respaldo cuando AWS Academy no esté disponible.

Docker Compose deberá levantar PostgreSQL con la configuración necesaria para ejecutar migraciones, seed y pruebas.

### Python

Python será utilizado para automatización, pruebas, validación y generación de artefactos cuando corresponda.

La justificación de esta decisión se documentará en `docs/ADR-002-python.md`.

### Configuración

Los valores públicos de configuración deberán mantenerse en `.env.example`.

Cada integrante podrá crear un archivo `.env` local, pero este archivo no deberá incluirse en Git.

## 6. Entregables

El repositorio final deberá contener:

* Código fuente.
* Configuración.
* Scripts.
* Docker Compose.
* Migraciones de base de datos.
* Seed sintético.
* Pruebas automáticas.
* Un caso normal.
* Dos casos límite.
* Un fallo declarado.
* Reporte o ADR dentro de `docs/`.
* Resultado machine-readable dentro de `artifacts/`.
* Archivo `evidence/m01-data-contract.json`.
* Instrucciones de ejecución.
* Tag `week-01-final`.
* SHA exacto de la versión entregada.
* Salida final de `make verify`.

En Google Classroom deberán entregarse:

* URL del repositorio del equipo.
* Tag `week-01-final`.
* SHA exacto.
* Salida de `make verify`.
* Archivo de evidencia.

## 7. Distribución de responsabilidades

### Nicolás David Juarez Mendoza

Responsabilidades asignadas:

* Analizar los requisitos de M01.
* Identificar las entidades de telemetría.
* Definir el contrato de datos.
* Definir las tablas.
* Definir las columnas y sus tipos.
* Definir las llaves primarias y foráneas.
* Definir las restricciones.
* Crear la estructura inicial de `db/`.
* Documentar su contribución.

Archivos principales de su propuesta:

* `docs/M01-requirements.md`
* `docs/ADR-001-data-contract.md`
* `db/README.md`
* `db/schema/telemetry-contract.sql`
* `docs/contributions/nicolas-david.md`

### Víctor Manuel Jiménez Suarez

Responsabilidades asignadas:

* Tomar como base el contrato definido por Nicolás David Juarez Mendoza.
* Convertir el contrato en migraciones.
* Garantizar que las migraciones sean reproducibles e idempotentes.
* Crear el seed sintético.
* Comprobar la creación de la base de datos desde cero.
* Comprobar la carga repetida del seed.
* Documentar su contribución.

### Angelica Arlett Santiago Serrano

Responsabilidades asignadas:

* Diseñar el caso normal.
* Diseñar el primer caso límite.
* Diseñar el segundo caso límite.
* Diseñar el fallo declarado.
* Automatizar las pruebas.
* Integrar las pruebas con `make verify`.
* Generar los resultados dentro de `artifacts/`.
* Comprobar `make setup`.
* Comprobar `make verify`.
* Comprobar `make run`.
* Documentar su contribución.

La distribución anterior indica quién lidera cada parte, pero no elimina la responsabilidad conjunta de revisar e integrar el resultado final.

## 8. Criterios de aceptación

La actividad se considerará completa cuando:

1. El contrato defina entidades, tablas, columnas, tipos, llaves y restricciones.
2. PostgreSQL pueda levantarse mediante Docker Compose.
3. Las migraciones puedan crear la base desde cero.
4. Las migraciones puedan volver a ejecutarse sin dañar la base.
5. El seed pueda ejecutarse más de una vez sin duplicar información.
6. Las relaciones entre ubicaciones, dispositivos y lecturas funcionen correctamente.
7. El caso normal sea exitoso.
8. El primer caso límite sea exitoso.
9. El segundo caso límite sea exitoso.
10. El fallo declarado sea rechazado por la base de datos.
11. `make setup` termine sin errores.
12. `make verify` termine sin errores.
13. `make run` termine sin errores.
14. Se genere un resultado machine-readable dentro de `artifacts/`.
15. `evidence/m01-data-contract.json` sea JSON válido y contenga la evidencia solicitada.
16. No existan secretos ni información personal en el repositorio.
17. Los tres integrantes hayan revisado el contrato y los ADR.
18. El tag `week-01-final` corresponda a la versión verificada.
19. El SHA entregado corresponda exactamente al commit etiquetado.
20. La URL del repositorio permita al docente revisar el proyecto.

## 9. Suposiciones

Para el desarrollo inicial se establecen las siguientes suposiciones:

* La telemetría será ambiental.
* Todos los datos utilizados serán sintéticos.
* Cada dispositivo pertenecerá a una ubicación.
* Cada lectura pertenecerá a un dispositivo existente.
* Las fechas y horas se almacenarán con zona horaria.
* PostgreSQL será el sistema gestor relacional.
* Docker Compose será el entorno local reproducible.
* AWS Academy será utilizado únicamente si está habilitado.
* Las métricas iniciales serán temperatura, humedad y dióxido de carbono.
* Python será utilizado para automatización y pruebas, sujeto a la aprobación conjunta del equipo.

## 10. Limitaciones iniciales

* La disponibilidad de AWS Academy depende de los servicios habilitados en Learner Lab.
* El alcance inicial no incluye autenticación de usuarios.
* El alcance inicial no incluye una interfaz gráfica.
* El alcance inicial no incluye información obtenida de sensores reales.
* Las métricas se limitan inicialmente a temperatura, humedad y dióxido de carbono.
* El proyecto no contempla procesamiento de telemetría en tiempo real.
* El proyecto no contempla análisis predictivo.
* Docker Desktop requiere que WSL 2 y la virtualización estén habilitados en Windows.
* Las decisiones propuestas deberán validarse con los demás integrantes antes de considerarse definitivas.

## 11. Revisión e integración conjunta

Las siguientes actividades serán responsabilidad compartida de Nicolás David Juarez Mendoza, Víctor Manuel Jiménez Suarez y Angelica Arlett Santiago Serrano.

### Revisión del contrato

Los tres integrantes deberán revisar:

* Si el esquema representa correctamente la telemetría ambiental.
* Si las relaciones entre entidades tienen sentido.
* Si las cardinalidades son correctas.
* Si los tipos de datos son adecuados.
* Si las llaves primarias y foráneas están correctamente definidas.
* Si las restricciones corresponden al contrato.
* Si los rangos de valores son razonables.
* Si el esquema puede convertirse en migraciones reproducibles.
* Si el seed puede respetar las reglas definidas.
* Si los casos de prueba pueden comprobar las restricciones.

El contrato permanecerá en estado `Propuesto` hasta que los tres integrantes lo revisen y aprueben.

### ADR de Python

Aunque una persona redacte la propuesta inicial, Nicolás David Juarez Mendoza, Víctor Manuel Jiménez Suarez y Angelica Arlett Santiago Serrano deberán acordar:

* La selección de Python.
* Las necesidades de M01 que cubre.
* Las alternativas consideradas.
* Las razones para descartar esas alternativas.
* Las ventajas de utilizar Python.
* Las consecuencias y posibles desventajas de la decisión.

La decisión estará documentada en `docs/ADR-002-python.md` y permanecerá en estado `Propuesto` hasta recibir la aprobación del equipo.

### Integración final

Nicolás David Juarez Mendoza, Víctor Manuel Jiménez Suarez y Angelica Arlett Santiago Serrano deberán comprobar conjuntamente la ejecución de:

```bash
make setup
make verify
make run
```

También deberán revisar en conjunto:

* Migraciones.
* Seed sintético.
* Pruebas automáticas.
* Resultado machine-readable.
* Archivos dentro de `artifacts/`.
* Archivo `evidence/m01-data-contract.json`.
* Ausencia de secretos.
* Documentación.
* Tag `week-01-final`.
* SHA exacto de la entrega.

Que un integrante automatice o ejecute inicialmente un comando no elimina la responsabilidad de los demás de revisar y comprobar el resultado final.

## 12. Condiciones de entrega

El trabajo deberá realizarse únicamente en el repositorio GitHub creado por el equipo, integrado por:

* Nicolás David Juarez Mendoza.
* Víctor Manuel Jiménez Suarez.
* Angelica Arlett Santiago Serrano.

Antes de crear el tag final deberán cumplirse estas condiciones:

1. Todos los cambios deberán estar integrados en la rama principal.
2. El repositorio deberá encontrarse en un estado limpio.
3. Los tres comandos requeridos deberán ejecutarse correctamente.
4. La evidencia deberá corresponder al commit definitivo.
5. El tag deberá crearse sobre el mismo commit identificado por el SHA entregado.
6. Los tres integrantes deberán estar de acuerdo con el contrato y las decisiones documentadas.

No se deberán realizar cambios adicionales al commit etiquetado sin actualizar nuevamente la evidencia, el tag y el SHA de la entrega.

La entrega deberá realizarse antes de la fecha y hora establecidas en Google Classroom. Los trabajos entregados después del cierre no serán aceptados.
