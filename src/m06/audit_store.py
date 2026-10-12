"""Auditoría segura e idempotente para operaciones M06.

La auditoría se almacena en una tabla separada de los eventos.
Nunca persiste secretos en claro ni copias completas before/after.
"""

from datetime import datetime, timezone
import json
import os
import re
import sys
import time

from botocore.exceptions import ClientError

from src.m05.dynamodb_client import (
    get_dynamodb_client,
    get_dynamodb_resource,
)


DEFAULT_AUDIT_TABLE = "cdrl_audit_log"

_SENSITIVE_KEYS = {
    "password",
    "token",
    "secret",
    "authorization",
    "credentials",
    "apikey",
    "connectionstring",
    "accesstoken",
    "refreshtoken",
    "clientsecret",
    "secretkey",
}

_REDACTED = "[REDACTED]"


class AuditTableSchemaError(RuntimeError):
    """La tabla de auditoría existe pero no cumple el contrato M06."""


def _normalized_key(key):
    """Normaliza nombres para detectar password, api_key, api-key, etc."""
    return "".join(
        character
        for character in str(key).lower()
        if character.isalnum()
    )


def _is_sensitive_key(key):
    return _normalized_key(key) in _SENSITIVE_KEYS


def sanitize_audit_context(data):
    """Devuelve una copia sanitizada de estructuras JSON-like."""
    if isinstance(data, dict):
        sanitized = {}

        for key, value in data.items():
            if _is_sensitive_key(key):
                sanitized[key] = _REDACTED
            else:
                sanitized[key] = sanitize_audit_context(value)

        return sanitized

    if isinstance(data, list):
        return [
            sanitize_audit_context(value)
            for value in data
        ]

    if isinstance(data, tuple):
        return [
            sanitize_audit_context(value)
            for value in data
        ]

    return data


def get_audit_table_name():
    """Obtiene el nombre de tabla desde configuración no sensible."""
    name = os.environ.get(
        "DYNAMODB_AUDIT_TABLE",
        DEFAULT_AUDIT_TABLE,
    )

    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,255}", name):
        raise ValueError(
            "DYNAMODB_AUDIT_TABLE requiere entre 3 y 255 "
            "caracteres alfanuméricos, _, - o ."
        )

    return name


def get_audit_table(table_name=None):
    """Devuelve el recurso DynamoDB Table."""
    name = (
        table_name
        if table_name is not None
        else get_audit_table_name()
    )

    return get_dynamodb_resource().Table(name)


def _check_audit_table_schema(table):
    """Valida que cdrl_audit_log tenga únicamente auditId como PK."""
    key_schema = {
        key["KeyType"]: key["AttributeName"]
        for key in table.get("KeySchema", [])
    }

    if key_schema != {"HASH": "auditId"}:
        raise AuditTableSchemaError(
            "La tabla de auditoría requiere auditId "
            "como única partition key."
        )

    attributes = {
        item["AttributeName"]: item["AttributeType"]
        for item in table.get("AttributeDefinitions", [])
    }

    if attributes != {"auditId": "S"}:
        raise AuditTableSchemaError(
            "auditId debe ser el único atributo de clave "
            "y debe ser String."
        )

    if table.get("GlobalSecondaryIndexes"):
        raise AuditTableSchemaError(
            "La tabla de auditoría M06 no requiere GSIs."
        )

    if table.get("LocalSecondaryIndexes"):
        raise AuditTableSchemaError(
            "La tabla de auditoría M06 no requiere LSIs."
        )


def ensure_audit_table(
    client=None,
    table_name=None,
    *,
    attempts=60,
    poll_seconds=1,
):
    """Crea y valida la tabla de auditoría de forma idempotente."""
    if type(attempts) is not int or attempts < 1:
        raise ValueError("attempts debe ser un entero positivo.")

    if poll_seconds < 0:
        raise ValueError("poll_seconds no puede ser negativo.")

    client = (
        client
        if client is not None
        else get_dynamodb_client()
    )

    name = (
        table_name
        if table_name is not None
        else get_audit_table_name()
    )

    try:
        client.describe_table(TableName=name)

    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")

        if error_code != "ResourceNotFoundException":
            raise

        try:
            client.create_table(
                TableName=name,
                BillingMode="PAY_PER_REQUEST",
                AttributeDefinitions=[
                    {
                        "AttributeName": "auditId",
                        "AttributeType": "S",
                    }
                ],
                KeySchema=[
                    {
                        "AttributeName": "auditId",
                        "KeyType": "HASH",
                    }
                ],
            )

        except ClientError as create_exc:
            create_code = (
                create_exc.response
                .get("Error", {})
                .get("Code")
            )

            if create_code != "ResourceInUseException":
                raise

    for attempt in range(attempts):
        try:
            description = client.describe_table(
                TableName=name
            )["Table"]

        except ClientError as exc:
            if (
                exc.response.get("Error", {}).get("Code")
                != "ResourceNotFoundException"
            ):
                raise

        else:
            _check_audit_table_schema(description)

            if description.get("TableStatus") == "ACTIVE":
                return description

            if description.get("TableStatus") not in (
                "CREATING",
                "UPDATING",
                "ACTIVE",
            ):
                raise AuditTableSchemaError(
                    "La tabla de auditoría no está disponible."
                )

        if attempt + 1 < attempts:
            time.sleep(poll_seconds)

    raise TimeoutError(
        f"La tabla {name} no alcanzó estado ACTIVE."
    )


