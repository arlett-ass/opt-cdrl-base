"""Pruebas de compatibilidad entre documentos persistidos v1/v2 y consumidor v1."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.m06.schema_evolution import UnsupportedSchemaVersionError
from src.m07.compatibility import (
    SUPPORTED_CONSUMER_VERSIONS,
    UnsupportedConsumerVersionError,
    adapt_for_consumer,
)
from src.m07.versioning import validate_document


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "m07_consumer_cases.json"
)


@pytest.fixture
def consumer_cases():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_v1_consumer_reads_stored_v1(consumer_cases):
    stored = deepcopy(consumer_cases["stored_v1"])

    result = adapt_for_consumer(stored, consumer_version=1)

    expected = validate_document(stored)

    assert result == expected
    assert result is not stored
    assert result["metadata"]["schemaVersion"] == 1


def test_v1_consumer_reads_stored_v2_without_breaking(consumer_cases):
    stored = deepcopy(consumer_cases["stored_v2"])
    original = deepcopy(stored)

    result = adapt_for_consumer(stored, consumer_version=1)

    expected = validate_document(consumer_cases["stored_v1"])

    assert result == expected

    assert result["eventId"] == stored["eventId"]
    assert result["type"] == stored["type"]
    assert result["source"] == stored["source"]
    assert result["timestamp"] == stored["timestamp"]

    assert result["payload"]["readingId"] == stored["payload"]["readingId"]
    assert result["payload"]["deviceId"] == stored["payload"]["deviceId"]
    assert result["payload"]["receivedAt"] == stored["payload"]["receivedAt"]

    assert result["payload"]["temperatureC"] == expected["payload"]["temperatureC"]
    assert result["payload"]["humidityPct"] == expected["payload"]["humidityPct"]
    assert result["payload"]["co2Ppm"] == expected["payload"]["co2Ppm"]

    assert result["metadata"]["schemaVersion"] == 1

    assert stored == original
    assert "measurements" in stored["payload"]
    assert "temperatureC" not in stored["payload"]


def test_adapter_does_not_modify_document(consumer_cases):
    stored = deepcopy(consumer_cases["stored_v2"])
    original = deepcopy(stored)

    result = adapt_for_consumer(stored, consumer_version=1)

    assert stored == original
    assert result is not stored
    assert result["payload"] is not stored["payload"]


def test_unsupported_consumer_version_is_declared(consumer_cases):
    stored = deepcopy(consumer_cases["stored_v1"])

    with pytest.raises(
        UnsupportedConsumerVersionError,
        match="Versión de consumidor no soportada",
    ):
        adapt_for_consumer(
            stored,
            consumer_version=consumer_cases["unsupported_consumer_version"],
        )

    assert stored == consumer_cases["stored_v1"]


def test_unsupported_stored_schema_version_is_rejected(consumer_cases):
    stored = deepcopy(consumer_cases["stored_v1"])
    stored["metadata"]["schemaVersion"] = (
        consumer_cases["unsupported_stored_schema_version"]
    )

    with pytest.raises(
        UnsupportedSchemaVersionError,
        match="99",
    ):
        adapt_for_consumer(stored, consumer_version=1)

    assert stored["metadata"]["schemaVersion"] == 99


def test_only_v1_consumer_is_currently_supported():
    assert SUPPORTED_CONSUMER_VERSIONS == (1,)