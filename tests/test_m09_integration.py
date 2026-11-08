"""David M09: autorización y auditoría persistente sobre DynamoDB Local.

Se usan tablas temporales propias y el sink real de Angélica con la fachada
de Víctor. La identidad técnica del fixture inspecciona el estado; los roles
de usuario solo acceden mediante SecureOperations. No se verifica AWS IAM.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import time
from uuid import UUID, uuid4

from botocore.exceptions import ClientError
import pytest

from src.m05.document_store import DuplicateEventError, query_by_type
from src.m05.dynamodb_client import get_dynamodb_client, get_dynamodb_resource
from src.m05.event_contract import build_event_id, validate_event
from src.m05.table_setup import ensure_table
from src.m06.audit_store import build_audit_record, ensure_audit_table, record_audit
from src.m06.schema_evolution import migrate_v1_to_v2
from src.m08.pagination import InvalidCursorError
from src.m09.authorization import IdentityRegistry
from src.m09.policy import AUDIT, EVENTS, ROLES
from src.m09.secure_operations import (
    AccessDeniedError, AuditUnavailableError, SecureOperations,
)
from src.m09.security_audit import SecurityAuditSink


CASES = json.loads((Path(__file__).parent / "fixtures" / "m09_security_cases.json").read_text(encoding="utf-8"))
START = "2026-11-08T10:00:00.000000Z"
END = "2026-11-08T10:10:00.000000Z"
EVENT_TYPE = "telemetry.reading"


def _event(index=0, version=1):
    device = 9900 + index
    timestamp = f"2026-11-08T10:0{index}:00.000000Z"
    event = validate_event({
        "eventId": build_event_id(device, timestamp),
        "type": EVENT_TYPE,
        "source": f"device-{device}",
        "timestamp": timestamp,
        "payload": {
            "readingId": device, "deviceId": device, "receivedAt": timestamp,
            "temperatureC": "23.45", "humidityPct": "51.20", "co2Ppm": "650.00",
        },
        "metadata": {"schemaVersion": 1},
    })
    return migrate_v1_to_v2(event) if version == 2 else event


def _rows(table, key):
    """Inspección técnica consistente, incluso si Scan requiere varias páginas."""
    items = []
    request = {"ConsistentRead": True}
    while True:
        page = table.scan(**request)
        items.extend(page.get("Items", []))
        if not page.get("LastEvaluatedKey"):
            return {item[key]: item for item in items}
        request["ExclusiveStartKey"] = page["LastEvaluatedKey"]


class EventProbe:
    """Observa llamadas y las reenvía al backend real; no simula el CRUD."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def __getattr__(self, name):
        operation = getattr(self.table, name)
        if name not in {"get_item", "put_item", "query", "scan", "update_item", "delete_item"}:
            return operation

        def observed(**kwargs):
            self.calls.append(name)
            return operation(**kwargs)

        return observed


@dataclass
class IntegrationLab:
    events: object
    audit: object
    registry: IdentityRegistry
    users: dict
    probe: EventProbe
    service: SecureOperations

    def records(self):
        records = list(_rows(self.audit, "auditId").values())
        assert len({r["auditId"] for r in records}) == len(records)
        for record in records:
            assert set(record) == set(CASES["expected_audit_fields"])
            assert str(UUID(record["auditId"])) == record["auditId"]
            assert str(UUID(record["attemptId"])) == record["attemptId"]
            assert record["timestamp"].endswith("Z")
            assert datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00")).utcoffset().total_seconds() == 0
        return sorted(records, key=lambda record: record["timestamp"])


@pytest.fixture
def lab():
    if os.environ.get("DYNAMODB_LOCAL", "").strip().lower() != "true":
        pytest.skip("Estas pruebas requieren DYNAMODB_LOCAL=true explícito; no se ejecutan contra AWS.")
    client = get_dynamodb_client()
    resource = get_dynamodb_resource()
    suffix = uuid4().hex
    names = []
    try:
        events_name = f"cdrl_m09_david_events_{suffix}"
        audit_name = f"cdrl_m09_david_audit_{suffix}"
        names.append(events_name)
        ensure_table(client=client, table_name=events_name, attempts=100, poll_seconds=0.05)
        names.append(audit_name)
        ensure_audit_table(client=client, table_name=audit_name, attempts=100, poll_seconds=0.05)
        events, audit = resource.Table(events_name), resource.Table(audit_name)
        registry = IdentityRegistry({f"test-david-{role}": role for role in ROLES})
        users = {role: registry.identity_for_verified_subject(f"test-david-{role}") for role in ROLES}
        probe = EventProbe(events)
        service = SecureOperations(registry=registry, table=probe, audit_sink=SecurityAuditSink(table=audit))
        yield IntegrationLab(events, audit, registry, users, probe, service)
    finally:
        # Los nombres son exclusivos de esta invocación, nunca tablas del proyecto.
        errors = []
        for name in reversed(names):
            try:
                client.delete_table(TableName=name)
                client.get_waiter("table_not_exists").wait(
                    TableName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 10},
                )
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                    errors.append(exc)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise RuntimeError("No se pudieron limpiar todas las tablas temporales M09.") from errors[0]