def _utc_now():
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def build_audit_record(
    event_id,
    *,
    action,
    trace_id,
    from_version,
    to_version,
    changed_fields,
    result="ok",
    reason="schema_version_upgrade",
    actor_id="system:m06-migrator",
    entity="cdrl_events",
    timestamp=None,
    context=None,
):
    """Construye un audit record pequeño y sanitizado."""
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("event_id debe ser una cadena no vacía.")

    if not isinstance(action, str) or not action.strip():
        raise ValueError("action debe ser una cadena no vacía.")

    if not isinstance(trace_id, str) or not trace_id.strip():
        raise ValueError("trace_id debe ser una cadena no vacía.")

    if not isinstance(actor_id, str) or not actor_id.strip():
        raise ValueError("actor_id debe ser una cadena no vacía.")

    if not isinstance(entity, str) or not entity.strip():
        raise ValueError("entity debe ser una cadena no vacía.")

    if not isinstance(result, str) or not result.strip():
        raise ValueError("result debe ser una cadena no vacía.")

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason debe ser una cadena no vacía.")

    if (
        type(from_version) is not int
        or type(to_version) is not int
        or from_version < 1
        or to_version < 1
    ):
        raise ValueError(
            "from_version y to_version deben ser enteros positivos."
        )

    if not isinstance(changed_fields, (list, tuple)):
        raise ValueError(
            "changed_fields debe ser una lista o tupla."
        )

    normalized_fields = sorted(
        {
            field
            for field in changed_fields
            if isinstance(field, str) and field.strip()
        }
    )

    if not normalized_fields:
        raise ValueError(
            "changed_fields debe contener al menos un campo."
        )

    timestamp = timestamp or _utc_now()

    if not isinstance(timestamp, str) or not timestamp.strip():
        raise ValueError(
            "timestamp debe ser una cadena no vacía."
        )

    # Identidad determinista para que repetir la misma migración
    # no genere múltiples registros equivalentes.
    audit_id = (
        f"{action}#{event_id}"
        f"#v{from_version}-v{to_version}"
    )

    record = {
        "auditId": audit_id,
        "eventId": event_id,
        "actorId": actor_id,
        "action": action,
        "entity": entity,
        "timestamp": timestamp,
        "traceId": trace_id,
        "result": result,
        "reason": reason,
        "fromVersion": from_version,
        "toVersion": to_version,
        "changedFields": normalized_fields,
    }

    if context is not None:
        record["context"] = context

    return sanitize_audit_context(record)


def record_audit(record, table=None):
    """Persiste auditoría una sola vez por auditId.

    Retorna True si creó el registro.
    Retorna False si auditId ya existía.
    """
    if not isinstance(record, dict):
        raise ValueError("record debe ser un objeto.")

    required = {
        "auditId",
        "eventId",
        "actorId",
        "action",
        "entity",
        "timestamp",
        "traceId",
        "result",
        "reason",
        "fromVersion",
        "toVersion",
        "changedFields",
    }

    if not required.issubset(record):
        missing = sorted(required - set(record))

        raise ValueError(
            "Faltan campos de auditoría: "
            + ", ".join(missing)
        )

    safe_record = sanitize_audit_context(record)

    table = (
        table
        if table is not None
        else get_audit_table()
    )

    try:
        table.put_item(
            Item=safe_record,
            ConditionExpression="attribute_not_exists(auditId)",
        )

    except ClientError as exc:
        if (
            exc.response.get("Error", {}).get("Code")
            == "ConditionalCheckFailedException"
        ):
            return False

        raise

    return True


def main():
    try:
        table = ensure_audit_table()

    except Exception as exc:
        print(
            f"No se pudo preparar auditoría M06: {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "table": table["TableName"],
                "status": table["TableStatus"],
                "partitionKey": "auditId",
            }
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())