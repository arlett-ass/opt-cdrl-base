"""Evolución versionada de documentos para el hito M06."""

from .schema_evolution import (
    SUPPORTED_SCHEMA_VERSIONS,
    UnsupportedSchemaVersionError,
    VersionedEventError,
    migrate_v1_to_v2,
    validate_versioned_event,
)

__all__ = [
    "SUPPORTED_SCHEMA_VERSIONS",
    "UnsupportedSchemaVersionError",
    "VersionedEventError",
    "migrate_v1_to_v2",
    "validate_versioned_event",
]