def _assert_attempt(records, *, role, action, results, resource=EVENTS):
    assert [record["result"] for record in records] == results
    assert len({record["attemptId"] for record in records}) == 1
    reasons = {"attempt": "authorized_attempt", "success": "operation_completed", "error": "operation_failed", "denied": "permission_denied"}
    for record in records:
        assert record["role"] == role
        assert record["actorId"] == f"test-david-{role}"
        assert record["action"] == action
        assert record["resource"] == resource
        assert record["reason"] == reasons[record["result"]]


@pytest.mark.parametrize("version", [1, 2], ids=["v1", "v2"])
def test_normal_writer_reader_persists_event_and_security_audit(lab, version):
    event = _event(version=version)
    original = deepcopy(event)
    assert lab.service.create_event(lab.users["cdrl_writer"], event) == event
    assert lab.service.get_event(lab.users["cdrl_reader"], event["eventId"]) == event
    assert event == original
    assert _rows(lab.events, "eventId") == {event["eventId"]: event}
    records = lab.records()
    assert len(records) == 4
    assert len({record["attemptId"] for record in records}) == 2
    for role, action in [("cdrl_writer", "PutItem"), ("cdrl_reader", "GetItem")]:
        _assert_attempt([r for r in records if r["action"] == action], role=role, action=action, results=["attempt", "success"])


@pytest.mark.parametrize("role,action", [
    ("cdrl_reader", "PutItem"), ("cdrl_reader", "UpdateItem"),
    ("cdrl_writer", "GetItem"), ("cdrl_operator", "GetItem"),
    ("cdrl_migrator", "Query"),
])
def test_boundary_forbidden_event_access_never_reaches_backend(lab, role, action):
    event = _event()
    lab.events.put_item(Item=event)
    before = _rows(lab.events, "eventId")
    methods = {
        "PutItem": lambda: lab.service.create_event(lab.users[role], _event(1)),
        "UpdateItem": lambda: lab.service.update_event(lab.users[role], event["eventId"], {"payload": {"temperatureC": "1.00"}}),
        "GetItem": lambda: lab.service.get_event(lab.users[role], event["eventId"]),
        "Query": lambda: lab.service.query_by_type_page(lab.users[role], EVENT_TYPE, START, END),
    }
    with pytest.raises(AccessDeniedError):
        methods[action]()
    assert lab.probe.calls == []
    assert _rows(lab.events, "eventId") == before
    _assert_attempt(lab.records(), role=role, action=action, results=["denied"])


@pytest.mark.parametrize("role", ROLES)
def test_declared_failure_delete_is_denied_and_document_survives(lab, role):
    event = _event()
    lab.events.put_item(Item=event)
    with pytest.raises(AccessDeniedError):
        lab.service.delete_event(lab.users[role], event["eventId"])
    assert lab.probe.calls == []
    assert _rows(lab.events, "eventId") == {event["eventId"]: event}
    _assert_attempt(lab.records(), role=role, action="DeleteItem", results=["denied"])


@pytest.mark.parametrize("role", ROLES)
def test_boundary_audit_access_denied_without_altering_previous_logs(lab, role):
    # Sembrar un log real y comprobar que cada intento solo agrega su denegación.
    lab.service.get_event(lab.users["cdrl_reader"], "missing-event")
    original = _rows(lab.audit, "auditId")
    target_id = next(iter(original))
    operations = [
        ("GetItem", lambda: lab.service.read_audit(lab.users[role], target_id)),
        ("PutItem", lambda: lab.service.write_audit(lab.users[role], {"auditId": target_id, "result": "forged"})),
        ("UpdateItem", lambda: lab.service.update_audit(lab.users[role], target_id, {"result": "forged"})),
        ("DeleteItem", lambda: lab.service.delete_audit(lab.users[role], target_id)),
    ]
    lab.probe.calls.clear()
    for action, operation in operations:
        before = _rows(lab.audit, "auditId")
        with pytest.raises(AccessDeniedError):
            operation()
        after = _rows(lab.audit, "auditId")
        assert all(after[key] == value for key, value in before.items())
        new = [value for key, value in after.items() if key not in before]
        _assert_attempt(new, role=role, action=action, resource=AUDIT, results=["denied"])
    records = lab.records()
    assert len(records) == len(original) + 4
    assert len({r["attemptId"] for r in records}) == 5
    assert lab.probe.calls == []
    assert _rows(lab.events, "eventId") == {}


