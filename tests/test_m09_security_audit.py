"""Pruebas de persistencia, privacidad y compatibilidad de auditoría M09/M06."""

from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import json
from uuid import uuid4

from botocore.exceptions import ClientError
import pytest

from src.m06.audit_store import (
    build_audit_record, record_audit, sanitize_audit_context, ensure_audit_table,
)
from src.m05.dynamodb_client import get_dynamodb_client, get_dynamodb_resource
from src.m09.security_audit import (
    SecurityAuditRecordError, SecurityAuditSink, create_security_audit_sink,
    validate_security_audit_record,
)


FIXTURE = Path(__file__).parent / "fixtures" / "m09_security_cases.json"


class MemoryAuditTable:
    """Tabla aislada; impide sobrescribir auditId, como DynamoDB."""

    def __init__(self):
        self.items = {}
        self.calls = []

    def put_item(self, *, Item, ConditionExpression):
        assert ConditionExpression == "attribute_not_exists(auditId)"
        self.calls.append(deepcopy(Item))
        if Item["auditId"] in self.items:
            raise ClientError({
                "Error": {
                    "Code": "ConditionalCheckFailedException",
                    "Message": "synthetic duplicate",
                },
            }, "PutItem")
        self.items[Item["auditId"]] = deepcopy(Item)
        return {}


def _record(*, result="denied", reason="permission_denied", attempt_id=None):
    return {
        "auditId": str(uuid4()),
        "attemptId": attempt_id or str(uuid4()),
        "actorId": "test-reader",
        "role": "cdrl_reader",
        "action": "DeleteItem",
        "resource": "cdrl_events",
        "result": result,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
    }


def test_security_audit_sink_writes_conditional_record_without_mutating_input():
    table = MemoryAuditTable()
    sink = create_security_audit_sink(table=table)
    record = _record()
    original = deepcopy(record)
    assert sink(record) is True
    assert record == original
    assert len(table.items) == 1
    assert table.items[record["auditId"]] == original


def test_duplicate_audit_id_never_overwrites_existing_security_log():
    table = MemoryAuditTable()
    sink = SecurityAuditSink(table=table)
    record = _record()
    assert sink(record) is True
    altered = dict(record, actorId="test-other")
    assert sink(altered) is False
    assert len(table.items) == 1
    assert table.items[record["auditId"]]["actorId"] == "test-reader"


@pytest.mark.parametrize("extra", [
    {"password": "synthetic-password-never-save"},
    {"context": {"secret": "synthetic-token-never-save"}},
    {"payload": {"credential": "synthetic-token-never-save"}},
    {"exception": "synthetic-private-exception"},
    {"eventId": "client-provided-arbitrary-identifier"},
])
def test_unexpected_client_details_cannot_be_persisted(extra):
    table = MemoryAuditTable()
    record = {**_record(), **extra}
    with pytest.raises(SecurityAuditRecordError):
        SecurityAuditSink(table=table)(record)
    assert table.items == {}
    assert table.calls == []


@pytest.mark.parametrize("field,value", [
    ("auditId", "not-a-uuid"),
    ("attemptId", None),
    ("role", "administrator"),
    ("action", "DropTable"),
    ("resource", "private-tokens"),
    ("result", "passed"),
    ("reason", "some arbitrary client text"),
    ("timestamp", "2026-11-06T12:00:00"),
    ("timestamp", "2026-11-06 12:00:00Z"),
    ("timestamp", "2026-11-06T12:00:00+02:00"),
    ("actorId", "Bearer synthetic-token"),
    ("actorId", "Basic synthetic-credentials"),
])
def test_invalid_audit_format_is_denied_before_persistence(field, value):
    record = _record()
    record[field] = value
    table = MemoryAuditTable()
    with pytest.raises(SecurityAuditRecordError):
        SecurityAuditSink(table=table)(record)
    assert table.calls == []


