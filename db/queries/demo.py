"""Ejecutar desde la raíz: python -m db.queries.demo --help."""

import argparse
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import psycopg2

from db.queries.telemetry import (
    devices_at_location,
    latest_reading,
    reading_statistics,
    readings_between,
    recent_active_readings,
)


def json_value(value):
    if isinstance(value, Decimal):
        return str(value)  # Conserva exactamente la precisión NUMERIC de PostgreSQL.
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Tipo no serializable: {type(value).__name__}")


def main():
    parser = argparse.ArgumentParser(description="Demostración M02 de consultas parametrizadas")
    parser.add_argument("--device-code", default="DEV-001")
    parser.add_argument("--start", type=datetime.fromisoformat, default="2026-01-02T08:00:00+00:00")
    parser.add_argument("--end", type=datetime.fromisoformat, default="2026-01-02T17:00:00+00:00")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("artifacts/m02-query-demo.json"))
    args = parser.parse_args()
    conn = None
    try:
        # Mismas variables y valores locales de desarrollo que rebuild.py.
        conn = psycopg2.connect(
            dbname=os.getenv("POSTGRES_DB", "cdrl"),
            user=os.getenv("POSTGRES_USER", "cdrl_dev"),
            password=os.getenv("POSTGRES_PASSWORD", "cdrl_dev_only"),
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            connect_timeout=5,
        )
        conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
        with conn.cursor() as cur:
            cur.execute("SELECT id, location_id FROM public.devices WHERE device_code = %s", (args.device_code,))
            device = cur.fetchone()
        if device is None:
            raise ValueError("El dispositivo no existe. Ejecuta rebuild.py o usa --device-code.")
        device_id, location_id = device
        # El seed termina en 2026; una ventana de 2035 ilustra el caso vacío.
        empty_start = datetime(2035, 1, 1, tzinfo=timezone.utc)
        empty_end = datetime(2035, 1, 2, tzinfo=timezone.utc)
        results = {
            "readings_between": readings_between(conn, device_id, args.start, args.end),
            "latest_reading": latest_reading(conn, device_id),
            "reading_statistics": reading_statistics(conn, device_id, args.start, args.end),
            "devices_at_location": devices_at_location(conn, location_id),
            "recent_active_readings": recent_active_readings(conn, args.start, args.end, args.limit),
            "empty_window_readings": readings_between(conn, device_id, empty_start, empty_end),
            "empty_window_statistics": reading_statistics(conn, device_id, empty_start, empty_end),
        }
        payload = {
            "assignmentId": "M02", "scope": "parameterized_queries",
            "generated_at": datetime.now(timezone.utc),
            "parameters": {"device_code": args.device_code, "device_id": device_id,
                           "location_id": location_id, "start": args.start, "end": args.end,
                           "limit": args.limit, "empty_start": empty_start, "empty_end": empty_end},
            "results": results,
        }
        serialized = json.dumps(payload, default=json_value, ensure_ascii=False, indent=2) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        print(serialized, end="")
    except ValueError as exc:
        parser.exit(2, f"Parámetros inválidos: {exc}\n")
    except psycopg2.Error as exc:
        # No imprimir DSN ni mensajes de conexión que puedan exponer credenciales.
        parser.exit(1, f"Error PostgreSQL ({type(exc).__name__}). Revisa conexión y migraciones.\n")
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()


if __name__ == "__main__":
    main()
