# ADR-009 — Seguridad NoSQL y auditoría

**Estado:** Propuesto. Implementación revisada y validada técnicamente en local; pendiente de revisión del equipo mediante PR antes de aceptar la decisión.

**Fecha:** 8 de noviembre de 2026.

**Responsables:** Víctor: autorización, fachada segura y ejemplo IAM; Angélica: auditoría, abuso y remediación; David: integración, pruebas, verificador, ADR y evidencia.

## 1. Contexto

M09 protege las operaciones documentales sobre `cdrl_events` de M05 y reutiliza `cdrl_audit_log` y la sanitización de M06. Debe conservar documentos v1/v2 de M06/M07 y las consultas paginadas de M08. Los roles conservan sus nombres conceptuales de M03; los permisos SQL no se trasladan a DynamoDB.

La validación utiliza Python 3.14, PostgreSQL 16 y DynamoDB Local con Docker Compose y datos sintéticos. DynamoDB Local permite comprobar la autorización de la aplicación y la persistencia de los logs, pero no aplica las políticas IAM de AWS. La corrección de mínimo privilegio de PostgreSQL M03 constituye un trabajo separado.

## 2. Decisión y matriz exacta

La fachada `SecureOperations` autoriza antes de ejecutar el CRUD. Toda combinación no declarada se rechaza. Un identificador, diccionario o nombre de rol enviado por el cliente no es una identidad confiable: `IdentityRegistry` entrega contextos opacos únicamente al adaptador del servidor que ya verificó el sujeto. Las pruebas controlan sujetos sintéticos; este módulo no implementa autenticación real.

| Operación y recurso | cdrl_reader | cdrl_writer | cdrl_operator | cdrl_migrator |
| --- | --- | --- | --- | --- |
| GetItem de eventos | Permitir | Denegar | Denegar | Denegar |
| Query de eventos e índices | Permitir | Denegar | Denegar | Denegar |
| PutItem para crear eventos | Denegar | Permitir | Denegar | Denegar |
| UpdateItem de eventos | Denegar | Denegar | Denegar | Denegar |
| DeleteItem de eventos | Denegar | Denegar | Denegar | Denegar |
| ReadOperationalSummary | Denegar | Denegar | Permitir | Denegar |
| Leer auditoría directamente | Denegar | Denegar | Denegar | Denegar |
| Crear, actualizar o borrar auditoría directamente | Denegar | Denegar | Denegar | Denegar |

El reader consulta los eventos sin obtener permisos de escritura. El writer crea con validación v1/v2 y `attribute_not_exists(eventId)`, para impedir reemplazos por duplicación. El operator solo recibe `eventId` y `type`: el esquema actual no contiene `status`. La consulta usa proyección y una segunda lista de campos permitidos dentro del servidor; no se entrega el documento completo para ocultarlo después en pantalla. El migrator no recibe operaciones mediante la interfaz M09 de usuarios.

La verificación prueba las 48 combinaciones de cuatro roles, seis acciones y dos recursos. Esa matriz de política se complementa con pruebas funcionales de la fachada, de la persistencia y de la protección de los datos.

## 3. Auditoría confiable y política ante fallos

`SecurityAuditSink` es una dependencia interna, obligatoria y configurada por el servidor. Los roles de usuario no pueden seleccionarla ni consultar directamente su tabla. La identidad técnica de los fixtures inspecciona los logs durante las pruebas.

Cada registro contiene exactamente `auditId`, `attemptId`, `actorId`, `role`, `action`, `resource`, `result`, `reason` y `timestamp` UTC. Una operación autorizada emite `attempt` antes del CRUD y `success` o `error` después. Una denegación emite `denied` sin acceder al backend de eventos. Cada emisión obtiene un `auditId` distinto; las emisiones de una llamada comparten `attemptId`, diferente al de otros intentos.

El sink valida y sanitiza mediante `sanitize_audit_context`, rechaza campos extra y escribe condicionalmente con `attribute_not_exists(auditId)`. No persiste documentos completos, cursores, argumentos arbitrarios ni texto de excepciones. Los registros históricos de migración M06 conservan su formato e identificadores; pueden coexistir con los registros de seguridad M09 en la misma tabla.

La confirmación del sink debe ser exactamente `True`. Si falla antes de la operación sensible, se devuelve `AuditUnavailableError` sin ejecutar el CRUD. Si falla después de iniciar el CRUD, se informa `operation_may_have_completed=True`: la escritura puede haberse realizado. No se declara éxito auditado ni se promete rollback. La escritura del evento y la del log son operaciones independientes, sin transacción atómica entre ambas.

## 4. Aplicación e IAM

`config/iam/m09-dynamodb-policy.json` es una plantilla propuesta de CloudFormation con políticas separadas por principal y ARNs parametrizados para tablas e índices. No se despliega durante esta validación. Una concesión IAM de `PutItem` por sí sola no obliga a crear condicionalmente ni garantiza logs inmutables; esas condiciones las aplica el backend confiable. No deben combinarse todos los permisos en una identidad ni entregarse credenciales técnicas a clientes.

Las políticas del servicio de resumen y del servicio de auditoría corresponden a componentes técnicos separados, no a roles seleccionables por el usuario. La autenticación real, asignación de identidades AWS, políticas adjuntas y pruebas con identidades limitadas en AWS Academy quedan fuera de lo validado aquí.

## 5. Alternativas y consecuencias

