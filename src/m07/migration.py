"""Conversión pura y migración condicional por documento para M07.

Se conserva el contrato M06 y la tabla M05. La condición compara los campos
del documento leído, además de la versión, para proteger cambios concurrentes
que todavía conserven v1. La compatibilidad de consumidores y el rollback se
integran por separado en M07.
"""

from copy import deepcopy

from botocore.exceptions import ClientError

from src.m05.dynamodb_client import get_table
from src.m06.schema_evolution import migrate_v1_to_v2
from src.m06.versioned_store import (
    ConcurrentSchemaMigrationError,
    VersionedEventNotFoundError,
)

from .versioning import TARGET_SCHEMA_VERSION, validate_document


__all__ = [
    "ConcurrentSchemaMigrationError",
    "VersionedEventNotFoundError",
    "migrate_document",
    "migrate_event",
]

_SNAPSHOT_FIELDS = ("metadata", "payload", "type", "source", "timestamp")


def migrate_document(document):
    """Convierte v1 a v2 sin efectos externos; v2 devuelve una copia equivalente.

    Conserva identidad, claves de GSIs, IDs, receivedAt y todas las mediciones.
    La conversión canónica de M06 valida y normaliza sin modificar la entrada.
    """
    return migrate_v1_to_v2(document)


def migrate_event(event_id, table=None):
    """Migra un evento almacenado y devuelve el resultado para su integración.

    ``event`` contiene el documento normalizado en v2; ``previousEvent`` es
    una copia de la imagen almacenada antes de migrar. ``changed`` indica una
    escritura exitosa, con ``fromVersion`` y ``toVersion`` explícitos. La imagen
    anterior se devuelve en memoria para coordinar rollback; no se persiste
    dentro del evento, ni constituye un backup durable o una auditoría.

    Un evento que ya es v2 no se escribe otra vez. Para v1 se usa lectura fuerte
    y una escritura condicional con la imagen cruda de todos los campos del
    contrato. Si cambian o desaparecen, se informa un conflicto sin reintentar
    ni sobrescribir el estado concurrente. Otros errores de DynamoDB se propagan.
    """
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("event_id debe ser una cadena no vacía.")

    table = table if table is not None else get_table()
    response = table.get_item(
        Key={"eventId": event_id},
        ConsistentRead=True,
    )
    stored = response.get("Item")
    if stored is None:
        raise VersionedEventNotFoundError(f"El evento {event_id} no existe.")

    previous = deepcopy(stored)
    current = validate_document(previous)
    from_version = current["metadata"]["schemaVersion"]
    migrated = migrate_document(current)
    result = {
        "event": migrated,
        "previousEvent": previous,
        "changed": from_version != TARGET_SCHEMA_VERSION,
        "fromVersion": from_version,
        "toVersion": TARGET_SCHEMA_VERSION,
    }

    if from_version == TARGET_SCHEMA_VERSION:
        return result

    # Las comparaciones usan la representación realmente almacenada: los
    # timestamps y decimales válidos pueden tener otra forma antes de normalizar.
    names = {"#event_id": "eventId"}
    names.update({f"#{field}": field for field in _SNAPSHOT_FIELDS})
    values = {
        f":expected_{field}": deepcopy(previous[field])
        for field in _SNAPSHOT_FIELDS
    }
    condition = "attribute_exists(#event_id) AND " + " AND ".join(
        f"#{field} = :expected_{field}" for field in _SNAPSHOT_FIELDS
    )

    try:
        table.put_item(
            Item=deepcopy(migrated),
            ConditionExpression=condition,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
    except ClientError as exc:
        if (
            exc.response.get("Error", {}).get("Code")
            == "ConditionalCheckFailedException"
        ):
            raise ConcurrentSchemaMigrationError(
                f"El evento {event_id} cambió o desapareció durante la migración M07."
            ) from exc
        raise

    return result
