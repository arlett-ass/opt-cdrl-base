"""Víctor M08: contrato del cursor y paginación sobre DynamoDB Local.

Los dobles comprueban las solicitudes sin sustituir las pruebas funcionales.
Estas últimas crean tablas sintéticas propias con los índices M05 y las
eliminan al finalizar; nunca utilizan cdrl_events ni requieren datos reales.
"""

from copy import deepcopy
from decimal import Decimal
import json
import os
import time
from uuid import uuid4

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
import pytest

from src.m05.document_store import create_event, query_by_type
from src.m05.dynamodb_client import get_dynamodb_client, get_dynamodb_resource
from src.m05.event_contract import build_event_id, validate_event
from src.m05.table_setup import ensure_table
from src.m06.schema_evolution import migrate_v1_to_v2
from src.m06.versioned_store import create_versioned_event
from src.m08.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    InvalidCursorError,
    query_by_type_page,
)


EVENT_TYPE = "telemetry.reading"
START = "2026-10-29T10:00:00.000000Z"
END = "2026-10-29T10:10:00.000000Z"
NATIVE_KEY = {
    "eventId": "telemetry#81001#1793268060000000",
    "type": EVENT_TYPE,
    "timestamp": "2026-10-29T10:01:00.000000Z",
}


def _cursor(key=None):
    return {
        "version": 1,
        "query": {"event_type": EVENT_TYPE, "start": START, "end": END},
        "last_evaluated_key": deepcopy(NATIVE_KEY if key is None else key),
    }


class RecordingTable:
    """Registra Query y falla si una petición de página consume otra página."""

    def __init__(self, response=None, error=None):
        self.response = {"Items": []} if response is None else deepcopy(response)
        self.error = error
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        assert len(self.calls) == 1, "Una llamada no debe drenar todas las páginas."
        if self.error is not None:
            raise self.error
        return deepcopy(self.response)

    def scan(self, **kwargs):
        raise AssertionError("La consulta paginada debe usar Query, no Scan.")


def _assert_native_request(table, page_size):
    assert len(table.calls) == 1
    request = table.calls[0]
    assert request["IndexName"] == "type-timestamp-index"
    assert request["Limit"] == page_size
    assert request["ScanIndexForward"] is True
    assert request.get("ConsistentRead") is not True
    assert "FilterExpression" not in request
    assert request["KeyConditionExpression"] == (
        Key("type").eq(EVENT_TYPE) & Key("timestamp").between(START, END)
    )
    return request


def test_first_page_uses_one_query_and_keeps_native_item_order():
    # Los IDs de un mismo timestamp no se reordenan por una garantía inventada.
    items = [
        {"eventId": "event-z", "timestamp": START},
        {"eventId": "event-a", "timestamp": START},
    ]
    table = RecordingTable({"Items": items, "LastEvaluatedKey": NATIVE_KEY})

    page = query_by_type_page(EVENT_TYPE, START, END, table=table)

    assert DEFAULT_PAGE_SIZE == 20
    assert MAX_PAGE_SIZE == 1000
    request = _assert_native_request(table, DEFAULT_PAGE_SIZE)
    assert "ExclusiveStartKey" not in request
    assert page == {"items": items, "next_cursor": _cursor()}
    # El cursor procede de LastEvaluatedKey, no del último elemento devuelto.
    assert page["next_cursor"]["last_evaluated_key"] != items[-1]


def test_json_cursor_continues_with_exact_native_key_and_normalized_filters():
    cursor = json.loads(json.dumps(_cursor()))
    original = deepcopy(cursor)
    table = RecordingTable({"Items": []})

    page = query_by_type_page(
        EVENT_TYPE,
        "2026-10-29T05:00:00-05:00",
        "2026-10-29T05:10:00-05:00",
        page_size=3,
        cursor=cursor,
        table=table,
    )

    request = _assert_native_request(table, 3)
    assert request["ExclusiveStartKey"] == NATIVE_KEY
    assert cursor == original
    assert page == {"items": [], "next_cursor": None}