@pytest.mark.parametrize("kind", ["unknown", "role-string", "client-dict", "foreign-registry"])
def test_unknown_or_forged_identity_is_denied_and_audited(lab, kind):
    identity = {
        "unknown": lab.registry.identity_for_verified_subject("unregistered-subject"),
        "role-string": "cdrl_reader",
        "client-dict": {"role": "cdrl_reader", "actorId": "test-david-cdrl_reader"},
        "foreign-registry": IdentityRegistry({"test-david-cdrl_reader": "cdrl_reader"}).identity_for_verified_subject("test-david-cdrl_reader"),
    }[kind]
    with pytest.raises(AccessDeniedError):
        lab.service.get_event(identity, "missing-event")
    assert lab.probe.calls == []
    assert _rows(lab.events, "eventId") == {}
    records = lab.records()
    assert len(records) == 1
    assert records[0]["actorId"] == records[0]["role"] == "unknown"
    assert records[0]["result"] == "denied"
    assert records[0]["reason"] == "untrusted_identity"
    assert records[0]["action"] == "GetItem"
    assert records[0]["resource"] == EVENTS


def test_operator_only_receives_safe_summary_with_durable_audit(lab):
    event = _event(version=2)
    lab.events.put_item(Item=event)
    result = lab.service.get_operational_summary(lab.users["cdrl_operator"], event["eventId"])
    assert result == {"eventId": event["eventId"], "type": EVENT_TYPE}
    assert _rows(lab.events, "eventId") == {event["eventId"]: event}
    _assert_attempt(lab.records(), role="cdrl_operator", action="ReadOperationalSummary", results=["attempt", "success"])


@pytest.mark.parametrize("version", [1, 2], ids=["v1", "v2"])
def test_duplicate_write_keeps_original_and_persists_error_without_secrets(lab, version):
    original = _event(version=version)
    lab.service.create_event(lab.users["cdrl_writer"], original)
    changed = deepcopy(original)
    payload = changed["payload"] if version == 1 else changed["payload"]["measurements"]
    payload["temperatureC"] = "24.00"
    with pytest.raises(DuplicateEventError):
        lab.service.create_event(lab.users["cdrl_writer"], changed)
    assert _rows(lab.events, "eventId") == {original["eventId"]: original}
    records = lab.records()
    assert len(records) == 4
    assert len({r["attemptId"] for r in records}) == 2
    _assert_attempt(records[2:], role="cdrl_writer", action="PutItem", results=["attempt", "error"])
    assert original["eventId"] not in json.dumps(records)


def test_missing_event_is_audited_without_inventing_a_document(lab):
    assert lab.service.get_event(lab.users["cdrl_reader"], "missing-event") is None
    assert _rows(lab.events, "eventId") == {}
    _assert_attempt(lab.records(), role="cdrl_reader", action="GetItem", results=["attempt", "success"])


def test_mixed_versions_paginate_without_omissions_and_audit_each_page(lab):
    events = [_event(index, 1 + index % 2) for index in range(3)]
    for event in events:
        lab.service.create_event(lab.users["cdrl_writer"], event)
    # El GSI es eventualmente consistente: esperar propagación del fixture.
    deadline = time.monotonic() + 10
    while query_by_type(EVENT_TYPE, START, END, table=lab.events) != events:
        if time.monotonic() >= deadline:
            pytest.fail("No se propagaron todos los documentos al GSI temporal M09.")
        time.sleep(0.05)
    found, cursor, pages = [], None, 0
    for _ in range(10):
        page = lab.service.query_by_type_page(lab.users["cdrl_reader"], EVENT_TYPE, START, END, page_size=1, cursor=cursor)
        pages += 1
        assert len(page["items"]) <= 1
        found.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        cursor = json.loads(json.dumps(cursor))
    else:
        pytest.fail("La paginación del fixture pequeño no terminó.")
    assert pages >= 3
    assert found == events
    assert len({event["eventId"] for event in found}) == 3
    assert {int(event["metadata"]["schemaVersion"]) for event in found} == {1, 2}
    records = lab.records()
    assert len(records) == 6 + 2 * pages
    assert len({r["attemptId"] for r in records}) == 3 + pages
    queries = [r for r in records if r["action"] == "Query"]
    for attempt_id in {r["attemptId"] for r in queries}:
        _assert_attempt([r for r in queries if r["attemptId"] == attempt_id], role="cdrl_reader", action="Query", results=["attempt", "success"])
    assert "last_evaluated_key" not in json.dumps(records)


