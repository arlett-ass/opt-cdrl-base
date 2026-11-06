"""Fachada M09 con autorización y un contrato explícito de auditoría interna.

Integración para Angélica y David:

* Construir SecureOperations una vez en el servidor con registry, table de
  eventos (opcional: factory M05) y audit_sink confiable OBLIGATORIO.
* audit_sink(record) debe guardar durablemente el registro sanitizado y
  devolver exactamente True. False, None o excepción significan fallo.
  No se crea un sink silencioso ni se permite elegirlo por petición.
* El registro contiene auditId UUID único por emisión, attemptId UUID por
  llamada, actorId, role, action, resource, result, reason y timestamp UTC.
  result: attempt (previo autorizado), success, error o denied. No reutilizar
  los IDs deterministas de migración M06 ni sus campos ficticios de versión.
* La denegación se audita antes de lanzar AccessDeniedError y nunca accede al
  backend de eventos. Una operación permitida exige auditoría previa; errores
  del CRUD se auditan y se propagan. Nunca se registra el texto del error,
  documento, ID solicitado, cursor ni argumentos arbitrarios del cliente.
* Fallo de auditoría -> AuditUnavailableError. Si falla tras iniciar el CRUD,
  operation_may_have_completed=True: el documento podría haberse escrito.
  Las dos escrituras no son atómicas; no se promete rollback ni éxito auditado.

M05 sigue siendo la implementación de lectura, consultas y creación v1.
La creación v2 reutiliza M06 y su validación compatible con M07; ambas crean
condicionalmente sin reemplazar. M08 conserva el cursor nativo sin alterarlo.
El operador recibe solo eventId y type: no existe status en el esquema actual.
Se solicita proyección al backend y se vuelve a filtrar dentro del servidor.

No hay autenticación real ni cumplimiento IAM en DynamoDB Local. El ejemplo
config/iam es una propuesta de despliegue separada por principal técnico.
"""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from src.m05 import document_store
from src.m05.dynamodb_client import get_table
from src.m06.audit_store import sanitize_audit_context
from src.m06.versioned_store import (
    DuplicateVersionedEventError, create_versioned_event,
)
from src.m07.versioning import validate_document
from src.m08.pagination import DEFAULT_PAGE_SIZE, query_by_type_page

from .authorization import IdentityRegistry, authorize
from .policy import AUDIT, EVENTS


class AccessDeniedError(PermissionError):
    """Intento rechazado y auditado, sin ejecutar la operación de datos."""


class AuditUnavailableError(RuntimeError):
    """No se pudo confirmar auditoría; nunca representa éxito auditado."""

    def __init__(self, *, operation_may_have_completed=False):
        self.operation_may_have_completed = operation_may_have_completed
        super().__init__(
            "No se pudo confirmar la auditoría. La operación puede haberse realizado."
            if operation_may_have_completed else
            "No se pudo confirmar la auditoría. No se ejecutó la operación de datos."
        )


class SecureOperations:
    """Dependencias de servidor fijas; los métodos no reciben roles ni tablas."""

    def __init__(self, *, registry, audit_sink, table=None):
        if type(registry) is not IdentityRegistry:
            raise TypeError("registry requiere IdentityRegistry.")
        if not callable(audit_sink):
            raise TypeError("audit_sink debe ser un servicio interno obligatorio.")
        self._registry = registry
        self._audit_sink = audit_sink
        self._table = table

    def _events(self):
        return self._table if self._table is not None else get_table()

    def _emit(self, decision, attempt_id, result, reason, *, may_have_completed=False):
        record = sanitize_audit_context({
            "auditId": str(uuid4()),
            "attemptId": attempt_id,
            "actorId": decision.actor_id,
            "role": decision.role,
            "action": decision.action,
            "resource": decision.resource,
            "result": result,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(
                timespec="microseconds",
            ).replace("+00:00", "Z"),
        })
        try:
            acknowledged = self._audit_sink(deepcopy(record))
        except Exception:
            raise AuditUnavailableError(
                operation_may_have_completed=may_have_completed,
            ) from None
        if acknowledged is not True:
            raise AuditUnavailableError(
                operation_may_have_completed=may_have_completed,
            )

    def _run(self, identity, action, resource, operation):
        decision = authorize(self._registry, identity, action, resource)
        attempt_id = str(uuid4())
        if not decision.allowed:
            self._emit(decision, attempt_id, "denied", decision.reason)
            raise AccessDeniedError("Operación no autorizada por la política M09.")
        self._emit(decision, attempt_id, "attempt", "authorized_attempt")
        try:
            result = operation()
        except Exception:
            self._emit(
                decision, attempt_id, "error", "operation_failed",
                may_have_completed=True,
            )
            raise
        self._emit(
            decision, attempt_id, "success", "operation_completed",
            may_have_completed=True,
        )
        return result

    def get_event(self, identity, event_id):
        return self._run(identity, "GetItem", EVENTS, lambda: document_store.get_event(
            event_id, table=self._events(),
        ))

    def create_event(self, identity, event):
        def create():
            document = validate_document(event)
            table = self._events()
            if document["metadata"]["schemaVersion"] == 1:
                return document_store.create_event(document, table=table)
            try:
                return create_versioned_event(document, table=table)
            except DuplicateVersionedEventError as exc:
                raise document_store.DuplicateEventError("El evento ya existe.") from exc
        return self._run(identity, "PutItem", EVENTS, create)

    def query_by_type(self, identity, event_type, start, end):
        return self._run(identity, "Query", EVENTS, lambda: document_store.query_by_type(
            event_type, start, end, table=self._events(),
        ))

    def query_by_source(self, identity, source, start, end):
        return self._run(identity, "Query", EVENTS, lambda: document_store.query_by_source(
            source, start, end, table=self._events(),
        ))

    def query_by_type_page(
        self, identity, event_type, start, end, *, page_size=DEFAULT_PAGE_SIZE, cursor=None,
    ):
        return self._run(identity, "Query", EVENTS, lambda: query_by_type_page(
            event_type, start, end, page_size=page_size, cursor=cursor, table=self._events(),
        ))

    def get_operational_summary(self, identity, event_id):
        def summary():
            if not isinstance(event_id, str) or not event_id.strip():
                raise ValueError("event_id debe ser una cadena no vacía.")
            item = self._events().get_item(
                Key={"eventId": event_id}, ConsistentRead=True,
                ProjectionExpression="#id, #type",
                ExpressionAttributeNames={"#id": "eventId", "#type": "type"},
            ).get("Item")
            if item is None:
                return None
            if item.get("eventId") != event_id or item.get("type") != "telemetry.reading":
                raise ValueError("El resumen requiere una identidad y tipo válidos.")
            return {"eventId": item["eventId"], "type": item["type"]}
        return self._run(identity, "ReadOperationalSummary", EVENTS, summary)

    def update_event(self, identity, event_id, changes):
        return self._run(identity, "UpdateItem", EVENTS, None)

    def delete_event(self, identity, event_id):
        return self._run(identity, "DeleteItem", EVENTS, None)

    def read_audit(self, identity, audit_id):
        return self._run(identity, "GetItem", AUDIT, None)

    def write_audit(self, identity, record):
        return self._run(identity, "PutItem", AUDIT, None)

    def update_audit(self, identity, audit_id, changes):
        return self._run(identity, "UpdateItem", AUDIT, None)

    def delete_audit(self, identity, audit_id):
        return self._run(identity, "DeleteItem", AUDIT, None)
