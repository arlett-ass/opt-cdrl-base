#!/usr/bin/env bash
set -euo pipefail

# Ejecutar siempre desde la raíz del repositorio.
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Resolver el intérprete de Python
PYTHON_BIN="${PYTHON:-python}"

if [[ -z "${PYTHON:-}" || "$PYTHON_BIN" == "python" || "$PYTHON_BIN" == "python3" ]]; then
    if [[ -x ".venv/bin/python" ]]; then
        PYTHON_BIN=".venv/bin/python"
    elif [[ -f ".venv/Scripts/python.exe" ]]; then
        PYTHON_BIN=".venv/Scripts/python.exe"
    elif command -v python >/dev/null 2>&1; then
        PYTHON_BIN="python"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="python3"
    else
        echo "ERROR: no se encontró Python." >&2
        echo "Activa o crea el entorno virtual antes de ejecutar make setup." >&2
        exit 1
    fi
fi

# Comprobar estructura mínima

mkdir -p \
    artifacts \
    evidence \
    docs \
    db/migrations \
    db/seed \
    src \
    tests

if [[ ! -f ".env.example" ]]; then
    echo "ERROR: falta .env.example." >&2
    exit 1
fi

if [[ ! -f "docker-compose.yml" ]]; then
    echo "ERROR: falta docker-compose.yml." >&2
    exit 1
fi

if [[ ! -f "rebuild.py" ]]; then
    echo "ERROR: falta rebuild.py." >&2
    exit 1
fi

if [[ ! -f "scripts/load_env.sh" ]]; then
    echo "ERROR: falta scripts/load_env.sh." >&2
    exit 1
fi

# Cargar configuración local de forma segura

source scripts/load_env.sh

if [[ -f ".env" ]]; then
    load_env_file .env
elif [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
    cp .env.example .env

    echo "Se creó .env a partir de .env.example." >&2
    echo "Define POSTGRES_PASSWORD en .env y vuelve a ejecutar make setup." >&2
    exit 1
fi

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
    echo "ERROR: POSTGRES_PASSWORD es obligatoria." >&2
    echo "Defínela en .env o como variable de entorno." >&2
    exit 1
fi

# Comprobar herramientas requeridas

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: Docker no está disponible en PATH." >&2
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "ERROR: Docker Compose no está disponible." >&2
    exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]] && ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "ERROR: no se puede ejecutar Python mediante: $PYTHON_BIN" >&2
    exit 1
fi

# Levantar infraestructura

echo "== CDRL: preparación reproducible =="

echo "[1/4] Validando Docker Compose..."
docker compose config --quiet

echo "[2/4] Levantando PostgreSQL y DynamoDB Local..."
docker compose up -d --wait

echo "[3/4] Estado de servicios..."
docker compose ps

# Preparar PostgreSQL

echo "[4/4] Aplicando migraciones y seed..."
"$PYTHON_BIN" rebuild.py

echo
echo "Setup CDRL completado correctamente."
echo "El entorno quedó preparado para ejecutar: make verify"