def test_invalid_cursor_persists_error_before_query(lab):
    with pytest.raises(InvalidCursorError):
        lab.service.query_by_type_page(lab.users["cdrl_reader"], EVENT_TYPE, START, END, cursor={})
    assert lab.probe.calls == []
    assert _rows(lab.events, "eventId") == {}
    _assert_attempt(lab.records(), role="cdrl_reader", action="Query", results=["attempt", "error"])


def test_recursive_sanitization_and_m06_m09_logs_coexist(lab):
    old = build_audit_record(
        "synthetic-m09-migration", action="schema.migrate.v1_to_v2",
        trace_id="synthetic-m09-trace", from_version=1, to_version=2,
        changed_fields=["metadata.schemaVersion"],
        context={"nested": [deepcopy(CASES["synthetic_secrets"])]},
    )
    assert record_audit(old, table=lab.audit) is True
    assert record_audit(old, table=lab.audit) is False
    with pytest.raises(AccessDeniedError):
        lab.service.create_event(lab.users["cdrl_reader"], deepcopy(CASES["synthetic_secrets"]))
    records = _rows(lab.audit, "auditId")
    assert len(records) == 2
    assert records[old["auditId"]] == old
    sanitized = records[old["auditId"]]["context"]["nested"][0]
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["Authorization"] == "[REDACTED]"
    assert sanitized["nested"]["api_key"] == "[REDACTED]"
    # M06 incluye números que boto3 devuelve como Decimal.
    serialized = json.dumps(records, default=str)
    assert "[REDACTED]" in serialized
    for secret in ("synthetic-password-never-save", "synthetic-token-never-save", "synthetic-api-key-never-save"):
        assert secret not in serialized
    security = [record for key, record in records.items() if key != old["auditId"]]
    assert set(security[0]) == set(CASES["expected_audit_fields"])
    _assert_attempt(security, role="cdrl_reader", action="PutItem", results=["denied"])
    assert lab.probe.calls == []


@pytest.mark.parametrize("operation", ["authorized-create", "denied-delete"])
def test_audit_failure_before_operation_fails_closed(lab, monkeypatch, operation):
    def unavailable(**kwargs):
        raise RuntimeError("synthetic-private-audit-failure")

    # Inyección de fallo solo en la escritura del sink; el backend sigue siendo real.
    monkeypatch.setattr(lab.audit, "put_item", unavailable)
    with pytest.raises(AuditUnavailableError) as raised:
        if operation == "authorized-create":
            lab.service.create_event(lab.users["cdrl_writer"], _event())
        else:
            lab.service.delete_event(lab.users["cdrl_reader"], _event()["eventId"])
    assert raised.value.operation_may_have_completed is False
    assert "synthetic-private-audit-failure" not in str(raised.value)
    assert lab.probe.calls == []
    assert _rows(lab.events, "eventId") == {}
    assert lab.records() == []


def test_audit_failure_after_write_reports_uncertainty_without_fake_rollback(lab, monkeypatch):
    original_put = lab.audit.put_item
    calls = []

    def fail_second_write(**kwargs):
        calls.append(kwargs["Item"]["result"])
        if len(calls) == 2:
            raise RuntimeError("synthetic-private-audit-failure")
        return original_put(**kwargs)

    monkeypatch.setattr(lab.audit, "put_item", fail_second_write)
    event = _event()
    with pytest.raises(AuditUnavailableError) as raised:
        lab.service.create_event(lab.users["cdrl_writer"], event)
    assert raised.value.operation_may_have_completed is True
    assert "synthetic-private-audit-failure" not in str(raised.value)
    assert calls == ["attempt", "success"]
    assert _rows(lab.events, "eventId") == {event["eventId"]: event}
    _assert_attempt(lab.records(), role="cdrl_writer", action="PutItem", results=["attempt"])
