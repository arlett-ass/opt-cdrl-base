
"""Benchmark reproducible de consultas M08 sobre DynamoDB Local."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
import platform
from pathlib import Path
import random
import time
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError

from src.m05.document_store import query_by_type
from src.m05.dynamodb_client import (
    get_dynamodb_client,
    get_dynamodb_resource,
)
from src.m05.event_contract import build_event_id, validate_event
from src.m05.table_setup import ensure_table
from src.m08.pagination import query_by_type_page


SAMPLE_SIZE = 10_000
DEFAULT_REPETITIONS = 100
PAGE_SIZE = 20
SEED = 20261031
EVENT_TYPE = "telemetry.reading"
SOURCE_COUNT = 100
ARTIFACT_PATH = Path("artifacts/m08-pagination-benchmark.json")


def timestamp_text(value):
    """Devuelve una fecha UTC con el formato utilizado por M05."""
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def percentile(values, percent):
    """Calcula un percentil mediante interpolación lineal."""
    if not values:
        raise ValueError("No se puede calcular un percentil sin mediciones.")

    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return ordered[lower]

    fraction = position - lower
    return (
        ordered[lower] * (1 - fraction)
        + ordered[upper] * fraction
    )


def build_dataset():
    """Genera 10,000 eventos válidos y reproducibles para M05."""
    rng = random.Random(SEED)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = []

    for index in range(SAMPLE_SIZE):
        timestamp = timestamp_text(
            base + timedelta(seconds=index)
        )
        device_id = rng.randint(1, SOURCE_COUNT)

        event = {
            "eventId": build_event_id(device_id, timestamp),
            "type": EVENT_TYPE,
            "source": f"device-{device_id}",
            "timestamp": timestamp,
            "payload": {
                "readingId": index + 1,
                "deviceId": device_id,
                "receivedAt": timestamp,
                "temperatureC": "23.45",
                "humidityPct": "51.20",
                "co2Ppm": "650.00",
            },
            "metadata": {"schemaVersion": 1},
        }

        events.append(validate_event(event))

    start = events[0]["timestamp"]
    end = events[-1]["timestamp"]
    expected_ids = {event["eventId"] for event in events}

    if len(expected_ids) != SAMPLE_SIZE:
        raise RuntimeError("El dataset contiene eventId duplicados.")

    return events, expected_ids, start, end


def load_dataset(table, events):
    """Carga el dataset sin realizar una petición por documento."""
    started = time.perf_counter()

    with table.batch_writer(overwrite_by_pkeys=["eventId"]) as batch:
        for event in events:
            batch.put_item(Item=event)

    return (time.perf_counter() - started) * 1000


def wait_for_index(table, start, end, expected_ids, timeout=60):
    """Espera a que el GSI refleje los 10,000 documentos."""
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        results = query_by_type(
            EVENT_TYPE, start, end, table=table
        )
        found_ids = {event["eventId"] for event in results}

        if found_ids == expected_ids:
            return

        time.sleep(0.25)

    raise TimeoutError(
        "El índice no reflejó todos los documentos sintéticos "
        "dentro del tiempo esperado."
    )


def baseline_full_query(table, start, end, expected_ids):
    """Ejecuta la consulta completa existente en M05."""
    results = query_by_type(
        EVENT_TYPE, start, end, table=table
    )

    result_ids = [event["eventId"] for event in results]

    if (
        len(results) != SAMPLE_SIZE
        or len(set(result_ids)) != SAMPLE_SIZE
        or set(result_ids) != expected_ids
    ):
        raise RuntimeError(
            "La línea base no devolvió exactamente los documentos esperados."
        )

    return len(results)


def paginated_first_page(table, start, end):
    """Mide la primera página sin recorrer las siguientes."""
    page = query_by_type_page(
        EVENT_TYPE,
        start,
        end,
        page_size=PAGE_SIZE,
        table=table,
    )

    if len(page["items"]) > PAGE_SIZE:
        raise RuntimeError("La primera página supera el tamaño solicitado.")

    return {
        "result_count": len(page["items"]),
        "has_next_cursor": page["next_cursor"] is not None,
    }


def paginated_full_traversal(table, start, end, expected_ids):
    """Recorre todas las páginas y valida continuidad e integridad."""
    cursor = None
    result_ids = []
    seen_cursors = set()
    page_count = 0
    empty_page_count = 0
    data_page_count = 0

    while True:
        page = query_by_type_page(
            EVENT_TYPE,
            start,
            end,
            page_size=PAGE_SIZE,
            cursor=cursor,
            table=table,
        )

        items = page["items"]

        if len(items) > PAGE_SIZE:
            raise RuntimeError("Una página superó el tamaño solicitado.")

        if items:
            data_page_count += 1
        else:
            empty_page_count += 1

        result_ids.extend(event["eventId"] for event in items)
        page_count += 1

        cursor = page["next_cursor"]

        if cursor is None:
            break

        # Comprueba que el cursor puede viajar como JSON,
        # como ocurriría entre dos solicitudes de un cliente.
        serialized = json.dumps(
            cursor, sort_keys=True, separators=(",", ":")
        )

        if serialized in seen_cursors:
            raise RuntimeError("Se detectó un cursor repetido.")

        seen_cursors.add(serialized)
        cursor = json.loads(serialized)

        if page_count >= SAMPLE_SIZE:
            raise RuntimeError("El recorrido excedió el límite de páginas.")

    if (
        len(result_ids) != SAMPLE_SIZE
        or len(set(result_ids)) != SAMPLE_SIZE
        or set(result_ids) != expected_ids
    ):
        raise RuntimeError(
            "La paginación produjo documentos omitidos o duplicados."
        )

    return {
        "result_count": len(result_ids),
        "page_count": page_count,
        "data_page_count": data_page_count,
        "empty_page_count": empty_page_count,
    }


def measure(operation):
    """Mide una operación completa en milisegundos."""
    started = time.perf_counter()
    result = operation()
    elapsed_ms = (time.perf_counter() - started) * 1000

    return elapsed_ms, result


def summarize(latencies, result_counts, page_counts=None):
    """Resume las latencias y conserva todas las muestras."""
    summary = {
        "repetitions": len(latencies),
        "p50_ms": round(percentile(latencies, 50), 3),
        "p95_ms": round(percentile(latencies, 95), 3),
        "min_ms": round(min(latencies), 3),
        "max_ms": round(max(latencies), 3),
        "latencies_ms": [round(value, 3) for value in latencies],
        "result_counts": result_counts,
    }

    if page_counts is not None:
        summary["page_counts"] = page_counts

    return summary


def run_benchmark(repetitions):
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("Las repeticiones deben ser un entero positivo.")

    if os.environ.get("DYNAMODB_LOCAL", "true").strip().lower() != "true":
        raise RuntimeError(
            "Este benchmark está diseñado para DynamoDB Local. "
            "Configura DYNAMODB_LOCAL=true antes de ejecutarlo."
        )

    events, expected_ids, start, end = build_dataset()

    table_name = f"cdrl_m08_bench_{uuid4().hex[:16]}"
    client = get_dynamodb_client()
    table_ready = False

    try:
        ensure_table(client=client, table_name=table_name)
        table_ready = True
        table = get_dynamodb_resource().Table(table_name)

        write_ms = load_dataset(table, events)
        wait_started = time.perf_counter()
        wait_for_index(table, start, end, expected_ids)
        index_wait_ms = (time.perf_counter() - wait_started) * 1000

        # Calentamiento fuera de las muestras medidas.
        baseline_full_query(table, start, end, expected_ids)
        paginated_first_page(table, start, end)
        paginated_full_traversal(table, start, end, expected_ids)

        latencies = {
            "baseline_full_query": [],
            "paginated_first_page": [],
            "paginated_full_traversal": [],
        }
        result_counts = {
            "baseline_full_query": [],
            "paginated_first_page": [],
            "paginated_full_traversal": [],
        }
        page_counts = []
        data_page_counts = []
        empty_page_counts = []

        # Alterna el orden para reducir el efecto de medir siempre
        # un escenario antes que los demás.
        rng = random.Random(SEED + 1)

        for _ in range(repetitions):
            scenarios = [
                "baseline_full_query",
                "paginated_first_page",
                "paginated_full_traversal",
            ]
            rng.shuffle(scenarios)

            for scenario in scenarios:
                if scenario == "baseline_full_query":
                    elapsed, count = measure(
                        lambda: baseline_full_query(
                            table, start, end, expected_ids
                        )
                    )
                    result_counts[scenario].append(count)

                elif scenario == "paginated_first_page":
                    elapsed, result = measure(
                        lambda: paginated_first_page(
                            table, start, end
                        )
                    )
                    result_counts[scenario].append(
                        result["result_count"]
                    )

                else:
                    elapsed, result = measure(
                        lambda: paginated_full_traversal(
                            table, start, end, expected_ids
                        )
                    )
                    result_counts[scenario].append(
                        result["result_count"]
                    )
                    page_counts.append(result["page_count"])
                    data_page_counts.append(result["data_page_count"])
                    empty_page_counts.append(result["empty_page_count"])

                latencies[scenario].append(elapsed)

        baseline = summarize(
            latencies["baseline_full_query"],
            result_counts["baseline_full_query"],
        )
        first_page = summarize(
            latencies["paginated_first_page"],
            result_counts["paginated_first_page"],
        )
        full_pages = summarize(
            latencies["paginated_full_traversal"],
            result_counts["paginated_full_traversal"],
            page_counts,
        )

        full_pages["data_page_counts"] = data_page_counts
        full_pages["empty_page_counts"] = empty_page_counts

        baseline_p50 = baseline["p50_ms"]
        paginated_p50 = full_pages["p50_ms"]

        comparison = {
            "baseline_vs_paginated_full_p50_change_percent": (
                round(
                    (paginated_p50 - baseline_p50) / baseline_p50 * 100,
                    2,
                )
                if baseline_p50 > 0 else None
            ),
            "interpretation": (
                "Un porcentaje positivo indica que el recorrido completo "
                "paginado tuvo mayor p50 que la línea base. Un porcentaje "
                "negativo indica menor p50."
            ),
            "first_page_note": (
                "La primera página no es una comparación equivalente "
                "a la consulta completa; se reporta por separado."
            ),
        }

        artifact = {
            "module": "M08",
            "benchmark": "pagination-index-performance",
            "status": "passed",
            "environment": {
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "boto3_version": boto3.__version__,
                "dynamodb_local": True,
                "dynamodb_port": os.environ.get("DYNAMODB_PORT", "8000"),
                "region": os.environ.get("AWS_REGION", "us-east-1"),
            },
            "dataset": {
                "records_requested": SAMPLE_SIZE,
                "records_confirmed": len(expected_ids),
                "seed": SEED,
                "event_type": EVENT_TYPE,
                "distinct_source_count": SOURCE_COUNT,
                "start": start,
                "end": end,
                "write_duration_ms": round(write_ms, 3),
                "index_propagation_wait_ms": round(index_wait_ms, 3),
            },
            "methodology": {
                "repetitions_per_scenario": repetitions,
                "page_size": PAGE_SIZE,
                "warmup_runs_per_scenario": 1,
                "timing_unit": "milliseconds",
                "baseline": "src.m05.document_store.query_by_type",
                "paginated": "src.m08.pagination.query_by_type_page",
                "first_page_and_full_traversal_measured_separately": True,
            },
            "results": {
                "baseline_full_query": baseline,
                "paginated_first_page": first_page,
                "paginated_full_traversal": full_pages,
            },
            "comparison": comparison,
        }

        ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT_PATH.write_text(
            json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        print(f"Benchmark completado: {ARTIFACT_PATH}")
        print(f"Documentos: {len(expected_ids)}")
        print(f"Repeticiones por escenario: {repetitions}")
        print()
        print("Escenario                         p50 (ms)    p95 (ms)")
        print(
            f"Línea base, completa             "
            f"{baseline['p50_ms']:>9.3f}    {baseline['p95_ms']:>9.3f}"
        )
        print(
            f"Primera página                   "
            f"{first_page['p50_ms']:>9.3f}    {first_page['p95_ms']:>9.3f}"
        )
        print(
            f"Paginación, recorrido completo   "
            f"{full_pages['p50_ms']:>9.3f}    {full_pages['p95_ms']:>9.3f}"
        )
        print()
        print("Diferencia de p50, recorrido completo vs. línea base:",
              comparison["baseline_vs_paginated_full_p50_change_percent"], "%")

    finally:
        if table_ready:
            try:
                client.delete_table(TableName=table_name)
                client.get_waiter("table_not_exists").wait(
                    TableName=table_name,
                    WaiterConfig={"Delay": 1, "MaxAttempts": 20},
                )
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                    print(
                        f"Advertencia: no se pudo eliminar la tabla temporal: {exc}"
                    )


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark M08 de paginación e índices."
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=DEFAULT_REPETITIONS,
        help="Repeticiones por escenario (predeterminado: 100).",
    )
    args = parser.parse_args()
    run_benchmark(args.repetitions)


if __name__ == "__main__":
    main()
