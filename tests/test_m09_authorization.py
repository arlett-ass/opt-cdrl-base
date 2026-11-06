"""Víctor M09: permisos, identidad confiable y envolturas M05–M08.

La auditoría se inyecta como un servicio técnico que debe confirmar cada
registro. Estos tests prueban ese contrato; la persistencia de la auditoría
y las pruebas de abuso corresponden a los módulos de Angélica. Los casos
funcionales solo crean tablas sintéticas propias en DynamoDB Local.
"""

from copy import copy, deepcopy
from decimal import Decimal
import json
import os
import time
from uuid import uuid4

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
import pytest

from src.m05.document_store import DuplicateEventError, query_by_type
from src.m05.dynamodb_client import get_dynamodb_client, get_dynamodb_resource
from src.m05.event_contract import build_event_id, validate_event
from src.m05.table_setup import ensure_table
from src.m06.schema_evolution import migrate_v1_to_v2
from src.m06.versioned_store import DuplicateVersionedEventError
from src.m09.authorization import IdentityRegistry, authorize
from src.m09.policy import ACTIONS, AUDIT, EVENTS, ROLES, is_allowed
from src.m09.secure_operations import (
    AccessDeniedError,
    AuditUnavailableError,
    SecureOperations,
)


START = "2026-11-05T10:00:00.000000Z"
END = "2026-11-05T10:10:00.000000Z"
EVENT_TYPE = "telemetry.reading"


def _event(device=9091, timestamp=START, version=1):
    document = validate_event({
        "eventId": build_event_id(device, timestamp),
        "type": EVENT_TYPE,
        "source": f"device-{device}",
        "timestamp": timestamp,
        "payload": {
            "readingId": device,
            "deviceId": device,
            "receivedAt": timestamp,
            "temperatureC": "23.45",
            "humidityPct": "51.20",
            "co2Ppm": "650.00",
        },
        "metadata": {"schemaVersion": 1},
    })
    return migrate_v1_to_v2(document) if version == 2 else document


class RecordingTable:
    """Backend estricto: registra accesos y respeta la creación condicional."""

    def __init__(self, items=(), responses=(), failure=None, timeline=None):
        self.items = {item["eventId"]: deepcopy(item) for item in items}
        self.responses = list(deepcopy(responses))
        self.failure = failure
        self.calls = []
        self.timeline = timeline if timeline is not None else []

    def _record(self, action, kwargs):
        self.timeline.append(action)
        self.calls.append((action, deepcopy(kwargs)))
        if self.failure is not None:
            raise self.failure

    def get_item(self, **kwargs):
        self._record("GetItem", kwargs)
        item = self.items.get(kwargs["Key"]["eventId"])
        # Devuelve campos extra a propósito: la capa segura debe filtrarlos.
        return {"Item": deepcopy(item)} if item is not None else {}

    def put_item(self, **kwargs):
        self._record("PutItem", kwargs)
        assert kwargs["ConditionExpression"] == "attribute_not_exists(eventId)"
        item = kwargs["Item"]
        if item["eventId"] in self.items:
            raise ClientError({"Error": {
                "Code": "ConditionalCheckFailedException", "Message": "duplicate synthetic event",
            }}, "PutItem")
        self.items[item["eventId"]] = deepcopy(item)
        return {}

    def query(self, **kwargs):
        self._record("Query", kwargs)
        return deepcopy(self.responses.pop(0)) if self.responses else {"Items": []}

    def update_item(self, **kwargs):
        raise AssertionError("UpdateItem nunca debe llegar al backend M09.")

    def delete_item(self, **kwargs):
        raise AssertionError("DeleteItem nunca debe llegar al backend M09.")

    def scan(self, **kwargs):
        raise AssertionError("Las consultas M09 deben conservar Query de M05/M08.")


@pytest.fixture
def identities():
    registry = IdentityRegistry({f"test-{role}": role for role in ROLES})
    contexts = {
        role: registry.identity_for_verified_subject(f"test-{role}") for role in ROLES
    }
    return registry, contexts


def _service(identities, table=None, sink=None, timeline=None):
    registry, _ = identities
    records = []

    def acknowledge(record):
        if timeline is not None:
            timeline.append(f"audit:{record['result']}")
        records.append(deepcopy(record))
        return True

    service = SecureOperations(
        registry=registry,
        audit_sink=sink if sink is not None else acknowledge,
        table=table,
    )
    return service, records


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("resource", [EVENTS, AUDIT])
def test_exact_role_action_resource_matrix(role, action, resource):
    allowed = resource == EVENTS and (
        (role == "cdrl_reader" and action in {"GetItem", "Query"})
        or (role == "cdrl_writer" and action == "PutItem")
        or (role == "cdrl_operator" and action == "ReadOperationalSummary")
    )
    assert is_allowed(role, action, resource) is allowed


