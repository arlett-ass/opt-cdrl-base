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


export PYTHON="$PYTHON_BIN"


if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
    echo "ERROR: POSTGRES_PASSWORD no está configurada." >&2
    echo "Ejecuta make setup y verifica tu archivo .env." >&2
    exit 1
fi


echo "Python integrado: $PYTHON_BIN"


echo
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
echo "== M07 / versionado, migración, compatibilidad y rollback =="
bash scripts/verify_m07.sh


echo
echo "Verificación integrada M01-M07 completada correctamente."
