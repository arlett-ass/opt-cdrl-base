#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ ! -f "scripts/load_env.sh" ]]; then
    echo "ERROR: falta scripts/load_env.sh." >&2
    exit 1
fi

source scripts/load_env.sh
load_env_file .env

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
    echo "ERROR: POSTGRES_PASSWORD no está configurada." >&2
    echo "Define la variable en .env o en el entorno." >&2
    exit 1
fi

PYTHON_BIN="${PYTHON:-python}"

REPORT="artifacts/m02-relational-results.json"
INVARIANT_REPORT="artifacts/m02-david-invariants.json"
QUERY_REPORT="artifacts/m02-query-demo.json"

required_files=(
    "db/migrations/001_schema.sql"
    "db/migrations/002_relational_model.sql"
    "db/queries/telemetry.py"
    "db/queries/demo.py"
    "tests/test_telemetry_contract.py"
    "tests/test_m02_invariants_david.py"
    "tests/test_m02_acceptance_angelica.py"
    "evidence/m02-relational-model.json"
)

echo "== M02: modelo relacional, invariantes y consultas =="

echo "[1/5] Verificando archivos requeridos..."

for file in "${required_files[@]}"; do
    if [[ ! -f "$file" ]]; then
        echo "ERROR: falta archivo requerido: $file" >&2
        exit 1
    fi
done

echo "OK: archivos M02 presentes."

mkdir -p artifacts

rm -f -- \
    "$REPORT" \
    "$INVARIANT_REPORT" \
    "$QUERY_REPORT"

echo "[2/5] Ejecutando 8 pruebas de invariantes y 4 de aceptación..."

"$PYTHON_BIN" -m pytest \
    tests/test_m02_invariants_david.py \
    tests/test_m02_acceptance_angelica.py \
    -v \
    --tb=short \
    --json-report \
    --json-report-file="$REPORT"

echo "[3/5] Validando las 12 pruebas M02..."

"$PYTHON_BIN" - "$REPORT" "$INVARIANT_REPORT" <<'PY'
import json
import sys
from pathlib import Path

report_path = Path(sys.argv[1])
invariant_report_path = Path(sys.argv[2])

if not report_path.is_file():
    raise SystemExit(
        f"ERROR: no se generó {report_path}"
    )

report = json.loads(
    report_path.read_text(encoding="utf-8")
)

tests = report.get("tests", [])

required_tests = {
    "tests/test_m02_invariants_david.py::test_duplicate_reading_is_rejected",
    "tests/test_m02_invariants_david.py::test_nonexistent_device_is_rejected",
    "tests/test_m02_invariants_david.py::test_required_device_is_rejected_when_null",
    "tests/test_m02_invariants_david.py::test_received_before_recorded_is_rejected",
    "tests/test_m02_invariants_david.py::test_device_with_readings_cannot_be_deleted",
    "tests/test_m02_invariants_david.py::test_location_with_devices_cannot_be_deleted",
    "tests/test_m02_invariants_david.py::test_context_view_returns_related_reading",
    "tests/test_m02_invariants_david.py::test_context_view_without_readings_is_empty",
    "tests/test_m02_acceptance_angelica.py::test_m02_normal",
    "tests/test_m02_acceptance_angelica.py::test_m02_empty",
    "tests/test_m02_acceptance_angelica.py::test_m02_boundaries",
    "tests/test_m02_acceptance_angelica.py::test_m02_declared_failure",
}

passed = {
    test.get("nodeid")
    for test in tests
    if test.get("outcome") == "passed"
}

if report.get("exitcode") != 0:
    raise SystemExit(
        "ERROR: pytest terminó con código distinto de cero."
    )

if len(tests) != 12:
    raise SystemExit(
        f"ERROR: se esperaban 12 pruebas M02 y se ejecutaron {len(tests)}."
    )

if any(test.get("outcome") != "passed" for test in tests):
    raise SystemExit(
        "ERROR: una o más pruebas M02 no fueron aprobadas."
    )

missing = required_tests - passed

if missing:
    raise SystemExit(
        "ERROR: faltan escenarios M02 aprobados: "
        + ", ".join(sorted(missing))
    )

invariant_tests = [
    test
    for test in tests
    if test.get("nodeid", "").startswith(
        "tests/test_m02_invariants_david.py::"
    )
]

invariant_report = {
    "assignmentId": "m02-relational-invariants",
    "status": "passed",
    "summary": {
        "total": len(invariant_tests),
        "passed": len(invariant_tests),
        "failed": 0,
    },
    "tests": invariant_tests,
}

invariant_report_path.write_text(
    json.dumps(invariant_report, indent=2) + "\n",
    encoding="utf-8",
)

print("OK: M02 terminó 12/12.")
print(" - 8 invariantes")
print(" - 4 escenarios de aceptación")
PY

echo "[4/5] Ejecutando demostración de consultas parametrizadas..."

"$PYTHON_BIN" -m db.queries.demo \
    --output "$QUERY_REPORT" \
    >/dev/null

echo "[5/5] Validando artifact de consultas..."

"$PYTHON_BIN" - "$QUERY_REPORT" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])

if not path.is_file():
    raise SystemExit(
        f"ERROR: no se generó {path}"
    )

payload = json.loads(
    path.read_text(encoding="utf-8")
)

if payload.get("assignmentId") != "M02":
    raise SystemExit(
        "ERROR: assignmentId incorrecto en el demo M02."
    )

if payload.get("scope") != "parameterized_queries":
    raise SystemExit(
        "ERROR: scope incorrecto en el demo M02."
    )

results = payload.get("results", {})

required_queries = {
    "readings_between",
    "latest_reading",
    "reading_statistics",
    "devices_at_location",
    "recent_active_readings",
}

missing = required_queries - set(results)

if missing:
    raise SystemExit(
        "ERROR: faltan consultas demostradas: "
        + ", ".join(sorted(missing))
    )

if "empty_window_readings" not in results:
    raise SystemExit(
        "ERROR: falta la demostración de resultado vacío."
    )

if results["empty_window_readings"] != []:
    raise SystemExit(
        "ERROR: la ventana vacía debía devolver una lista vacía."
    )

print(
    "OK: las 5 consultas parametrizadas fueron ejecutadas "
    "y el caso vacío fue validado."
)
PY

echo
echo "M02 verificado correctamente."
echo "Artifact de pruebas: $REPORT"
echo "Artifact de invariantes: $INVARIANT_REPORT"
echo "Artifact de consultas: $QUERY_REPORT"