"""Pruebas contra PostgreSQL real; los datos propios se revierten al terminar."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from db.queries import telemetry as q
from test_telemetry_contract import telemetry_context


START = datetime(2026, 3, 1, 8, tzinfo=timezone.utc)
END = START + timedelta(hours=1)


@pytest.fixture
def query_data(telemetry_context):
    conn, cur, device_id = telemetry_context
    cur.execute("SELECT location_id FROM devices WHERE id = %s", (device_id,))
    location_id = cur.fetchone()[0]
    cur.execute("""
        INSERT INTO devices (location_id, device_code, name, status, installed_at)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
    """, (location_id, "TEST-QUERY-INACTIVE", "Sensor inactivo", "inactive", START))
    inactive_id = cur.fetchone()[0]
    for target in (device_id, inactive_id):
        for offset, temperature, humidity, co2 in [(0, 20, 40, 500), (1, 24, 60, 700)]:
            recorded = START + timedelta(hours=offset)
            cur.execute("""
                INSERT INTO telemetry_readings
                    (device_id, recorded_at, received_at, temperature_c, humidity_pct, co2_ppm)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (target, recorded, recorded, temperature, humidity, co2))
    return conn, device_id, inactive_id, location_id


def test_range_normal_order_and_device_isolation(query_data):
    conn, device_id, _, _ = query_data
    rows = q.readings_between(conn, device_id, START, END)
    assert [r["recorded_at"] for r in rows] == [START, END]
    assert {r["device_id"] for r in rows} == {device_id}
    assert [r["temperature_c"] for r in rows] == [Decimal("20"), Decimal("24")]


def test_range_includes_both_boundaries(query_data):
    conn, device_id, _, _ = query_data
    for point in (START, END):
        assert [r["recorded_at"] for r in q.readings_between(conn, device_id, point, point)] == [point]


def test_empty_range_and_null_aggregates(query_data):
    conn, device_id, _, _ = query_data
    start, end = END + timedelta(days=1), END + timedelta(days=2)
    assert q.readings_between(conn, device_id, start, end) == []
    stats = q.reading_statistics(conn, device_id, start, end)
    assert stats.pop("reading_count") == 0
    assert all(value is None for value in stats.values())


def test_latest_reading(query_data):
    conn, device_id, _, _ = query_data
    assert q.latest_reading(conn, device_id)["recorded_at"] == END


def test_latest_without_readings(telemetry_context):
    conn, _, device_id = telemetry_context
    assert q.latest_reading(conn, device_id) is None


def test_statistics_all_metrics(query_data):
    conn, device_id, _, _ = query_data
    stats = q.reading_statistics(conn, device_id, START, END)
    assert stats["reading_count"] == 2
    for metric, low, avg, high in [("temperature_c", 20, 22, 24), ("humidity_pct", 40, 50, 60), ("co2_ppm", 500, 600, 700)]:
        assert stats[f"min_{metric}"] == Decimal(low)
        assert stats[f"avg_{metric}"] == Decimal(avg)
        assert stats[f"max_{metric}"] == Decimal(high)


def test_devices_at_location_and_empty_location(query_data):
    conn, device_id, inactive_id, location_id = query_data
    assert [r["id"] for r in q.devices_at_location(conn, location_id)] == sorted([device_id, inactive_id])
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO locations (location_code, name, latitude, longitude)
            VALUES (%s, %s, %s, %s) RETURNING id
        """, ("TEST-QUERY-EMPTY", "Sin dispositivos", 0, 0))
        empty_id = cur.fetchone()[0]
    assert q.devices_at_location(conn, empty_id) == []


def test_recent_active_filters_orders_and_limits(query_data):
    conn, device_id, inactive_id, _ = query_data
    rows = q.recent_active_readings(conn, START, END, 1000)
    own = [r for r in rows if r["device_id"] in (device_id, inactive_id)]
    assert len(own) == 2
    assert {r["device_id"] for r in own} == {device_id}
    assert all(r["device_status"] == "active" for r in rows)
    order = [(r["recorded_at"], r["reading_id"]) for r in rows]
    assert order == sorted(order, reverse=True)
    assert q.recent_active_readings(conn, START, END, 1) == rows[:1]


def test_recent_empty_window(query_data):
    conn, _, _, _ = query_data
    # Una ventana elegida a partir del máximo real garantiza ausencia de registros.
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(recorded_at) FROM telemetry_readings")
        after_last = cur.fetchone()[0] + timedelta(seconds=1)
    assert q.recent_active_readings(conn, after_last, after_last, 1) == []


@pytest.mark.parametrize("bad_id", [0, -1, True, "1 OR 1=1", 1.5, 2**63])
def test_invalid_identifiers_fail_before_sql(bad_id):
    for func, args in [(q.readings_between, (bad_id, START, END)), (q.latest_reading, (bad_id,)),
                       (q.reading_statistics, (bad_id, START, END)), (q.devices_at_location, (bad_id,))]:
        with pytest.raises(ValueError):
            func(None, *args)


@pytest.mark.parametrize("start,end", [(END, START), (START.replace(tzinfo=None), END), (START, "2026-03-01")])
def test_invalid_ranges_fail_before_sql(start, end):
    for func in (q.readings_between, q.reading_statistics):
        with pytest.raises(ValueError):
            func(None, 1, start, end)
    with pytest.raises(ValueError):
        q.recent_active_readings(None, start, end)


@pytest.mark.parametrize("limit", [0, -1, 1001, True, "1; DROP TABLE devices", 1.5])
def test_invalid_limits_fail_before_sql(limit):
    with pytest.raises(ValueError):
        q.recent_active_readings(None, START, END, limit)
