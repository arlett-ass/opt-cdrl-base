#!/usr/bin/env bash

set -euo pipefail

# Ejecutar siempre desde la raiz del repositorio.
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

MATRIX="src/m04/storage_matrix.json"
PYTEST_REPORT="artifacts/.m04-pytest-report.json"
REPORT="artifacts/m04-storage-selection-results.json"

# ------------------------------------------------------------
# Resolver Python de forma portable.
# ------------------------------------------------------------

if [[ -n "${PYTHON:-}" ]]; then
    PYTHON_BIN="$PYTHON"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    echo "ERROR: no se encontro Python." >&2
    echo "Define PYTHON o activa un entorno virtual." >&2
    exit 1
fi

required_files=(
    "src/m04/storage_matrix.json"
    "src/m04/storage_decision.py"
    "tests/test_m04_storage_selection.py"
    "docs/ADR-004-nosql-storage-selection.md"
)

echo "== M04: seleccion de almacenamiento NoSQL =="

echo "[1/5] Verificando archivos requeridos..."

for file in "${required_files[@]}"; do
    if [[ ! -f "$file" ]]; then
        echo "ERROR: falta archivo requerido: $file" >&2
        exit 1
    fi
done

echo "OK: archivos M04 presentes."

echo "[2/5] Validando matriz reproducible..."

"$PYTHON_BIN" - "$MATRIX" <<'PY'
import sys

from src.m04.storage_decision import (
    evaluate_matrix,
    load_matrix,
)

matrix_path = sys.argv[1]
matrix = load_matrix(matrix_path)

result = evaluate_matrix(matrix)

if result["weights_total"] != 100:
    raise SystemExit(
        "ERROR: los pesos de la matriz no suman 100."
    )

if result["alternatives_evaluated"] != 4:
    raise SystemExit(
        "ERROR: la matriz no contiene cuatro alternativas."
    )

if result["decision_status"] != "complete":
    raise SystemExit(
        "ERROR: la matriz M04 todavia tiene criterios pendientes."
    )

if result["pending_scores"]:
    raise SystemExit(
        "ERROR: existen puntuaciones pendientes en la matriz M04."
    )

if not result["winners"]:
    raise SystemExit(
        "ERROR: la matriz completa no produjo una alternativa ganadora."
    )

if result["winners"] != ["document"]:
    raise SystemExit(
        "ERROR: el resultado reproducible esperado de la matriz "
        "es Document/MongoDB."
    )

if result["tie"]:
    raise SystemExit(
        "ERROR: la matriz real no debe terminar empatada."
    )

scores = {
    item["id"]: item["weighted_score"]
    for item in result["results"]
}

expected_scores = {
    "document": 3.95,
    "graph": 2.9,
    "column": 3.8,
    "object": 2.9,
}

if scores != expected_scores:
    raise SystemExit(
        "ERROR: los resultados ponderados no coinciden con "
        f"la matriz aprobada. Esperado={expected_scores}, "
        f"obtenido={scores}"
    )

print("OK: matriz estructuralmente valida y completa.")
print(
    "Alternativas evaluadas:",
    result["alternatives_evaluated"],
)
print(
    "Estado de decision:",
    result["decision_status"],
)
print(
    "Ganador(es):",
    ", ".join(result["winners"]),
)

for item in result["results"]:
    print(
        " - "
        f"{item['name']} / {item['representative']}: "
        f"{item['weighted_score']:.2f}"
    )
PY

echo "[3/5] Ejecutando pruebas M04..."

mkdir -p artifacts

rm -f -- "$PYTEST_REPORT"
rm -f -- "$REPORT"

"$PYTHON_BIN" -m pytest \
    tests/test_m04_storage_selection.py \
    -v \
    --tb=short \
    --json-report \
    --json-report-file="$PYTEST_REPORT"

echo "[4/5] Generando y validando artifact machine-readable..."

"$PYTHON_BIN" - "$MATRIX" "$PYTEST_REPORT" "$REPORT" <<'PY'
import json
import sys
from pathlib import Path

