#!/usr/bin/env bash

# Carga variables simples KEY=VALUE desde un archivo .env.
#
# No usa `source .env`, para evitar ejecutar accidentalmente contenido
# del archivo como comandos de shell.
#
# Las variables que ya existen en el entorno tienen prioridad.
# Esto permite que GitHub Actions proporcione sus propios valores.

load_env_file() {
    local file="${1:-.env}"
    local line
    local key
    local value

    [[ -f "$file" ]] || return 0

    while IFS= read -r line || [[ -n "$line" ]]; do
        # Compatibilidad con archivos creados desde Windows.
        line="${line%$'\r'}"

        # Eliminar BOM UTF-8 si existe.
        line="${line#$'\xEF\xBB\xBF'}"

        # Quitar espacios iniciales.
        line="${line#"${line%%[![:space:]]*}"}"

        # Ignorar líneas vacías y comentarios.
        [[ -z "$line" || "$line" == \#* ]] && continue

        # Solo procesar líneas KEY=VALUE.
        [[ "$line" == *=* ]] || continue

        key="${line%%=*}"
        value="${line#*=}"

        # Quitar espacios finales de la clave.
        key="${key%"${key##*[![:space:]]}"}"

        # Solo aceptar nombres válidos de variables.
        if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
            echo "ERROR: nombre de variable inválido en $file." >&2
            return 1
        fi

        # Permitir valores entre comillas simples o dobles.
        if [[ "$value" == \"*\" ]]; then
            value="${value:1:${#value}-2}"
        elif [[ "$value" == \'*\' ]]; then
            value="${value:1:${#value}-2}"
        fi

        # Una variable ya definida por el entorno tiene prioridad.
        if [[ -z "${!key:-}" ]]; then
            export "$key=$value"
        fi
    done < "$file"
}