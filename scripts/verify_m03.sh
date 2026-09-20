#!/usr/bin/env bash

set -euo pipefail

# Ejecutar siempre desde la raiz del repositorio.
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

PYTHON_BIN="${PYTHON:-python}"

REPORT="artifacts/m03-security-results.json"

required_files=(
    "db/migrations/003_security_roles.sql"
    "tests/test_m03_security.py"
    "docs/ADR-003-relational-security.md"
    ".env.example"
    "docker-compose.yml"
)

echo "== M03: seguridad relacional y minimo privilegio =="

echo "[1/6] Verificando archivos requeridos..."

for file in "${required_files[@]}"; do
    if [[ ! -f "$file" ]]; then
        echo "ERROR: falta archivo requerido: $file"
        exit 1
    fi
done

echo "OK: archivos M03 presentes."

echo "[2/6] Verificando que .env no este rastreado..."

if git ls-files --error-unmatch .env >/dev/null 2>&1; then
    echo "ERROR: .env esta rastreado por Git."
    exit 1
fi

echo "OK: .env no esta rastreado."

echo "[3/6] Revisando secretos en archivos rastreados..."

TRACKED_FILES="$(git ls-files)"

if grep -nEI \
    '(-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|postgres(ql)?://[^[:space:]]+:[^[:space:]@]+@)' \
    $TRACKED_FILES >/dev/null 2>&1; then
    echo "ERROR: se detecto un posible secreto en archivos rastreados."
    grep -nEI \
        '(-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|postgres(ql)?://[^[:space:]]+:[^[:space:]@]+@)' \
        $TRACKED_FILES || true
    exit 1
fi

echo "OK: no se detectaron patrones de secretos."

echo "[4/6] Ejecutando pruebas M03..."

mkdir -p artifacts

"$PYTHON_BIN" -m pytest \
    tests/test_m03_security.py \
    -v \
    --json-report \
    --json-report-file="$REPORT"

echo "[5/6] Validando artifact machine-readable..."

"$PYTHON_BIN" - "$REPORT" <<'PY'
import json
import sys
from pathlib import Path

report_path = Path(sys.argv[1])

if not report_path.is_file():
    raise SystemExit(
        f"ERROR: no se genero el artifact {report_path}"
    )

with report_path.open(encoding="utf-8") as fh:
    report = json.load(fh)

summary = report.get("summary", {})

passed = summary.get("passed", 0)
failed = summary.get("failed", 0)
errors = summary.get("error", summary.get("errors", 0))
total = summary.get("total", 0)

if total != 4:
    raise SystemExit(
        f"ERROR: se esperaban 4 pruebas M03 y se encontraron {total}."
    )

if passed != 4 or failed != 0 or errors != 0:
    raise SystemExit(
        "ERROR: las pruebas M03 no terminaron 4/4 aprobadas. "
        f"passed={passed}, failed={failed}, errors={errors}"
    )

required_tests = {
    "test_reader_can_query_context_view",
    "test_writer_can_insert_telemetry_reading",
    "test_operator_can_update_device_status",
    "test_reader_insert_is_rejected_by_authorization",
}

executed_tests = set()

for test in report.get("tests", []):
    nodeid = test.get("nodeid", "")
    outcome = test.get("outcome")

    test_name = nodeid.rsplit("::", 1)[-1]

    if test_name in required_tests and outcome == "passed":
        executed_tests.add(test_name)

missing = required_tests - executed_tests

if missing:
    raise SystemExit(
        "ERROR: faltan escenarios M03 aprobados: "
        + ", ".join(sorted(missing))
    )

print(
    "OK: artifact M03 valido: "
    "4 pruebas ejecutadas y 4 aprobadas."
)
PY

echo "[6/6] Verificando fallo declarado de autorizacion..."

if ! grep -q \
    'test_reader_insert_is_rejected_by_authorization' \
    tests/test_m03_security.py; then
    echo "ERROR: falta el fallo declarado de autorizacion."
    exit 1
fi

if ! grep -q 'InsufficientPrivilege' tests/test_m03_security.py; then
    echo "ERROR: el fallo declarado no valida InsufficientPrivilege."
    exit 1
fi

if ! grep -q '42501' tests/test_m03_security.py; then
    echo "ERROR: el fallo declarado no valida SQLSTATE 42501."
    exit 1
fi

echo "OK: fallo declarado valida InsufficientPrivilege / SQLSTATE 42501."

echo
echo "M03 verificado correctamente."
echo "Artifact: $REPORT"