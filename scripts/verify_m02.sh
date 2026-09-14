#!/usr/bin/env bash
set -euo pipefail

# Ejecutar siempre desde la raíz del repositorio.
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

PYTHON_BIN="${PYTHON:-python}"
REPORT="artifacts/m02-relational-results.json"

required_files=(
  "db/migrations/001_schema.sql"
  "db/migrations/002_relational_model.sql"
  "db/queries/telemetry.py"
  "db/queries/demo.py"
  "tests/test_telemetry_contract.py"
  "tests/test_m02_invariants_david.py"
  "tests/test_m02_acceptance_angelica.py"
)

for required in "${required_files[@]}"; do
  if [[ ! -f "$required" ]]; then
    echo "Falta un archivo requerido: $required" >&2
    exit 1
  fi
done

mkdir -p artifacts

# Evita confundir un reporte anterior con esta ejecución.
rm -f -- "$REPORT"

echo "Ejecutando pruebas de invariantes y aceptación de M02..."

"$PYTHON_BIN" -m pytest \
  tests/test_m02_invariants_david.py \
  tests/test_m02_acceptance_angelica.py \
  -v \
  --tb=short \
  --json-report \
  --json-report-file="$REPORT"

# Comprueba que el reporte contiene resultados satisfactorios y que se ejecutaron los cuatro escenarios de aceptación.
"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

path = Path("artifacts/m02-relational-results.json")
report = json.loads(path.read_text(encoding="utf-8"))
tests = report.get("tests", [])

required_cases = {
    "tests/test_m02_acceptance_angelica.py::test_m02_normal",
    "tests/test_m02_acceptance_angelica.py::test_m02_empty",
    "tests/test_m02_acceptance_angelica.py::test_m02_boundaries",
    "tests/test_m02_acceptance_angelica.py::test_m02_declared_failure",
}

passed = {
    test["nodeid"]
    for test in tests
    if test.get("outcome") == "passed"
}

if report.get("exitcode") != 0:
    raise SystemExit("El reporte indica una ejecución fallida.")

if not tests or any(test.get("outcome") != "passed" for test in tests):
    raise SystemExit("Hay pruebas no aprobadas o no se ejecutaron pruebas.")

missing = required_cases - passed
if missing:
    raise SystemExit(
        "Faltan escenarios de aceptación aprobados: "
        + ", ".join(sorted(missing))
    )

print(f"M02: {len(tests)} pruebas aprobadas.")
print(f"Reporte válido: {path}")
PY

echo "Verificación M02 completada."