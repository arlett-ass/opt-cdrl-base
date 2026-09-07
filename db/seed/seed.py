import os
from datetime import datetime, timedelta, timezone
import psycopg2

def get_connection():
    return psycopg2.connect(
        dbname=os.environ.get("POSTGRES_DB", "cdrl"),
        user=os.getenv("POSTGRES_USER", "cdrl_dev"),
        password=os.getenv("POSTGRES_PASSWORD", "cdrl_dev_only"),
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=os.environ.get("POSTGRES_PORT", "5432")
    )

def run_seed():
    conn = get_connection()
    cur = conn.cursor()

    try:
        print("Sembrando ubicaciones (locations)...")
        locations = [
            ("LOC-001", "Zona Norte Sintetica", 19.432600, -99.133200),
            ("LOC-002", "Zona Centro Sintetica", 20.000000, -98.000000),
            ("LOC-003", "Zona Sur Sintetica", 18.500000, -97.500000),
        ]

        location_ids = {}

        for code, name, latitude, longitude in locations:
            cur.execute(
                """
                INSERT INTO locations (
                    location_code,
                    name,
                    latitude,
                    longitude
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (location_code)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude
                RETURNING id;
                """,
                (code, name, latitude, longitude),
            )

            location_ids[code] = cur.fetchone()[0]

        print("Sembrando dispositivos (devices)...")
        devices = [
            ("DEV-001", "Sensor Ambiental 1", "active", "LOC-001"),
            ("DEV-002", "Sensor Ambiental 2", "active", "LOC-001"),
            ("DEV-003", "Sensor Ambiental 3", "maintenance", "LOC-002"),
            ("DEV-004", "Sensor Ambiental 4", "inactive", "LOC-002"),
            ("DEV-005", "Sensor Ambiental 5", "active", "LOC-003"),
        ]
        device_ids = {}

        installed_at = datetime(
            2026, 1, 1, 12, 0, tzinfo=timezone.utc
        )

        for device_code, name, status, location_code in devices:
            cur.execute(
                """
                INSERT INTO devices (
                    location_id,
                    device_code,
                    name,
                    status,
                    installed_at
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (device_code)
                DO UPDATE SET
                    location_id = EXCLUDED.location_id,
                    name = EXCLUDED.name,
                    status = EXCLUDED.status,
                    installed_at = EXCLUDED.installed_at
                RETURNING id;
                """,
                (
                    location_ids[location_code],
                    device_code,
                    name,
                    status,
                    installed_at,
                ),
            )

            device_ids[device_code] = cur.fetchone()[0]

        print("Sembrando lecturas (telemetry_readings)...")
        base_time = datetime(
            2026, 1, 2, 8, 0, tzinfo=timezone.utc
        )

        for device_index, device_code in enumerate(device_ids):
            device_id = device_ids[device_code]

            for reading_index in range(10):
                recorded_at = base_time + timedelta(hours=reading_index)
                received_at = recorded_at + timedelta(minutes=5)

                temperature = (
                    20.00
                    + device_index
                    + reading_index * 0.10
                )

                humidity = (
                    40.00
                    + device_index
                    + reading_index
                )

                co2 = (
                    500.00
                    + device_index * 50
                    + reading_index * 10
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
                    ON CONFLICT (device_id, recorded_at)
                    DO UPDATE SET
                        received_at = EXCLUDED.received_at,
                        temperature_c = EXCLUDED.temperature_c,
                        humidity_pct = EXCLUDED.humidity_pct,
                        co2_ppm = EXCLUDED.co2_ppm;
                    """,
                    (
                        device_id,
                        recorded_at,
                        received_at,
                        temperature,
                        humidity,
                        co2,
                    ),
                )

        conn.commit()
        print("¡Seed completado!")

    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run_seed()