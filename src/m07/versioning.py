"""Contrato M07 compartido con M06 para documentos de telemetría v1/v2.

La v1 conserva las métricas directamente en ``payload``; la v2 las agrupa
en ``payload.measurements``. La identidad y las claves de los índices no
cambian. M06 sigue siendo la fuente de las reglas de validación.
"""

from src.m05.event_contract import EventValidationError
from src.m06.schema_evolution import (
    SUPPORTED_SCHEMA_VERSIONS,
    UnsupportedSchemaVersionError,
    VersionedEventError,
    validate_versioned_event,
)


TARGET_SCHEMA_VERSION = 2

__all__ = [
    "EventValidationError",
    "SUPPORTED_SCHEMA_VERSIONS",
    "TARGET_SCHEMA_VERSION",
    "UnsupportedSchemaVersionError",
    "VersionedEventError",
    "get_schema_version",
    "validate_document",
]


def validate_document(document):
    """Devuelve una copia normalizada v1/v2 sin modificar el argumento.

    Reutiliza las invariantes de M06: campos exactos, versión explícita,
    identidad determinista, timestamps UTC y métricas ``Decimal``. Una
    versión desconocida se rechaza antes de cualquier escritura.
    """
    return validate_versioned_event(document)


def get_schema_version(document):
    """Obtiene la versión de un documento que cumple el contrato completo.

    No basta con declarar ``schemaVersion = 2``: también se valida que la
    estructura y los datos correspondan a esa versión.
    """
    return validate_document(document)["metadata"]["schemaVersion"]
