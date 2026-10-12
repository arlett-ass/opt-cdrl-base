"""Pruebas M06 de coexistencia, migración e idempotencia v1/v2."""

from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

from botocore.exceptions import ClientError
import pytest

from src.m06.schema_evolution import (
    UnsupportedSchemaVersionError,
    migrate_v1_to_v2,
    validate_versioned_event,
)
from src.m06.versioned_store import (
    create_versioned_event,
    get_versioned_event,
    migrate_event_to_v2,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "m06_versioned_events.json"


@pytest.fixture
def events():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class MemoryTable:
    """Sustituto pequeño de DynamoDB Table para pruebas sin servicios externos."""

    def __init__(self):
        self.items = {}
        self.put_calls = []

    def get_item(self, *, Key, ConsistentRead):
        assert ConsistentRead is True
        item = self.items.get(Key["eventId"])
        return {"Item": deepcopy(item)} if item is not None else {}

    def put_item(self, *, Item, ConditionExpression, **kwargs):
        self.put_calls.append(deepcopy(Item))
        event_id = Item["eventId"]
        current = self.items.get(event_id)

        if (
            ConditionExpression == "attribute_not_exists(eventId)"
            and current is not None
        ):
            self._conditional_failure()

        if ":from_version" in kwargs.get("ExpressionAttributeValues", {}):
            if (
                current is None
                or current.get("metadata", {}).get("schemaVersion") != 1
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


def test_versioned_store_coexists_and_migrates_without_data_loss(events):
    table = MemoryTable()
    original_v1 = deepcopy(events["v1"])

    # El mismo evento representado en ambos contratos conserva sus datos.
    pure_migration = migrate_v1_to_v2(original_v1)
    assert pure_migration == validate_versioned_event(events["v2_equivalent"])
    assert migrate_v1_to_v2(pure_migration) == pure_migration
    assert original_v1 == events["v1"]

    # Eventos v1 y v2 pueden permanecer juntos en la tabla compartida.
    create_versioned_event(events["v1"], table=table)
    create_versioned_event(events["v1_coexisting"], table=table)
    assert (
        get_versioned_event(events["v1"]["eventId"], table=table)
        ["metadata"]["schemaVersion"]
        == 1
    )
    assert (
        get_versioned_event(events["v1_coexisting"]["eventId"], table=table)
        ["metadata"]["schemaVersion"]
        == 1
    )

    migrated = migrate_event_to_v2(events["v1"]["eventId"], table=table)
    assert migrated == validate_versioned_event(events["v2_equivalent"])
    assert migrated["eventId"] == original_v1["eventId"]
    assert migrated["type"] == original_v1["type"]
    assert migrated["source"] == original_v1["source"]
    assert migrated["timestamp"] == original_v1["timestamp"]
    assert (
        migrated["payload"]["readingId"]
        == original_v1["payload"]["readingId"]
    )
    assert (
        migrated["payload"]["deviceId"]
        == original_v1["payload"]["deviceId"]
    )
    assert (
        migrated["payload"]["receivedAt"]
        == original_v1["payload"]["receivedAt"]
    )
    assert migrated["payload"]["measurements"] == {
        "temperatureC": Decimal("23.45"),
        "humidityPct": Decimal("51.20"),
        "co2Ppm": Decimal("650.00"),
    }
    assert (
        get_versioned_event(events["v1"]["eventId"], table=table)
        ["metadata"]["schemaVersion"]
        == 2
    )
    assert (
        get_versioned_event(events["v1_coexisting"]["eventId"], table=table)
        ["metadata"]["schemaVersion"]
        == 1
    )

    writes_after_first_migration = len(table.put_calls)
    retried_migration = migrate_event_to_v2(
        events["v1"]["eventId"],
        table=table,
    )
    assert retried_migration == migrated
    assert len(table.put_calls) == writes_after_first_migration

    unsupported = deepcopy(events["v1"])
    unsupported["metadata"]["schemaVersion"] = 999
    with pytest.raises(UnsupportedSchemaVersionError, match="999"):
        validate_versioned_event(unsupported)
    with pytest.raises(UnsupportedSchemaVersionError, match="999"):
        migrate_v1_to_v2(unsupported)


def test_migrating_existing_v2_is_idempotent_and_does_not_write(events):
    table = MemoryTable()
    created = create_versioned_event(events["v2_equivalent"], table=table)
    put_count = len(table.put_calls)

    pure_first = migrate_v1_to_v2(events["v2_equivalent"])
    pure_second = migrate_v1_to_v2(pure_first)
    first = migrate_event_to_v2(created["eventId"], table=table)
    second = migrate_event_to_v2(created["eventId"], table=table)

    assert pure_first == created
    assert pure_second == pure_first
    assert first == created
    assert second == first
    assert len(table.put_calls) == put_count
