#!/usr/bin/env bash
set -euo pipefail
cd "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# Invalidar resultados antiguos incluso si falta Python o falla la configuración.
rm -f -- artifacts/m09-nosql-security-audit-results.json
source scripts/load_env.sh
load_env_file .env

PYTHON_BIN="${PYTHON:-python3}"
if [[ -x .venv/bin/python ]]; then
    PYTHON_BIN=.venv/bin/python
elif [[ -f .venv/Scripts/python.exe ]]; then
    PYTHON_BIN=.venv/Scripts/python.exe
fi

# El verificador cubre autorización de aplicación local, no identidades AWS.
export DYNAMODB_LOCAL="${DYNAMODB_LOCAL:-true}"
echo "Python M09: $PYTHON_BIN"
"$PYTHON_BIN" - <<'PY'
from datetime import datetime, timezone
import hashlib
import itertools
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

import boto3


ARTIFACT = Path("artifacts/m09-nosql-security-audit-results.json")
SUITES = (
    "tests/test_m09_authorization.py",
    "tests/test_m09_security_audit.py",
    "tests/test_m09_abuse.py",
    "tests/test_m09_integration.py",
)
ROLES = ("cdrl_reader", "cdrl_writer", "cdrl_operator", "cdrl_migrator")
ACTIONS = ("GetItem", "Query", "PutItem", "UpdateItem", "DeleteItem", "ReadOperationalSummary")
RESOURCES = ("cdrl_events", "cdrl_audit_log")
AUDIT_FIELDS = {"auditId", "attemptId", "actorId", "role", "action", "resource", "result", "reason", "timestamp"}

# Cada grupo requiere pruebas de la ejecución actual, incluyendo parametrizaciones.
SCENARIOS = {
    "normal": ("test_normal_writer_reader_persists_event_and_security_audit",),
    "boundary1": ("test_boundary_forbidden_event_access_never_reaches_backend",),
    "boundary2": ("test_boundary_audit_access_denied_without_altering_previous_logs",),
    "declaredFailure": ("test_declared_failure_delete_is_denied_and_document_survives",),
    "trustedIdentity": ("test_unknown_or_forged_identity_is_denied_and_audited",),
    "operationalSummary": ("test_operator_only_receives_safe_summary_with_durable_audit",),
    "durableAudit": (
        "test_security_audit_is_durable_and_append_only_in_dynamodb_local",
        "test_end_to_end_authorization_and_durable_audit_in_dynamodb_local",
    ),
    "sanitization": (
        "test_recursive_sanitization_and_m06_m09_logs_coexist",
        "test_audit_record_contains_no_request_content_or_secret",
    ),
    "distinctAuditIds": ("test_consecutive_denials_have_distinct_audit_and_attempt_ids",),
    "abuseRemediation": ("test_isolated_excessive_permission_is_removed_before_real_operations",),
    "auditFailureBeforeOperation": ("test_audit_failure_before_operation_fails_closed",),
    "auditFailureAfterWrite": ("test_audit_failure_after_write_reports_uncertainty_without_fake_rollback",),
    "mixedVersionsAndPagination": ("test_mixed_versions_paginate_without_omissions_and_audit_each_page",),
    "duplicateWrite": ("test_duplicate_write_keeps_original_and_persists_error_without_secrets",),
    "missingEvent": ("test_missing_event_is_audited_without_inventing_a_document",),
    "invalidCursor": ("test_invalid_cursor_persists_error_before_query",),
}


def require(condition, message):
    if not condition:
        raise SystemExit("ERROR M09: " + message)


def function_name(test):
    return test["nodeid"].rsplit("::", 1)[-1].split("[", 1)[0]


def matrix_id(role, action, resource):
    return f"{SUITES[0]}::test_exact_role_action_resource_matrix[{resource}-{action}-{role}]"


