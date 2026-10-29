"""David M07: estrategia de rollback usando previousEvent.

Estas pruebas validan la estrategia de recuperación sin realizar
escrituras adicionales en DynamoDB. El rollback consiste en conservar
la imagen previa entregada por migrate_event().
"""

from copy import deepcopy

import pytest

from src.m07.migration import migrate_event


class MemoryTable:
    """Tabla mínima para probar migrate_event."""

    def __init__(self, document):
        self.item = deepcopy(document)
        self.put_calls = 0

    def get_item(self, *, Key, ConsistentRead):
        return {"Item": deepcopy(self.item)}

    def put_item(
        self,
        *,
        Item,
        ConditionExpression,
        ExpressionAttributeNames,
        ExpressionAttributeValues,
    ):
        self.put_calls += 1
        self.item = deepcopy(Item)
        return {}


@pytest.fixture
def document_v1():
    return {
        "eventId": "telemetry#7001#1792596600123456",
        "type": "telemetry.reading",
        "source": "device-7001",
        "timestamp": "2026-10-21T15:30:00.123456Z",
        "payload": {
            "readingId": 1,
            "deviceId": 7001,
            "receivedAt": "2026-10-21T15:30:01.000000Z",
            "temperatureC": "23.45",
            "humidityPct": "51.20",
            "co2Ppm": "650.00",
        },
        "metadata": {
            "schemaVersion": 1,
        },
    }


def test_previous_event_can_be_used_as_safe_snapshot(document_v1):
    table = MemoryTable(document_v1)

    result = migrate_event(document_v1["eventId"], table=table)

    previous = result["previousEvent"]

    assert previous["metadata"]["schemaVersion"] == 1
    assert previous["payload"]["temperatureC"] == "23.45"
    assert previous["payload"]["humidityPct"] == "51.20"
    assert previous["payload"]["co2Ppm"] == "650.00"

    assert result["event"]["metadata"]["schemaVersion"] == 2
    assert result["changed"] is True


def test_snapshot_is_independent_from_migrated_document(document_v1):
    table = MemoryTable(document_v1)

    result = migrate_event(document_v1["eventId"], table=table)

    previous = result["previousEvent"]
    migrated = result["event"]

    migrated["payload"]["measurements"]["temperatureC"] = 999

    assert previous["payload"]["temperatureC"] == "23.45"


def test_previous_event_preserves_original_document(document_v1):
    original = deepcopy(document_v1)

    table = MemoryTable(document_v1)

    result = migrate_event(document_v1["eventId"], table=table)

    assert result["previousEvent"] == original


def test_strategy_requires_previous_event(document_v1):
    table = MemoryTable(document_v1)

    result = migrate_event(document_v1["eventId"], table=table)

    assert "previousEvent" in result
    assert result["previousEvent"] is not None


def test_migration_performs_single_write(document_v1):
    table = MemoryTable(document_v1)

    migrate_event(document_v1["eventId"], table=table)

    assert table.put_calls == 1


def test_reexecution_does_not_generate_new_write(document_v1):
    table = MemoryTable(document_v1)

    migrate_event(document_v1["eventId"], table=table)
    migrate_event(document_v1["eventId"], table=table)

    assert table.put_calls == 1