import os
import random
from datetime import datetime, timedelta
import psycopg2
from faker import Faker

fake = Faker()

def run_seed():
    conn = psycopg2.connect(
        dbname=os.environ.get("POSTGRES_DB", "postgres"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", "postgres"),
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=os.environ.get("DB_PORT", "5432")
    )
    cur = conn.cursor()

    try:
        print("Sembrando ubicaciones (locations)...")
        location_ids = []
        for _ in range(3):
            lat = round(random.uniform(-90.0, 90.0), 6)
            lon = round(random.uniform(-180.0, 180.0), 6)
            cur.execute(
                "INSERT INTO locations (location_code, name, latitude, longitude) VALUES (%s, %s, %s, %s) RETURNING id;",
                (fake.unique.bothify(text='LOC-####'), fake.company(), lat, lon)
            )
            location_ids.append(cur.fetchone()[0])

        print("Sembrando dispositivos (devices)...")
        device_ids = []
        statuses = ['active', 'inactive', 'maintenance']
        for _ in range(5):
            loc_id = random.choice(location_ids)
            status = random.choice(statuses)
            installed_at = fake.date_time_between(start_date='-1y', end_date='now')
            cur.execute(
                "INSERT INTO devices (location_id, device_code, name, status, installed_at) VALUES (%s, %s, %s, %s, %s) RETURNING id;",
                (loc_id, fake.unique.bothify(text='DEV-????'), fake.word().capitalize() + " Sensor", status, installed_at)
            )
            device_ids.append(cur.fetchone()[0])

        print("Sembrando lecturas (telemetry_readings)...")
        for dev_id in device_ids:
            base_time = datetime.now() - timedelta(days=5)
            for i in range(10):
                recorded_at = base_time + timedelta(hours=i)
                received_at = recorded_at + timedelta(minutes=random.randint(1, 15)) 
                temp = round(random.uniform(-10.0, 45.0), 2)
                hum = round(random.uniform(20.0, 90.0), 2)
                co2 = round(random.uniform(400.0, 2000.0), 2)

                cur.execute(
                    "INSERT INTO telemetry_readings (device_id, recorded_at, received_at, temperature_c, humidity_pct, co2_ppm) VALUES (%s, %s, %s, %s, %s, %s);",
                    (dev_id, recorded_at, received_at, temp, hum, co2)
                )

        conn.commit()
        print("¡Seed completado!")
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run_seed()