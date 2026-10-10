"""Operaciones M06 que combinan evolución de esquema y auditoría segura."""

from .audit_store import (
    build_audit_record,
    record_audit,
)
from .versioned_store import (
    VersionedEventNotFoundError,
    get_versioned_event,
    migrate_event_to_v2,
)


_MIGRATION_CHANGED_FIELDS = [
    "metadata.schemaVersion",
    "payload.temperatureC",
    "payload.humidityPct",
    "payload.co2Ppm",
    "payload.measurements",
]


def migrate_event_with_audit(
    event_id,
    *,
    trace_id,
    event_table=None,
    audit_table=None,
    audit_context=None,
    occurred_at=None,
):
    """Migra un evento v1 a v2 y registra auditoría si hubo cambio real.

    Si el evento ya está en v2, la operación es idempotente:
    no vuelve a persistirlo ni crea otra entrada de auditoría.
    """
    current = get_versioned_event(
        event_id,
        table=event_table,
    )

    if current is None:
        raise VersionedEventNotFoundError(
            f"El evento {event_id} no existe."
        )

    from_version = current["metadata"]["schemaVersion"]

    if from_version == 2:
        return {
            "event": current,
            "changed": False,
            "auditCreated": False,
            "auditRecord": None,
        }

    migrated = migrate_event_to_v2(
        event_id,
        table=event_table,
    )

    record = build_audit_record(
        event_id,
        action="schema.migrate.v1_to_v2",
        trace_id=trace_id,
        from_version=1,
        to_version=2,
        changed_fields=_MIGRATION_CHANGED_FIELDS,
        result="ok",
        reason="schema_version_upgrade",
        actor_id="system:m06-migrator",
        entity="cdrl_events",
        timestamp=occurred_at,
        context=audit_context,
    )

    audit_created = record_audit(
        record,
        table=audit_table,
    )

    return {
        "event": migrated,
        "changed": True,
        "auditCreated": audit_created,
        "auditRecord": record,
    }