@pytest.mark.parametrize("role,action,resource", [
    ("admin", "GetItem", EVENTS),
    ("cdrl_reader", "Scan", EVENTS),
    ("cdrl_reader", "GetItem", "unrelated_table"),
    ("CDRL_READER", "GetItem", EVENTS),
    ("cdrl_reader", "getitem", EVENTS),
    (None, "GetItem", EVENTS),
    ({"role": "cdrl_reader"}, "GetItem", EVENTS),
    ("cdrl_reader", [], EVENTS),
    ("cdrl_reader", "GetItem", {}),
])
def test_undeclared_or_malformed_permission_is_denied(role, action, resource):
    assert is_allowed(role, action, resource) is False


def test_only_context_issued_by_the_configured_registry_is_trusted(identities):
    registry, contexts = identities
    reader = contexts["cdrl_reader"]
    other_registry = IdentityRegistry({"test-cdrl_reader": "cdrl_reader"})
    foreign = other_registry.identity_for_verified_subject("test-cdrl_reader")
    assert authorize(registry, reader, "GetItem", EVENTS).allowed is True
    assert registry.identity_for_verified_subject("unregistered") is None
    for forged in (None, "cdrl_reader", {"actorId": "test-cdrl_reader", "role": "cdrl_reader"}, foreign, copy(reader)):
        decision = authorize(registry, forged, "GetItem", EVENTS)
        assert decision.allowed is False
        assert decision.actor_id == "unknown"
        assert decision.role == "unknown"


@pytest.mark.parametrize("identity", [None, "cdrl_reader", {"role": "cdrl_reader"}])
def test_untrusted_identity_is_audited_without_backend_access(identities, identity):
    table = RecordingTable([_event()])
    service, records = _service(identities, table)
    with pytest.raises(AccessDeniedError):
        service.get_event(identity, _event()["eventId"])
    assert table.calls == []
    assert records[0]["result"] == "denied"
    assert records[0]["actorId"] == "unknown"


@pytest.mark.parametrize("role", ROLES)
def test_delete_update_and_audit_crud_are_denied_without_changing_data(identities, role):
    _, contexts = identities
    table = RecordingTable([_event()])
    before = deepcopy(table.items)
    service, records = _service(identities, table)
    identity = contexts[role]
    attempts = [
        lambda: service.delete_event(identity, _event()["eventId"]),
        lambda: service.update_event(identity, _event()["eventId"], {"type": "changed"}),
        lambda: service.read_audit(identity, "synthetic-audit-id"),
        lambda: service.write_audit(identity, {"auditId": "synthetic-audit-id"}),
        lambda: service.update_audit(identity, "synthetic-audit-id", {"result": "forged"}),
        lambda: service.delete_audit(identity, "synthetic-audit-id"),
    ]
    for attempt in attempts:
        with pytest.raises(AccessDeniedError):
            attempt()
    assert table.calls == []
    assert table.items == before
    assert len(records) == len(attempts)
    assert all(record["result"] == "denied" for record in records)
    assert len({record["attemptId"] for record in records}) == len(attempts)
    assert len({record["auditId"] for record in records}) == len(attempts)


def test_denial_precedes_argument_validation_and_default_table_resolution(identities, monkeypatch):
    _, contexts = identities

    def forbidden_factory():
        raise AssertionError("Un rechazo no debe resolver ni consultar DynamoDB.")

    monkeypatch.setattr("src.m09.secure_operations.get_table", forbidden_factory)
    service, records = _service(identities)
    with pytest.raises(AccessDeniedError):
        service.create_event(contexts["cdrl_reader"], {"password": "synthetic-denied-secret"})
    with pytest.raises(AccessDeniedError):
        service.get_event(contexts["cdrl_writer"], None)
    with pytest.raises(AccessDeniedError):
        service.get_event(contexts["cdrl_operator"], _event()["eventId"])
    assert len(records) == 3
    assert "synthetic-denied-secret" not in json.dumps(records)


