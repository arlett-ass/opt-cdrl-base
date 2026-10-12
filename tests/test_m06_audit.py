"""Prueba M06 de auditoría segura e idempotente."""

from copy import deepcopy
import json
from pathlib import Path

from botocore.exceptions import ClientError

from src.m06.audit_store import record_audit
from src.m06.audited_operations import (
    migrate_event_with_audit,
)
from src.m06.versioned_store import (
    create_versioned_event,
)


VERSIONED_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "m06_versioned_events.json"
)

AUDIT_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "m06_audit_cases.json"
)


class MemoryEventTable:
    """Sustituto mínimo de cdrl_events para probar la operación auditada."""

    def __init__(self):
        self.items = {}

    def get_item(self, *, Key, ConsistentRead):
        assert ConsistentRead is True

        item = self.items.get(Key["eventId"])

        return (
            {"Item": deepcopy(item)}
            if item is not None
            else {}
        )

    def put_item(
        self,
        *,
        Item,
        ConditionExpression,
        **kwargs,
    ):
        event_id = Item["eventId"]
        current = self.items.get(event_id)

        if (
            ConditionExpression
            == "attribute_not_exists(eventId)"
            and current is not None
        ):
            self._conditional_failure()

        expected_version = (
            kwargs
            .get("ExpressionAttributeValues", {})
            .get(":from_version")
        )

        if expected_version is not None:
            if (
                current is None
                or current.get("metadata", {}).get(
                    "schemaVersion"
                )
                != expected_version
            ):
                self._conditional_failure()

        self.items[event_id] = deepcopy(Item)

        return {}

    @staticmethod
    def _conditional_failure():
        raise ClientError(
            {
                "Error": {
                    "Code": "ConditionalCheckFailedException",
                    "Message": "synthetic conditional failure",
                }
            },
            "PutItem",
        )


class MemoryAuditTable:
    """Sustituto mínimo de cdrl_audit_log."""

    def __init__(self):
        self.items = {}

    def put_item(
        self,
        *,
        Item,
        ConditionExpression,
    ):
        assert (
            ConditionExpression
            == "attribute_not_exists(auditId)"
        )

        audit_id = Item["auditId"]

        if audit_id in self.items:
            raise ClientError(
                {
                    "Error": {
                        "Code": "ConditionalCheckFailedException",
                        "Message": "synthetic duplicate audit",
                    }
                },
                "PutItem",
            )

        self.items[audit_id] = deepcopy(Item)

        return {}


def test_audit_redacts_secrets_and_retry_does_not_duplicate():
    versioned_events = json.loads(
        VERSIONED_FIXTURE.read_text(
            encoding="utf-8"
        )
    )

    audit_case = json.loads(
        AUDIT_FIXTURE.read_text(
            encoding="utf-8"
        )
    )

    event_table = MemoryEventTable()
    audit_table = MemoryAuditTable()

    original = versioned_events["v1"]

    create_versioned_event(
        original,
        table=event_table,
    )

    first = migrate_event_with_audit(
        original["eventId"],
        trace_id=audit_case["traceId"],
        event_table=event_table,
        audit_table=audit_table,
        audit_context=audit_case["auditContext"],
        occurred_at="2026-10-09T20:00:00.000000Z",
    )

    assert first["changed"] is True
    assert first["auditCreated"] is True
    assert first["event"]["metadata"]["schemaVersion"] == 2

    assert len(audit_table.items) == 1

    persisted = next(
        iter(audit_table.items.values())
    )

    serialized = json.dumps(
        persisted,
        sort_keys=True,
    )

    # Ningún valor sensible sintético puede persistirse.
    for sensitive_value in audit_case["sensitiveValues"]:
        assert sensitive_value not in serialized

    # Las claves pueden permanecer para dar contexto,
    # pero sus valores deben estar redactados.
    assert (
        persisted["context"]["password"]
        == "[REDACTED]"
    )
    assert (
        persisted["context"]["token"]
        == "[REDACTED]"
    )
    assert (
        persisted["context"]["nested"]["secret"]
        == "[REDACTED]"
    )
    assert (
        persisted["context"]["headers"]["Authorization"]
        == "[REDACTED]"
    )
    assert (
        persisted["context"]["apiKey"]
        == "[REDACTED]"
    )
    assert (
        persisted["context"]["connectionString"]
        == "[REDACTED]"
    )

    # No se copian documentos completos before/after.
    assert "before" not in persisted
    assert "after" not in persisted

    # Campos operativos requeridos por la auditoría M06.
    assert persisted["eventId"] == original["eventId"]
    assert persisted["actorId"] == "system:m06-migrator"
    assert persisted["action"] == "schema.migrate.v1_to_v2"
    assert persisted["entity"] == "cdrl_events"
    assert persisted["traceId"] == audit_case["traceId"]
    assert persisted["result"] == "ok"
    assert persisted["reason"] == "schema_version_upgrade"

    assert persisted["fromVersion"] == 1
    assert persisted["toVersion"] == 2

    assert "metadata.schemaVersion" in persisted["changedFields"]
    assert "payload.measurements" in persisted["changedFields"]

    audit_id = persisted["auditId"]

    # También comprobamos directamente la escritura condicional:
    # intentar registrar exactamente la misma auditoría devuelve False.
    duplicate_created = record_audit(
        first["auditRecord"],
        table=audit_table,
    )

    assert duplicate_created is False
    assert len(audit_table.items) == 1

    # Segundo intento de migración:
    # como el evento ya está en v2, debe ser un no-op.
    second = migrate_event_with_audit(
        original["eventId"],
        trace_id=audit_case["traceId"],
        event_table=event_table,
        audit_table=audit_table,
        audit_context=audit_case["auditContext"],
        occurred_at="2026-10-09T20:01:00.000000Z",
    )

    assert second["changed"] is False
    assert second["auditCreated"] is False
    assert second["auditRecord"] is None

    assert len(audit_table.items) == 1
    assert audit_id in audit_table.items