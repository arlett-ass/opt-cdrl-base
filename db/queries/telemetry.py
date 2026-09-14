"""SQL fijo y valores separados mediante psycopg2; no administra transacciones."""

from datetime import datetime

from psycopg2.extras import RealDictCursor


def _positive_id(value):
    if type(value) is not int or not 1 <= value <= 9223372036854775807:
        raise ValueError("El identificador debe ser un entero positivo BIGINT.")


def _date_range(start, end):
    for value in (start, end):
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError("Las fechas deben incluir zona horaria.")
    if start > end:
        raise ValueError("La fecha inicial no puede superar la final.")


def _fetch(conn, sql, params):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def readings_between(conn, device_id, start, end):
    """Lecturas ascendentes del dispositivo en el intervalo inclusivo [start, end]."""
    _positive_id(device_id)
    _date_range(start, end)
    return _fetch(conn, """
        SELECT id, device_id, recorded_at, received_at,
               temperature_c, humidity_pct, co2_ppm
        FROM public.telemetry_readings
        WHERE device_id = %s AND recorded_at BETWEEN %s AND %s
        ORDER BY recorded_at, id
    """, (device_id, start, end))


def latest_reading(conn, device_id):
    """Una lectura o None cuando el dispositivo no tiene lecturas."""
    _positive_id(device_id)
    rows = _fetch(conn, """
        SELECT id, device_id, recorded_at, received_at,
               temperature_c, humidity_pct, co2_ppm
        FROM public.telemetry_readings
        WHERE device_id = %s
        ORDER BY recorded_at DESC, id DESC
        LIMIT 1
    """, (device_id,))
    return rows[0] if rows else None


def reading_statistics(conn, device_id, start, end):
    """COUNT y AVG/MIN/MAX de las tres métricas; agregados None si COUNT=0."""
    _positive_id(device_id)
    _date_range(start, end)
    return _fetch(conn, """
        SELECT COUNT(*) AS reading_count,
               AVG(temperature_c) AS avg_temperature_c,
               MIN(temperature_c) AS min_temperature_c,
               MAX(temperature_c) AS max_temperature_c,
               AVG(humidity_pct) AS avg_humidity_pct,
               MIN(humidity_pct) AS min_humidity_pct,
               MAX(humidity_pct) AS max_humidity_pct,
               AVG(co2_ppm) AS avg_co2_ppm,
               MIN(co2_ppm) AS min_co2_ppm,
               MAX(co2_ppm) AS max_co2_ppm
        FROM public.telemetry_readings
        WHERE device_id = %s AND recorded_at BETWEEN %s AND %s
    """, (device_id, start, end))[0]


def devices_at_location(conn, location_id):
    """Dispositivos de cualquier estado, ordenados por ID."""
    _positive_id(location_id)
    return _fetch(conn, """
        SELECT id, location_id, device_code, name, status, installed_at
        FROM public.devices
        WHERE location_id = %s
        ORDER BY id
    """, (location_id,))


def recent_active_readings(conn, start, end, limit=20):
    """Lecturas de dispositivos actualmente activos, más recientes primero."""
    _date_range(start, end)
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("El límite debe ser un entero entre 1 y 1000.")
    return _fetch(conn, """
        SELECT reading_id, device_id, device_code, device_status,
               location_id, location_code, recorded_at,
               temperature_c, humidity_pct, co2_ppm
        FROM public.v_telemetry_context
        WHERE device_status = %s AND recorded_at BETWEEN %s AND %s
        ORDER BY recorded_at DESC, reading_id DESC
        LIMIT %s
    """, ("active", start, end, limit))
