#!/usr/bin/env bash
set -euo pipefail

# Ejecutar siempre desde la raíz del repositorio.
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ ! -f "scripts/load_env.sh" ]]; then
    echo "ERROR: falta scripts/load_env.sh." >&2
    exit 1
fi

# Cargar configuración
source scripts/load_env.sh
load_env_file .env

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
    echo "ERROR: POSTGRES_PASSWORD no está configurada." >&2
    echo "Ejecuta make setup y verifica tu archivo .env." >&2
    exit 1
fi

# Python utilizado por los verificadores
export PYTHON="${PYTHON:-python}"

# Verificaciones integradas
echo "== CDRL: verificación integrada =="

echo
echo "== M01 / contrato base =="
bash scripts/verify_base.sh

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
echo "Verificación integrada M01-M05 completada correctamente."