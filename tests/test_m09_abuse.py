"""Pruebas de abuso y remediación de M09, sin permisos peligrosos reales."""

from copy import deepcopy
from pathlib import Path
import json
import os
from uuid import uuid4

from botocore.exceptions import ClientError
import pytest

from src.m05.event_contract import validate_event
from src.m05.dynamodb_client import get_dynamodb_client, get_dynamodb_resource
from src.m05.table_setup import ensure_table
from src.m06.audit_store import ensure_audit_table
from src.m09.authorization import IdentityRegistry
from src.m09.policy import AUDIT, EVENTS, ROLES, is_allowed
from src.m09.secure_operations import (
    AccessDeniedError, AuditUnavailableError, SecureOperations,
)
from src.m09.security_audit import SecurityAuditSink


HERE = Path(__file__).parent / "fixtures"
CASES = json.loads((HERE / "m09_security_cases.json").read_text(encoding="utf-8"))
SAMPLE = json.loads((HERE / "m06_versioned_events.json").read_text(encoding="utf-8"))["v1"]


class MemoryEvents:
    def __init__(self, items=()):
        self.items = {x["eventId"]: deepcopy(x) for x in items}
        self.calls = []

    def get_item(self, *, Key, ConsistentRead=True, **kwargs):
        self.calls.append("GetItem")
        event = self.items.get(Key["eventId"])
        if event is None:
            return {}
        if "ProjectionExpression" in kwargs:
            return {"Item": {"eventId": event["eventId"], "type": event["type"]}}
        return {"Item": deepcopy(event)}

    def put_item(self, *, Item, ConditionExpression):
        self.calls.append("PutItem")
        assert ConditionExpression == "attribute_not_exists(eventId)"
        if Item["eventId"] in self.items:
            raise ClientError({"Error":{"Code":"ConditionalCheckFailedException","Message":"duplicate"}}, "PutItem")
        self.items[Item["eventId"]] = deepcopy(Item)
        return {}

    def delete_item(self, *, Key):
        self.calls.append("DeleteItem")
        return self.items.pop(Key["eventId"], None)


class MemoryAudit:
    def __init__(self, fail_on_call=None):
        self.items = {}
        self.calls = 0
        self.fail_on_call = fail_on_call

    def put_item(self, *, Item, ConditionExpression):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise ClientError({"Error":{"Code":"ServiceUnavailable","Message":"synthetic-private-error"}}, "PutItem")
        assert ConditionExpression == "attribute_not_exists(auditId)"
        if Item["auditId"] in self.items:
            raise ClientError({"Error":{"Code":"ConditionalCheckFailedException","Message":"duplicate"}}, "PutItem")
        self.items[Item["auditId"]] = deepcopy(Item)
        return {}


@pytest.fixture
def context():
    assignments = {subject: "cdrl_" + role for role, subject in CASES["identities"].items()}
    registry = IdentityRegistry(assignments)
    identities = {
        role: registry.identity_for_verified_subject(subject)
        for subject, role in assignments.items()
    }
    return registry, identities


def _service(context, events=None, audit=None):
    registry, identities = context
    events = events if events is not None else MemoryEvents([SAMPLE])
    audit = audit if audit is not None else MemoryAudit()
    service = SecureOperations(registry=registry, table=events, audit_sink=SecurityAuditSink(table=audit))
    return service, identities, events, audit


@pytest.mark.parametrize("case", CASES["permission_cases"])
def test_declared_permission_matrix_matches_secured_operations(case):
    expected = case["expected"] == "allowed"
    assert is_allowed(case["role"], case["action"], case["resource"]) is expected


def test_reader_can_read_event_and_audit_is_persisted(context):
    service, users, events, audit = _service(context)
    assert service.get_event(users["cdrl_reader"], SAMPLE["eventId"]) == SAMPLE
    assert [entry["result"] for entry in audit.items.values()] == ["attempt", "success"]
    assert len({entry["attemptId"] for entry in audit.items.values()}) == 1
    assert len({entry["auditId"] for entry in audit.items.values()}) == 2


def test_writer_can_create_once_with_durable_audit(context):
    service, users, events, audit = _service(context, events=MemoryEvents())
    assert service.create_event(users["cdrl_writer"], SAMPLE) == validate_event(SAMPLE)
    assert SAMPLE["eventId"] in events.items
    assert [entry["result"] for entry in audit.items.values()] == ["attempt", "success"]


