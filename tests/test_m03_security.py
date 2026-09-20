from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
import pytest
from psycopg2 import errors
from rebuild import get_connection

@pytest.fixture
def security_context():
    """
    Crear datos sinteticos exclusivos para cada prueba de la entrega de m03.
    La conexión permanece dentro de una transacción y al finalizar se ejecuta ROLLBACK
    por lo que ninguna prueba modifica permanentemente el seed.
    """

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    suffix = uuid4().hex[:8]
    location_code = f"M03-LOC-{suffix}"
    device_code = f"M03-DEV-{suffix}"

    try:
        cur.execute(
            """
            INSERT INTO public.locations (
                location_code,
                name,
                latitude,
                longitude
            )
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (
                location_code,
                "M03 Security Test Location",
                Decimal("20.000000"),
                Decimal("-98.000000"),
            ),
        )
        location_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO public.devices (
                location_id,
                device_code,
                name,
                status,
                installed_at
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                location_id,
                device_code,
                "M03 Security Test Device",
                "active",
                datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc),
            ),
        )
        device_id = cur.fetchone()[0]

        yield {
            "conn": conn,
            "cur": cur,
            "device_id": device_id,
            "device_code": device_code,
        }

    finally:
        try:
            cur.execute("RESET ROLE")
        except Exception:
            conn.rollback()

        conn.rollback()
        cur.close()
        conn.close()

def test_reader_can_query_context_view(security_context):
    """
    Caso normal: cdrl_reader puede consultar la vista relacional.
    """
    cur = security_context["cur"]

    cur.execute("SET ROLE cdrl_reader")

    cur.execute(
        """
        SELECT device_code
        FROM public.v_telemetry_context
        WHERE device_id = %s
        """,
        (security_context["device_id"],),
    )

    assert cur.fetchall() == []

def test_writer_can_insert_telemetry_reading(security_context):
    """
    Caso limite 1: cdrl_writer puede insertar telemetria y utilizar la secuencia identity necesaria para generar el id.
    """
    cur = security_context["cur"]
    device_id = security_context["device_id"]

    recorded_at = datetime(
        2026, 9, 19, 12, 0, tzinfo=timezone.utc
    )
    received_at = recorded_at + timedelta(seconds=1)

    cur.execute("SET ROLE cdrl_writer")

    cur.execute(
        """
        INSERT INTO public.telemetry_readings (
            device_id,
            recorded_at,
            received_at,
            temperature_c,
            humidity_pct,
            co2_ppm
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            device_id,
            recorded_at,
            received_at,
            Decimal("25.00"),
            Decimal("50.00"),
            Decimal("500.00"),
        ),
    )

    reading_id = cur.fetchone()[0]

    assert reading_id is not None

def test_operator_can_update_device_status(security_context):
    """
    Caso limite 2: cdrl_operator puede modificar exclusivamente la columna status.
    """
    cur = security_context["cur"]
    device_id = security_context["device_id"]

    cur.execute("SET ROLE cdrl_operator")

    cur.execute(
        """
        UPDATE public.devices
        SET status = %s
        WHERE id = %s
        """,
        ("maintenance", device_id),
    )

    assert cur.rowcount == 1

    cur.execute(
        """
        SELECT status
        FROM public.devices
        WHERE id = %s
        """,
        (device_id,),
    )

    assert cur.fetchone()[0] == "maintenance"

def test_reader_insert_is_rejected_by_authorization(security_context,):
    """
    Fallo declarado: cdrl_reader intenta insertar datos validos.

    La operacion debe ser rechazada por autorizacion, no por CHECK, FK, UNIQUE ni datos invalidos.
    """
    cur = security_context["cur"]
    device_id = security_context["device_id"]

    recorded_at = datetime(
        2026, 9, 19, 13, 0, tzinfo=timezone.utc
    )
    received_at = recorded_at + timedelta(seconds=1)

    cur.execute("SET ROLE cdrl_reader")

    with pytest.raises(errors.InsufficientPrivilege) as exc:
        cur.execute(
            """
            INSERT INTO public.telemetry_readings (
                device_id,
                recorded_at,
                received_at,
                temperature_c,
                humidity_pct,
                co2_ppm
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                device_id,
                recorded_at,
                received_at,
                Decimal("25.00"),
                Decimal("50.00"),
                Decimal("500.00"),
            ),
        )

    assert exc.value.pgcode == "42501"