from src.m04.storage_decision import (
    evaluate_matrix,
    load_matrix,
)

matrix_path = Path(sys.argv[1])
pytest_path = Path(sys.argv[2])
report_path = Path(sys.argv[3])

if not pytest_path.is_file():
    raise SystemExit(
        f"ERROR: no se genero {pytest_path}"
    )

pytest_report = json.loads(
    pytest_path.read_text(encoding="utf-8")
)

summary = pytest_report.get("summary", {})

passed = summary.get("passed", 0)
failed = summary.get("failed", 0)
errors = summary.get(
    "error",
    summary.get("errors", 0),
)
total = summary.get("total", 0)

if total != 4:
    raise SystemExit(
        "ERROR: se esperaban 4 pruebas M04 "
        f"y se encontraron {total}."
    )

if passed != 4 or failed != 0 or errors != 0:
    raise SystemExit(
        "ERROR: las pruebas M04 no terminaron "
        "4/4 aprobadas. "
        f"passed={passed}, "
        f"failed={failed}, "
        f"errors={errors}"
    )

required_tests = {
    "test_real_matrix_is_valid_and_produces_decision",
    "test_score_boundaries_one_and_five_are_valid",
    "test_tie_is_preserved_without_invented_tiebreak",
    "test_invalid_weights_are_rejected",
}

executed_tests = set()

for test in pytest_report.get("tests", []):
    nodeid = test.get("nodeid", "")
    outcome = test.get("outcome")

    test_name = nodeid.rsplit("::", 1)[-1]

    if (
        test_name in required_tests
        and outcome == "passed"
    ):
        executed_tests.add(test_name)

missing = required_tests - executed_tests

if missing:
    raise SystemExit(
        "ERROR: faltan escenarios M04 aprobados: "
        + ", ".join(sorted(missing))
    )

matrix = load_matrix(matrix_path)
decision = evaluate_matrix(matrix)

if decision["decision_status"] != "complete":
    raise SystemExit(
        "ERROR: no se puede generar el artifact "
        "con una decision pendiente."
    )

if decision["pending_scores"]:
    raise SystemExit(
        "ERROR: el artifact contiene puntuaciones pendientes."
    )

if decision["winners"] != ["document"]:
    raise SystemExit(
        "ERROR: el resultado final esperado es Document/MongoDB."
    )

if decision["tie"]:
    raise SystemExit(
        "ERROR: la matriz real no debe producir empate."
    )

artifact = {
    "module": "M04",
    "verification_status": "passed",
    "matrix_file": str(matrix_path).replace("\\", "/"),
    "decision": decision,
    "tests": {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
    },
    "scenarios": {
        "normal": (
            "test_real_matrix_is_valid_and_produces_decision"
        ),
        "boundary_scores": (
            "test_score_boundaries_one_and_five_are_valid"
        ),
        "tie": (
            "test_tie_is_preserved_without_invented_tiebreak"
        ),
        "declared_failure": (
            "test_invalid_weights_are_rejected"
        ),
    },
}

report_path.parent.mkdir(
    parents=True,
    exist_ok=True,
)

report_path.write_text(
    json.dumps(
        artifact,
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

print(
    "OK: artifact M04 valido: "
    "4 pruebas ejecutadas y 4 aprobadas."
)

print(
    "Estado de decision:",
    decision["decision_status"],
)

print(
    "Ganador:",
    decision["winners"][0],
)
PY

rm -f -- "$PYTEST_REPORT"

echo "[5/5] Verificando fallo declarado..."

if ! grep -q \
    'test_invalid_weights_are_rejected' \
    tests/test_m04_storage_selection.py; then
    echo \
        "ERROR: falta el fallo declarado de pesos invalidos." \
        >&2
    exit 1
fi

if ! grep -q \
    'MatrixValidationError' \
    tests/test_m04_storage_selection.py; then
    echo \
        "ERROR: el fallo declarado no valida MatrixValidationError." \
        >&2
    exit 1
fi

echo "OK: fallo declarado rechaza pesos que no suman 100."

echo
echo "M04 verificado correctamente."
echo "Artifact: $REPORT"