@pytest.mark.parametrize("role", ROLES)
def test_delete_event_is_denied_to_every_role_without_backend_call(context, role):
    service, users, events, audit = _service(context)
    before = deepcopy(events.items)
    with pytest.raises(AccessDeniedError):
        service.delete_event(users[role], SAMPLE["eventId"])
    assert events.items == before
    assert events.calls == []
    logged = list(audit.items.values())
    assert len(logged) == 1
    assert logged[0]["result"] == "denied"
    assert logged[0]["role"] == role
    assert logged[0]["action"] == "DeleteItem"


@pytest.mark.parametrize("method,params", [
    ("read_audit", ("synthetic-audit-id",)),
    ("write_audit", ({"token": "synthetic-secret"},)),
    ("update_audit", ("synthetic-audit-id", {"result": "success"})),
    ("delete_audit", ("synthetic-audit-id",)),
])
@pytest.mark.parametrize("role", ROLES)
def test_no_user_role_can_access_or_modify_audit_logs(context, role, method, params):
    service, users, events, audit = _service(context)
    old = deepcopy(audit.items)
    with pytest.raises(AccessDeniedError):
        getattr(service, method)(users[role], *params)
    assert events.calls == []
    assert len(audit.items) == len(old) + 1  # Solo el nuevo rechazo auditado
    assert list(audit.items.values())[-1]["resource"] == AUDIT
    assert list(audit.items.values())[-1]["result"] == "denied"


def test_unknown_actor_is_denied_without_event_io(context):
    service, _, events, audit = _service(context)
    with pytest.raises(AccessDeniedError):
        service.delete_event({"role":"cdrl_reader"}, SAMPLE["eventId"])
    assert events.calls == []
    entry = next(iter(audit.items.values()))
    assert entry["actorId"] == "unknown"
    assert entry["reason"] == "untrusted_identity"


def test_reader_cannot_create_and_writer_cannot_read(context):
    service, users, events, audit = _service(context)
    with pytest.raises(AccessDeniedError):
        service.create_event(users["cdrl_reader"], SAMPLE)
    with pytest.raises(AccessDeniedError):
        service.get_event(users["cdrl_writer"], SAMPLE["eventId"])
    assert events.calls == []
    assert all(x["result"] == "denied" for x in audit.items.values())


def test_operator_receives_only_whitelisted_operational_fields(context):
    service, users, events, audit = _service(context)
    summary = service.get_operational_summary(users["cdrl_operator"], SAMPLE["eventId"])
    assert summary == {"eventId": SAMPLE["eventId"], "type": SAMPLE["type"]}
    assert "payload" not in summary
    with pytest.raises(AccessDeniedError):
        service.get_event(users["cdrl_operator"], SAMPLE["eventId"])
    assert [entry["result"] for entry in audit.items.values()] == ["attempt", "success", "denied"]



def test_isolated_excessive_permission_is_removed_before_real_operations(context):
    """Demuestra el riesgo de DeleteItem y comprueba la política corregida."""

    scenario = CASES["isolated_abuse"]

    # Primera parte: simulación de una política insegura.
    # Este permiso solo existe dentro de la prueba.
    unsafe_permissions = {
        ("GetItem", EVENTS),
        ("Query", EVENTS),
        ("DeleteItem", EVENTS),
    }

    assert scenario["unsafe_policy_allows"] is True
    assert (scenario["action"], scenario["resource"]) in unsafe_permissions

    vulnerable_events = MemoryEvents([SAMPLE])

    # Se demuestra que el permiso excesivo permitiría eliminar el evento.
    vulnerable_events.delete_item(
        Key={"eventId": SAMPLE["eventId"]}
    )

    assert SAMPLE["eventId"] not in vulnerable_events.items
    assert vulnerable_events.calls == ["DeleteItem"]

    # Segunda parte: política segura implementada por Víctor.
    service, users, protected_events, audit = _service(context)

    assert is_allowed(
        "cdrl_reader",
        "DeleteItem",
        EVENTS,
    ) is False

    with pytest.raises(AccessDeniedError):
        service.delete_event(
            users["cdrl_reader"],
            SAMPLE["eventId"],
        )

    # El documento permanece intacto.
    assert SAMPLE["eventId"] in protected_events.items
    assert protected_events.calls == []

    # El intento rechazado queda registrado.
    records = list(audit.items.values())

    assert len(records) == 1
    assert records[0]["result"] == "denied"
    assert records[0]["reason"] == "permission_denied"
    assert records[0]["action"] == "DeleteItem"


