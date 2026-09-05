# ADR-002 — Selección de Python para M01

## Estado

Propuesto para revisión y aprobación de los tres integrantes:

* Nicolás David Juarez Mendoza.
* Víctor Manuel Jiménez Suarez.
* Angelica Arlett Santiago Serrano.

## Contexto

El hito M01 requiere definir un contrato de datos de telemetría y levantar una base de datos relacional compatible con un entorno cloud.

La solución debe incluir:

* Migraciones reproducibles e idempotentes.
* Seed con datos completamente sintéticos.
* Pruebas automáticas.
* Un caso normal.
* Dos casos límite.
* Un fallo declarado.
* Resultados legibles por una máquina.
* Evidencia en formato JSON.
* Integración con PostgreSQL.
* Ejecución local mediante Docker Compose.
* Automatización mediante `make setup`, `make verify` y `make run`.

El equipo necesita seleccionar un lenguaje que permita automatizar estas tareas sin agregar complejidad innecesaria y que pueda ejecutarse tanto localmente como en integración continua.

## Decisión

El equipo utilizará Python 3 como lenguaje principal para:

* Automatizar la ejecución de las migraciones.
* Cargar el seed sintético.
* Implementar las pruebas automáticas.
* Validar los resultados.
* Generar artefactos y evidencias.
* Leer la configuración desde variables de entorno.
* Integrar las operaciones con el Makefile.

El esquema y las restricciones de la base de datos continuarán expresándose en PostgreSQL mediante archivos SQL versionados.

Python se encargará de ejecutar, comprobar y automatizar dichos archivos cuando corresponda.

PostgreSQL será la base de datos relacional y Docker Compose proporcionará el entorno local reproducible.

## ¿Por qué Python?

Python fue seleccionado por las siguientes razones:

1. Permite crear scripts de automatización con una cantidad reducida de código.
2. Cuenta con librerías para conectarse de forma segura a PostgreSQL.
3. Facilita la creación y ejecución de pruebas automáticas.
4. Incluye soporte para generar y validar archivos JSON.
5. Puede ejecutarse en Linux, Windows mediante WSL y GitHub Actions.
6. Puede integrarse directamente con los comandos del Makefile.
7. Permite leer la configuración desde variables de entorno.
8. No requiere desarrollar una aplicación web completa para resolver M01.
9. Es adecuado para automatizar migraciones, seed, verificaciones y evidencias.
10. Tiene una curva de aprendizaje apropiada para el alcance del proyecto.
11. Permite separar la lógica de automatización del contrato SQL.
12. Facilita el manejo controlado de errores y códigos de salida.

## Necesidades de M01 cubiertas por Python

| Necesidad                  | Uso de Python                                               |
| -------------------------- | ----------------------------------------------------------- |
| Conexión con PostgreSQL    | Uso de una librería compatible con PostgreSQL               |
| Migraciones                | Ejecución ordenada de archivos SQL versionados              |
| Seed sintético             | Script con inserciones controladas                          |
| Idempotencia               | Consultas con identificadores únicos y manejo de conflictos |
| Pruebas automáticas        | Ejecución de pruebas mediante Pytest                        |
| Caso normal                | Prueba con una lectura ambiental válida                     |
| Casos límite               | Pruebas con valores permitidos en los extremos              |
| Fallo declarado            | Comprobación del rechazo de un dato inválido                |
| Resultado machine-readable | Generación de archivos JSON                                 |
| Evidencia                  | Uso de la biblioteca estándar `json`                        |
| Automatización             | Ejecución de scripts desde el Makefile                      |
| Variables de entorno       | Lectura de configuración sin incluir secretos en el código  |
| Integración continua       | Ejecución de pruebas en GitHub Actions                      |
| Manejo de errores          | Excepciones y códigos de salida controlados                 |

## Herramientas previstas

El equipo podrá utilizar:

* Python 3.
* Pytest para las pruebas automáticas.
* Psycopg para la conexión con PostgreSQL.
* Archivos SQL versionados para las migraciones.
* Scripts Python para ejecutar las migraciones y el seed.
* La biblioteca estándar `json` para generar artefactos y evidencia.
* Docker Compose para ejecutar PostgreSQL localmente.
* Make para estandarizar los comandos.
* GitHub Actions para comprobar el proyecto automáticamente.

Las dependencias deberán declararse en un archivo como `requirements.txt`.

Cuando sea posible, las versiones deberán fijarse para mejorar la reproducibilidad.

No deberán instalarse dependencias manualmente sin documentarlas.

## Alternativas consideradas

### Node.js

Node.js permite conectarse a PostgreSQL, ejecutar scripts y crear pruebas automáticas.

También ofrece un ecosistema amplio para desarrollar aplicaciones web y servicios.

Se descartó para M01 porque Python permite mantener los scripts de migración, seed, pruebas y evidencia con una estructura pequeña y directa.

Node.js continúa siendo una alternativa válida para una aplicación web futura, pero no fue seleccionado para este hito.

### Bash y SQL sin un lenguaje adicional

Se consideró utilizar únicamente scripts Bash y archivos SQL.

Se descartó como solución principal porque:

* El manejo de errores puede ser menos claro.
* Las pruebas automáticas serían más difíciles de organizar y mantener.
* La generación de resultados JSON requeriría herramientas adicionales.
* Puede presentar diferencias de ejecución entre Windows y Linux.
* La lógica necesaria para comprobar el seed idempotente sería más difícil de estructurar.
* El control de excepciones de PostgreSQL sería menos legible.