def test_native_cursor_timestamp_is_validated_without_rewriting_its_raw_form():
    raw_key = {**NATIVE_KEY, "timestamp": "2026-10-29T10:01:00Z"}
    cursor = _cursor(raw_key)
    original = deepcopy(cursor)
    table = RecordingTable()

    query_by_type_page(EVENT_TYPE, START, END, cursor=cursor, table=table)

    request = _assert_native_request(table, DEFAULT_PAGE_SIZE)
    assert request["ExclusiveStartKey"] == raw_key
    assert request["ExclusiveStartKey"]["timestamp"] == "2026-10-29T10:01:00Z"
    assert cursor == original


@pytest.mark.parametrize("items", [[], [{"eventId": "one", "timestamp": START}]])
def test_short_or_empty_page_with_native_key_still_has_continuation(items):
    table = RecordingTable({"Items": items, "LastEvaluatedKey": NATIVE_KEY})

    page = query_by_type_page(EVENT_TYPE, START, END, page_size=5, table=table)

    assert page == {"items": items, "next_cursor": _cursor()}
    _assert_native_request(table, 5)


@pytest.mark.parametrize("ending", [{}, {"LastEvaluatedKey": {}}])
def test_absent_or_empty_native_key_ends_the_traversal(ending):
    table = RecordingTable({"Items": [], **ending})

    assert query_by_type_page(EVENT_TYPE, START, END, table=table) == {
        "items": [], "next_cursor": None,
    }
    _assert_native_request(table, DEFAULT_PAGE_SIZE)


@pytest.mark.parametrize("page_size", [1, 20, 1000])
def test_inclusive_page_size_boundaries_are_forwarded(page_size):
    table = RecordingTable()

    query_by_type_page(EVENT_TYPE, START, END, page_size=page_size, table=table)

    _assert_native_request(table, page_size)


@pytest.mark.parametrize("page_size", [0, -1, 1001, True, False, None, 1.0, Decimal("20"), "20"])
def test_invalid_page_size_is_rejected_before_query(page_size):
    table = RecordingTable()

    with pytest.raises(ValueError):
        query_by_type_page(EVENT_TYPE, START, END, page_size=page_size, table=table)

    assert table.calls == []


@pytest.mark.parametrize("event_type", [None, "", "   ", 1, True])
def test_invalid_event_type_is_rejected_before_query(event_type):
    table = RecordingTable()

    with pytest.raises(ValueError):
        query_by_type_page(event_type, START, END, table=table)

    assert table.calls == []


@pytest.mark.parametrize(
    "start,end",
    [(END, START), ("2026-10-29T10:00:00", END), ("invalid", END), (START, None)],
)
def test_invalid_temporal_range_is_rejected_before_query(start, end):
    table = RecordingTable()

    with pytest.raises(ValueError):
        query_by_type_page(EVENT_TYPE, start, end, table=table)

    assert table.calls == []