@pytest.mark.parametrize("version", [1, 2])
def test_writer_creates_once_reader_preserves_version_and_denials_preserve_data(identities, version):
    _, contexts = identities
    table = RecordingTable()
    service, records = _service(identities, table)
    event = _event(version=version)
    original = deepcopy(event)
    assert service.create_event(contexts["cdrl_writer"], event) == event
    assert event == original
    assert service.get_event(contexts["cdrl_reader"], event["eventId"]) == event
    assert isinstance(table.items[event["eventId"]]["payload"][
        "measurements" if version == 2 else "temperatureC"
    ], dict if version == 2 else Decimal)
    before = deepcopy(table.items)
    changed = deepcopy(event)
    if version == 2:
        changed["payload"]["measurements"]["temperatureC"] = "24.00"
    else:
        changed["payload"]["temperatureC"] = "24.00"
    with pytest.raises((DuplicateEventError, DuplicateVersionedEventError)):
        service.create_event(contexts["cdrl_writer"], changed)
    with pytest.raises(AccessDeniedError):
        service.create_event(contexts["cdrl_reader"], changed)
    assert table.items == before
    assert records[-1]["result"] == "denied"
    assert any(record["result"] == "error" for record in records)


def test_missing_event_returns_none_with_audited_success(identities):
    _, contexts = identities
    service, records = _service(identities, RecordingTable())
    assert service.get_event(contexts["cdrl_reader"], "missing-event") is None
    assert [record["result"] for record in records] == ["attempt", "success"]


def test_operator_gets_only_projected_operational_fields(identities):
    _, contexts = identities
    document = _event(version=2)
    document.update({"password": "synthetic-secret", "status": "unapproved-status"})
    table = RecordingTable([document])
    service, records = _service(identities, table)
    result = service.get_operational_summary(contexts["cdrl_operator"], document["eventId"])
    assert result == {"eventId": document["eventId"], "type": EVENT_TYPE}
    action, request = table.calls[0]
    assert action == "GetItem"
    expression = request["ProjectionExpression"]
    names = request.get("ExpressionAttributeNames", {})
    projected = {names.get(part.strip(), part.strip()) for part in expression.split(",")}
    assert projected == {"eventId", "type"}
    assert "synthetic-secret" not in json.dumps(records)
    with pytest.raises(AccessDeniedError):
        service.get_event(contexts["cdrl_operator"], document["eventId"])
    with pytest.raises(AccessDeniedError):
        service.get_operational_summary(contexts["cdrl_reader"], document["eventId"])


@pytest.mark.parametrize("unsafe_type", [None, {"token": "synthetic-nested-secret"}, "unsafe.type"])
def test_operator_rejects_unsupported_or_nested_type_values(identities, unsafe_type):
    _, contexts = identities
    document = _event()
    document["type"] = unsafe_type
    service, records = _service(identities, RecordingTable([document]))
    with pytest.raises(ValueError):
        service.get_operational_summary(contexts["cdrl_operator"], document["eventId"])
    assert [record["result"] for record in records] == ["attempt", "error"]
    assert "synthetic-nested-secret" not in json.dumps(records)


def test_authorized_invalid_input_is_audited_without_writing_or_querying(identities):
    _, contexts = identities
    table = RecordingTable()
    service, records = _service(identities, table)
    with pytest.raises(ValueError):
        service.create_event(contexts["cdrl_writer"], {"password": "synthetic-invalid-secret"})
    with pytest.raises(ValueError):
        service.query_by_type_page(contexts["cdrl_reader"], EVENT_TYPE, START, END, cursor={})
    assert table.calls == []
    assert table.items == {}
    assert [record["result"] for record in records] == ["attempt", "error", "attempt", "error"]
    assert "synthetic-invalid-secret" not in json.dumps(records)


def test_unknown_action_and_resource_are_normalized_before_audit_integration(identities):
    registry, contexts = identities
    decision = authorize(
        registry, contexts["cdrl_reader"],
        "synthetic-private-action-secret", {"token": "synthetic-private-resource-secret"},
    )
    assert decision.allowed is False
    assert decision.action == "unknown"
    assert decision.resource == "unknown"
    assert decision.reason == "permission_denied"


