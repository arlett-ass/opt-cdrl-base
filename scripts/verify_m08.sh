#!/usr/bin/env bash
set -euo pipefail
cd "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source scripts/load_env.sh
load_env_file .env
PYTHON_BIN="${PYTHON:-python3}"
if [[ -x .venv/bin/python ]]; then PYTHON_BIN=.venv/bin/python; fi

mkdir -p artifacts
REPORT=artifacts/m08-pagination-tests.json
RESULT=artifacts/m08-pagination-index-performance-results.json
# No reutilizar un resultado aprobado de una ejecución anterior.
rm -f -- "$REPORT" "$RESULT"
for file in src/m08/pagination.py src/m08/benchmark.py tests/test_m08_pagination.py \
    docs/ADR-008-pagination-index-performance.md evidence/m08-pagination-index-performance.json \
    artifacts/m08-pagination-benchmark.json; do
    [[ -f "$file" ]] || { echo "ERROR: falta $file" >&2; exit 1; }
done
"$PYTHON_BIN" -m pytest tests/test_m08_pagination.py -q --json-report --json-report-file="$REPORT"
"$PYTHON_BIN" - "$REPORT" "$RESULT" <<'PY'
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys

def require(condition, message):
    if not condition:
        raise SystemExit("ERROR M08: " + message)

def positive_int(value):
    return type(value) is int and value > 0

def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0

report = json.loads(Path(sys.argv[1]).read_text())
tests = report.get("tests", [])
summary = report.get("summary", {})
require(report.get("exitcode") == 0 and len(tests) > 0, "pytest no terminó correctamente o no ejecutó pruebas")
require(summary.get("total") == len(tests) == summary.get("passed"), "el total no coincide con las pruebas aprobadas")
require(all(test.get("outcome") == "passed" for test in tests), "hay pruebas fallidas, omitidas o xfail")
names = {test["nodeid"].split("::")[-1].split("[")[0] for test in tests}
scenarios = {
    "normal_and_integrity": "test_real_traversal_has_no_duplicates_or_omissions_and_preserves_m05",
    "empty_range": "test_real_empty_range_has_no_next_cursor",
    "short_page": "test_real_fewer_items_than_page_size_returns_the_available_documents",
    "invalid_cursor": "test_invalid_cursor_is_a_controlled_error_before_query",
    "invalid_page_size": "test_invalid_page_size_is_rejected_before_query",
    "insertions_without_snapshot": "test_real_insertions_before_and_after_the_cursor_demonstrate_no_snapshot",
    "equal_timestamps": "test_real_equal_timestamps_continue_without_claiming_an_event_id_tiebreak",
    "json_cursor": "test_json_cursor_continues_with_exact_native_key_and_normalized_filters",
    "mixed_versions": "test_real_mixed_v1_v2_documents_keep_all_data_and_decimal_measurements",
}
require(set(scenarios.values()) <= names, "faltan escenarios obligatorios aprobados")

evidence = json.loads(Path("evidence/m08-pagination-index-performance.json").read_text())
require(evidence.get("assignmentId") == "m08-pagination-index-performance", "identificador de evidencia incorrecto")
require(all(evidence.get(field) for field in ("commands", "results", "assumptions", "limitations")), "evidencia incompleta")
commit = evidence.get("commitSha")
require(commit is None or (isinstance(commit, str) and len(commit) == 40 and all(character in "0123456789abcdef" for character in commit)), "SHA de evidencia inválido")
require(commit is not None or bool(evidence.get("sourceState")), "evidencia sin commit ni identificación del estado local")

