#!/usr/bin/env bash

set -euo pipefail

# Ejecutar siempre desde la raiz del repositorio.
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

ARTIFACT="artifacts/m05-document-store-results.json"
PYTEST_REPORT="artifacts/.m05-pytest-report.json"

# ------------------------------------------------------------
# Resolver Python de forma portable.
#
# Casos soportados:
# - Windows PowerShell + bash.exe/WSL + .venv de Windows
# - Linux/WSL con .venv Linux
# - CI con python/python3 global
# - PYTHON personalizado cuando apunta a un ejecutable valido
# ------------------------------------------------------------

PYTHON_BIN=""

# Si PYTHON contiene una ruta/comando personalizado distinto del
# valor generico "python"/"python3", intentar respetarlo primero.
if [[ -n "${PYTHON:-}" && "${PYTHON}" != "python" && "${PYTHON}" != "python3" ]]; then
    if command -v "$PYTHON" >/dev/null 2>&1; then
        PYTHON_BIN="$PYTHON"
    elif [[ -f "$PYTHON" ]]; then
        PYTHON_BIN="$PYTHON"
    fi
fi

# Entorno virtual de Windows accesible desde WSL/Git Bash.
if [[ -z "$PYTHON_BIN" && -f ".venv/Scripts/python.exe" ]]; then
    PYTHON_BIN=".venv/Scripts/python.exe"
fi