def test_m05_indexed_queries_and_native_m08_cursor_are_preserved(identities):
    _, contexts = identities
    one, two = _event(), _event(9092, version=2)
    key = {name: one[name] for name in ("eventId", "type", "timestamp")}
    table = RecordingTable(responses=[
        {"Items": [one]}, {"Items": [two]},
        {"Items": [one], "LastEvaluatedKey": key}, {"Items": [two]},
    ])
    service, records = _service(identities, table)
    reader = contexts["cdrl_reader"]
    assert service.query_by_type(reader, EVENT_TYPE, START, END) == [one]
    assert service.query_by_source(reader, two["source"], START, END) == [two]
    page = service.query_by_type_page(reader, EVENT_TYPE, START, END, page_size=1)
    assert page["items"] == [one]
    cursor = json.loads(json.dumps(page["next_cursor"]))
    assert cursor["last_evaluated_key"] == key
    final = service.query_by_type_page(reader, EVENT_TYPE, START, END, page_size=2, cursor=cursor)
    assert final == {"items": [two], "next_cursor": None}
    assert table.calls[0][1]["IndexName"] == "type-timestamp-index"
    assert table.calls[1][1]["IndexName"] == "source-timestamp-index"
    request = table.calls[-1][1]
    assert request["ExclusiveStartKey"] == key
    assert request["Limit"] == 2
    assert request["KeyConditionExpression"] == (
        Key("type").eq(EVENT_TYPE) & Key("timestamp").between(START, END)
    )
    assert len(records) == 8


@pytest.mark.parametrize("role", ["cdrl_writer", "cdrl_operator", "cdrl_migrator"])
def test_all_query_variants_deny_non_readers_before_backend(identities, role):
    _, contexts = identities
    table = RecordingTable()
    service, records = _service(identities, table)
    for method, args in [
        (service.query_by_type, (EVENT_TYPE, START, END)),
        (service.query_by_source, ("device-9091", START, END)),
        (service.query_by_type_page, (EVENT_TYPE, START, END)),
    ]:
        with pytest.raises(AccessDeniedError):
            method(contexts[role], *args)
    assert table.calls == []
    assert all(record["result"] == "denied" for record in records)


def test_audit_acknowledgement_surrounds_backend_and_uses_distinct_records(identities):
    _, contexts = identities
    timeline = []
    table = RecordingTable([_event()], timeline=timeline)
    service, records = _service(identities, table, timeline=timeline)
    for _ in range(2):
        service.get_event(contexts["cdrl_reader"], _event()["eventId"])
    assert timeline == ["audit:attempt", "GetItem", "audit:success"] * 2
    required = {"auditId", "attemptId", "actorId", "role", "action", "resource", "result", "reason", "timestamp"}
    assert all(required <= set(record) for record in records)
    assert len({record["auditId"] for record in records}) == 4
    assert records[0]["attemptId"] == records[1]["attemptId"]
    assert records[2]["attemptId"] == records[3]["attemptId"]
    assert records[0]["attemptId"] != records[2]["attemptId"]
    assert all(record["actorId"] == "test-cdrl_reader" for record in records)
    assert all(record["action"] == "GetItem" and record["resource"] == EVENTS for record in records)


@pytest.mark.parametrize("sink", [None, False, "discard"])
def test_audit_dependency_is_required(identities, sink):
    registry, _ = identities
    with pytest.raises(TypeError):
        SecureOperations(registry=registry, audit_sink=sink, table=RecordingTable())


@pytest.mark.parametrize("acknowledgement", [False, None, 1, "saved", {}])
def test_missing_positive_audit_acknowledgement_blocks_sensitive_write(identities, acknowledgement):
    _, contexts = identities
    table = RecordingTable()
    service, _ = _service(identities, table, sink=lambda record: acknowledgement)
    with pytest.raises(AuditUnavailableError) as raised:
        service.create_event(contexts["cdrl_writer"], _event())
    assert raised.value.operation_may_have_completed is False
    assert table.calls == []
    assert table.items == {}


def test_failed_denial_audit_still_denies_without_database_access(identities):
    _, contexts = identities
    table = RecordingTable([_event()])

    def failed_sink(record):
        raise RuntimeError("synthetic-private-audit-secret")

    service, _ = _service(identities, table, sink=failed_sink)
    with pytest.raises(AuditUnavailableError) as raised:
        service.delete_event(contexts["cdrl_reader"], _event()["eventId"])
    assert raised.value.operation_may_have_completed is False
    assert "synthetic-private-audit-secret" not in str(raised.value)
    assert table.calls == []


def test_post_write_audit_failure_reports_possible_write_without_faking_rollback(identities):
    _, contexts = identities
    table = RecordingTable()
    attempts = []

    def sink(record):
        attempts.append(deepcopy(record))
        return len(attempts) == 1

    service, _ = _service(identities, table, sink=sink)
    with pytest.raises(AuditUnavailableError) as raised:
        service.create_event(contexts["cdrl_writer"], _event())
    assert raised.value.operation_may_have_completed is True
    assert table.items[_event()["eventId"]] == _event()
    assert [record["result"] for record in attempts] == ["attempt", "success"]


