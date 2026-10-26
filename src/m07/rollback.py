from copy import deepcopy

from botocore.exceptions import ClientError

from src.m05.dynamodb_client import get_table
from src.m06.versioned_store import (
    ConcurrentSchemaMigrationError,
    VersionedEventNotFoundError,
)

from .versioning import TARGET_SCHEMA_VERSION, validate_document


__all__ = [
    "rollback_event",
]


_PROTECTED_FIELDS = (
    "metadata",
    "payload",
    "type",
    "source",
    "timestamp",
)


def rollback_event(previous_event, table=None):
    """
    Restaura un documento v1 previamente migrado.

    previous_event corresponde exactamente al campo previousEvent devuelto por
    migrate_event().

    El rollback solamente ocurre cuando el documento almacenado continúa
    siendo exactamente el esperado (v2 equivalente del snapshot).

    Devuelve:

        {
            "event": documento_restaurado,
            "changed": bool,
            "fromVersion": 2,
            "toVersion": 1,
        }
    """

    previous = validate_document(previous_event)

    if previous["metadata"]["schemaVersion"] != 1:
        raise ValueError(
            "previous_event debe corresponder a un documento v1."
        )

    table = table if table is not None else get_table()

    event_id = previous["eventId"]

    response = table.get_item(
        Key={"eventId": event_id},
        ConsistentRead=True,
    )

    current = response.get("Item")

    if current is None:
        raise VersionedEventNotFoundError(
            f"El evento {event_id} no existe."
        )

    current = validate_document(current)

    #
    # Si ya está nuevamente en v1,
    # no hacemos ninguna escritura.
    #
    if current["metadata"]["schemaVersion"] == 1:
        return {
            "event": deepcopy(current),
            "changed": False,
            "fromVersion": 1,
            "toVersion": 1,
        }

    #
    # Construimos la condición usando exactamente
    # el documento almacenado (v2).
    #
    names = {"#event_id": "eventId"}

    names.update(
        {
            f"#{field}": field
            for field in _PROTECTED_FIELDS
        }
    )

    values = {
        f":expected_{field}": deepcopy(current[field])
        for field in _PROTECTED_FIELDS
    }

    condition = (
        "attribute_exists(#event_id) AND "
        + " AND ".join(
            f"#{field} = :expected_{field}"
            for field in _PROTECTED_FIELDS
        )
    )

    try:

        table.put_item(
            Item=deepcopy(previous),
            ConditionExpression=condition,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    except ClientError as exc:

        if (
            exc.response["Error"]["Code"]
            == "ConditionalCheckFailedException"
        ):
            raise ConcurrentSchemaMigrationError(
                f"El evento {event_id} cambió durante el rollback."
            ) from exc

        raise

    return {
        "event": deepcopy(previous),
        "changed": True,
        "fromVersion": TARGET_SCHEMA_VERSION,
        "toVersion": 1,
    }