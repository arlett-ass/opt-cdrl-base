"""CRUD y consultas indexadas para el almacén documental M05.

Este módulo reutiliza el contrato y la configuración creados para M05.
No crea infraestructura y no usa Scan para resolver consultas principales.
"""

from copy import deepcopy

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from .dynamodb_client import get_table
from .event_contract import normalize_timestamp, validate_event


class DuplicateEventError(RuntimeError):
    """Se intentó crear un eventId que ya existe."""


class EventNotFoundError(RuntimeError):
    """La operación requiere un evento que no existe."""


def _require_event_id(event_id):
    """Valida el identificador recibido por operaciones CRUD."""
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("event_id debe ser una cadena no vacía.")

    return event_id


def _require_non_empty_string(value, name):
    """Valida strings usados como claves de consulta."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} debe ser una cadena no vacía.")

    return value


def _normalize_range(start, end):
    """Normaliza un rango UTC inclusivo y rechaza intervalos invertidos."""
    normalized_start = normalize_timestamp(start)
    normalized_end = normalize_timestamp(end)

    if normalized_start > normalized_end:
        raise ValueError("start no puede ser posterior a end.")

    return normalized_start, normalized_end


def _merge_changes(current, changes):
    """Aplica cambios parciales sin modificar el documento original."""
    if not isinstance(changes, dict):
        raise ValueError("changes debe ser un objeto.")

    result = deepcopy(current)

    for key, value in changes.items():
        if (
            isinstance(value, dict)
            and isinstance(result.get(key), dict)
        ):
            result[key] = _merge_changes(
                result[key],
                value,
            )
        else:
            result[key] = deepcopy(value)

    return result


def create_event(event, table=None):
    """Valida y crea un evento sin permitir duplicados.

    La condición attribute_not_exists(eventId) evita que un
    reintento sobre la misma identidad lógica sobrescriba
    silenciosamente el evento.

    Devuelve una copia normalizada del documento insertado.
    """
    document = validate_event(event)

    table = table if table is not None else get_table()

    try:
        table.put_item(
            Item=document,
            ConditionExpression="attribute_not_exists(eventId)",
        )
    except ClientError as exc:
        error_code = exc.response.get(
            "Error",
            {},
        ).get("Code")

        if error_code == "ConditionalCheckFailedException":
            raise DuplicateEventError(
                f"El evento {document['eventId']} ya existe."
            ) from exc

        raise

    return document


def get_event(event_id, table=None):
    """Obtiene un evento por la partition key eventId.

    Devuelve el documento si existe o None cuando no existe.
    """
    event_id = _require_event_id(event_id)

    table = table if table is not None else get_table()

    response = table.get_item(
        Key={"eventId": event_id},
        ConsistentRead=True,
    )

    return response.get("Item")


def update_event(event_id, changes, table=None):
    """Actualiza un evento existente sin permitir upsert accidental.

    Primero recupera el documento actual, combina los cambios,
    vuelve a validar el contrato completo y finalmente reemplaza
    el documento únicamente si eventId todavía existe.
    """
    event_id = _require_event_id(event_id)

    if not isinstance(changes, dict) or not changes:
        raise ValueError(
            "changes debe ser un objeto no vacío."
        )

    table = table if table is not None else get_table()

    current = get_event(
        event_id,
        table=table,
    )

    if current is None:
        raise EventNotFoundError(
            f"El evento {event_id} no existe."
        )

    candidate = _merge_changes(
        current,
        changes,
    )

    if candidate.get("eventId") != event_id:
        raise ValueError(
            "eventId no puede modificarse."
        )

    document = validate_event(candidate)

    try:
        table.put_item(
            Item=document,
            ConditionExpression="attribute_exists(eventId)",
        )
    except ClientError as exc:
        error_code = exc.response.get(
            "Error",
            {},
        ).get("Code")

        if error_code == "ConditionalCheckFailedException":
            raise EventNotFoundError(
                f"El evento {event_id} dejó de existir."
            ) from exc

        raise

    return document


def delete_event(event_id, table=None):
    """Elimina un evento de forma idempotente.

    Devuelve True si existía y fue eliminado.
    Devuelve False cuando ya estaba ausente.
    """
    event_id = _require_event_id(event_id)

    table = table if table is not None else get_table()

    response = table.delete_item(
        Key={"eventId": event_id},
        ReturnValues="ALL_OLD",
    )

    return "Attributes" in response


def _query_index(
    index_name,
    partition_name,
    partition_value,
    start,
    end,
    table=None,
):
    """Ejecuta Query sobre un GSI y consume su paginación."""
    partition_value = _require_non_empty_string(
        partition_value,
        partition_name,
    )

    normalized_start, normalized_end = _normalize_range(
        start,
        end,
    )

    table = table if table is not None else get_table()

    items = []

    query_args = {
        "IndexName": index_name,
        "KeyConditionExpression": (
            Key(partition_name).eq(partition_value)
            & Key("timestamp").between(
                normalized_start,
                normalized_end,
            )
        ),
        "ScanIndexForward": True,
    }

    while True:
        response = table.query(
            **query_args,
        )

        items.extend(
            response.get("Items", [])
        )

        last_key = response.get(
            "LastEvaluatedKey"
        )

        if not last_key:
            break

        query_args["ExclusiveStartKey"] = last_key

    return sorted(
        items,
        key=lambda item: (
            item["timestamp"],
            item["eventId"],
        ),
    )


def query_by_type(
    event_type,
    start,
    end,
    table=None,
):
    """Consulta type + rango temporal mediante type-timestamp-index."""
    return _query_index(
        "type-timestamp-index",
        "type",
        event_type,
        start,
        end,
        table=table,
    )


def query_by_source(
    source,
    start,
    end,
    table=None,
):
    """Consulta source + rango temporal mediante source-timestamp-index."""
    return _query_index(
        "source-timestamp-index",
        "source",
        source,
        start,
        end,
        table=table,
    )