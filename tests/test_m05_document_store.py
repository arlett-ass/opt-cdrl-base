"""Pruebas reproducibles del almacén documental M05."""

import json
import time
from decimal import Decimal
from pathlib import Path

import pytest

from src.m05.document_store import (
    DuplicateEventError,
    EventNotFoundError,
    create_event,
    delete_event,
    get_event,
    query_by_source,
    query_by_type,
    update_event,
)
from src.m05.dynamodb_client import get_table
from src.m05.event_contract import EventValidationError
from src.m05.table_setup import ensure_table


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "m05_events.json"


@pytest.fixture(scope="session")
def m05_table():
    """Garantiza que la tabla e índices M05 existan antes de probar."""
    ensure_table()
    return get_table()


@pytest.fixture()
def events():
    """Carga los fixtures sintéticos definidos por el equipo."""
    return json.loads(
        FIXTURE_PATH.read_text(encoding="utf-8")
    )


@pytest.fixture(autouse=True)
def clean_test_events(m05_table, events):
    """Deja los eventId usados por las pruebas en estado reproducible."""
    event_ids = [
        events["valid"]["eventId"],
        events["invalid"]["eventId"],
        events["missing_event_id"],
    ]

    for event_id in event_ids:
        delete_event(event_id, table=m05_table)

    yield

    for event_id in event_ids:
        delete_event(event_id, table=m05_table)


def _wait_for_event_in_query(query_function, event_id, *args):
    """Espera brevemente la propagación eventual de los GSIs."""
    for _ in range(20):
        items = query_function(*args)

        if any(
            item.get("eventId") == event_id
            for item in items
        ):
            return items

        time.sleep(0.1)

    return []


def test_document_store_normal_flow(m05_table, events):
    """Caso normal: CRUD completo y consultas por ambos GSIs."""
    event = events["valid"]
    event_id = event["eventId"]

    created = create_event(
        event,
        table=m05_table,
    )

    assert created["eventId"] == event_id

    stored = get_event(
        event_id,
        table=m05_table,
    )

    assert stored is not None
    assert stored["eventId"] == event_id
    assert stored["payload"]["deviceId"] == 42

    updated = update_event(
        event_id,
        {
            "payload": {
                "temperatureC": "24.00",
            }
        },
        table=m05_table,
    )

    assert updated["payload"]["temperatureC"] == Decimal("24.00")

    by_type = _wait_for_event_in_query(
        lambda event_type, start, end: query_by_type(
            event_type,
            start,
            end,
            table=m05_table,
        ),
        event_id,
        event["type"],
        event["timestamp"],
        event["timestamp"],
    )

    assert any(
        item["eventId"] == event_id
        for item in by_type
    )

    by_source = _wait_for_event_in_query(
        lambda source, start, end: query_by_source(
            source,
            start,
            end,
            table=m05_table,
        ),
        event_id,
        event["source"],
        event["timestamp"],
        event["timestamp"],
    )

    assert any(
        item["eventId"] == event_id
        for item in by_source
    )

    assert delete_event(
        event_id,
        table=m05_table,
    ) is True

    assert get_event(
        event_id,
        table=m05_table,
    ) is None


def test_duplicate_event_is_rejected(m05_table, events):
    """Límite 1: el mismo eventId no puede crearse dos veces."""
    event = events["valid"]
    duplicate = events["duplicate"]

    create_event(
        event,
        table=m05_table,
    )

    with pytest.raises(DuplicateEventError):
        create_event(
            duplicate,
            table=m05_table,
        )

    stored = get_event(
        event["eventId"],
        table=m05_table,
    )

    assert stored is not None
    assert stored["eventId"] == event["eventId"]


def test_missing_event_is_handled(m05_table, events):
    """Límite 2: read/update/delete manejan una identidad ausente."""
    missing_id = events["missing_event_id"]

    assert get_event(
        missing_id,
        table=m05_table,
    ) is None

    with pytest.raises(EventNotFoundError):
        update_event(
            missing_id,
            {
                "payload": {
                    "temperatureC": "25.00",
                }
            },
            table=m05_table,
        )

    assert get_event(
        missing_id,
        table=m05_table,
    ) is None

    assert delete_event(
        missing_id,
        table=m05_table,
    ) is False


def test_invalid_document_is_rejected(m05_table, events):
    """Fallo declarado: un documento inválido nunca se persiste."""
    invalid = events["invalid"]

    with pytest.raises(EventValidationError):
        create_event(
            invalid,
            table=m05_table,
        )

    assert get_event(
        invalid["eventId"],
        table=m05_table,
    ) is None
