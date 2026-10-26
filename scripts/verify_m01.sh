#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ ! -f "scripts/load_env.sh" ]]; then
    echo "ERROR: falta scripts/load_env.sh." >&2
    exit 1
fi

# Cargar la configuración requerida por PostgreSQL.
# Si las variables ya vienen del entorno, por ejemplo desde CI,
# load_env_file conserva esos valores.
source scripts/load_env.sh
load_env_file .env


if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
    echo "ERROR: POSTGRES_PASSWORD no está configurada." >&2
    echo "Define la variable en .env o en el entorno." >&2
    exit 1
fi


# Resolver Python de forma portable:
# - WSL/Linux: .venv/bin/python
# - Windows Git Bash: .venv/Scripts/python.exe
# - CI: variable PYTHON
# - fallback: python / python3

PYTHON_BIN=""


if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"

elif [[ -x ".venv/Scripts/python.exe" ]]; then
    PYTHON_BIN=".venv/Scripts/python.exe"

elif [[ -n "${PYTHON:-}" ]]; then

    if command -v "$PYTHON" >/dev/null 2>&1; then
        PYTHON_BIN="$PYTHON"

    elif [[ -x "$PYTHON" ]]; then
        PYTHON_BIN="$PYTHON"
    fi

fi


if [[ -z "$PYTHON_BIN" ]] && command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi


if [[ -z "$PYTHON_BIN" ]] && command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
fi


if [[ -z "$PYTHON_BIN" ]]; then
    echo "ERROR: no se encontró Python utilizable." >&2
    exit 1
fi


if ! "$PYTHON_BIN" -c "import sys" >/dev/null 2>&1; then
    echo "ERROR: Python no puede ejecutarse: $PYTHON_BIN" >&2
    exit 1
fi


echo "Python M01: $PYTHON_BIN"


REPORT="artifacts/m01-tests.json"


required_files=(
    "db/migrations/001_schema.sql"
    "db/seed/seed.py"
    "rebuild.py"
    "tests/test_telemetry_contract.py"
    "evidence/m01-data-contract.json"
)


echo "== M01: contrato de datos y pruebas =="


echo "[1/4] Verificando archivos requeridos..."


for file in "${required_files[@]}"; do
    if [[ ! -f "$file" ]]; then
        echo "ERROR: falta archivo requerido: $file" >&2
        exit 1
    fi
done


echo "OK: archivos M01 presentes."


echo "[2/4] Ejecutando las cuatro pruebas M01..."


mkdir -p artifacts
rm -f -- "$REPORT"


"$PYTHON_BIN" -m pytest \
    tests/test_telemetry_contract.py \
    -v \
    --tb=short \
    --json-report \
    --json-report-file="$REPORT"


echo "[3/4] Validando artifact machine-readable..."


"$PYTHON_BIN" - "$REPORT" <<'PY'
import json
import sys
from pathlib import Path

report_path = Path(sys.argv[1])

if not report_path.is_file():
    raise SystemExit(
        f"ERROR: no se generó el artifact {report_path}"
    )

with report_path.open(encoding="utf-8") as fh:
    report = json.load(fh)

tests = report.get("tests", [])
summary = report.get("summary", {})

required_tests = {
    "test_normal_reading_is_accepted",
    "test_lower_temperature_boundary_is_accepted",
    "test_upper_co2_boundary_is_accepted",
    "test_humidity_above_maximum_is_rejected",
}


passed_tests = {
    test.get("nodeid", "").rsplit("::", 1)[-1]
    for test in tests
    if test.get("outcome") == "passed"
}


passed = summary.get("passed", 0)
failed = summary.get("failed", 0)
errors = summary.get("error", summary.get("errors", 0))
total = summary.get("total", len(tests))


if report.get("exitcode") != 0:
    raise SystemExit(
        "ERROR: pytest terminó con un código distinto de cero."
    )


if total != 4:
    raise SystemExit(
        f"ERROR: M01 requiere exactamente 4 pruebas; se ejecutaron {total}."
    )


if passed != 4 or failed != 0 or errors != 0:
    raise SystemExit(
        "ERROR: M01 no terminó 4/4 aprobadas. "
        f"passed={passed}, failed={failed}, errors={errors}"
    )


missing = required_tests - passed_tests


if missing:
    raise SystemExit(
        "ERROR: faltan escenarios M01 aprobados: "
        + ", ".join(sorted(missing))
    )


print(
    "OK: artifact M01 válido: "
    "4 pruebas ejecutadas y 4 aprobadas."
)
PY


echo "[4/4] Verificando escenarios obligatorios..."


"$PYTHON_BIN" - "$REPORT" <<'PY'
import json
import sys
from pathlib import Path


report = json.loads(
    Path(sys.argv[1]).read_text(encoding="utf-8")
)


names = {
    test.get("nodeid", "").rsplit("::", 1)[-1]
    for test in report.get("tests", [])
    if test.get("outcome") == "passed"
}


required = {
    "test_normal_reading_is_accepted",
    "test_lower_temperature_boundary_is_accepted",
    "test_upper_co2_boundary_is_accepted",
    "test_humidity_above_maximum_is_rejected",
}


if not required.issubset(names):
    raise SystemExit(
        "ERROR: M01 no contiene caso normal, "
        "dos límites y fallo declarado."
    )


print(
    "OK: caso normal + 2 límites + 1 fallo declarado verificados."
)
PY


echo
echo "M01 verificado correctamente."
echo "Artifact: $REPORT"