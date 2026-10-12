"""Validación y migración pura entre las versiones v1 y v2 de telemetría.

M05 conserva el contrato v1. M06 acepta ese contrato y la versión v2, que
agrupa las mediciones en ``payload.measurements``. Las claves utilizadas por
la tabla y sus GSIs permanecen en el nivel superior del documento.
"""

from copy import deepcopy
from decimal import Decimal

from src.m05.event_contract import EventValidationError, validate_event


SUPPORTED_SCHEMA_VERSIONS = (1, 2)
_MEASUREMENT_FIELDS = ("temperatureC", "humidityPct", "co2Ppm")


class VersionedEventError(EventValidationError):
    """Evento versionado que no cumple el contrato M06."""


class UnsupportedSchemaVersionError(VersionedEventError):
    """El evento declara una versión de esquema que M06 no reconoce."""


def _schema_version(event):
    if not isinstance(event, dict):
        raise VersionedEventError("event debe ser un objeto.")

    metadata = event.get("metadata")
    if not isinstance(metadata, dict) or set(metadata) != {"schemaVersion"}:
        raise VersionedEventError(
            "metadata debe contener únicamente schemaVersion."
        )

    raw_version = metadata["schemaVersion"]
    if type(raw_version) is int:
        version = raw_version
    elif (
        isinstance(raw_version, Decimal)
        and raw_version.is_finite()
        and raw_version == raw_version.to_integral_value()
    ):
        version = int(raw_version)
    else:
        raise VersionedEventError("schemaVersion debe ser un entero.")

    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchemaVersionError(
            f"schemaVersion no soportada: {version}. "
            "Versiones admitidas: "
            f"{', '.join(map(str, SUPPORTED_SCHEMA_VERSIONS))}."
        )
    return version


def _require_fields(value, expected, name):
    if not isinstance(value, dict):
        raise VersionedEventError(f"{name} debe ser un objeto.")
    if set(value) != set(expected):
        raise VersionedEventError(
            f"{name} debe contener exactamente: {', '.join(expected)}."
        )


def _as_v1_candidate(event):
    """Expresa v2 temporalmente como v1 para reutilizar sus invariantes."""
    _require_fields(
        event,
        ("eventId", "type", "source", "timestamp", "payload", "metadata"),
        "event",
    )
    payload = event["payload"]
    _require_fields(
        payload,
        ("readingId", "deviceId", "receivedAt", "measurements"),
        "payload",
    )
    measurements = payload["measurements"]
    _require_fields(measurements, _MEASUREMENT_FIELDS, "payload.measurements")

    return {
        "eventId": event["eventId"],
        "type": event["type"],
        "source": event["source"],
        "timestamp": event["timestamp"],
        "payload": {
            "readingId": payload["readingId"],
            "deviceId": payload["deviceId"],
            "receivedAt": payload["receivedAt"],
            **measurements,
        },
        "metadata": {"schemaVersion": 1},
    }


def _v2_from_normalized_v1(event):
    payload = event["payload"]
    return {
        "eventId": event["eventId"],
        "type": event["type"],
        "source": event["source"],
        "timestamp": event["timestamp"],
        "payload": {
            "readingId": payload["readingId"],
            "deviceId": payload["deviceId"],
            "receivedAt": payload["receivedAt"],
            "measurements": {
                field: payload[field]
                for field in _MEASUREMENT_FIELDS
            },
        },
        "metadata": {"schemaVersion": 2},
    }


def validate_versioned_event(event):
    """Valida y normaliza un evento v1 o v2 sin modificar el argumento.

    La validación v1 reutiliza el contrato M05. Para v2, el documento se
    expresa como v1 de forma temporal, lo que aplica las mismas reglas de
    identidad, timestamps y rangos de medición antes de reconstruir v2.
    """
    version = _schema_version(event)
    if version == 1:
        return validate_event(event)

    normalized_v1 = validate_event(_as_v1_candidate(event))
    return _v2_from_normalized_v1(normalized_v1)


def migrate_v1_to_v2(event):
    """Convierte v1 a v2; v2 produce un no-op equivalente e inmutable.

    La función es pura: devuelve un documento nuevo, conserva identidad y
    datos de negocio, y rechaza explícitamente cualquier versión desconocida.
    """
    normalized = validate_versioned_event(event)
    if normalized["metadata"]["schemaVersion"] == 2:
        return deepcopy(normalized)
    return _v2_from_normalized_v1(normalized)
