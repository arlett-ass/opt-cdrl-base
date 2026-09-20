# ADR-003 Seguridad Relacional y Minimo Privilegio

## Estado

Aceptado.

## Contexto

M03 agrega una capa de seguridad sobre el modelo relacional construido en M01 y M02. La base debe separar las responsabilidades de migración, escritura, lectura y operación, y las credenciales deben permanecer fuera del repositorio.

La configuración anterior contenía una contraseña de desarrollo como valor por defecto. Aunque era sintética, seguía siendo una credencial funcional embebida en archivos versionados y permitía iniciar el entorno sin declarar explícitamente el secreto.

## Decisión

Adoptamos cuatro roles de PostgreSQL con responsabilidades separadas:

| Rol | Responsabilidad |
| --- | --- |
| `cdrl_migrator` | Administrar la estructura necesaria para migraciones controladas. |
| `cdrl_writer` | Insertar nuevas lecturas de telemetría. |
| `cdrl_reader` | Consultar tablas y la vista relacional. |
| `cdrl_operator` | Modificar únicamente el estado de los dispositivos. |

Los roles se crean como `NOLOGIN` porque representan conjuntos de privilegios y no credenciales de acceso independientes.
La política de permisos se implementa en `db/migrations/003_security_roles.sql`. Las pruebas automatizadas de acceso permitido y denegado se integrarán mediante `tests/test_m03_security.py` y `scripts/verify_m03.sh`.

### Política de mínimo privilegio

Los cuatro roles reciben `USAGE` sobre el esquema `public` y permiso `SELECT` sobre:

- `locations`
- `devices`
- `telemetry_readings`
- `v_telemetry_context`

`cdrl_writer` recibe adicionalmente permiso `INSERT` sobre `telemetry_readings`.

Debido a que `telemetry_readings.id` utiliza una secuencia para generar identificadores, `cdrl_writer` recibe también `USAGE` sobre esa secuencia. Esto permite insertar nuevas lecturas sin otorgar permisos estructurales adicionales.

`cdrl_operator` recibe únicamente:

`UPDATE (status)` sobre `devices`.

De esta forma, el operador puede modificar el estado operativo de un dispositivo sin recibir autorización para modificar otras columnas.

`cdrl_migrator` representa el rol estructural y conserva la propiedad de las tablas, la vista y la secuencia utilizadas por el modelo.

Antes de aplicar los permisos específicos se eliminan privilegios anteriores mediante `REVOKE`, evitando depender de permisos implícitos o configuraciones previas.


## Manejo de secretos

Las credenciales se reciben únicamente mediante variables de entorno. `rebuild.py`, `db/seed/seed.py`, `db/queries/demo.py` y las pruebas de contrato requieren `POSTGRES_PASSWORD` y no contienen una contraseña alternativa.

`.env.example` contiene la variable vacía como guía de configuración, pero no contiene una credencial utilizable. Los archivos `.env`, `.env.local` y otros archivos de entorno quedan ignorados por Git, mientras que `.env.example` permanece versionado como plantilla.

Docker Compose mantiene sus valores no sensibles por defecto, pero exige `POSTGRES_PASSWORD` mediante interpolación obligatoria. Si la variable no está definida, el servicio no debe iniciar.

### Rotación de credenciales

El procedimiento definido para rotar una credencial es:

1. Generar una credencial nueva fuera del repositorio y almacenarla mediante el mecanismo seguro disponible.
2. Actualizar la credencial correspondiente en PostgreSQL.
3. Actualizar `POSTGRES_PASSWORD` únicamente en el entorno local, AWS Academy Learner Lab o el servicio seguro utilizado.
4. Reiniciar o reconectar los componentes que utilizan la credencial.
5. Ejecutar `make verify` para comprobar que el sistema continúa funcionando.
6. Confirmar que la credencial anterior dejó de ser válida.
7. Evitar registrar credenciales anteriores o nuevas en Git, artifacts, evidence o mensajes de commit.

La rotación no requiere modificar el código fuente porque la aplicación obtiene la credencial desde el entorno.

### Pruebas de seguridad

Se creó `tests/test_m03_security.py` con los cuatro escenarios requeridos para la entrega.

1. Caso normal: `cdrl_reader` ejecuta una consulta sobre `v_telemetry_context` y PostgreSQL permite la operación.

2. Caso límite 1: `cdrl_writer` inserta una lectura válida en `telemetry_readings`. La prueba también comprueba indirectamente que el rol puede utilizar la secuencia necesaria para generar el identificador de la lectura.

3. Caso límite 2: `cdrl_operator` modifica el campo `status` de un dispositivo existente, demostrando el funcionamiento del permiso de actualización limitado a esa columna.

4. Fallo declarado: `cdrl_reader` intenta insertar una lectura cuyos datos cumplen el contrato relacional. PostgreSQL rechaza la operación mediante `psycopg2.errors.InsufficientPrivilege` y SQLSTATE `42501`.

