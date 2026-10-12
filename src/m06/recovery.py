
"""Recuperación controlada de fixtures sintéticos para M06.

El procedimiento pre-valida todo el fixture antes de escribir, restaura
únicamente eventos ausentes y verifica la integridad al terminar.
"""

import json
from pathlib import Path
from time import perf_counter

from botocore.exceptions import ClientError

from src.m05.dynamodb_client import get_table
from src.m06.schema_evolution import validate_versioned_event


class RecoveryFixtureError(ValueError):
    """El fixture de recuperación no cumple el contrato esperado."""


class RecoveryConflictError(RuntimeError):
    """Existe un eventId del fixture con contenido distinto al esperado."""


class RecoveryWriteError(RuntimeError):
    """Una escritura de recovery no pudo completarse de forma segura."""


def load_recovery_fixture(path):
    """Carga un fixture JSON y devuelve su lista de eventos.

    El archivo debe contener un objeto con una propiedad ``events``.
    La validación semántica completa se realiza antes de cualquier escritura.
    """
    fixture_path = Path(path)

    if not fixture_path.is_file():
        raise RecoveryFixtureError(
            f"No existe el fixture de recuperación: {fixture_path}"
        )

    try:
        payload = json.loads(
            fixture_path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        raise RecoveryFixtureError(
            f"El fixture no contiene JSON válido: {fixture_path}"
        ) from exc

    if not isinstance(payload, dict):
        raise RecoveryFixtureError(
            "El fixture de recuperación debe ser un objeto JSON."
        )

    if set(payload) != {"fixtureId", "events"}:
        raise RecoveryFixtureError(
            "El fixture debe contener exactamente fixtureId y events."
        )

    fixture_id = payload["fixtureId"]

    if not isinstance(fixture_id, str) or not fixture_id.strip():
        raise RecoveryFixtureError(
            "fixtureId debe ser una cadena no vacía."
        )

    events = payload["events"]

    validate_recovery_fixture(events)

    return events


def validate_recovery_fixture(items):
    """Valida completamente el fixture antes de cualquier escritura.

    Devuelve documentos normalizados v1/v2 y rechaza eventId duplicados.
    """
    if not isinstance(items, list) or not items:
        raise RecoveryFixtureError(
            "El fixture debe contener una lista no vacía de eventos."
        )

    normalized = []
    event_ids = set()

    for index, item in enumerate(items):
        try:
            event = validate_versioned_event(item)
        except Exception as exc:
            raise RecoveryFixtureError(
                f"Evento inválido en posición {index}: {exc}"
            ) from exc

        event_id = event["eventId"]

        if event_id in event_ids:
            raise RecoveryFixtureError(
                f"eventId duplicado en fixture: {event_id}"
            )

        event_ids.add(event_id)
        normalized.append(event)

    return normalized


def _read_raw_event(table, event_id):
    response = table.get_item(
        Key={"eventId": event_id},
        ConsistentRead=True,
    )

    return response.get("Item")


def _events_are_equivalent(stored, expected):
    if stored is None:
        return False

    try:
        return validate_versioned_event(stored) == expected
    except Exception:
        return False


def restore_fixture(items, table=None):
    """Restaura de forma controlada los eventos ausentes del fixture.

    Flujo:
    1. Pre-valida todos los elementos.
    2. Pre-lee los eventId y detecta conflictos.
    3. Restaura únicamente los ausentes.
    4. Verifica todos los eventos al finalizar.
    5. Devuelve métricas reproducibles.

    Un documento existente e idéntico se contabiliza como ``skipped``.
    Un documento existente con el mismo eventId pero contenido diferente
    se considera conflicto y no se sobrescribe.
    """
    started_at = perf_counter()

    # Regla crítica: toda la validación ocurre antes de escribir.
    expected_events = validate_recovery_fixture(items)

    table = table if table is not None else get_table()

    missing = []
    skipped_count = 0

    # Preflight completo antes de escribir.
    for expected in expected_events:
        event_id = expected["eventId"]
        stored = _read_raw_event(table, event_id)

        if stored is None:
            missing.append(expected)
            continue

        if not _events_are_equivalent(stored, expected):
            raise RecoveryConflictError(
                "El eventId "
                f"{event_id} ya existe con contenido distinto al fixture."
            )

        skipped_count += 1

    restored_count = 0

    for expected in missing:
        try:
            table.put_item(
                Item=expected,
                ConditionExpression="attribute_not_exists(eventId)",
            )
        except ClientError as exc:
            if (
                exc.response.get("Error", {}).get("Code")
                == "ConditionalCheckFailedException"
            ):
                raise RecoveryWriteError(
                    "El evento cambió durante la recuperación: "
                    f"{expected['eventId']}"
                ) from exc

            raise

        restored_count += 1

    verified_count = 0

    for expected in expected_events:
        stored = _read_raw_event(
            table,
            expected["eventId"],
        )

        if _events_are_equivalent(stored, expected):
            verified_count += 1

    expected_count = len(expected_events)
    integrity_passed = verified_count == expected_count

    duration_ms = round(
        (perf_counter() - started_at) * 1000,
        3,
    )

    return {
        "expectedCount": expected_count,
        "restoredCount": restored_count,
        "skippedCount": skipped_count,
        "verifiedCount": verified_count,
        "durationMs": duration_ms,
        "integrityPassed": integrity_passed,
    }
