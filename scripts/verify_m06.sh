#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

ARTIFACT="artifacts/m06-evolution-audit-recovery-results.json"
PYTEST_REPORT="artifacts/.m06-pytest-report.json"

# ------------------------------------------------------------
# Configuración local.
# ------------------------------------------------------------

if [[ ! -f "scripts/load_env.sh" ]]; then
    echo "ERROR: falta scripts/load_env.sh." >&2
    exit 1
fi

source scripts/load_env.sh
load_env_file .env

# ------------------------------------------------------------
# Resolver Python de forma portable.
#
# Se prefiere el venv Linux/WSL antes que un posible venv Windows.
# ------------------------------------------------------------

PYTHON_BIN=""

if [[ -n "${PYTHON:-}" && "${PYTHON}" != "python" && "${PYTHON}" != "python3" ]]; then
    if command -v "$PYTHON" >/dev/null 2>&1; then
        PYTHON_BIN="$PYTHON"
    elif [[ -x "$PYTHON" ]]; then
        PYTHON_BIN="$PYTHON"
    fi
fi

if [[ -z "$PYTHON_BIN" && -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
fi

if [[ -z "$PYTHON_BIN" && -n "${PYTHON:-}" ]]; then
    if command -v "$PYTHON" >/dev/null 2>&1; then
        PYTHON_BIN="$PYTHON"
    fi
fi

if [[ -z "$PYTHON_BIN" ]] && command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

if [[ -z "$PYTHON_BIN" ]] && command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
fi

if [[ -z "$PYTHON_BIN" && -f ".venv/Scripts/python.exe" ]]; then
    PYTHON_BIN=".venv/Scripts/python.exe"
fi

if [[ -z "$PYTHON_BIN" ]]; then
    echo "ERROR: no se encontró Python utilizable." >&2
    exit 1
fi

if ! "$PYTHON_BIN" -c "import sys" >/dev/null 2>&1; then
    echo "ERROR: Python no puede ejecutarse: $PYTHON_BIN" >&2
    exit 1
fi

echo "Python M06: $PYTHON_BIN"

# ------------------------------------------------------------
# Archivos requeridos.
# ------------------------------------------------------------

required_files=(
    "src/m06/__init__.py"
    "src/m06/schema_evolution.py"
    "src/m06/versioned_store.py"
    "src/m06/audit_store.py"
    "src/m06/audited_operations.py"
    "src/m06/recovery.py"
    "tests/fixtures/m06_versioned_events.json"
    "tests/fixtures/m06_audit_cases.json"
    "tests/fixtures/m06_recovery_fixture.json"
    "tests/test_m06_evolution.py"
    "tests/test_m06_audit.py"
    "tests/test_m06_recovery.py"
    "docs/ADR-006-evolution-audit-recovery.md"
)

echo "== M06: evolucion, auditoria y recuperacion =="

echo "[1/8] Verificando archivos requeridos..."

for file in "${required_files[@]}"; do
    if [[ ! -f "$file" ]]; then
        echo "ERROR: falta archivo requerido: $file" >&2
        exit 1
    fi
done

mkdir -p artifacts

echo "OK: archivos M06 presentes."

# ------------------------------------------------------------
# Dependencias y fixtures.
# ------------------------------------------------------------

echo "[2/8] Validando dependencias y fixtures..."

"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

import boto3
import pytest

fixtures = (
    "tests/fixtures/m06_versioned_events.json",
    "tests/fixtures/m06_audit_cases.json",
    "tests/fixtures/m06_recovery_fixture.json",
)

for name in fixtures:
    json.loads(
        Path(name).read_text(
            encoding="utf-8"
        )
    )

print("OK: dependencias y fixtures M06 válidos.")
PY

# ------------------------------------------------------------
# DynamoDB.
# ------------------------------------------------------------

echo "[3/8] Verificando conexión con DynamoDB..."

"$PYTHON_BIN" - <<'PY'
from src.m05.dynamodb_client import get_dynamodb_client

client = get_dynamodb_client()
client.list_tables(Limit=1)

print("OK: DynamoDB responde correctamente.")
PY

# ------------------------------------------------------------
# Infraestructura idempotente.
# ------------------------------------------------------------

echo "[4/8] Preparando tablas de eventos y auditoría..."

"$PYTHON_BIN" -m src.m05.table_setup >/dev/null
"$PYTHON_BIN" -m src.m05.table_setup >/dev/null

"$PYTHON_BIN" -m src.m06.audit_store >/dev/null
"$PYTHON_BIN" -m src.m06.audit_store >/dev/null

"$PYTHON_BIN" - <<'PY'
from src.m05.dynamodb_client import (
    get_dynamodb_client,
    get_table_name,
)
from src.m06.audit_store import get_audit_table_name

client = get_dynamodb_client()

event_table = get_table_name()
audit_table = get_audit_table_name()

for table_name in (event_table, audit_table):
    description = client.describe_table(
        TableName=table_name
    )["Table"]

    if description.get("TableStatus") != "ACTIVE":
        raise SystemExit(
            f"ERROR: {table_name} no está ACTIVE."
        )

print(
    "OK: tablas ACTIVE e idempotentes:",
    event_table,
    audit_table,
)
PY

# ------------------------------------------------------------
# Pytest M06.
# ------------------------------------------------------------

echo "[5/8] Ejecutando pruebas M06..."

rm -f "$PYTEST_REPORT"

set +e

"$PYTHON_BIN" -m pytest \
    tests/test_m06_evolution.py \
    tests/test_m06_audit.py \
    tests/test_m06_recovery.py \
    -q \
    --json-report \
    --json-report-file="$PYTEST_REPORT"

PYTEST_STATUS=$?

set -e

if [[ "$PYTEST_STATUS" -ne 0 ]]; then
    echo "ERROR: pytest reportó fallos en M06." >&2
    exit "$PYTEST_STATUS"
fi

if [[ ! -f "$PYTEST_REPORT" ]]; then
    echo "ERROR: pytest no generó el reporte JSON M06." >&2
    exit 1
fi

# ------------------------------------------------------------
# Integración real + artifact.
# ------------------------------------------------------------

echo "[6/8] Ejecutando demostración integrada y generando artifact..."

"$PYTHON_BIN" - "$PYTEST_REPORT" "$ARTIFACT" <<'PY'
from copy import deepcopy
import json
import sys
from pathlib import Path

from src.m05.dynamodb_client import get_table
from src.m06.audit_store import (
    get_audit_table,
)
from src.m06.audited_operations import (
    migrate_event_with_audit,
)
from src.m06.recovery import (
    load_recovery_fixture,
    restore_fixture,
)
from src.m06.schema_evolution import (
    SUPPORTED_SCHEMA_VERSIONS,
    validate_versioned_event,
)
from src.m06.versioned_store import (
    create_versioned_event,
    get_versioned_event,
)


pytest_report_path = Path(sys.argv[1])
artifact_path = Path(sys.argv[2])

pytest_report = json.loads(
    pytest_report_path.read_text(
        encoding="utf-8"
    )
)

tests = pytest_report.get("tests", [])
summary = pytest_report.get("summary", {})

total = summary.get(
    "total",
    summary.get("collected", len(tests)),
)
passed = summary.get("passed", 0)
failed = summary.get("failed", 0)
errors = summary.get(
    "error",
    summary.get("errors", 0),
)

executed = {
    test.get("nodeid", "").split("::")[-1]:
    test.get("outcome")
    for test in tests
}

scenario_tests = {
    "normal":
        "test_versioned_store_coexists_and_migrates_without_data_loss",
    "boundary1":
        "test_migrating_existing_v2_is_idempotent_and_does_not_write",
    "boundary2":
        "test_audit_redacts_secrets_and_retry_does_not_duplicate",
    "declaredFailure":
        "test_invalid_fixture_fails_before_any_partial_restore",
    "recovery":
        "test_controlled_loss_is_restored_and_measured",
}

if total != 5:
    raise SystemExit(
        f"ERROR: se esperaban 5 tests M06 y se ejecutaron {total}."
    )

if passed != 5 or failed != 0 or errors != 0:
    raise SystemExit(
        "ERROR: M06 no terminó 5/5. "
        f"passed={passed}, failed={failed}, errors={errors}"
    )

for scenario, test_name in scenario_tests.items():
    if executed.get(test_name) != "passed":
        raise SystemExit(
            "ERROR: escenario M06 no aprobado: "
            f"{scenario} -> {test_name}"
        )


versioned_fixture = json.loads(
    Path(
        "tests/fixtures/m06_versioned_events.json"
    ).read_text(
        encoding="utf-8"
    )
)

audit_fixture = json.loads(
    Path(
        "tests/fixtures/m06_audit_cases.json"
    ).read_text(
        encoding="utf-8"
    )
)

recovery_fixture_path = Path(
    "tests/fixtures/m06_recovery_fixture.json"
)

recovery_events = load_recovery_fixture(
    recovery_fixture_path
)

event_table = get_table()
audit_table = get_audit_table()

versioned_event = versioned_fixture["v1"]
versioned_event_id = versioned_event["eventId"]

audit_id = (
    "schema.migrate.v1_to_v2"
    f"#{versioned_event_id}"
    "#v1-v2"
)

recovery_ids = [
    event["eventId"]
    for event in recovery_events
]


def delete_event(event_id):
    event_table.delete_item(
        Key={"eventId": event_id}
    )


def delete_audit(audit_record_id):
    audit_table.delete_item(
        Key={"auditId": audit_record_id}
    )


# Estado reproducible previo.
delete_event(versioned_event_id)

for event_id in recovery_ids:
    delete_event(event_id)

delete_audit(audit_id)

try:
    # --------------------------------------------------------
    # Evolución + auditoría real.
    # --------------------------------------------------------

    create_versioned_event(
        versioned_event,
        table=event_table,
    )

    first = migrate_event_with_audit(
        versioned_event_id,
        trace_id="trace-m06-verifier",
        event_table=event_table,
        audit_table=audit_table,
        audit_context=audit_fixture["auditContext"],
        occurred_at="2026-10-11T20:00:00.000000Z",
    )

    if not first["changed"]:
        raise SystemExit(
            "ERROR: la migración real no reportó cambio."
        )

    if not first["auditCreated"]:
        raise SystemExit(
            "ERROR: la migración real no creó auditoría."
        )

    migrated = get_versioned_event(
        versioned_event_id,
        table=event_table,
    )

    if migrated["metadata"]["schemaVersion"] != 2:
        raise SystemExit(
            "ERROR: el evento no terminó en schemaVersion 2."
        )

    persisted_audit = audit_table.get_item(
        Key={"auditId": audit_id},
        ConsistentRead=True,
    ).get("Item")

    if persisted_audit is None:
        raise SystemExit(
            "ERROR: no se encontró el audit record."
        )

    serialized_audit = json.dumps(
        persisted_audit,
        sort_keys=True,
        default=str,
    )

    for sensitive_value in audit_fixture["sensitiveValues"]:
        if sensitive_value in serialized_audit:
            raise SystemExit(
                "ERROR: se persistió un valor sensible en auditoría."
            )

    second = migrate_event_with_audit(
        versioned_event_id,
        trace_id="trace-m06-verifier-retry",
        event_table=event_table,
        audit_table=audit_table,
        audit_context=audit_fixture["auditContext"],
        occurred_at="2026-10-11T20:01:00.000000Z",
    )

    if second["changed"]:
        raise SystemExit(
            "ERROR: el reintento volvió a migrar un documento v2."
        )

    if second["auditCreated"]:
        raise SystemExit(
            "ERROR: el reintento duplicó la auditoría."
        )

    # --------------------------------------------------------
    # Recovery real.
    # --------------------------------------------------------

    normalized_recovery = [
        validate_versioned_event(event)
        for event in recovery_events
    ]

    for event in normalized_recovery:
        event_table.put_item(
            Item=event,
            ConditionExpression="attribute_not_exists(eventId)",
        )

    lost_event = normalized_recovery[0]

    delete_event(
        lost_event["eventId"]
    )

    missing = event_table.get_item(
        Key={"eventId": lost_event["eventId"]},
        ConsistentRead=True,
    ).get("Item")

    if missing is not None:
        raise SystemExit(
            "ERROR: no se pudo provocar la pérdida controlada."
        )

    recovery_result = restore_fixture(
        recovery_events,
        table=event_table,
    )

    if recovery_result["expectedCount"] != 3:
        raise SystemExit(
            "ERROR: expectedCount incorrecto."
        )

    if recovery_result["restoredCount"] != 1:
        raise SystemExit(
            "ERROR: restoredCount debe ser 1."
        )

    if recovery_result["skippedCount"] != 2:
        raise SystemExit(
            "ERROR: skippedCount debe ser 2."
        )

    if recovery_result["verifiedCount"] != 3:
        raise SystemExit(
            "ERROR: verifiedCount debe ser 3."
        )

    if recovery_result["integrityPassed"] is not True:
        raise SystemExit(
            "ERROR: recovery no superó la comprobación de integridad."
        )

    artifact = {
        "module": "M06",
        "verification_status": "passed",
        "evolution": {
            "strategy": "coexist-and-explicit-migrate",
            "supportedVersions": list(
                SUPPORTED_SCHEMA_VERSIONS
            ),
            "idempotentMigration": True,
            "realMigrationVerified": True,
        },
        "audit": {
            "operation": "schema.migrate.v1_to_v2",
            "recordCreated": True,
            "sensitiveValuesPersisted": False,
            "retryCreatedDuplicate": False,
            "traceId": "trace-m06-verifier",
        },
        "recovery": {
            "fixture": str(recovery_fixture_path),
            **recovery_result,
        },
        "tests": {
            "normal": "passed",
            "boundary1": "passed",
            "boundary2": "passed",
            "declaredFailure": "passed",
            "recovery": "passed",
            "total": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
        },
        "scenarioTests": scenario_tests,
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

finally:
    delete_event(versioned_event_id)

    for event_id in recovery_ids:
        delete_event(event_id)

    delete_audit(audit_id)


print(
    "OK: demostración real M06 completada."
)
print(
    "OK: artifact generado:",
    artifact_path,
)
PY

# ------------------------------------------------------------
# Validación del artifact generado.
# ------------------------------------------------------------

echo "[7/8] Validando artifact M06..."

"$PYTHON_BIN" - "$ARTIFACT" <<'PY'
import json
import sys
from pathlib import Path

artifact = json.loads(
    Path(sys.argv[1]).read_text(
        encoding="utf-8"
    )
)

if artifact.get("module") != "M06":
    raise SystemExit(
        "ERROR: módulo incorrecto en artifact M06."
    )

if artifact.get("verification_status") != "passed":
    raise SystemExit(
        "ERROR: artifact M06 no declara passed."
    )

evolution = artifact.get("evolution", {})

if evolution.get("supportedVersions") != [1, 2]:
    raise SystemExit(
        "ERROR: versiones soportadas incorrectas."
    )

if evolution.get("idempotentMigration") is not True:
    raise SystemExit(
        "ERROR: no se demostró migración idempotente."
    )

if evolution.get("realMigrationVerified") is not True:
    raise SystemExit(
        "ERROR: no se verificó migración real."
    )

audit = artifact.get("audit", {})

if audit.get("recordCreated") is not True:
    raise SystemExit(
        "ERROR: auditoría real no creada."
    )

if audit.get("sensitiveValuesPersisted") is not False:
    raise SystemExit(
        "ERROR: el artifact indica valores sensibles persistidos."
    )

if audit.get("retryCreatedDuplicate") is not False:
    raise SystemExit(
        "ERROR: el reintento duplicó auditoría."
    )

recovery = artifact.get("recovery", {})

expected_recovery = {
    "expectedCount": 3,
    "restoredCount": 1,
    "skippedCount": 2,
    "verifiedCount": 3,
    "integrityPassed": True,
}

for key, expected in expected_recovery.items():
    if recovery.get(key) != expected:
        raise SystemExit(
            f"ERROR: recovery.{key} incorrecto: "
            f"{recovery.get(key)!r}"
        )

duration = recovery.get("durationMs")

if not isinstance(duration, (int, float)) or duration < 0:
    raise SystemExit(
        "ERROR: durationMs no contiene una medición válida."
    )

tests = artifact.get("tests", {})

if tests.get("total") != 5:
    raise SystemExit(
        "ERROR: artifact no registra 5 pruebas."
    )

if tests.get("passed") != 5:
    raise SystemExit(
        "ERROR: artifact no registra 5 pruebas aprobadas."
    )

for scenario in (
    "normal",
    "boundary1",
    "boundary2",
    "declaredFailure",
    "recovery",
):
    if tests.get(scenario) != "passed":
        raise SystemExit(
            f"ERROR: escenario {scenario} no está aprobado."
        )

print("OK: artifact M06 válido.")
PY

# ------------------------------------------------------------
# Limpieza del reporte temporal.
# ------------------------------------------------------------

echo "[8/8] Limpiando reporte temporal..."

rm -f "$PYTEST_REPORT"

echo
echo "== M06 completado =="
echo "Versiones soportadas: 1 y 2"
echo "Auditoría: segura e idempotente"
echo "Recovery: 1 restaurado / 3 verificados"
echo "Tests: 5/5 PASSED"
echo "Artifact: $ARTIFACT"
echo
echo "[M06] Verificación completada correctamente."

