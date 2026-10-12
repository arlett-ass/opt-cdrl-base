"""Pruebas M06 de recuperación controlada y ausencia de restore parcial."""

from pathlib import Path
from copy import deepcopy

import pytest

from src.m05.dynamodb_client import get_table
from src.m05.table_setup import ensure_table
from src.m06.recovery import (
    RecoveryFixtureError,
    load_recovery_fixture,
    restore_fixture,
)
from src.m06.schema_evolution import validate_versioned_event


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "m06_recovery_fixture.json"
)


@pytest.fixture(scope="session")
def recovery_table():
    """Garantiza que cdrl_events exista antes de recovery."""
    ensure_table()
    return get_table()


@pytest.fixture()
def recovery_events():
    return load_recovery_fixture(FIXTURE_PATH)


@pytest.fixture(autouse=True)
def clean_recovery_events(recovery_table, recovery_events):
    """Aísla los eventId sintéticos usados por las pruebas M06."""
    event_ids = [
        event["eventId"]
        for event in recovery_events
    ]

    for event_id in event_ids:
        recovery_table.delete_item(
            Key={"eventId": event_id}
        )

    yield

    for event_id in event_ids:
        recovery_table.delete_item(
            Key={"eventId": event_id}
        )


def _get_raw(table, event_id):
    return table.get_item(
        Key={"eventId": event_id},
        ConsistentRead=True,
    ).get("Item")


def test_controlled_loss_is_restored_and_measured(
    recovery_table,
    recovery_events,
):
    """Caso recovery: una pérdida sintética se restaura y se mide."""
    normalized = [
        validate_versioned_event(event)
        for event in recovery_events
    ]

    for event in normalized:
        recovery_table.put_item(
            Item=event,
            ConditionExpression="attribute_not_exists(eventId)",
        )

    lost_event = normalized[0]

    recovery_table.delete_item(
        Key={"eventId": lost_event["eventId"]}
    )

    assert (
        _get_raw(
            recovery_table,
            lost_event["eventId"],
        )
        is None
    )

    result = restore_fixture(
        recovery_events,
        table=recovery_table,
    )

    assert result["expectedCount"] == 3
    assert result["restoredCount"] == 1
    assert result["skippedCount"] == 2
    assert result["verifiedCount"] == 3
    assert result["durationMs"] >= 0
    assert result["integrityPassed"] is True

    for expected in normalized:
        stored = _get_raw(
            recovery_table,
            expected["eventId"],
        )

        assert stored is not None
        assert (
            validate_versioned_event(stored)
            == expected
        )


def test_invalid_fixture_fails_before_any_partial_restore(
    recovery_table,
    recovery_events,
):
    """Fallo declarado: fixture inválido no restaura parcialmente."""
    invalid = deepcopy(recovery_events)

    invalid[1]["metadata"]["schemaVersion"] = 999

    with pytest.raises(
        RecoveryFixtureError,
        match="posición 1",
    ):
        restore_fixture(
            invalid,
            table=recovery_table,
        )

    for event in recovery_events:
        assert (
            _get_raw(
                recovery_table,
                event["eventId"],
            )
            is None
        )
