# ADR-003 Seguridad Relacional y Minimo Privilegio

## Estado

Aceptado.

## Contexto

M03 agrega una capa de seguridad sobre el modelo relacional construido en M01 y M02. La base debe separar las responsabilidades de migración, escritura, lectura y operación, y las credenciales deben permanecer fuera del repositorio.

La configuración anterior contenía una contraseña de desarrollo como valor por defecto. Aunque era sintética, seguía siendo una credencial funcional embebida en archivos versionados y permitía iniciar el entorno sin declarar explícitamente el secreto.

## Decisión

Adoptamos cuatro roles de PostgreSQL con mínimo privilegio:

| Rol | Responsabilidad |
| --- | --- |
| `cdrl_migrator` | Administrar la estructura necesaria para migraciones controladas. |
| `cdrl_writer` | Insertar nuevas lecturas de telemetría. |
| `cdrl_reader` | Consultar tablas y la vista relacional. |
| `cdrl_operator` | Modificar únicamente el estado de los dispositivos. |

La política de permisos se implementa en `db/migrations/003_security_roles.sql`. Las pruebas automatizadas de acceso permitido y denegado se integrarán mediante `tests/test_m03_security.py` y `scripts/verify_m03.sh`.

## Manejo de secretos

Las credenciales se reciben únicamente mediante variables de entorno. `rebuild.py`, `db/seed/seed.py`, `db/queries/demo.py` y las pruebas de contrato requieren `POSTGRES_PASSWORD` y no contienen una contraseña alternativa.

`.env.example` contiene la variable vacía como guía de configuración, pero no contiene una credencial utilizable. Los archivos `.env`, `.env.local` y otros archivos de entorno quedan ignorados por Git, mientras que `.env.example` permanece versionado como plantilla.

Docker Compose mantiene sus valores no sensibles por defecto, pero exige `POSTGRES_PASSWORD` mediante interpolación obligatoria. Si la variable no está definida, el servicio no debe iniciar.

## Rotación de credenciales

1. Generar una credencial nueva fuera del repositorio y almacenarla en el mecanismo seguro disponible.
2. Actualizar la credencial del principal de acceso correspondiente en PostgreSQL.
3. Actualizar `POSTGRES_PASSWORD` únicamente en el entorno local, AWS Academy Learner Lab o el servicio seguro utilizado.
4. Reiniciar o reconectar el componente que utiliza la credencial.
5. Ejecutar `make verify` y confirmar que la nueva credencial funciona.
6. Confirmar que la credencial anterior ya no es válida.
7. No registrar ningún valor anterior o nuevo en Git, archivos de evidencia ni mensajes de commit.

La rotación no requiere modificar el código fuente: sólo cambia la variable de entorno y la credencial almacenada en PostgreSQL.

## Participación técnica de Víctor Manuel Jiménez Suárez

Víctor eliminó los valores de contraseña por defecto, hizo obligatoria la variable `POSTGRES_PASSWORD` y mantuvo la configuración reproducible sin guardar secretos. Su contribución comprende:

- `.env.example`: plantilla sin credenciales utilizables.
- `.gitignore`: exclusión de archivos de entorno locales sin excluir `.env.example`.
- `rebuild.py` y `db/seed/seed.py`: validación explícita de la variable obligatoria.
- `db/queries/demo.py` y `tests/test_telemetry_contract.py`: eliminación de referencias heredadas a la contraseña por defecto.
- `docker-compose.yml`: eliminación del fallback de contraseña.
- Este ADR: procedimiento de rotación y alcance de la protección de secretos.

## Validación

La revisión local comprueba que `.env` no está rastreado, que los archivos de entorno locales están ignorados, que no existe `cdrl_dev_only` en archivos rastreados y que no hay patrones de claves privadas, claves AWS o cadenas de conexión con contraseña.

La validación completa de M03 deberá incluir los escenarios positivos, los casos límite, al menos tres accesos denegados, el artifact JSON y la ejecución integrada de `make verify`.

## Opciones consideradas

Se descartó conservar una contraseña de desarrollo dentro del repositorio porque permite iniciar el sistema con una credencial conocida y contradice la separación entre código y secretos. También se descartó guardar credenciales en `docker-compose.yml`, scripts o archivos de pruebas.

## Consecuencias

La configuración es más segura y hace explícita la dependencia de la credencial. El entorno local requiere definir `POSTGRES_PASSWORD` antes de ejecutar Docker Compose o scripts de conexión, pero la rotación no exige cambios de código y la revisión de secretos puede automatizarse.

## Limitaciones

La solución está orientada al entorno académico y utiliza Docker Compose como respaldo de AWS Academy Learner Lab. Los roles y permisos cubren únicamente los objetos definidos por M01 y M02. La verificación integral de autorizaciones depende de la migración 003 y de las pruebas M03.

## Resultado

La rama de Víctor deja la configuración sin contraseñas funcionales versionadas, exige el secreto desde el entorno y documenta cómo rotarlo sin modificar el repositorio.
