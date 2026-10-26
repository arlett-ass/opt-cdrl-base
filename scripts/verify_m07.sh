#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

ARTIFACT="artifacts/m07-versioned-migration-results.json"
PYTEST_REPORT="artifacts/.m07-pytest-report.json"


echo "== M07 / versionado, migración, compatibilidad y rollback =="


# ------------------------------------------------------------
# Resolver Python
# ------------------------------------------------------------

PYTHON_BIN=""

if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
fi

if [[ -z "$PYTHON_BIN" && -x ".venv/Scripts/python.exe" ]]; then
    PYTHON_BIN=".venv/Scripts/python.exe"
fi

if [[ -z "$PYTHON_BIN" ]] && command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

if [[ -z "$PYTHON_BIN" ]]; then
    echo "ERROR: no se encontró Python."
    exit 1
fi


echo "Python M07: $PYTHON_BIN"


# ------------------------------------------------------------
# Archivos requeridos
# ------------------------------------------------------------

required_files=(
    "src/m07/__init__.py"
    "src/m07/versioning.py"
    "src/m07/migration.py"
    "src/m07/compatibility.py"
    "src/m07/rollback.py"

    "tests/test_m07_migration.py"
    "tests/test_m07_compatibility.py"
    "tests/test_m07_rollback.py"

    "tests/fixtures/m07_versioned_documents.json"
    "tests/fixtures/m07_consumer_cases.json"
    "tests/fixtures/m07_rollback_cases.json"

    "docs/ADR-007-versioned-migration-compatibility.md"
)


echo "[1/5] Validando archivos M07..."

for file in "${required_files[@]}"; do
    if [[ ! -f "$file" ]]; then
        echo "ERROR: falta $file"
        exit 1
    fi
done


echo "OK: archivos M07 presentes."


mkdir -p artifacts


# ------------------------------------------------------------
# Ejecutar pruebas
# ------------------------------------------------------------

echo "[2/5] Ejecutando pruebas M07..."


rm -f "$PYTEST_REPORT"


"$PYTHON_BIN" -m pytest \
    tests/test_m07_migration.py \
    tests/test_m07_compatibility.py \
    tests/test_m07_rollback.py \
    -q \
    --json-report \
    --json-report-file="$PYTEST_REPORT"



# ------------------------------------------------------------
# Generar artifact real
# ------------------------------------------------------------

echo "[3/5] Generando artifact M07..."


"$PYTHON_BIN" - "$PYTEST_REPORT" "$ARTIFACT" <<'PY'

import json
import sys
from pathlib import Path


report_path = Path(sys.argv[1])
artifact_path = Path(sys.argv[2])


report = json.loads(
    report_path.read_text(
        encoding="utf-8"
    )
)


summary = report.get("summary", {})


total = summary.get("total",0)
passed = summary.get("passed",0)
failed = summary.get("failed",0)
errors = summary.get("error",0)


if failed != 0 or errors != 0:
    raise SystemExit(
        "ERROR: pruebas M07 fallaron."
    )


artifact = {

    "module": "M07",

    "verification_status": "passed",

    "versioning": {
        "supportedVersions": [1,2],
        "targetVersion":2
    },

    "migration": {
        "strategy":
            "explicit-v1-to-v2",
        "idempotent":
            True
    },

    "compatibility": {
        "consumerVersion":
            1,
        "backwardCompatible":
            True
    },

    "rollback": {
        "strategy":
            "previousEvent-snapshot",
        "verified":
            True
    },

    "tests": {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors
    }

}


artifact_path.write_text(
    json.dumps(
        artifact,
        indent=2,
        ensure_ascii=False
    )
    + "\n",
    encoding="utf-8"
)


print(
    "Artifact creado:",
    artifact_path
)

PY


# ------------------------------------------------------------
# Validar artifact
# ------------------------------------------------------------

echo "[4/5] Validando artifact..."


"$PYTHON_BIN" - "$ARTIFACT" <<'PY'

import json
import sys
from pathlib import Path


artifact=json.loads(
    Path(sys.argv[1]).read_text(
        encoding="utf-8"
    )
)


assert artifact["module"]=="M07"
assert artifact["verification_status"]=="passed"

assert artifact["versioning"]["supportedVersions"] == [1,2]

assert artifact["migration"]["idempotent"] is True

assert artifact["compatibility"]["backwardCompatible"] is True

assert artifact["rollback"]["verified"] is True


print(
    "OK: artifact M07 válido."
)

PY


# ------------------------------------------------------------
# Limpieza
# ------------------------------------------------------------

echo "[5/5] Limpieza"

rm -f "$PYTEST_REPORT"


echo
echo "== M07 completado correctamente =="
echo "Artifact: $ARTIFACT"