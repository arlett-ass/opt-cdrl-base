"""Consulta de una página sobre el GSI type-timestamp-index existente.

M05 conserva ``query_by_type()`` y su retorno de lista completa como línea
base. Esta API nueva realiza un solo Query por llamada, sin Scan, offset,
recorrido automático ni ordenamiento posterior de los elementos.

Contrato para integrar el benchmark y el verificador del equipo:

* ``page_size`` es un int entre 1 y 1000; su valor predeterminado es 20.
  El tope 1000 es una política de esta API, no un límite de DynamoDB.
  Es un máximo por solicitud, no una garantía de llenar la página.
* El retorno contiene ``items`` y ``next_cursor``. Este último es None si
  DynamoDB no devuelve LastEvaluatedKey. Una página corta o vacía con cursor
  todavía puede continuarse; el cursor no garantiza más coincidencias.
* El cursor es un dict serializable en JSON, con ``version = 1``, ``query``
  (event_type, start, end normalizados) y ``last_evaluated_key``. La clave
  nativa completa se conserva y se envía intacta como ExclusiveStartKey.
* El cursor se reutiliza con los mismos filtros y la misma tabla. Se permite
  cambiar page_size. Se valida su forma y contexto, no su autenticidad ni
  la existencia actual del elemento. No es un token firmado.
* Se respeta el orden por timestamp del GSI. Los empates no ofrecen un
  desempate global por eventId. Los documentos v1/v2 se devuelven intactos.
* El GSI es eventualmente consistente y no proporciona un snapshot. Una
  inserción anterior a la posición del cursor puede quedar fuera del resto
  del recorrido; una posterior puede aparecer cuando se propague al índice.
  Las pruebas de continuidad sin cambios esperan antes la propagación.

La API usa la configuración y tabla de M05 cuando no se inyecta ``table``.
Los errores de entrada son ValueError/InvalidCursorError; los errores del
servicio se propagan, sin ocultarlos como una página vacía.
"""

from copy import deepcopy

from boto3.dynamodb.conditions import Key

from src.m05.dynamodb_client import get_table
from src.m05.event_contract import normalize_timestamp


DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 1000
_CURSOR_VERSION = 1
_CURSOR_FIELDS = {"version", "query", "last_evaluated_key"}
_KEY_FIELDS = {"eventId", "type", "timestamp"}


class InvalidCursorError(ValueError):
    """Cursor mal formado o que pertenece a otros filtros de consulta."""


def _exclusive_start_key(cursor, query):
    if not isinstance(cursor, dict) or set(cursor) != _CURSOR_FIELDS:
        raise InvalidCursorError("El cursor debe contener version, query y last_evaluated_key.")
    if type(cursor["version"]) is not int or cursor["version"] != _CURSOR_VERSION:
        raise InvalidCursorError("Versión de cursor no soportada.")
    if not isinstance(cursor["query"], dict) or cursor["query"] != query:
        raise InvalidCursorError("El cursor no corresponde al tipo y rango solicitados.")

    key = cursor["last_evaluated_key"]
    if (
        not isinstance(key, dict)
        or set(key) != _KEY_FIELDS
        or any(not isinstance(value, str) or not value.strip() for value in key.values())
    ):
        raise InvalidCursorError("La clave del cursor requiere eventId, type y timestamp no vacíos.")
    if key["type"] != query["event_type"]:
        raise InvalidCursorError("El tipo de la clave no corresponde a la consulta.")
    try:
        # Se comprueba el formato sin cambiar la representación de la clave:
        # ExclusiveStartKey debe recibir exactamente la que entregó DynamoDB.
        normalize_timestamp(key["timestamp"])
    except ValueError as exc:
        raise InvalidCursorError("El timestamp del cursor no es válido.") from exc
    if not query["start"] <= key["timestamp"] <= query["end"]:
        raise InvalidCursorError("La clave del cursor está fuera del rango solicitado.")
    return deepcopy(key)


def query_by_type_page(
    event_type,
    start,
    end,
    *,
    page_size=DEFAULT_PAGE_SIZE,
    cursor=None,
    table=None,
):
    """Devuelve ``{'items': [...], 'next_cursor': dict | None}`` con un solo Query.

    ``cursor=None`` inicia el recorrido. Para continuar, conservar next_cursor
    y suministrarlo con los mismos filtros y tabla. El consumidor decide cuándo
    pedir la siguiente página. Las fechas admiten el mismo formato de M05 y
    sus extremos son inclusivos. La tabla y ambos GSIs existentes no cambian.
    """
    if not isinstance(event_type, str) or not event_type.strip():
        raise ValueError("event_type debe ser una cadena no vacía.")
    if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size debe ser un entero entre 1 y {MAX_PAGE_SIZE}.")

    normalized_start = normalize_timestamp(start)
    normalized_end = normalize_timestamp(end)
    if normalized_start > normalized_end:
        raise ValueError("start no puede ser posterior a end.")
    query = {
        "event_type": event_type,
        "start": normalized_start,
        "end": normalized_end,
    }
    kwargs = {
        "IndexName": "type-timestamp-index",
        "KeyConditionExpression": (
            Key("type").eq(event_type)
            & Key("timestamp").between(normalized_start, normalized_end)
        ),
        "ScanIndexForward": True,
        "Limit": page_size,
    }
    if cursor is not None:
        kwargs["ExclusiveStartKey"] = _exclusive_start_key(cursor, query)

    table = table if table is not None else get_table()
    response = table.query(**kwargs)
    last_key = response.get("LastEvaluatedKey")
    next_cursor = None
    if last_key:
        next_cursor = {
            "version": _CURSOR_VERSION,
            "query": query,
            "last_evaluated_key": deepcopy(last_key),
        }
    return {"items": deepcopy(response.get("Items", [])), "next_cursor": next_cursor}