Bash podrá utilizarse como apoyo para ejecutar comandos, pero no será el lenguaje principal de las pruebas y la generación de evidencia.

### Java

Java ofrece herramientas maduras para trabajar con bases de datos, migraciones y pruebas automáticas.

Se descartó porque requiere mayor configuración, estructura y tiempo de preparación para un hito pequeño enfocado principalmente en el contrato de datos.

### Ejecución manual con una herramienta gráfica

Se consideró crear las tablas y cargar los datos manualmente mediante una interfaz gráfica de PostgreSQL.

Se descartó porque:

* No sería reproducible.
* No podría automatizarse.
* No sería apropiado para GitHub Actions.
* No permitiría verificar fácilmente la creación desde cero.
* Dependería de acciones manuales realizadas por una persona.
* No cumpliría el objetivo de ejecutar el proyecto mediante Make.

## Compatibilidad con cloud

Python no dependerá de una instalación local específica de PostgreSQL.

La configuración se obtendrá mediante variables de entorno, por lo que la solución podrá conectarse a:

* PostgreSQL ejecutado mediante Docker Compose.
* Un servicio PostgreSQL disponible en AWS Academy Learner Lab, cuando esté habilitado.

El código no deberá incluir:

* Usuarios reales.
* Contraseñas reales.
* Tokens.
* Credenciales de AWS.
* Datos personales.
* Cadenas de conexión reales.
* Información proveniente de ambientes de producción.

Los archivos de ejemplo únicamente contendrán valores públicos, sintéticos o marcadores de posición.

## Consecuencias positivas

* Scripts pequeños y legibles.
* Pruebas automáticas fáciles de ejecutar.
* Generación directa de archivos JSON.
* Integración sencilla con PostgreSQL.
* Compatibilidad con GitHub Actions.
* Ejecución estandarizada mediante Make.
* Menor configuración para el alcance de M01.
* Manejo claro de errores y resultados.
* Separación entre el contrato SQL y la automatización.
* Posibilidad de reutilizar funciones entre migraciones, seed y pruebas.

## Consecuencias negativas

* Será necesario instalar las dependencias de Python.
* Las versiones deberán controlarse para mantener la reproducibilidad.
* Los tres integrantes deberán utilizar la misma estructura y convenciones.
* El proyecto deberá controlar correctamente el entorno virtual.
* Una versión no compatible de Python podría provocar diferencias entre equipos.
* El equipo deberá evitar colocar credenciales directamente en los scripts.

## Reglas de implementación

* Utilizar Python 3.
* Declarar las dependencias del proyecto.
* Utilizar un entorno virtual cuando corresponda.
* Leer la configuración mediante variables de entorno.
* No guardar credenciales reales.
* Mantener el contrato relacional en archivos SQL versionados.
* Ejecutar las pruebas desde `make verify`.
* Generar evidencia en un formato legible por una máquina.
* Mantener los datos completamente sintéticos.
* Comprobar que la solución funcione desde una base vacía.
* Comprobar la ejecución repetida de las migraciones.
* Comprobar la ejecución repetida del seed.
* Devolver códigos de salida diferentes de cero cuando una verificación falle.
* No ocultar errores inesperados durante las pruebas.

## Revisión del equipo

Nicolás David Juarez Mendoza, Víctor Manuel Jiménez Suarez y Angelica Arlett Santiago Serrano deberán comprobar:

* Que Python cubra las necesidades de M01.
* Que las alternativas evaluadas estén correctamente explicadas.
* Que el código pueda ejecutarse mediante Make.
* Que no existan secretos en el repositorio.
* Que el entorno sea reproducible.
* Que el contrato pueda implementarse con PostgreSQL.
* Que las dependencias estén documentadas.
* Que la solución pueda ejecutarse desde una base vacía.
* Que los resultados puedan almacenarse en formato JSON.

## Aprobación

| Integrante                       | Responsabilidad en la revisión                          | Estado    |
| -------------------------------- | ------------------------------------------------------- | --------- |
| Nicolás David Juarez Mendoza     | Validar requisitos, contrato, entidades y esquema       | Pendiente |
| Víctor Manuel Jiménez Suarez     | Validar migraciones, idempotencia y seed                | Pendiente |
| Angelica Arlett Santiago Serrano | Validar pruebas, automatización, artefactos y evidencia | Pendiente |

El estado del ADR cambiará de `Propuesto` a `Aceptado` cuando los tres integrantes hayan revisado y aprobado la decisión.

Cuando se obtenga la aprobación, deberá actualizarse:

* El estado general del ADR.
* El estado de cada integrante en la tabla.
* Cualquier observación acordada por el equipo.

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
* La evidencia.
* La ausencia de secretos.
* El tag `week-01-final`.
* El SHA exacto entregado.

Que un integrante implemente una parte no elimina la responsabilidad de los demás de revisar el resultado final.

## Resultado de la decisión

Python 3 será el lenguaje principal utilizado para automatizar el trabajo de M01.

PostgreSQL y los archivos SQL versionados continuarán siendo responsables de definir y aplicar el esquema relacional.

La decisión busca cumplir los requisitos de manera clara, reproducible y verificable, sin desarrollar componentes fuera del alcance del hito.
