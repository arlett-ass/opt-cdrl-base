import os
import psycopg2
import pytest
from psycopg2 import errors
from datetime import datetime, timezone
from decimal import Decimal

def get_connection():
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB", "cdrl"),
        user=os.getenv("POSTGRES_USER", "cdrl_dev"),
        password=os.getenv("POSTGRES_PASSWORD", "cdrl_dev_only"),
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("POSTGRES_PORT", "5432"),
    )

@pytest.fixture
def telemetry_context():
    """
    Crea una ubicación y un dispositivo exclusivamente para cada prueba.

    Todo se ejecuta dentro de una transacción que se revierte al final,
    por lo que las pruebas no contaminan la base ni el seed.
    """
    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO locations (
            location_code,
            name,
            latitude,
            longitude
        )
        VALUES (
            'TEST-LOC-M01',
            'Ubicacion sintetica de prueba',
            19.000000,
            -99.000000
        )
        RETURNING id;
        """
    )

    location_id = cur.fetchone()[0]

    cur.execute(
        """
        INSERT INTO devices (
            location_id,
            device_code,
            name,
            status,
            installed_at
        )
        VALUES (
            %s,
            'TEST-DEV-M01',
            'Sensor sintetico de prueba',
            'active',
            '2026-01-01T00:00:00+00:00'
        )
        RETURNING id;
        """,
        (location_id,),
    )

    device_id = cur.fetchone()[0]

    yield conn, cur, device_id

    conn.rollback()
    cur.close()
    conn.close()

def insert_reading(
    cur,
    device_id,
    temperature="24.00",
    humidity="50.00",
    co2="500.00",
):
    recorded_at = datetime(
        2026, 2, 1, 10, 0,
        tzinfo=timezone.utc,
    )

    received_at = datetime(
        2026, 2, 1, 10, 5,
        tzinfo=timezone.utc,
    )

    cur.execute(
        """
        INSERT INTO telemetry_readings (
            device_id,
            recorded_at,
            received_at,
            temperature_c,
            humidity_pct,
            co2_ppm
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        (
            device_id,
            recorded_at,
            received_at,
            Decimal(str(temperature)),
            Decimal(str(humidity)),
            Decimal(str(co2)),
        ),
    )

    return cur.fetchone()[0]

def test_normal_reading_is_accepted(telemetry_context):
    """
    Caso normal:
    temperatura = 24.00 °C
    humedad = 50.00 %
    CO2 = 500.00 ppm
    Resultado esperado: aceptado.
    """
    _, cur, device_id = telemetry_context

    reading_id = insert_reading(
        cur,
        device_id,
        temperature="24.00",
        humidity="50.00",
        co2="500.00",
    )

    assert reading_id is not None

def test_lower_temperature_boundary_is_accepted(
    telemetry_context,
):
    """
    Caso límite #1:
    temperatura = -50.00 °C
    Resultado esperado: aceptado.
    """
    _, cur, device_id = telemetry_context

    reading_id = insert_reading(
        cur,
        device_id,
        temperature="-50.00",
    )

    assert reading_id is not None

def test_upper_co2_boundary_is_accepted(
    telemetry_context,
):
    """
    Caso límite #2:
    CO2 = 10000.00 ppm
    Resultado esperado: aceptado.
    """
    _, cur, device_id = telemetry_context

    reading_id = insert_reading(
        cur,
        device_id,
        co2="10000.00",
    )

    assert reading_id is not None

def test_humidity_above_maximum_is_rejected(
    telemetry_context,
):
    """
    Fallo declarado:
    humedad = 100.05 %
    Resultado esperado:
    PostgreSQL debe rechazarla por ck_telemetry_humidity.
    """
    _, cur, device_id = telemetry_context

    with pytest.raises(errors.CheckViolation) as exc_info:
        insert_reading(
            cur,
            device_id,
            humidity="100.05",
        )

    assert (
        exc_info.value.diag.constraint_name
        == "ck_telemetry_humidity"
    )