benchmark_path = Path("artifacts/m08-pagination-benchmark.json")
benchmark = json.loads(benchmark_path.read_text())
require(benchmark.get("module") == "M08" and benchmark.get("status") == "passed", "benchmark sin resultado M08 aprobado")
require(benchmark.get("benchmark") == "pagination-index-performance", "benchmark incorrecto")
environment = benchmark["environment"]
require(all(environment.get(key) for key in ("python_version", "platform", "boto3_version", "region", "dynamodb_port")), "entorno del benchmark incompleto")
require(environment.get("dynamodb_local") is True, "benchmark no identificado como local")
dataset, method = benchmark["dataset"], benchmark["methodology"]
records = dataset["records_confirmed"]
require(positive_int(records) and records == dataset["records_requested"], "muestra incompleta")
require(records == 10000, "el plan M08 requiere una muestra de 10,000 documentos")
require(positive_int(dataset["distinct_source_count"]) and dataset["distinct_source_count"] <= records, "fuentes inválidas")
require(type(dataset["seed"]) is int and bool(dataset["event_type"]), "seed o filtro ausente")
require(datetime.fromisoformat(dataset["start"]) <= datetime.fromisoformat(dataset["end"]), "rango temporal inválido")
repetitions, page_size = method["repetitions_per_scenario"], method["page_size"]
require(positive_int(repetitions) and positive_int(page_size) and page_size <= 1000, "repeticiones o tamaño inválidos")
require(repetitions == 100 and page_size == 20, "el plan M08 fija 100 repeticiones y página de 20")
require(positive_int(method["warmup_runs_per_scenario"]), "calentamiento ausente")
require(method["timing_unit"] == "milliseconds" and method["first_page_and_full_traversal_measured_separately"] is True, "metodología no comparable")
require(method["baseline"] == "src.m05.document_store.query_by_type" and method["paginated"] == "src.m08.pagination.query_by_type_page", "operaciones comparadas incorrectas")

def percentile(values, percent):
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

metrics = {}
for scenario in ("baseline_full_query", "paginated_first_page", "paginated_full_traversal"):
    result = benchmark["results"][scenario]
    samples, counts = result["latencies_ms"], result["result_counts"]
    require(result["repetitions"] == len(samples) == len(counts) == repetitions, scenario + ": muestras incompletas")
    require(all(finite_number(value) for value in samples), scenario + ": latencias inválidas")
    expected = min(page_size, records) if scenario == "paginated_first_page" else records
    require(all(type(count) is int and count == expected for count in counts), scenario + ": conteos incorrectos")
    for field, expected_value in (("p50_ms", percentile(samples, 50)), ("p95_ms", percentile(samples, 95)), ("min_ms", min(samples)), ("max_ms", max(samples))):
        require(finite_number(result[field]) and abs(result[field] - expected_value) <= 0.002, scenario + ": " + field + " no coincide con las muestras")
    metrics[scenario] = {key: result[key] for key in ("p50_ms", "p95_ms")}
full = benchmark["results"]["paginated_full_traversal"]
for field in ("page_counts", "data_page_counts", "empty_page_counts"):
    require(len(full[field]) == repetitions and all(type(value) is int and value >= 0 for value in full[field]), "conteos de páginas inválidos")
for total, data, empty in zip(full["page_counts"], full["data_page_counts"], full["empty_page_counts"]):
    require(data >= math.ceil(records / page_size) and total == data + empty, "conteos de páginas inconsistentes")
baseline_p50 = metrics["baseline_full_query"]["p50_ms"]
require(baseline_p50 > 0, "mediana base nula")
change = (metrics["paginated_full_traversal"]["p50_ms"] - baseline_p50) / baseline_p50 * 100
require(abs(benchmark["comparison"]["baseline_vs_paginated_full_p50_change_percent"] - change) <= 0.002, "comparación inconsistente")

sources = ("src/m08/pagination.py", "src/m08/benchmark.py", "tests/test_m08_pagination.py", "scripts/verify_m08.sh", "scripts/verify_all.sh", "docs/ADR-008-pagination-index-performance.md")
artifact = {
    "module": "M08", "verification_status": "passed",
    "verifiedAt": datetime.now(timezone.utc).isoformat(),
    "baseCommitSha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "sourceSha256": {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in sources},
    "environment": {"python": platform.python_version(), "platform": platform.platform()},
    "tests": {"total": len(tests), "passed": len(tests), "failed": 0, "skipped": 0},
    "testReport": sys.argv[1], "scenarios": scenarios,
    "benchmark": {"path": str(benchmark_path), "sha256": hashlib.sha256(benchmark_path.read_bytes()).hexdigest(),
                  "validation": "stored_measurements_validated_not_rerun", "environment": environment,
                  "records": records, "repetitions": repetitions, "metrics": metrics},
    "limitations": ["DynamoDB Local; no garantiza rendimiento en AWS.", "Cursor sin snapshot ni desempate global por eventId.", "baseCommitSha identifica HEAD; sourceSha256 identifica los archivos efectivamente probados, incluidos cambios sin commit."]
}
Path(sys.argv[2]).write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n")
print(f"M08: {len(tests)} pruebas aprobadas; benchmark almacenado validado sin repetir mediciones.")
print("Artifact:", sys.argv[2])
PY