def validate_report(report):
    tests = report.get("tests", [])
    summary = report.get("summary", {})
    require(report.get("exitcode") == 0, "pytest no terminó correctamente")
    require(isinstance(tests, list) and len(tests) > 0, "no se ejecutaron pruebas")
    require(summary.get("total") == summary.get("passed") == len(tests), "conteos de pytest inconsistentes")
    require(summary.get("collected") == len(tests), "hay pruebas recolectadas sin ejecutar")
    require(all(summary.get(key, 0) == 0 for key in ("failed", "error", "errors", "skipped", "xfailed", "xpassed", "deselected")), "hay pruebas fallidas, omitidas o no ejecutadas")
    for test in tests:
        require(test.get("outcome") == "passed", "una prueba no está aprobada")
        require(all(test.get(phase, {}).get("outcome") == "passed" for phase in ("setup", "call", "teardown")), "una fase de pytest no terminó correctamente")
    nodeids = {test["nodeid"] for test in tests}
    require(len(nodeids) == len(tests), "identificadores de prueba duplicados")
    require({nodeid.split("::", 1)[0] for nodeid in nodeids} == set(SUITES), "no se ejecutaron exactamente las cuatro suites M09")
    require(all(matrix_id(*entry) in nodeids for entry in itertools.product(ROLES, ACTIONS, RESOURCES)), "matriz rol/acción/recurso incompleta")
    for names in SCENARIOS.values():
        require(set(names) <= {function_name(test) for test in tests}, "faltan escenarios obligatorios: " + ", ".join(names))

    # No basta con conservar una parametrización y omitir el resto del contrato.
    mandatory = {
        "test_normal_writer_reader_persists_event_and_security_audit": ("v1", "v2"),
        "test_duplicate_write_keeps_original_and_persists_error_without_secrets": ("v1", "v2"),
        "test_boundary_forbidden_event_access_never_reaches_backend": (
            "cdrl_reader-PutItem", "cdrl_reader-UpdateItem", "cdrl_writer-GetItem",
            "cdrl_operator-GetItem", "cdrl_migrator-Query",
        ),
        "test_declared_failure_delete_is_denied_and_document_survives": ROLES,
        "test_boundary_audit_access_denied_without_altering_previous_logs": ROLES,
        "test_unknown_or_forged_identity_is_denied_and_audited": ("unknown", "role-string", "client-dict", "foreign-registry"),
        "test_audit_failure_before_operation_fails_closed": ("authorized-create", "denied-delete"),
    }
    require(all(f"{SUITES[3]}::{name}[{case}]" in nodeids for name, cases in mandatory.items() for case in cases), "faltan parametrizaciones obligatorias de integración")
    return tests


def source_state():
    paths = {Path(path) for path in SUITES}
    paths.update((Path("scripts/verify_m09.sh"), Path("scripts/verify_all.sh"), Path("scripts/load_env.sh"), Path("requirements.txt"), Path("config/iam/m09-dynamodb-policy.json")))
    for directory in ("src/m05", "src/m06", "src/m07", "src/m08", "src/m09", "tests/fixtures"):
        paths.update(path for path in Path(directory).rglob("*") if path.suffix in {".py", ".json"})
    paths.update(Path("tests").rglob("conftest.py"))
    hashes = {path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}
    head = subprocess.check_output(["git", "rev-parse", "--verify", "HEAD^{commit}"], text=True).strip()
    tracked = set(subprocess.check_output(["git", "ls-files", "-z", "--", *hashes], text=True).rstrip("\0").split("\0"))
    dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *hashes]).returncode
    require(dirty in (0, 1), "no se pudo comprobar el estado de las fuentes")
    return {"head": head, "sourcesMatchHead": dirty == 0 and set(hashes) <= tracked, "sourceSha256": hashes}


print("== M09 / seguridad NoSQL y auditoría ==", flush=True)
ARTIFACT.parent.mkdir(exist_ok=True)
# Un fallo nuevo nunca debe dejar un artifact de éxito de una ejecución anterior.
ARTIFACT.unlink(missing_ok=True)
require(os.environ.get("DYNAMODB_LOCAL", "").strip().lower() == "true", "este verificador requiere DYNAMODB_LOCAL=true; no valida AWS IAM")
print("[1/4] Comprobando archivos y estado de las fuentes...", flush=True)
for path in (*SUITES, "src/m09/policy.py", "src/m09/authorization.py", "src/m09/secure_operations.py", "src/m09/security_audit.py", "config/iam/m09-dynamodb-policy.json", "tests/fixtures/m09_security_cases.json"):
    require(Path(path).is_file(), "falta " + path)
cases = json.loads(Path("tests/fixtures/m09_security_cases.json").read_text(encoding="utf-8"))
require(set(cases["expected_audit_fields"]) == AUDIT_FIELDS, "fixture de auditoría incompatible")
json.loads(Path("config/iam/m09-dynamodb-policy.json").read_text(encoding="utf-8"))
before = source_state()