# Entorno virtual Linux/WSL.
if [[ -z "$PYTHON_BIN" && -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
fi

# Si Makefile envio PYTHON=python o PYTHON=python3 y ese comando
# realmente existe en el entorno Bash, utilizarlo.
if [[ -z "$PYTHON_BIN" && -n "${PYTHON:-}" ]]; then
    if command -v "$PYTHON" >/dev/null 2>&1; then
        PYTHON_BIN="$PYTHON"
    fi
fi

# Fallback global para CI/Linux.
if [[ -z "$PYTHON_BIN" ]] && command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

if [[ -z "$PYTHON_BIN" ]] && command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
fi

if [[ -z "$PYTHON_BIN" ]]; then
    echo "ERROR: no se encontro Python utilizable." >&2
    echo "Activa o crea .venv, o define PYTHON con una ruta valida." >&2
    exit 1
fi

# Confirmar que el interprete elegido realmente puede ejecutarse.
if ! "$PYTHON_BIN" -c "import sys" >/dev/null 2>&1; then
    echo "ERROR: el Python seleccionado no puede ejecutarse: $PYTHON_BIN" >&2
    exit 1
fi

echo "Python M05: $PYTHON_BIN"

# ------------------------------------------------------------
# Archivos requeridos.
# ------------------------------------------------------------

required_files=(
    "src/m05/__init__.py"
    "src/m05/dynamodb_client.py"
    "src/m05/event_contract.py"
    "src/m05/table_setup.py"
    "src/m05/document_store.py"
    "tests/fixtures/m05_events.json"
    "tests/test_m05_document_store.py"
    "docs/ADR-005-document-store.md"
    "evidence/m05-document-store.json"
)

echo "== M05: almacen documental, validacion e indices =="

echo "[1/8] Verificando archivos requeridos..."

for file in "${required_files[@]}"; do
    if [[ ! -f "$file" ]]; then
        echo "ERROR: falta archivo requerido: $file" >&2
        exit 1
    fi
done

mkdir -p artifacts

echo "OK: archivos M05 presentes."

# ------------------------------------------------------------
# Dependencias y JSON base.
# ------------------------------------------------------------

echo "[2/8] Verificando dependencias Python..."

"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

import boto3
import pytest

for path in (
    "tests/fixtures/m05_events.json",
    "evidence/m05-document-store.json",
):
    json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )

print("OK: boto3, pytest, fixtures y evidence disponibles.")
PY

# ------------------------------------------------------------
# Conexion DynamoDB.
# ------------------------------------------------------------

echo "[3/8] Verificando conexion con DynamoDB..."

"$PYTHON_BIN" - <<'PY'
from src.m05.dynamodb_client import get_dynamodb_client

client = get_dynamodb_client()
client.list_tables(Limit=1)

print("OK: DynamoDB responde correctamente.")
PY

# ------------------------------------------------------------
# Setup idempotente.
# ------------------------------------------------------------

echo "[4/8] Preparando tabla e indices..."

# Primera ejecucion: crea o valida infraestructura.
"$PYTHON_BIN" -m src.m05.table_setup

# Segunda ejecucion: demuestra que el setup es idempotente.
"$PYTHON_BIN" -m src.m05.table_setup >/dev/null

echo "OK: table_setup puede ejecutarse repetidamente."

# ------------------------------------------------------------
# Estructura de tabla e indices.
# ------------------------------------------------------------

echo "[5/8] Validando estructura de tabla e indices..."

"$PYTHON_BIN" - <<'PY'
from src.m05.dynamodb_client import (
    get_dynamodb_client,
    get_table_name,
)

EXPECTED_TABLE = "cdrl_events"

EXPECTED_TABLE_KEY = {
    ("eventId", "HASH"),
}

EXPECTED_INDEXES = {
    "type-timestamp-index": {
        ("type", "HASH"),
        ("timestamp", "RANGE"),
    },
    "source-timestamp-index": {
        ("source", "HASH"),
        ("timestamp", "RANGE"),
    },
}

client = get_dynamodb_client()
table_name = get_table_name()

if table_name != EXPECTED_TABLE:
    raise SystemExit(
        "ERROR: la tabla configurada no coincide con cdrl_events. "
        f"Encontrada: {table_name}"
    )

description = client.describe_table(
    TableName=table_name
)["Table"]

status = description.get("TableStatus")

if status != "ACTIVE":
    raise SystemExit(
        f"ERROR: la tabla no esta ACTIVE. Estado: {status}"
    )

actual_table_key = {
    (
        item["AttributeName"],
        item["KeyType"],
    )
    for item in description.get(
        "KeySchema",
        [],
    )
}

if actual_table_key != EXPECTED_TABLE_KEY:
    raise SystemExit(
        "ERROR: la clave primaria no coincide con eventId. "
        f"Encontrada: {sorted(actual_table_key)}"
    )

global_indexes = description.get(
    "GlobalSecondaryIndexes",
    [],
)

actual_indexes = {
    index["IndexName"]: {
        (
            item["AttributeName"],
            item["KeyType"],
        )
        for item in index.get(
            "KeySchema",
            [],
        )
    }
    for index in global_indexes
}

if set(actual_indexes) != set(EXPECTED_INDEXES):
    raise SystemExit(
        "ERROR: los GSIs declarados no coinciden con M05. "
        f"Encontrados: {sorted(actual_indexes)}"
    )

for index_name, expected_schema in EXPECTED_INDEXES.items():
    actual_schema = actual_indexes[index_name]

    if actual_schema != expected_schema:
        raise SystemExit(
            "ERROR: esquema incorrecto para "
            f"{index_name}. "
            f"Encontrado: {sorted(actual_schema)}"
        )

for index in global_indexes:
    index_name = index["IndexName"]

    if index_name in EXPECTED_INDEXES:
        projection = index.get(
            "Projection",
            {},
        ).get("ProjectionType")

        if projection != "ALL":
            raise SystemExit(
                "ERROR: proyeccion incorrecta para "
                f"{index_name}: {projection}"
            )

print(
    "OK: tabla e indices correctos:",
    table_name,
    sorted(actual_indexes),
)
PY

# ------------------------------------------------------------
# Confirmar Query + GSIs y ausencia de Scan.
# ------------------------------------------------------------

echo "[6/8] Validando patrones de acceso..."

"$PYTHON_BIN" - <<'PY'
import re
from pathlib import Path

source = Path(
    "src/m05/document_store.py"
).read_text(
    encoding="utf-8"
)

if re.search(r"\.scan\s*\(", source):
    raise SystemExit(
        "ERROR: document_store.py utiliza Scan."
    )

if not re.search(r"\.query\s*\(", source):
    raise SystemExit(
        "ERROR: document_store.py no utiliza Query."
    )

required_indexes = (
    "type-timestamp-index",
    "source-timestamp-index",
)

for index_name in required_indexes:
    if index_name not in source:
        raise SystemExit(
            "ERROR: falta el indice declarado "
            f"{index_name} en document_store.py."
        )

if "get_item" not in source:
    raise SystemExit(
        "ERROR: no se encontro GetItem/get_item para eventId."
    )

print(
    "OK: consultas principales usan GetItem/Query "
    "y los indices declarados."
)
PY

# ------------------------------------------------------------
# Ejecutar exactamente los tests M05.
# ------------------------------------------------------------

echo "[7/8] Ejecutando pruebas M05..."

rm -f "$PYTEST_REPORT"

set +e

"$PYTHON_BIN" -m pytest \
    tests/test_m05_document_store.py \
    -q \
    --json-report \
    --json-report-file="$PYTEST_REPORT"

PYTEST_STATUS=$?

set -e

if [[ "$PYTEST_STATUS" -ne 0 ]]; then
    echo "ERROR: pytest reporto fallos en M05." >&2
    exit "$PYTEST_STATUS"
fi

if [[ ! -f "$PYTEST_REPORT" ]]; then
    echo "ERROR: pytest no genero el reporte JSON." >&2
    exit 1
fi

# ------------------------------------------------------------
# Validar 4/4 y generar artifact.
# ------------------------------------------------------------

echo "[8/8] Validando escenarios y generando artifact..."

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

total = summary.get(
    "total",
    summary.get("collected", 0),
)

passed = summary.get(
    "passed",
    0,
)

failed = summary.get(
    "failed",
    0,
)

errors = summary.get(
    "error",
    summary.get("errors", 0),
)

expected_scenarios = {
    "normal": "test_document_store_normal_flow",
    "boundary_duplicate": "test_duplicate_event_is_rejected",
    "boundary_absence": "test_missing_event_is_handled",
    "declared_failure": "test_invalid_document_is_rejected",
}

tests = report.get(
    "tests",
    [],
)

executed = {
    test.get(
        "nodeid",
        "",
    ).split("::")[-1]: test.get(
        "outcome"
    )
    for test in tests
}

if total != 4:
    raise SystemExit(
        "ERROR: se esperaban exactamente 4 tests M05 "
        f"y se ejecutaron {total}."
    )

if passed != 4:
    raise SystemExit(
        f"ERROR: se esperaban 4 tests aprobados y hubo {passed}."
    )

if failed != 0:
    raise SystemExit(
        f"ERROR: se esperaban 0 tests fallidos y hubo {failed}."
    )

if errors != 0:
    raise SystemExit(
        f"ERROR: se esperaban 0 errores y hubo {errors}."
    )

for scenario, test_name in expected_scenarios.items():
    outcome = executed.get(
        test_name
    )

    if outcome != "passed":
        raise SystemExit(
            "ERROR: escenario requerido no aprobado: "
            f"{scenario} -> {test_name}. "
            f"Resultado: {outcome}"
        )

artifact = {
    "module": "M05",
    "verification_status": "passed",
    "store": "DynamoDB",
    "table": "cdrl_events",
    "indexes": [
        "type-timestamp-index",
        "source-timestamp-index",
    ],
    "tests": {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
    },
    "scenarios": expected_scenarios,
}

artifact_path.parent.mkdir(
    parents=True,
    exist_ok=True,
)

artifact_path.write_text(
    json.dumps(
        artifact,
        indent=2,
        ensure_ascii=False,
    )
    + "\n",
    encoding="utf-8",
)

print(
    "OK: artifact generado:",
    artifact_path,
)
PY

# ------------------------------------------------------------
# Validar artifact generado.
# ------------------------------------------------------------

"$PYTHON_BIN" - "$ARTIFACT" <<'PY'
import json
import sys
from pathlib import Path

artifact_path = Path(
    sys.argv[1]
)

artifact = json.loads(
    artifact_path.read_text(
        encoding="utf-8"
    )
)

if artifact.get("module") != "M05":
    raise SystemExit(
        "ERROR: modulo incorrecto en artifact."
    )

if artifact.get("verification_status") != "passed":
    raise SystemExit(
        "ERROR: artifact no declara estado passed."
    )

if artifact.get("store") != "DynamoDB":
    raise SystemExit(
        "ERROR: store incorrecto en artifact."
    )

if artifact.get("table") != "cdrl_events":
    raise SystemExit(
        "ERROR: tabla incorrecta en artifact."
    )

expected_indexes = {
    "type-timestamp-index",
    "source-timestamp-index",
}

actual_indexes = set(
    artifact.get(
        "indexes",
        [],
    )
)

if actual_indexes != expected_indexes:
    raise SystemExit(
        "ERROR: indices incorrectos en artifact."
    )

tests = artifact.get(
    "tests",
    {},
)

if tests.get("total") != 4:
    raise SystemExit(
        "ERROR: artifact no registra total=4."
    )

if tests.get("passed") != 4:
    raise SystemExit(
        "ERROR: artifact no registra passed=4."
    )

if tests.get("failed") != 0:
    raise SystemExit(
        "ERROR: artifact registra tests fallidos."
    )

if tests.get("errors") != 0:
    raise SystemExit(
        "ERROR: artifact registra errores."
    )

expected_scenarios = {
    "normal": "test_document_store_normal_flow",
    "boundary_duplicate": "test_duplicate_event_is_rejected",
    "boundary_absence": "test_missing_event_is_handled",
    "declared_failure": "test_invalid_document_is_rejected",
}

if artifact.get("scenarios") != expected_scenarios:
    raise SystemExit(
        "ERROR: escenarios incorrectos en artifact."
    )

declared_failure = artifact.get(
    "scenarios",
    {},
).get(
    "declared_failure"
)

if declared_failure != "test_invalid_document_is_rejected":
    raise SystemExit(
        "ERROR: fallo declarado no registrado correctamente."
    )

print("OK: artifact M05 valido.")
PY

# El reporte temporal de pytest no forma parte de la entrega.
rm -f "$PYTEST_REPORT"

echo
echo "== M05 completado =="
echo "Tabla: cdrl_events"
echo "Indices:"
echo "  - type-timestamp-index"
echo "  - source-timestamp-index"
echo "Tests: 4/4 PASSED"
echo "Artifact: $ARTIFACT"
echo
echo "[M05] Verificacion completada correctamente."