def _invalid_cursors():
    cases = [
        ("empty", {}), ("list", []), ("string", "not-a-cursor"), ("number", 1),
        ("bool", True),
    ]
    for name, value in [("bool_version", True), ("string_version", "1"), ("unknown_version", 2)]:
        cursor = _cursor()
        cursor["version"] = value
        cases.append((name, cursor))
    cursor = _cursor()
    del cursor["version"]
    cases.append(("missing_version", cursor))
    cursor = _cursor()
    cursor["extra"] = "unexpected"
    cases.append(("extra_envelope_field", cursor))
    cursor = _cursor()
    cursor["query"] = []
    cases.append(("invalid_query", cursor))
    for field, value in [
        ("event_type", "other.type"), ("start", "2026-10-29T10:00:01.000000Z"),
        ("end", "2026-10-29T10:20:00.000000Z"),
    ]:
        cursor = _cursor()
        cursor["query"][field] = value
        cases.append((f"different_{field}", cursor))
    cursor = _cursor()
    cursor["query"]["extra"] = 1
    cases.append(("extra_query_field", cursor))
    cursor = _cursor()
    cursor["last_evaluated_key"] = None
    cases.append(("null_key", cursor))
    for field in ("eventId", "type", "timestamp"):
        cursor = _cursor()
        del cursor["last_evaluated_key"][field]
        cases.append((f"missing_key_{field}", cursor))
        cursor = _cursor()
        cursor["last_evaluated_key"][field] = ""
        cases.append((f"empty_key_{field}", cursor))
        cursor = _cursor()
        cursor["last_evaluated_key"][field] = 12
        cases.append((f"non_string_key_{field}", cursor))
    cursor = _cursor()
    cursor["last_evaluated_key"]["extra"] = "unexpected"
    cases.append(("extra_native_key_field", cursor))
    cursor = _cursor()
    cursor["last_evaluated_key"]["type"] = "other.type"
    cases.append(("different_key_partition", cursor))
    cursor = _cursor()
    cursor["last_evaluated_key"]["timestamp"] = "2026-10-29T09:59:59.000000Z"
    cases.append(("key_before_range", cursor))
    cursor = _cursor()
    cursor["last_evaluated_key"]["timestamp"] = "2026-10-29T10:10:00.000001Z"
    cases.append(("key_after_range", cursor))
    cursor = _cursor()
    cursor["last_evaluated_key"]["timestamp"] = "2026-10-29T10:01:not-a-time"
    cases.append(("malformed_key_timestamp_inside_lexical_range", cursor))
    return [pytest.param(cursor, id=name) for name, cursor in cases]


@pytest.mark.parametrize("cursor", _invalid_cursors())
def test_invalid_cursor_is_a_controlled_error_before_query(cursor):
    table = RecordingTable()
    original = deepcopy(cursor)

    with pytest.raises(InvalidCursorError):
        query_by_type_page(EVENT_TYPE, START, END, cursor=cursor, table=table)

    assert table.calls == []
    assert cursor == original


@pytest.mark.parametrize("code", ["AccessDeniedException", "ResourceNotFoundException", "ValidationException"])
def test_service_errors_are_propagated_without_becoming_empty_results(code):
    failure = ClientError({"Error": {"Code": code, "Message": "synthetic M08 failure"}}, "Query")
    table = RecordingTable(error=failure)

    with pytest.raises(ClientError) as raised:
        query_by_type_page(EVENT_TYPE, START, END, cursor=_cursor(), table=table)

    assert raised.value is failure
    assert len(table.calls) == 1


def test_default_table_factory_is_used_when_no_table_is_injected(monkeypatch):
    table = RecordingTable()
    monkeypatch.setattr("src.m08.pagination.get_table", lambda: table)

    assert query_by_type_page(EVENT_TYPE, START, END) == {"items": [], "next_cursor": None}
    _assert_native_request(table, DEFAULT_PAGE_SIZE)


def test_invalid_arguments_do_not_even_resolve_the_default_table(monkeypatch):
    def forbidden_factory():
        raise AssertionError("Los argumentos deben validarse antes de resolver Table.")

    monkeypatch.setattr("src.m08.pagination.get_table", forbidden_factory)
    with pytest.raises(ValueError):
        query_by_type_page(EVENT_TYPE, START, END, page_size=0)
    with pytest.raises(InvalidCursorError):
        query_by_type_page(EVENT_TYPE, START, END, cursor={})


@pytest.fixture
def real_table():
    """Tabla local única por prueba, con las dos GSIs originales de M05."""
    if os.environ.get("DYNAMODB_LOCAL", "true").strip().lower() != "true":
        pytest.fail("Las pruebas funcionales M08 requieren DYNAMODB_LOCAL=true.")
    client = get_dynamodb_client()
    table_name = f"cdrl_m08_tests_{uuid4().hex[:16]}"
    ensure_table(client=client, table_name=table_name, attempts=100, poll_seconds=0.05)
    table = get_dynamodb_resource().Table(table_name)
    try:
        yield table
    finally:
        client.delete_table(TableName=table_name)
        client.get_waiter("table_not_exists").wait(
            TableName=table_name, WaiterConfig={"Delay": 1, "MaxAttempts": 10},
        )