with tempfile.TemporaryDirectory(prefix=".m09-", dir="artifacts") as temporary:
    report_path = Path(temporary) / "pytest.json"
    print("[2/4] Ejecutando las cuatro suites M09 con DynamoDB Local...", flush=True)
    completed = subprocess.run([
        sys.executable, "-m", "pytest", *SUITES, "-v", "--tb=short",
        "--json-report", "--json-report-file=" + str(report_path),
    ])
    if completed.returncode != 0:
        # Conservar el código de pytest, incluso ante fallo de colección o cero pruebas.
        raise SystemExit(completed.returncode)
    require(report_path.is_file(), "pytest no generó su reporte actual")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    tests = validate_report(report)
    require(before == source_state(), "las fuentes o HEAD cambiaron durante las pruebas; repetir verificación")

    print("[3/4] Validando escenarios y generando artifact...", flush=True)
    scenarios = {}
    for label, names in SCENARIOS.items():
        selected = [test["nodeid"] for test in tests if function_name(test) in names]
        scenarios[label] = {"status": "passed", "testExecutions": len(selected), "tests": selected}
        print(f"PASSED — {label}: {len(selected)} ejecuciones", flush=True)

    matrix = []
    for role, action, resource in itertools.product(ROLES, ACTIONS, RESOURCES):
        allowed = resource == "cdrl_events" and (
            (role == "cdrl_reader" and action in {"GetItem", "Query"})
            or (role == "cdrl_writer" and action == "PutItem")
            or (role == "cdrl_operator" and action == "ReadOperationalSummary")
        )
        matrix.append({"role": role, "action": action, "resource": resource, "expectedDecision": "allowed" if allowed else "denied", "status": "passed", "test": matrix_id(role, action, resource)})
    artifact = {
        "assignmentId": "m09-nosql-security-audit",
        "module": "M09",
        "verification_status": "passed",
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(), "platform": platform.platform(),
            "boto3": boto3.__version__, "dynamodbLocal": True,
            "dynamodbPort": os.environ.get("DYNAMODB_PORT", "8000"),
            "region": os.environ.get("AWS_REGION", "us-east-1"),
            "authentication": "synthetic_server_controlled_identities",
            "authorization": "Python_application_layer", "awsIamVerified": False,
        },
        "sourceState": before,
        "tests": {
            "total": len(tests), "passed": len(tests), "failed": 0, "errors": 0, "skipped": 0,
            "suites": {suite: sum(test["nodeid"].split("::", 1)[0] == suite for test in tests) for suite in SUITES},
            "cases": [{"nodeid": test["nodeid"], "outcome": test["outcome"]} for test in tests],
        },
        "authorization": {"scope": "application_policy_tests", "matrix": matrix},
        "scenarios": scenarios,
        "audit": {
            "requiredFields": sorted(AUDIT_FIELDS),
            "persistence": scenarios["durableAudit"],
            "sanitization": scenarios["sanitization"],
            "distinctIdentifiers": scenarios["distinctAuditIds"],
            "userAccessDenied": scenarios["boundary2"],
        },
        "denials": {label: scenarios[label] for label in ("boundary1", "boundary2", "declaredFailure", "trustedIdentity")},
        "abuseRemediation": {
            **scenarios["abuseRemediation"], "scope": "isolated_in_memory_fixture",
            "before": "excessive_DeleteItem_permission_deletes_synthetic_event",
            "after": "secured_operation_denies_DeleteItem_and_preserves_event",
            "awsPermissionsChanged": False,
        },
        "auditFailures": {
            "beforeOperation": scenarios["auditFailureBeforeOperation"],
            "afterWrite": scenarios["auditFailureAfterWrite"],
            "method": "controlled_failure_injection", "atomicityClaimed": False,
        },
        "limitations": [
            "DynamoDB Local no aplica IAM; el JSON IAM es una propuesta sin validación AWS.",
            "Los escenarios pueden compartir pruebas; sus conteos no son aditivos ni cuentan registros de auditoría.",
            "La escritura del evento y la auditoría son independientes; un fallo posterior puede dejar el evento persistido.",
            "La remediación usa un fixture en memoria; la integración persistente usa tablas locales temporales.",
            "Este artifact cubre M09; el resultado global M01–M09 se obtiene de make verify.",
        ],
    }
    output = Path(temporary) / "artifact.json"
    output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    require(json.loads(output.read_text(encoding="utf-8")) == artifact, "artifact JSON inconsistente")
    output.replace(ARTIFACT)

print("[4/4] Resumen y trazabilidad:")
print(f"M09: {len(tests)}/{len(tests)} pruebas aprobadas; matriz: {len(matrix)} combinaciones.")
print("HEAD:", before["head"])
print("Fuentes:", "coinciden con HEAD" if before["sourcesMatchHead"] else "incluyen cambios locales; consultar sourceSha256")
print("Artifact:", ARTIFACT)
print("SHA-256:", hashlib.sha256(ARTIFACT.read_bytes()).hexdigest())
print("IAM AWS: no verificado. M09 completado correctamente.")
PY
