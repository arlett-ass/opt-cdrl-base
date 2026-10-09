"""Acceso a documentos v1/v2 sobre la tabla de eventos M05 existente."""

from botocore.exceptions import ClientError

from src.m05.dynamodb_client import get_table

from .schema_evolution import migrate_v1_to_v2, validate_versioned_event


class DuplicateVersionedEventError(RuntimeError):
    """Se intentó insertar un eventId ya presente en cdrl_events."""


class VersionedEventNotFoundError(RuntimeError):
    """La migración solicitada no encontró el eventId en cdrl_events."""


class ConcurrentSchemaMigrationError(RuntimeError):
    """El evento cambió de versión antes de guardar la migración."""


def create_versioned_event(event, table=None):
    """Valida y crea un documento v1 o v2 en la tabla M05 configurada."""
    document = validate_versioned_event(event)
    table = table if table is not None else get_table()
    try:
        table.put_item(
            Item=document,
            ConditionExpression="attribute_not_exists(eventId)",
        )
    except ClientError as exc:
        if (
            exc.response.get("Error", {}).get("Code")
            == "ConditionalCheckFailedException"
        ):
            raise DuplicateVersionedEventError(
                f"El evento {document['eventId']} ya existe."
            ) from exc
        raise
    return document


def get_versioned_event(event_id, table=None):
    """Lee y valida un documento v1/v2 por la PK eventId."""
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("event_id debe ser una cadena no vacía.")
    table = table if table is not None else get_table()
    response = table.get_item(
        Key={"eventId": event_id},
        ConsistentRead=True,
    )
    item = response.get("Item")
    return validate_versioned_event(item) if item is not None else None


def migrate_event_to_v2(event_id, table=None):
    """Migra un evento almacenado; v2 retorna sin escribir nuevamente.

    La escritura condicional exige que el documento siga existiendo como v1,
    evitando reemplazar un evento que otro proceso ya convirtió a v2.
    """
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("event_id debe ser una cadena no vacía.")
    table = table if table is not None else get_table()
    current = get_versioned_event(event_id, table=table)
    if current is None:
        raise VersionedEventNotFoundError(
            f"El evento {event_id} no existe."
        )

    migrated = migrate_v1_to_v2(current)
    if current["metadata"]["schemaVersion"] == 2:
        return migrated

    try:
        table.put_item(
            Item=migrated,
            ConditionExpression=(
                "attribute_exists(#event_id) AND "
                "#metadata.#schema_version = :from_version"
            ),
            ExpressionAttributeNames={
                "#event_id": "eventId",
                "#metadata": "metadata",
                "#schema_version": "schemaVersion",
            },
            ExpressionAttributeValues={":from_version": 1},
        )
    except ClientError as exc:
        if (
            exc.response.get("Error", {}).get("Code")
            == "ConditionalCheckFailedException"
        ):
            raise ConcurrentSchemaMigrationError(
                f"El evento {event_id} ya no conserva la versión v1 esperada."
            ) from exc
        raise
    return migrated
