from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
import pytest
from psycopg2 import errors
from rebuild import get_connection
from db.queries.telemetry import readings_between

START = datetime(2026, 4, 1, 12, tzinfo=timezone.utc)

@pytest.fixture
def acceptance_context():
    """Datos propios por prueba, sin depender de fixtures de M01."""
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            suffix = uuid4().hex

            cur.execute(
                """
                INSERT INTO locations
                    (location_code, name, latitude, longitude)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (f"M02-LOC-{suffix}", "Ubicacion de prueba", 0, 0),
            )
            location_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO devices
                    (location_id, device_code, name, status, installed_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    location_id,
                    f"M02-DEV-{suffix}",
                    "Sensor de prueba",
                    "active",
                    START - timedelta(days=1),
                ),
            )
            device_id = cur.fetchone()[0]

            yield conn, cur, device_id
    finally:
        conn.rollback()
        conn.close()

def add_reading(cur, device_id, recorded_at, temperature, humidity, co2):
    cur.execute(
        """
        INSERT INTO telemetry_readings
            (device_id, recorded_at, received_at,
             temperature_c, humidity_pct, co2_ppm)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            device_id,
            recorded_at,
            recorded_at,
            Decimal(temperature),
            Decimal(humidity),
            Decimal(co2),
        ),
    )

def test_m02_normal(acceptance_context):
    conn, cur, device_id = acceptance_context
    add_reading(cur, device_id, START, "24.00", "50.00", "500.00")

    rows = readings_between(conn, device_id, START, START)

    assert len(rows) == 1
    assert rows[0]["device_id"] == device_id
    assert rows[0]["recorded_at"] == START
    assert rows[0]["temperature_c"] == Decimal("24.00")
    assert rows[0]["humidity_pct"] == Decimal("50.00")
    assert rows[0]["co2_ppm"] == Decimal("500.00")

def test_m02_empty(acceptance_context):
    conn, cur, device_id = acceptance_context
    add_reading(cur, device_id, START, "24.00", "50.00", "500.00")

    after = START + timedelta(days=1)

    assert readings_between(conn, device_id, after, after) == []

    # Comprueba que el resultado vacío se debe al filtro temporal.
    assert len(readings_between(conn, device_id, START, START)) == 1

def test_m02_boundaries(acceptance_context):
    conn, cur, device_id = acceptance_context
    end = START + timedelta(seconds=1)

    add_reading(cur, device_id, START, "-50.00", "0.00", "0.00")
    add_reading(cur, device_id, end, "80.00", "100.00", "10000.00")

    rows = readings_between(conn, device_id, START, end)

    assert [row["recorded_at"] for row in rows] == [START, end]
    assert [
        (row["temperature_c"], row["humidity_pct"], row["co2_ppm"])
        for row in rows
    ] == [
        (Decimal("-50.00"), Decimal("0.00"), Decimal("0.00")),
        (Decimal("80.00"), Decimal("100.00"), Decimal("10000.00")),
    ]

def test_m02_declared_failure(acceptance_context):
    conn, cur, device_id = acceptance_context
    cur.execute("SAVEPOINT invalid_reading")

    with pytest.raises(errors.CheckViolation) as exc:
        add_reading(cur, device_id, START, "24.00", "101.00", "500.00")

    assert exc.value.diag.constraint_name == "ck_telemetry_humidity"
    assert exc.value.pgcode == "23514"

    # Recupera la transacción después del rechazo esperado.
    cur.execute("ROLLBACK TO SAVEPOINT invalid_reading")

    # La operación inválida no dejó una lectura almacenada.
    assert readings_between(conn, device_id, START, START) == []