| Alternativa | Decisión y motivo |
| --- | --- |
| Acceso amplio al CRUD para todos | Descartado: permitiría lecturas o modificaciones fuera de la responsabilidad de cada actor. |
| Solo controles Python como protección de todo el despliegue | Insuficiente: código con acceso al proceso o a credenciales puede saltarse la fachada. Los controles locales no demuestran IAM. |
| Solo IAM | Insuficiente para este flujo: Local no lo aplica y la lógica de creación, resumen, identidad y auditoría necesita controles del backend. |
| Autorización de aplicación y políticas IAM separadas para despliegue | Elegida, con límites explícitos: la aplicación está probada localmente y el ejemplo IAM requiere validación AWS posterior. |

La decisión permite trazabilidad y rechaza accesos indebidos antes del CRUD. Agrega complejidad y escrituras de auditoría: normalmente dos por operación autorizada y una por denegación. No se han medido costos en AWS. Una indisponibilidad de auditoría reduce la disponibilidad del servicio y un fallo posterior puede exigir reconciliación.

## 6. Compatibilidad y excepciones técnicas

Se conserva el CRUD histórico de M05 y las operaciones internas de M06/M07; M09 envuelve su uso autorizado sin modificar sus implementaciones. El mantenimiento y las migraciones requieren un contexto técnico aislado y permisos revisados por separado. No se habilitan como una excepción seleccionable mediante `cdrl_migrator`.

M08 mantiene `Query`, sus GSIs y el cursor JSON con la clave nativa. Los documentos v1/v2 se devuelven intactos. Los índices son eventualmente consistentes; las pruebas esperan propagación antes de comprobar continuidad. La paginación no garantiza snapshot ni desempate global por eventId.

## 7. Abuso, remediación y validación real

El caso de Angélica `test_isolated_excessive_permission_is_removed_before_real_operations` crea un permiso excesivo `DeleteItem` en un fixture en memoria: antes elimina un documento sintético; después, la fachada segura lo rechaza, mantiene el documento y registra la denegación. No modifica permisos de producción ni demuestra remediación de una política AWS desplegada.

David añade 29 ejecuciones de integración con tablas temporales reales en DynamoDB Local. Los cuatro escenarios mínimos quedan cubiertos así:

| Escenario | Comprobación |
| --- | --- |
| Normal | Writer crea v1/v2; reader recupera los datos; ambos intentos dejan auditoría persistida. Reader también recorre Query paginado. |
| Límite 1 | Reader no crea ni actualiza; writer/operator no leen directamente; migrator no consulta. No hay llamadas al backend de eventos ni cambios en documentos. |
| Límite 2 | Los cuatro roles no pueden leer ni alterar auditoría; los logs anteriores quedan intactos y se agrega la denegación. |
| Fallo declarado | DeleteItem se rechaza para los cuatro roles; el evento permanece y el rechazo queda auditado. |

También se verifican identidades desconocidas/falsificadas, resumen seguro del operator, eventos inexistentes, duplicados, IDs distintos, sanitización recursiva, errores de cursor, coexistencia M06/M09 y fallos de auditoría anteriores y posteriores al CRUD.

Las cuatro suites M09 aprueban 193 pruebas: autorización 96, auditoría 29, abuso/remediación 39 e integración de David 29. `make verify` aprueba 345 pruebas M01–M09, sin fallos ni omisiones. El resultado del benchmark M08 conservado se valida sin repetir sus mediciones; estos conteos no representan pruebas IAM.

La revisión de David ejecuta `make setup` dos veces en un proyecto Compose con volúmenes nuevos y verifica idempotencia. Ejecuta `make verify` y mantiene `make run` en primer plano mientras realiza consultas SQL y una creación/lectura/denegación M09 con cinco logs persistidos. Solo se detienen y eliminan los recursos temporales de esa revisión. La terminación solicitada de `make run` se distingue de un fallo de arranque.

El verificador rechaza reportes incompletos, pruebas omitidas, conteos inconsistentes, combinaciones o parametrizaciones faltantes y cero pruebas. Elimina un artifact anterior al comenzar y conserva el código de salida de pytest ante fallos. Los conteos y nombres del artifact provienen de la ejecución actual; los grupos de escenarios pueden compartir pruebas.

## 8. Reproducción, evidencia y cierre

Desde la raíz del repositorio, con Docker, las dependencias de `requirements.txt` y un `.env` local preparado fuera de Git:

```bash
make setup
make setup
make verify
make run
```

`make run` mantiene Compose en primer plano; detenerlo después de las comprobaciones funcionales. Para ejecutar solo M09, usar `bash scripts/verify_m09.sh`; el script selecciona el modo local por defecto y rechaza `DYNAMODB_LOCAL=false`.

El artifact `artifacts/m09-nosql-security-audit-results.json` registra pruebas, matriz, escenarios, ambiente y hashes de fuentes. `evidence/m09-nosql-security-audit.json` conserva los resultados históricos de la revisión, el SHA probado y las huellas de logs y artifact. Los logs de los comandos Make acompañan esa evidencia. Una nueva ejecución puede regenerar artifacts; no reescribe automáticamente la evidencia histórica ni sus hashes.

En el entorno administrado la ejecución local selecciona un archivo AWS sin credenciales, conservando el perfil de bloqueo inyectado. La fábrica existente usa únicamente credenciales sintéticas contra loopback. No se agregan credenciales al código ni a los registros de entrega.

El campo `commitSha` identifica el código que se probó. Guardar sus resultados crea un commit posterior; no se intenta insertar el SHA del propio commit dentro de sí mismo. La entrega externa debe registrar el SHA exacto apuntado por `week-09-final` después de integrar y validar `development` y `main`.

Quedan pendientes la revisión/aceptación del ADR, el PR de David hacia `development`, el PR hacia `main`, las verificaciones remotas y sobre el commit final, el tag `week-09-final` y la entrega en Classroom. La corrección M03 solo podrá incorporarse mediante su PR independiente y pruebas propias. Este ADR no declara esas acciones completadas.
