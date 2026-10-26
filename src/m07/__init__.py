"""Motor M07 de versionado, migración y recuperación sobre el contrato existente M06."""

from .migration import migrate_document, migrate_event
from .rollback import rollback_event
from .versioning import (
    SUPPORTED_SCHEMA_VERSIONS,
    TARGET_SCHEMA_VERSION,
    get_schema_version,
    validate_document,
)

__all__ = [
    "SUPPORTED_SCHEMA_VERSIONS",
    "TARGET_SCHEMA_VERSION",
    "get_schema_version",
    "migrate_document",
    "migrate_event",
    "rollback_event",
    "validate_document",
]