En el fallo declarado se utilizan datos válidos para evitar que la operación sea rechazada por una restricción `CHECK`, `FOREIGN KEY`, `UNIQUE` o `NOT NULL`. De esta forma, el rechazo demuestra específicamente el funcionamiento de la autorización.

### Aislamiento de las pruebas

Las pruebas de M03 crean una ubicación y un dispositivo sintéticos exclusivos para cada ejecución.

Los códigos se generan de forma única para evitar conflictos con el seed y con otras ejecuciones.

Cada escenario se ejecuta dentro de una transacción. Después de preparar los datos se utiliza `SET ROLE` para adoptar temporalmente el rol que se desea comprobar.

Al finalizar se restablece el contexto mediante `RESET ROLE` y se ejecuta `ROLLBACK`.

Por esta razón, las pruebas no modifican permanentemente el seed ni acumulan datos de prueba en PostgreSQL.

### Verificación automatizada

Se creó `scripts/verify_m03.sh` para automatizar la validación de M03.

El script realiza las siguientes comprobaciones:

- verifica la existencia de los archivos requeridos por M03;
- comprueba que `.env` no se encuentre rastreado por Git;
- revisa archivos rastreados en busca de patrones de claves privadas, claves AWS y cadenas de conexión PostgreSQL que contengan contraseña;
- ejecuta `tests/test_m03_security.py`;
- genera el resultado machine-readable mediante `pytest-json-report`;
- exige exactamente cuatro escenarios ejecutados y cuatro aprobados;
- comprueba que los cuatro nombres de prueba requeridos se encuentren en el reporte;
- comprueba que el fallo declarado valide `InsufficientPrivilege` y SQLSTATE `42501`.

El resultado machine-readable se genera en:

`artifacts/m03-security-results.json`

El objetivo `verify` del Makefile conserva las verificaciones anteriores y agrega M03 al final del flujo:

1. `scripts/verify_base.sh`
2. `scripts/verify_m02.sh`
3. `scripts/verify_m03.sh`

La ejecución integrada de `make verify` produjo 12 pruebas M02 aprobadas y 4 pruebas M03 aprobadas.

## Opciones consideradas

### Mantener una identidad con privilegios amplios

Se descartó utilizar una sola identidad con permisos de lectura, escritura, operación y administración porque cualquier componente tendría capacidades superiores a las necesarias.

La separación en cuatro roles permite aplicar mínimo privilegio y comprobar cada responsabilidad de forma independiente.

### Mantener una contraseña de desarrollo dentro del repositorio

Se descartó conservar una contraseña funcional como valor por defecto porque permitiría iniciar el sistema utilizando una credencial conocida almacenada junto con el código.

Se decidió exigir la credencial mediante `POSTGRES_PASSWORD`.

### Crear usuarios independientes con contraseña para cada rol

Se decidió mantener los roles de autorización como `NOLOGIN` durante M03. Las pruebas utilizan una conexión administrativa controlada y `SET ROLE` para comprobar la matriz de permisos sin almacenar nuevas credenciales.

## Consecuencias

- La base diferencia responsabilidades de migración, escritura, lectura y operación.
- Los componentes pueden trabajar con permisos limitados a sus responsabilidades.
- Las operaciones no autorizadas pueden ser rechazadas directamente por PostgreSQL.
- Las credenciales dejan de depender de valores funcionales versionados.
- El entorno requiere declarar `POSTGRES_PASSWORD` antes de utilizar los componentes que se conectan a PostgreSQL.
- Las pruebas M03 pueden repetirse sin modificar permanentemente el seed.
- `make verify` conserva la validación de entregas anteriores e incorpora la seguridad relacional de M03.

## Limitaciones

La solución está orientada al entorno académico y utiliza Docker Compose como respaldo de AWS Academy Learner Lab. Los roles y permisos cubren únicamente los objetos definidos por M01 y M02. La verificación integral de autorizaciones depende de la migración 003 y de las pruebas M03.

## Resultado

La entrega M03 queda preparada para comprobar que:

- existen roles separados para migración, escritura, lectura y operación;
- los cuatro roles trabajan bajo una política de mínimo privilegio;
- `cdrl_reader` puede consultar la información relacional;
- `cdrl_writer` puede insertar nuevas lecturas de telemetría;
- `cdrl_operator` puede modificar el estado de los dispositivos;
- una operación de escritura realizada por `cdrl_reader` es rechazada por autorización con SQLSTATE `42501`;
- los datos utilizados por las pruebas no modifican permanentemente el seed;
- `.env` permanece fuera del control de versiones;
- las credenciales se reciben mediante variables de entorno;
- existe un procedimiento documentado de rotación de credenciales;
- `scripts/verify_m03.sh` genera y valida el artifact machine-readable;
- las cuatro pruebas M03 se ejecutan y aprueban;
- `make verify` ejecuta de forma integrada las validaciones de la base, M02 y M03.