@pytest.mark.parametrize("result,reason", [
    ("attempt", "authorized_attempt"),
    ("success", "operation_completed"),
    ("error", "operation_failed"),
    ("denied", "untrusted_identity"),
])
def test_all_agreed_security_results_are_accepted(result, reason):
    record = _record(result=result, reason=reason)
    assert validate_security_audit_record(record) == record


def test_each_emission_can_keep_attempt_id_but_has_distinct_audit_id():
    table = MemoryAuditTable()
    sink = SecurityAuditSink(table=table)
    attempt = str(uuid4())
    before = _record(result="attempt", reason="authorized_attempt", attempt_id=attempt)
    after = _record(result="success", reason="operation_completed", attempt_id=attempt)
    assert before["auditId"] != after["auditId"]
    assert sink(before) is True
    assert sink(after) is True
    assert len(table.items) == 2
    assert {r["attemptId"] for r in table.items.values()} == {attempt}


def test_sensitive_keys_are_sanitized_recursively_by_existing_m06_utility():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    secret_context = fixture["synthetic_secrets"]
    safe = sanitize_audit_context(secret_context)
    assert safe["password"] == "[REDACTED]"
    assert safe["Authorization"] == "[REDACTED]"
    assert safe["nested"]["api_key"] == "[REDACTED]"
    assert not any(
        secret in json.dumps(safe)
        for secret in ("synthetic-password-never-save",
                       "synthetic-token-never-save", "synthetic-api-key-never-save")
    )


def test_m06_migration_audit_and_m09_security_audit_coexist_without_schema_changes():
    table = MemoryAuditTable()
    old = build_audit_record(
        "synthetic-migration-event",
        action="schema.migrate.v1_to_v2",
        trace_id="synthetic-trace-1",
        from_version=1,
        to_version=2,
        changed_fields=["metadata.schemaVersion"],
        context={"token": "synthetic-secret-never-save"},
    )
    assert record_audit(old, table=table) is True
    assert record_audit(old, table=table) is False
    new = _record()
    assert SecurityAuditSink(table=table)(new) is True
    assert len(table.items) == 2
    assert table.items[old["auditId"]]["fromVersion"] == 1
    assert "fromVersion" not in table.items[new["auditId"]]
    assert table.items[old["auditId"]]["context"]["token"] == "[REDACTED]"


def test_fixture_declares_expected_audit_contract():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(fixture["expected_audit_fields"]) == set(_record())
    assert len(fixture["permission_cases"]) >= 4


def test_security_audit_is_durable_and_append_only_in_dynamodb_local():
    """Integración real aislada: el servicio escribe en tabla DynamoDB Local."""
    if os.environ.get("DYNAMODB_LOCAL", "").strip().lower() != "true":
        pytest.skip("Prueba de integración solo con DYNAMODB_LOCAL=true.")
    client = get_dynamodb_client()
    name = "cdrl_m09_audit_test_" + uuid4().hex[:16]
    ensure_audit_table(client=client, table_name=name, attempts=100, poll_seconds=0.05)
    table = get_dynamodb_resource().Table(name)
    try:
        sink = SecurityAuditSink(table=table)
        record = _record()
        assert sink(record) is True
        assert table.get_item(Key={"auditId": record["auditId"]}, ConsistentRead=True)["Item"] == record
        assert sink(dict(record, actorId="test-other")) is False
        assert table.get_item(Key={"auditId": record["auditId"]}, ConsistentRead=True)["Item"] == record
    finally:
        client.delete_table(TableName=name)
        client.get_waiter("table_not_exists").wait(
            TableName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 10},
        )


def test_dynamodb_error_is_not_reported_as_success():
    """Un error de DynamoDB no debe contarse como auditoría guardada."""

    class FailingAuditTable:
        def put_item(self, *, Item, ConditionExpression):
            raise ClientError(
                {
                    "Error": {
                        "Code": "ServiceUnavailable",
                        "Message": "Synthetic service failure",
                    }
                },
                "PutItem",
            )

    sink = SecurityAuditSink(table=FailingAuditTable())

    with pytest.raises(ClientError) as error:
        sink(_record())

    assert (
        error.value.response["Error"]["Code"]
        == "ServiceUnavailable"
    )