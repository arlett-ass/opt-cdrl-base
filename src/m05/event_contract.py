"""Contrato v1 de telemetría. No realiza escrituras ni modifica el argumento.

Las fechas se guardan UTC con seis decimales para ordenar los GSIs.
Las métricas se devuelven como Decimal, nunca float. La unicidad persistida
corresponde al create condicional del CRUD, no a este validador puro.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re


class EventValidationError(ValueError):
    """Documento incompatible con el contrato documental M05."""


_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)"
)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_BIGINT_MAX = 9223372036854775807


def _fields(value, expected, name):
    if not isinstance(value, dict):
        raise EventValidationError(f"{name} debe ser un objeto.")
    if set(value) != set(expected):
        raise EventValidationError(
            f"{name} debe contener exactamente: {', '.join(expected)}."
        )


def _positive_integer(value, name):
    # boto3 devuelve números de DynamoDB como Decimal, incluso los enteros.
    if type(value) is int:
        number = value
    elif isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value():
        number = value
    else:
        raise EventValidationError(f"{name} debe ser un entero positivo.")
    if not 1 <= number <= _BIGINT_MAX:
        raise EventValidationError(f"{name} debe estar entre 1 y {_BIGINT_MAX}.")
    return int(number)


def _parse_timestamp(value, name):
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise EventValidationError(f"{name} requiere ISO-8601 con zona y hasta 6 decimales.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise EventValidationError(f"{name} contiene una fecha o zona inválida.") from exc


def normalize_timestamp(value):
    """Acepta un instante ISO con zona; devuelve YYYY-MM-DDTHH:MM:SS.ffffffZ."""
    dt = _parse_timestamp(value, "timestamp")
    return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}T{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}.{dt.microsecond:06d}Z"


def build_event_id(device_id, timestamp):
    """Identidad por dispositivo e instante UTC; cálculo entero sin redondeo float."""
    device_id = _positive_integer(device_id, "payload.deviceId")
    delta = _parse_timestamp(timestamp, "timestamp") - _EPOCH
    micros = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
    return f"telemetry#{device_id}#{micros}"


def _metric(value, name, minimum, maximum):
    if type(value) not in (str, int, Decimal):
        raise EventValidationError(f"{name} debe ser decimal exacto; no se aceptan float/bool.")
    if isinstance(value, str) and not re.fullmatch(r"-?\d+(?:\.\d{1,2})?", value):
        raise EventValidationError(f"{name} requiere una cadena decimal con hasta 2 decimales.")
    try:
        number = Decimal(value)
        if not number.is_finite() or not Decimal(minimum) <= number <= Decimal(maximum):
            raise EventValidationError(f"{name} debe estar entre {minimum} y {maximum}.")
        normalized = number.quantize(Decimal("0.01"))
        if normalized != number:
            raise EventValidationError(f"{name} no puede perder precisión al usar 2 decimales.")
        return normalized
    except InvalidOperation as exc:
        raise EventValidationError(f"{name} no es un decimal válido.") from exc


def validate_event(event):
    """Valida v1 y devuelve un documento nuevo normalizado para boto3 resource.

    Se rechazan campos desconocidos para no persistir datos fuera del contrato.
    source debe corresponder a deviceId y eventId al instante normalizado.
    No comprueba existencia del dispositivo en PostgreSQL ni duplicados remotos.
    """
    _fields(event, ("eventId", "type", "source", "timestamp", "payload", "metadata"), "event")
    payload = event["payload"]
    _fields(payload, ("readingId", "deviceId", "receivedAt", "temperatureC", "humidityPct", "co2Ppm"), "payload")
    _fields(event["metadata"], ("schemaVersion",), "metadata")
    version = _positive_integer(event["metadata"]["schemaVersion"], "schemaVersion")
    if version != 1:
        raise EventValidationError("schemaVersion no soportada; se requiere 1.")
    if event["type"] != "telemetry.reading":
        raise EventValidationError("type debe ser telemetry.reading.")
    device_id = _positive_integer(payload["deviceId"], "payload.deviceId")
    reading_id = _positive_integer(payload["readingId"], "payload.readingId")
    timestamp = normalize_timestamp(event["timestamp"])
    received_at = normalize_timestamp(payload["receivedAt"])
    if received_at < timestamp:
        raise EventValidationError("receivedAt no puede ser anterior a timestamp.")
    event_id = build_event_id(device_id, timestamp)
    if event["eventId"] != event_id:
        raise EventValidationError("eventId debe coincidir con deviceId y timestamp normalizado.")
    source = f"device-{device_id}"
    if event["source"] != source:
        raise EventValidationError("source debe coincidir con device-{deviceId}.")
    return {
        "eventId": event_id,
        "type": "telemetry.reading",
        "source": source,
        "timestamp": timestamp,
        "payload": {
            "readingId": reading_id,
            "deviceId": device_id,
            "receivedAt": received_at,
            "temperatureC": _metric(payload["temperatureC"], "temperatureC", "-50", "80"),
            "humidityPct": _metric(payload["humidityPct"], "humidityPct", "0", "100"),
            "co2Ppm": _metric(payload["co2Ppm"], "co2Ppm", "0", "10000"),
        },
        "metadata": {"schemaVersion": version},
    }
