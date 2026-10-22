"""Víctor M07: transformación v1/v2, persistencia e idempotencia.

Estas pruebas no requieren las consultas ni los componentes de evidencia del
resto del equipo. La tabla en memoria evalúa la condición completa sobre el
estado almacenado y permite introducir una carrera antes de PutItem.
"""

from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

from botocore.exceptions import ClientError
import pytest

from src.m07.migration import (
    ConcurrentSchemaMigrationError,
    VersionedEventNotFoundError,
    migrate_document,
    migrate_event,
)
from src.m07.versioning import (
    EventValidationError,
    SUPPORTED_SCHEMA_VERSIONS,
    TARGET_SCHEMA_VERSION,
    UnsupportedSchemaVersionError,
    VersionedEventError,
    get_schema_version,
    validate_document,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "m07_versioned_documents.json"
_CONDITION = (
    "attribute_exists(#event_id) AND #metadata = :expected_metadata "
    "AND #payload = :expected_payload AND #type = :expected_type "
    "AND #source = :expected_source AND #timestamp = :expected_timestamp"
)
_NAMES = {
    "#event_id": "eventId",
    "#metadata": "metadata",
    "#payload": "payload",
    "#type": "type",
    "#source": "source",
    "#timestamp": "timestamp",
}
_PROTECTED_FIELDS = ("metadata", "payload", "type", "source", "timestamp")


@pytest.fixture
def documents():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _client_error(code):
    return ClientError(
        {"Error": {"Code": code, "Message": "synthetic M07 failure"}},
        "PutItem",
    )


class ConditionalMemoryTable:
    """Sustituto acotado de Table que rechaza condiciones incompletas.

    No supone que schemaVersion=1 implique que el documento no cambió: compara
    todos los atributos observados. Conserva la imagen raw para que la prueba
    también detecte condiciones construidas con valores ya normalizados.
    """

    def __init__(self, documents=(), *, before_put=None, put_error=None):
        self.items = {
            document["eventId"]: deepcopy(document)
            for document in documents
        }
        self.get_calls = []
        self.put_calls = []
        self.successful_puts = []
        self.before_put = before_put
        self.put_error = put_error

    def get_item(self, *, Key, ConsistentRead):
        assert set(Key) == {"eventId"}
        assert ConsistentRead is True
        self.get_calls.append(deepcopy(Key))
        current = self.items.get(Key["eventId"])
        return {"Item": deepcopy(current)} if current is not None else {}

    def put_item(
        self,
        *,
        Item,
        ConditionExpression,
        ExpressionAttributeNames,
        ExpressionAttributeValues,
    ):
        assert ConditionExpression == _CONDITION
        assert ExpressionAttributeNames == _NAMES
        assert set(ExpressionAttributeValues) == {
            f":expected_{field}" for field in _PROTECTED_FIELDS
        }
        self.put_calls.append({
            "Item": deepcopy(Item),
            "ExpressionAttributeValues": deepcopy(ExpressionAttributeValues),
        })

        if self.before_put is not None:
            hook, self.before_put = self.before_put, None
            hook(self)
        if self.put_error is not None:
            raise self.put_error

        current = self.items.get(Item["eventId"])
        if current is None or any(
            field not in current
            or current[field] != ExpressionAttributeValues[f":expected_{field}"]
            for field in _PROTECTED_FIELDS
        ):
            raise _client_error("ConditionalCheckFailedException")

        self.items[Item["eventId"]] = deepcopy(Item)
        self.successful_puts.append(deepcopy(Item))
        return {}


def _assert_result(result, *, event, previous, changed, from_version):
    assert result == {
        "event": event,
        "previousEvent": previous,
        "changed": changed,
        "fromVersion": from_version,
        "toVersion": TARGET_SCHEMA_VERSION,
    }
    assert type(result["changed"]) is bool


def test_pure_migration_preserves_identity_data_and_input(documents):
    original = deepcopy(documents["v1"])
    expected = validate_document(documents["v2_equivalent"])

    migrated = migrate_document(original)

    assert SUPPORTED_SCHEMA_VERSIONS == (1, 2)
    assert TARGET_SCHEMA_VERSION == 2
    assert migrated == expected
    assert original == documents["v1"]
    assert migrated is not original
    for field in ("eventId", "type", "source", "timestamp"):
        assert migrated[field] == original[field]
    for field in ("readingId", "deviceId", "receivedAt"):
        assert migrated["payload"][field] == original["payload"][field]
    assert migrated["payload"]["measurements"] == {
        "temperatureC": Decimal("23.45"),
        "humidityPct": Decimal("51.20"),
        "co2Ppm": Decimal("650.00"),
    }
    assert migrate_document(migrated) == migrated


def test_normal_flow_preserves_coexisting_v1_and_reexecution_does_not_write(documents):
    original = deepcopy(documents["v1"])
    untouched = deepcopy(documents["v1_coexisting"])
    table = ConditionalMemoryTable([original, untouched])
    expected = validate_document(documents["v2_equivalent"])

    first = migrate_event(original["eventId"], table=table)

    _assert_result(first, event=expected, previous=original, changed=True, from_version=1)
    assert table.items[original["eventId"]] == expected
    assert table.items[untouched["eventId"]] == untouched
    assert len(table.put_calls) == len(table.successful_puts) == 1
    assert get_schema_version(table.items[untouched["eventId"]]) == 1
    assert get_schema_version(table.items[original["eventId"]]) == 2

    second = migrate_event(original["eventId"], table=table)

    _assert_result(second, event=expected, previous=expected, changed=False, from_version=2)
    assert len(table.put_calls) == len(table.successful_puts) == 1
    assert original == documents["v1"]


def test_existing_v2_is_a_noop_with_independent_result_copies(documents):
    original = deepcopy(documents["v2_equivalent"])
    table = ConditionalMemoryTable([original])
    expected = validate_document(original)

    first = migrate_event(original["eventId"], table=table)
    second = migrate_event(original["eventId"], table=table)

    _assert_result(first, event=expected, previous=original, changed=False, from_version=2)
    assert second == first
    assert table.put_calls == []
    first["event"]["payload"]["measurements"]["temperatureC"] = Decimal("0.00")
    first["previousEvent"]["payload"]["measurements"]["co2Ppm"] = "0.00"
    assert second["event"] == expected
    assert second["previousEvent"] == original
    assert table.items[original["eventId"]] == original


def test_compare_and_swap_uses_raw_values_before_timestamp_normalization(documents):
    original = deepcopy(documents["v1"])
    original["timestamp"] = "2026-10-21T10:30:00.123456-05:00"
    original["payload"]["receivedAt"] = "2026-10-21T10:30:01-05:00"
    table = ConditionalMemoryTable([original])

    result = migrate_event(original["eventId"], table=table)

    _assert_result(
        result,
        event=validate_document(documents["v2_equivalent"]),
        previous=original,
        changed=True,
        from_version=1,
    )
    assert table.put_calls[0]["ExpressionAttributeValues"] == {
        f":expected_{field}": original[field] for field in _PROTECTED_FIELDS
    }
    result["previousEvent"]["payload"]["temperatureC"] = "0.00"
    assert original["payload"]["temperatureC"] == "23.45"
    assert table.items[original["eventId"]]["payload"]["measurements"]["temperatureC"] == Decimal("23.45")


@pytest.mark.parametrize("version", [1, 2])
def test_get_schema_version_validates_whole_document_and_does_not_mutate(documents, version):
    document = deepcopy(documents["v1" if version == 1 else "v2_equivalent"])
    document["metadata"]["schemaVersion"] = Decimal(version)
    original = deepcopy(document)

    assert get_schema_version(document) == version
    assert validate_document(document)["metadata"]["schemaVersion"] == version
    assert document == original
    document["source"] = "wrong-device"
    with pytest.raises(ValueError):
        get_schema_version(document)


@pytest.mark.parametrize(
    "field,value",
    [
        ("temperatureC", "-50.00"),
        ("temperatureC", "80.00"),
        ("humidityPct", "0.00"),
        ("humidityPct", "100.00"),
        ("co2Ppm", "0.00"),
        ("co2Ppm", "10000.00"),
    ],
)
def test_pure_migration_preserves_inclusive_measurement_bounds(documents, field, value):
    original = deepcopy(documents["v1"])
    original["payload"][field] = value

    migrated = migrate_document(original)

    assert migrated["payload"]["measurements"][field] == Decimal(value)
    assert original["payload"][field] == value


@pytest.mark.parametrize(
    "field,value",
    [
        ("temperatureC", "-50.01"),
        ("temperatureC", "80.01"),
        ("humidityPct", "-0.01"),
        ("humidityPct", "100.01"),
        ("co2Ppm", "-0.01"),
        ("co2Ppm", "10000.01"),
        ("temperatureC", 23.45),
        ("humidityPct", True),
        ("co2Ppm", "650.001"),
    ],
)
def test_invalid_measurements_never_persist(documents, field, value):
    invalid = deepcopy(documents["v1"])
    invalid["payload"][field] = value
    table = ConditionalMemoryTable([invalid])

    with pytest.raises(EventValidationError):
        migrate_document(invalid)
    with pytest.raises(EventValidationError):
        migrate_event(invalid["eventId"], table=table)

    assert table.put_calls == []
    assert table.items[invalid["eventId"]] == invalid


def test_unknown_schema_version_is_explicitly_rejected_without_writes(documents):
    invalid = deepcopy(documents["v1"])
    invalid["metadata"]["schemaVersion"] = 99
    table = ConditionalMemoryTable([invalid])

    for function in (validate_document, get_schema_version, migrate_document):
        with pytest.raises(UnsupportedSchemaVersionError, match="99"):
            function(invalid)
    with pytest.raises(UnsupportedSchemaVersionError, match="99"):
        migrate_event(invalid["eventId"], table=table)

    assert table.put_calls == []
    assert table.items[invalid["eventId"]] == invalid


@pytest.mark.parametrize("version", [True, "1", Decimal("1.5"), Decimal("NaN")])
def test_non_integer_schema_versions_are_rejected(documents, version):
    invalid = deepcopy(documents["v1"])
    invalid["metadata"]["schemaVersion"] = version
    with pytest.raises(VersionedEventError):
        get_schema_version(invalid)


@pytest.mark.parametrize("event_id", [None, "", "   ", 7071, True])
def test_invalid_event_id_does_not_reach_storage(event_id):
    table = ConditionalMemoryTable()

    with pytest.raises(ValueError):
        migrate_event(event_id, table=table)

    assert table.get_calls == []
    assert table.put_calls == []


def test_missing_event_never_creates_an_item(documents):
    table = ConditionalMemoryTable()

    with pytest.raises(VersionedEventNotFoundError):
        migrate_event(documents["v1"]["eventId"], table=table)

    assert table.put_calls == []
    assert table.items == {}


@pytest.mark.parametrize("race", ["modified_v1", "migrated_v2", "deleted"])
def test_concurrent_changes_are_not_overwritten(documents, race):
    original = deepcopy(documents["v1"])
    event_id = original["eventId"]
    if race == "modified_v1":
        winner = deepcopy(original)
        winner["payload"]["temperatureC"] = "24.00"
    elif race == "migrated_v2":
        winner = migrate_document(original)
    else:
        winner = None

    def concurrent_writer(table):
        if winner is None:
            del table.items[event_id]
        else:
            table.items[event_id] = deepcopy(winner)

    table = ConditionalMemoryTable([original], before_put=concurrent_writer)

    with pytest.raises(ConcurrentSchemaMigrationError):
        migrate_event(event_id, table=table)

    assert len(table.put_calls) == 1
    assert table.successful_puts == []
    assert table.items.get(event_id) == winner
    assert original == documents["v1"]


def test_other_dynamodb_errors_are_not_reported_as_concurrent_migrations(documents):
    original = deepcopy(documents["v1"])
    failure = _client_error("AccessDeniedException")
    table = ConditionalMemoryTable([original], put_error=failure)

    with pytest.raises(ClientError) as raised:
        migrate_event(original["eventId"], table=table)

    assert raised.value is failure
    assert table.successful_puts == []
    assert table.items[original["eventId"]] == original
