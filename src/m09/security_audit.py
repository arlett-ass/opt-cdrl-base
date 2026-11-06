"""Auditoría persistente de intentos de seguridad M09.

Este módulo reutiliza la tabla y sanitización M06 sin alterar sus registros de
migración. Se conecta a SecureOperations mediante audit_sink(record).

El sink solo acepta los nueve campos previstos por Víctor: no almacena
documentos, cursores, peticiones, excepciones ni contexto arbitrario.
La escritura es condicional para impedir sobrescribir un auditId ya utilizado.

Solo debe construirse en el proceso confiable del servidor. No es una API que
permita a los roles de usuario escribir directamente en la tabla.
"""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

from botocore.exceptions import ClientError

from src.m06.audit_store import get_audit_table, sanitize_audit_context
from .policy import ACTIONS, AUDIT, EVENTS, ROLES


REQUIRED_FIELDS = frozenset({
    "auditId", "attemptId", "actorId", "role", "action",
    "resource", "result", "reason", "timestamp",
})
RESULT_REASONS = {
    "attempt": "authorized_attempt",
    "success": "operation_completed",
    "error": "operation_failed",
    "denied": None,
}
DENIAL_REASONS = frozenset({"permission_denied", "untrusted_identity"})


class SecurityAuditRecordError(ValueError):
    """El intento no cumple el formato seguro de auditoría M09."""


def _valid_uuid(value):
    if type(value) is not str:
        return False
    try:
        return str(UUID(value)) == value.lower()
    except (ValueError, AttributeError, TypeError):
        return False


def validate_security_audit_record(record):
    """Devuelve una copia validada y sanitizada del formato acordado con Víctor.

    Deniega campos adicionales para impedir que un error del llamador persista
    tokens o datos privados bajo nombres aparentemente inofensivos.
    """
    if type(record) is not dict or set(record) != REQUIRED_FIELDS:
        raise SecurityAuditRecordError("Campos de auditoría M09 no permitidos o incompletos.")

    safe = sanitize_audit_context(deepcopy(record))

    if not _valid_uuid(safe["auditId"]) or not _valid_uuid(safe["attemptId"]):
        raise SecurityAuditRecordError("Identificadores de auditoría inválidos.")

    for key in ("actorId", "role", "action", "resource", "result", "reason", "timestamp"):
        if type(safe[key]) is not str or not safe[key].strip():
            raise SecurityAuditRecordError("Campo de auditoría inválido.")

    if safe["role"] not in (*ROLES, "unknown"):
        raise SecurityAuditRecordError("Rol de auditoría no declarado.")
    if safe["action"] not in (*ACTIONS, "unknown"):
        raise SecurityAuditRecordError("Acción de auditoría no declarada.")
    if safe["resource"] not in (EVENTS, AUDIT, "unknown"):
        raise SecurityAuditRecordError("Recurso de auditoría no declarado.")
    if safe["result"] not in RESULT_REASONS:
        raise SecurityAuditRecordError("Resultado de auditoría no declarado.")
    if safe["result"] == "denied":
        if safe["reason"] not in DENIAL_REASONS:
            raise SecurityAuditRecordError("Razón de denegación no declarada.")
    elif safe["reason"] != RESULT_REASONS[safe["result"]]:
        raise SecurityAuditRecordError("Razón no compatible con el resultado.")

    # En M09 se utiliza una marca UTC exacta; nunca tiempo local sin zona.
    try:
        stamp = safe["timestamp"]
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if not stamp.endswith("Z") or parsed.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError("Se requiere UTC Z.")
    except (ValueError, TypeError, OverflowError) as exc:
        raise SecurityAuditRecordError("Fecha UTC de auditoría inválida.") from None

    return safe


class SecurityAuditSink:
    """Componente interno que persiste el registro y confirma con True.

    Reintentar el MISMO auditId no sobrescribe un log y devuelve False.
    SecureOperations interpreta cualquier False como fallo de auditoría,
    nunca como éxito silencioso.
    """

    def __init__(self, *, table=None):
        self._table = table

    def __call__(self, record):
        safe = validate_security_audit_record(record)
        table = self._table if self._table is not None else get_audit_table()
        try:
            table.put_item(
                Item=safe,
                ConditionExpression="attribute_not_exists(auditId)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        return True


def create_security_audit_sink(*, table=None):
    """Construye el sink confiable que recibe SecureOperations(audit_sink=...)."""
    return SecurityAuditSink(table=table)