def test_post_read_audit_failure_does_not_return_an_unaudited_document(identities):
    _, contexts = identities
    table = RecordingTable([_event()])
    attempts = []

    def sink(record):
        attempts.append(deepcopy(record))
        return len(attempts) == 1

    service, _ = _service(identities, table, sink=sink)
    with pytest.raises(AuditUnavailableError) as raised:
        service.get_event(contexts["cdrl_reader"], _event()["eventId"])
    assert raised.value.operation_may_have_completed is True
    assert [action for action, _ in table.calls] == ["GetItem"]
    assert [record["result"] for record in attempts] == ["attempt", "success"]


def test_backend_error_is_audited_without_copying_exception_secrets(identities):
    _, contexts = identities
    failure = ClientError({"Error": {
        "Code": "ResourceNotFoundException", "Message": "synthetic-private-service-secret",
    }}, "GetItem")
    table = RecordingTable(failure=failure)
    service, records = _service(identities, table)
    with pytest.raises(ClientError) as raised:
        service.get_event(contexts["cdrl_reader"], "synthetic-private-request-secret")
    assert raised.value is failure
    assert [record["result"] for record in records] == ["attempt", "error"]
    serialized = json.dumps(records)
    assert "synthetic-private-service-secret" not in serialized
    assert "synthetic-private-request-secret" not in serialized


@pytest.fixture
def real_table():
    if os.environ.get("DYNAMODB_LOCAL", "").strip().lower() != "true":
        pytest.skip("Activar explícitamente DYNAMODB_LOCAL=true para casos funcionales M09.")
    client = get_dynamodb_client()
    table_name = f"cdrl_m09_tests_{uuid4().hex[:16]}"
    ensure_table(client=client, table_name=table_name, attempts=100, poll_seconds=0.05)
    table = get_dynamodb_resource().Table(table_name)
    try:
        yield table
    finally:
        client.delete_table(TableName=table_name)
        client.get_waiter("table_not_exists").wait(
            TableName=table_name, WaiterConfig={"Delay": 1, "MaxAttempts": 10},
        )


@pytest.mark.parametrize("version", [1, 2])
def test_real_writer_reader_duplicate_and_denied_delete(identities, real_table, version):
    _, contexts = identities
    service, records = _service(identities, real_table)
    event = _event(version=version)
    assert service.create_event(contexts["cdrl_writer"], event) == event
    assert service.get_event(contexts["cdrl_reader"], event["eventId"]) == event
    with pytest.raises((DuplicateEventError, DuplicateVersionedEventError)):
        service.create_event(contexts["cdrl_writer"], event)
    for role in ROLES:
        with pytest.raises(AccessDeniedError):
            service.delete_event(contexts[role], event["eventId"])
        assert real_table.get_item(Key={"eventId": event["eventId"]}, ConsistentRead=True)["Item"] == event
    assert sum(record["result"] == "denied" for record in records) == 4


def test_real_mixed_versions_use_native_cursor_and_keep_operational_summary_safe(identities, real_table):
    _, contexts = identities
    service, records = _service(identities, real_table)
    events = [_event(9190 + index, f"2026-11-05T10:0{index}:00.000000Z", 1 + index % 2) for index in range(3)]
    for event in events:
        service.create_event(contexts["cdrl_writer"], event)
    deadline = time.monotonic() + 5
    while len(query_by_type(EVENT_TYPE, START, END, table=real_table)) != len(events):
        if time.monotonic() >= deadline:
            pytest.fail("El GSI no propagó el fixture M09 en el plazo esperado.")
        time.sleep(0.05)
    found, cursor = [], None
    for _ in range(10):
        page = service.query_by_type_page(contexts["cdrl_reader"], EVENT_TYPE, START, END, page_size=1, cursor=cursor)
        found.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        cursor = json.loads(json.dumps(cursor))
    else:
        pytest.fail("El fixture pequeño no terminó de paginar.")
    assert found == events
    for event in events:
        assert service.get_operational_summary(contexts["cdrl_operator"], event["eventId"]) == {
            "eventId": event["eventId"], "type": EVENT_TYPE,
        }
    assert all(record["result"] in {"attempt", "success"} for record in records)


def test_real_failed_pre_write_audit_leaves_event_absent(identities, real_table):
    _, contexts = identities
    service, _ = _service(identities, real_table, sink=lambda record: False)
    with pytest.raises(AuditUnavailableError) as raised:
        service.create_event(contexts["cdrl_writer"], _event())
    assert raised.value.operation_may_have_completed is False
    assert "Item" not in real_table.get_item(Key={"eventId": _event()["eventId"]}, ConsistentRead=True)