def _timestamp(minute, second=0):
    return f"2026-10-29T10:{minute:02d}:{second:02d}.000000Z"


def _event(device_id, timestamp):
    return validate_event({
        "eventId": build_event_id(device_id, timestamp),
        "type": EVENT_TYPE,
        "source": f"device-{device_id}",
        "timestamp": timestamp,
        "payload": {
            "readingId": device_id,
            "deviceId": device_id,
            "receivedAt": timestamp,
            "temperatureC": "23.45",
            "humidityPct": "51.20",
            "co2Ppm": "650.00",
        },
        "metadata": {"schemaVersion": 1},
    })


def _put_events(table, events):
    for event in events:
        create_event(event, table=table)


def _wait_for_ids(table, start, end, expected_ids):
    """Separa la propagación eventual del índice del contrato de paginación."""
    deadline = time.monotonic() + 5
    while True:
        found = query_by_type(EVENT_TYPE, start, end, table=table)
        if {event["eventId"] for event in found} == set(expected_ids):
            return found
        if time.monotonic() >= deadline:
            pytest.fail("El GSI no reflejó los IDs sintéticos dentro del plazo de propagación.")
        time.sleep(0.05)


def _walk(table, start, end, page_size, cursor=None):
    items, pages, seen_cursors = [], [], set()
    for _ in range(100):
        page = query_by_type_page(
            EVENT_TYPE, start, end, page_size=page_size, cursor=cursor, table=table,
        )
        assert len(page["items"]) <= page_size
        items.extend(page["items"])
        pages.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            return items, pages
        serialized = json.dumps(cursor, sort_keys=True)
        assert serialized not in seen_cursors, "El cursor no debe repetirse indefinidamente."
        seen_cursors.add(serialized)
        cursor = json.loads(serialized)
    pytest.fail("El recorrido de este dataset pequeño no terminó en cien páginas.")


@pytest.mark.parametrize("page_size", [1, 2, 20])
def test_real_traversal_has_no_duplicates_or_omissions_and_preserves_m05(real_table, page_size):
    start, end = _timestamp(0), _timestamp(1)
    events = [_event(81000 + i, _timestamp(0, i)) for i in range(7)]
    expected = {event["eventId"] for event in events}
    _put_events(real_table, events)
    baseline = _wait_for_ids(real_table, start, end, expected)

    items, pages = _walk(real_table, start, end, page_size)

    ids = [event["eventId"] for event in items]
    assert set(ids) == expected
    assert len(ids) == len(set(ids)) == len(events)
    assert [event["timestamp"] for event in items] == sorted(event["timestamp"] for event in items)
    assert {event["eventId"]: event for event in items} == {
        event["eventId"]: event for event in baseline
    }
    assert isinstance(baseline, list), "M05 debe conservar su retorno de lista completa."
    assert pages[-1]["next_cursor"] is None
    if page_size < len(events):
        assert len(pages) > 1


def test_real_empty_range_has_no_next_cursor(real_table):
    page = query_by_type_page(EVENT_TYPE, _timestamp(10), _timestamp(11), table=real_table)

    assert page == {"items": [], "next_cursor": None}


def test_real_fewer_items_than_page_size_returns_the_available_documents(real_table):
    start, end = _timestamp(20), _timestamp(21)
    events = [_event(82000 + i, _timestamp(20, i)) for i in range(3)]
    expected = {event["eventId"] for event in events}
    _put_events(real_table, events)
    _wait_for_ids(real_table, start, end, expected)

    page = query_by_type_page(EVENT_TYPE, start, end, page_size=20, table=real_table)

    assert {event["eventId"] for event in page["items"]} == expected
    assert len(page["items"]) == 3
    assert page["next_cursor"] is None


