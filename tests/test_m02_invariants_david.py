import pytest
from psycopg2 import errors

from test_telemetry_contract import (
    telemetry_context,
    insert_reading,
)


def test_duplicate_reading_is_rejected(telemetry_context):
    _, cur, device_id = telemetry_context
    insert_reading(cur, device_id)

    with pytest.raises(errors.UniqueViolation) as exc:
        insert_reading(cur, device_id)

    assert (
        exc.value.diag.constraint_name
        == "uq_telemetry_device_recorded_at"
    )


def test_nonexistent_device_is_rejected(telemetry_context):
    _, cur, _ = telemetry_context

    # Obtiene un ID que no existe en esta base de prueba.
    cur.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM devices")
    missing_device_id = cur.fetchone()[0]

    with pytest.raises(errors.ForeignKeyViolation) as exc:
        insert_reading(cur, missing_device_id)

    assert (
        exc.value.diag.constraint_name
        == "fk_telemetry_readings_device"
    )


def test_required_device_is_rejected_when_null(telemetry_context):
    _, cur, _ = telemetry_context

    with pytest.raises(errors.NotNullViolation) as exc:
        insert_reading(cur, None)

    assert exc.value.diag.column_name == "device_id"


def test_received_before_recorded_is_rejected(telemetry_context):
    _, cur, device_id = telemetry_context
    reading_id = insert_reading(cur, device_id)

    with pytest.raises(errors.CheckViolation) as exc:
        cur.execute(
            """
            UPDATE telemetry_readings
            SET received_at = recorded_at - INTERVAL '1 second'
            WHERE id = %s
            """,
            (reading_id,),
        )

    assert (
        exc.value.diag.constraint_name
        == "ck_telemetry_timestamp_order"
    )


def test_device_with_readings_cannot_be_deleted(telemetry_context):
    _, cur, device_id = telemetry_context
    insert_reading(cur, device_id)

    with pytest.raises(errors.ForeignKeyViolation) as exc:
        cur.execute(
            "DELETE FROM devices WHERE id = %s",
            (device_id,),
        )

    assert (
        exc.value.diag.constraint_name
        == "fk_telemetry_readings_device"
    )


def test_location_with_devices_cannot_be_deleted(telemetry_context):
    _, cur, device_id = telemetry_context

    cur.execute(
        "SELECT location_id FROM devices WHERE id = %s",
        (device_id,),
    )
    location_id = cur.fetchone()[0]

    with pytest.raises(errors.ForeignKeyViolation) as exc:
        cur.execute(
            "DELETE FROM locations WHERE id = %s",
            (location_id,),
        )

    assert exc.value.diag.constraint_name == "fk_devices_location"


def test_context_view_returns_related_reading(telemetry_context):
    _, cur, device_id = telemetry_context
    reading_id = insert_reading(cur, device_id)

    cur.execute(
        """
        SELECT reading_id, device_code, location_code
        FROM public.v_telemetry_context
        WHERE device_id = %s
        """,
        (device_id,),
    )

    assert cur.fetchall() == [
        (reading_id, "TEST-DEV-M01", "TEST-LOC-M01")
    ]


def test_context_view_without_readings_is_empty(telemetry_context):
    _, cur, device_id = telemetry_context

    # El dispositivo existe, pero todavía no tiene lecturas.
    cur.execute(
        """
        SELECT reading_id
        FROM public.v_telemetry_context
        WHERE device_id = %s
        """,
        (device_id,),
    )

    assert cur.fetchall() == []