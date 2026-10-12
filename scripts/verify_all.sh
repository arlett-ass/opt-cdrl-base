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
    echo "Ejecuta make setup y verifica tu archivo .env." >&2
    exit 1
fi

export PYTHON="${PYTHON:-python}"

echo "== CDRL: verificación integrada =="

echo
echo "== Base del repositorio =="
bash scripts/verify_base.sh

echo
echo "== M01 / contrato de datos =="
bash scripts/verify_m01.sh

echo
echo "== M02 / modelo relacional =="
bash scripts/verify_m02.sh

echo
echo "== M03 / seguridad relacional =="
bash scripts/verify_m03.sh

echo
echo "== M04 / selección NoSQL =="
bash scripts/verify_m04.sh

echo
echo "== M05 / almacenamiento documental =="
bash scripts/verify_m05.sh

echo
echo "== M06 / evolución, auditoría y recuperación =="
bash scripts/verify_m06.sh

echo
echo "Verificación integrada M01-M06 completada correctamente."