def test_audit_write_failure_prevents_event_creation(context):
    audit = MemoryAudit(fail_on_call=1)
    service, users, events, _ = _service(context, events=MemoryEvents(), audit=audit)
    with pytest.raises(AuditUnavailableError) as raised:
        service.create_event(users["cdrl_writer"], SAMPLE)
    assert raised.value.operation_may_have_completed is False
    assert events.items == {}
    assert events.calls == []


def test_late_audit_failure_does_not_claim_rollback(context):
    audit = MemoryAudit(fail_on_call=2)
    service, users, events, _ = _service(context, events=MemoryEvents(), audit=audit)
    with pytest.raises(AuditUnavailableError) as raised:
        service.create_event(users["cdrl_writer"], SAMPLE)
    assert raised.value.operation_may_have_completed is True
    assert SAMPLE["eventId"] in events.items
    assert "synthetic-private-error" not in str(raised.value)


def test_consecutive_denials_have_distinct_audit_and_attempt_ids(context):
    service, users, events, audit = _service(context)
    for _ in range(2):
        with pytest.raises(AccessDeniedError):
            service.delete_event(users["cdrl_reader"], SAMPLE["eventId"])
    logged = list(audit.items.values())
    assert len(logged) == 2
    assert len({x["auditId"] for x in logged}) == 2
    assert len({x["attemptId"] for x in logged}) == 2


def test_audit_record_contains_no_request_content_or_secret(context):
    service, users, events, audit = _service(context)
    secret = "synthetic-password-never-save"
    with pytest.raises(AccessDeniedError):
        service.write_audit(users["cdrl_reader"], {"password": secret})
    assert secret not in json.dumps(audit.items)
    assert set(next(iter(audit.items.values()))) == set(CASES["expected_audit_fields"])


def test_end_to_end_authorization_and_durable_audit_in_dynamodb_local(context):
    """Prueba integrada de las dos tablas reales sin modificar datos permanentes."""
    if os.environ.get("DYNAMODB_LOCAL", "").strip().lower() != "true":
        pytest.skip("Prueba de integración solo con DYNAMODB_LOCAL=true.")

    client = get_dynamodb_client()

    suffix = uuid4().hex[:16]
    events_name = "cdrl_m09_events_" + suffix
    audit_name = "cdrl_m09_audit_" + suffix

    created_tables = []

    try:
        # Preparar las tablas temporales.
        # Se registran antes de intentar crearlas para poder
        # limpiar incluso una creación parcialmente completada.
        created_tables.append(events_name)
        ensure_table(
            client=client,
            table_name=events_name,
            attempts=100,
            poll_seconds=0.05,
        )

        created_tables.append(audit_name)
        ensure_audit_table(
            client=client,
            table_name=audit_name,
            attempts=100,
            poll_seconds=0.05,
        )

        events = get_dynamodb_resource().Table(events_name)
        audit = get_dynamodb_resource().Table(audit_name)

        service, users, _, _ = _service(
            context,
            events=events,
            audit=audit,
        )

        # Escritura autorizada.
        assert service.create_event(
            users["cdrl_writer"],
            SAMPLE,
        ) == validate_event(SAMPLE)

        # Lectura autorizada.
        assert service.get_event(
            users["cdrl_reader"],
            SAMPLE["eventId"],
        ) == validate_event(SAMPLE)

        # Eliminación denegada.
        with pytest.raises(AccessDeniedError):
            service.delete_event(
                users["cdrl_reader"],
                SAMPLE["eventId"],
            )

        # El documento sigue existiendo.
        stored = events.get_item(
            Key={"eventId": SAMPLE["eventId"]},
            ConsistentRead=True,
        )["Item"]

        assert stored == validate_event(SAMPLE)

        # Solo la identidad técnica de pruebas consulta los logs.
        audit_records = audit.scan()["Items"]

        assert len(audit_records) == 5

        assert sorted(x["result"] for x in audit_records) == sorted([
            "attempt",
            "success",
            "attempt",
            "success",
            "denied",
        ])

        assert len({x["auditId"] for x in audit_records}) == 5
        assert len({x["attemptId"] for x in audit_records}) == 3

        assert all(
            set(x) == set(CASES["expected_audit_fields"])
            for x in audit_records
        )

        assert "password" not in json.dumps(audit_records).lower()

    finally:
        # Limpiar las tablas temporales, incluso ante un fallo.
        for name in reversed(created_tables):
            try:
                client.delete_table(TableName=name)
                client.get_waiter("table_not_exists").wait(
                    TableName=name,
                    WaiterConfig={"Delay": 1, "MaxAttempts": 10},
                )
            except ClientError as error:
                if error.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                    raise