def test_real_equal_timestamps_continue_without_claiming_an_event_id_tiebreak(real_table):
    timestamp = _timestamp(30)
    # Distintos dispositivos hacen válidos los IDs con el mismo timestamp.
    events = [_event(device_id, timestamp) for device_id in (83999, 83001, 83600, 83002, 83555, 83003)]
    expected = {event["eventId"] for event in events}
    _put_events(real_table, events)
    _wait_for_ids(real_table, timestamp, timestamp, expected)

    items, pages = _walk(real_table, timestamp, timestamp, page_size=2)

    ids = [event["eventId"] for event in items]
    assert set(ids) == expected
    assert len(ids) == len(set(ids)) == len(events)
    assert all(event["timestamp"] == timestamp for event in items)
    assert len(pages) > 1


def test_real_mixed_v1_v2_documents_keep_all_data_and_decimal_measurements(real_table):
    start, end = _timestamp(50), _timestamp(51)
    originals = [_event(85000 + i, _timestamp(50, i)) for i in range(5)]
    documents = [
        document if i % 2 == 0 else migrate_v1_to_v2(document)
        for i, document in enumerate(originals)
    ]
    expected = {document["eventId"]: document for document in documents}
    for document in documents:
        create_versioned_event(document, table=real_table)
    baseline = _wait_for_ids(real_table, start, end, expected)

    items, pages = _walk(real_table, start, end, page_size=2)

    actual = {document["eventId"]: document for document in items}
    assert actual == expected
    assert actual == {document["eventId"]: document for document in baseline}
    assert len(items) == len(actual) == len(documents)
    assert {int(document["metadata"]["schemaVersion"]) for document in items} == {1, 2}
    assert len(pages) > 1
    assert pages[-1]["next_cursor"] is None
    for document in items:
        payload = document["payload"]
        measurements = payload if document["metadata"]["schemaVersion"] == 1 else payload["measurements"]
        assert {field: measurements[field] for field in ("temperatureC", "humidityPct", "co2Ppm")} == {
            "temperatureC": Decimal("23.45"),
            "humidityPct": Decimal("51.20"),
            "co2Ppm": Decimal("650.00"),
        }
        assert all(isinstance(measurements[field], Decimal) for field in ("temperatureC", "humidityPct", "co2Ppm"))


def test_real_insertions_before_and_after_the_cursor_demonstrate_no_snapshot(real_table):
    start, end = _timestamp(40), _timestamp(41)
    events = [_event(84000 + i, _timestamp(40, second)) for i, second in enumerate((10, 20, 30, 40))]
    original_ids = {event["eventId"] for event in events}
    _put_events(real_table, events)
    _wait_for_ids(real_table, start, end, original_ids)
    first = query_by_type_page(EVENT_TYPE, start, end, page_size=2, table=real_table)
    first_ids = {event["eventId"] for event in first["items"]}
    assert first_ids == {event["eventId"] for event in events[:2]}
    assert first["next_cursor"] is not None

    before = _event(84901, _timestamp(40, 15))
    after = _event(84902, _timestamp(40, 25))
    _put_events(real_table, [before, after])
    _wait_for_ids(real_table, start, end, original_ids | {before["eventId"], after["eventId"]})

    remaining, _ = _walk(real_table, start, end, 2, cursor=first["next_cursor"])
    remaining_ids = [event["eventId"] for event in remaining]

    assert set(remaining_ids) == (original_ids - first_ids) | {after["eventId"]}
    assert before["eventId"] not in remaining_ids
    assert len(remaining_ids) == len(set(remaining_ids))
    assert not first_ids.intersection(remaining_ids)
    # La inserción anterior al cursor no se relee y la posterior puede aparecer:
    # el cursor continúa desde una posición; no congela el dataset original.
