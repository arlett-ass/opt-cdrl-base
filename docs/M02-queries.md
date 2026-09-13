# M02 — Consultas parametrizadas y demostración

Esta contribución implementa la parte de consultas y DML del reparto del equipo
(antes asignada a Angélica), sobre el modelo de la rama de David. El DML de carga
se reutiliza desde `db/seed/seed.py`: inserciones y actualizaciones parametrizadas
con `ON CONFLICT`. La demostración consulta esos datos sintéticos.

## Archivos

- `db/queries/telemetry.py`: cinco funciones con SQL estático y parámetros psycopg2.
- `db/queries/demo.py`: CLI de solo lectura que guarda resultados JSON.
- `tests/test_m02_queries_victor.py`: casos normal, vacío, límites y entradas inválidas.
- `docs/ADR-004-parameterized-queries.md`: decisiones de diseño.

## Preparación en PowerShell / VS Code

Desde la carpeta principal del repositorio, con Python y Docker Desktop disponibles:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
docker compose up -d --wait postgres
.\.venv\Scripts\python.exe rebuild.py
.\.venv\Scripts\python.exe -m db.queries.demo
.\.venv\Scripts\python.exe -m pytest tests/test_m02_queries_victor.py -q --json-report --json-report-file=artifacts/m02-query-tests.json
```

No hace falta activar el entorno virtual. Si ya existe `.venv`, omite su creación.
`rebuild.py` aplica las migraciones 001/002 pendientes y carga el seed; debe ejecutarse
en la base de desarrollo del equipo. La demo no ejecuta migraciones ni escribe datos.

Las variables de conexión son `DB_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`,
`POSTGRES_USER` y `POSTGRES_PASSWORD`, iguales a las del proyecto existente.
Python lee las variables del proceso; no carga `.env` automáticamente. Si cambias
los valores de Compose en `.env`, exporta también los mismos valores en tu terminal.
No guardes credenciales en los archivos de código ni en el JSON.

Con Make y Python disponibles también puedes usar:

```bash
make queries
make verify-queries
# Si el ejecutable de tu entorno se llama python3:
make queries PYTHON=python3
```

Se conservan los objetivos `setup`, `verify` y `run` existentes.
Actualmente `make verify` verifica la estructura base y `make run` levanta Compose;
los nuevos objetivos permiten integrar esta contribución sin sustituir el trabajo
de automatización del integrante encargado de la evidencia final.

## Contrato de las consultas

| Función | Parámetros | Resultado vacío |
| --- | --- | --- |
| `readings_between` | `device_id`, `start`, `end` | Lista `[]` |
| `latest_reading` | `device_id` | `None` (JSON `null`) |
| `reading_statistics` | `device_id`, `start`, `end` | `reading_count=0`; AVG/MIN/MAX son `null` |
| `devices_at_location` | `location_id` | Lista `[]` |
| `recent_active_readings` | `start`, `end`, `limit` | Lista `[]` |

Las funciones reciben además `conn`, una conexión psycopg2 abierta. Devuelven
diccionarios y listas; no hacen `commit`, ni cierran la conexión del llamador.

- IDs: enteros positivos válidos para BIGINT; un ID positivo inexistente produce vacío.
- Fechas: objetos `datetime` con zona horaria. El intervalo es inclusivo `[start, end]`.
  `start == end` consulta exactamente ese instante; `start > end` se rechaza.
- Límite: entero entre 1 y 1000. Booleanos, texto y decimales se rechazan.
- Última lectura: más reciente de todo el historial del dispositivo, independientemente
  del intervalo usado para las otras consultas.
- Lecturas recientes: solo dispositivos cuyo estado actual es `active`; orden por
  fecha descendente e ID descendente para resolver empates.
- La vista de David refleja la ubicación y el estado actuales, no los históricos.

Ejemplo desde Python:

```python
from datetime import datetime, timezone
from db.queries.telemetry import readings_between

rows = readings_between(
    conn,
    device_id=1,  # Usa un ID real de tu base, no asumas que el seed empieza en 1.
    start=datetime(2026, 1, 2, 8, tzinfo=timezone.utc),
    end=datetime(2026, 1, 2, 17, tzinfo=timezone.utc),
)
```

Internamente se ejecuta `cur.execute(sql, (device_id, start, end))`.
Los marcadores `%s` no llevan comillas ni se reemplazan mediante f-strings,
concatenación o el operador `%`. psycopg2 adapta los valores por separado.

## Demostración y resultados esperados

```powershell
.\.venv\Scripts\python.exe -m db.queries.demo --device-code DEV-001 --start 2026-01-02T08:00:00+00:00 --end 2026-01-02T17:00:00+00:00 --limit 5
```

La demo resuelve el ID a partir de `device_code`, mediante otra consulta parametrizada.
Escribe `artifacts/m02-query-demo.json` y también imprime el JSON. En una base recién
cargada únicamente con el seed del proyecto se espera:

| Resultado | Valor |
| --- | --- |
| Lecturas de DEV-001 en el intervalo | 10 |
| Última lectura de DEV-001 | 2026-01-02 17:00 UTC |
| Temperatura mín./prom./máx. | 20.00 / 20.45 / 20.90 °C |
| Humedad mín./prom./máx. | 40.00 / 44.50 / 49.00 % |
| CO₂ mín./prom./máx. | 500.00 / 545.00 / 590.00 ppm |
| Dispositivos en la ubicación de DEV-001 | 2 |
| Lecturas recientes activas con límite 5 | 5 |
| Lecturas de DEV-001 entre 2035-01-01 y 2035-01-02 | 0 |

El último intervalo ilustra el caso vacío con el seed actual. En otra base podría
contener datos; la demo registra los resultados reales y no afirma que las pruebas
pasaron. Los campos NUMERIC se serializan como cadenas decimales para conservar
precisión; las fechas se serializan en ISO 8601 con zona horaria.

## Pruebas y evidencia de esta contribución

Las pruebas de integración crean datos dentro de transacciones y hacen rollback.
Comprueban aislamiento por dispositivo, los dos extremos del intervalo, última
lectura, los nueve agregados, ubicaciones vacías, filtro por estado, orden y límite.
Las pruebas de validación rechazan IDs, fechas y límites incorrectos antes de SQL.

```powershell
# Solo validación de parámetros, sin necesidad de PostgreSQL:
.\.venv\Scripts\python.exe -m pytest tests/test_m02_queries_victor.py -q -k invalid

# Modelo de David, contrato previo y consultas, con PostgreSQL preparado:
.\.venv\Scripts\python.exe -m pytest tests -q --json-report --json-report-file=artifacts/m02-all-tests.json
```

Los JSON de `artifacts/` están ignorados por Git en la configuración existente.
Se regeneran con los comandos anteriores y deben incorporarse a la entrega según
el procedimiento de evidencia del equipo. Esta contribución no declara el tag ni
el SHA final y no sustituye `evidence/m02-relational-model.json`.

## Explicación para la defensa

1. Las FK y CHECK de David garantizan la integridad; las consultas aprovechan ese modelo.
2. Parametrizar mantiene separados el SQL y los valores que recibe la aplicación.
3. Una búsqueda vacía devuelve `[]`; un agregado sin filas tiene COUNT=0 y AVG=NULL.
4. El índice UNIQUE existente `(device_id, recorded_at)` sirve para búsquedas por
   dispositivo y fecha; esta contribución no duplica ese índice.
5. Las pruebas comprueban resultados contra PostgreSQL y revierten sus datos de prueba.

## Verificación local realizada

El 2026-09-12 se aplicaron ambas migraciones y el seed en una base temporal nueva
con PostgreSQL 16.15 y Python 3.12.14. Resultado: **36 pruebas aprobadas**, de las
cuales **24 corresponden a consultas**. La demo produjo 10 lecturas, 2 dispositivos,
5 lecturas recientes y una lista vacía en la ventana de 2035; los agregados coinciden
con la tabla anterior. El servidor temporal se detuvo después de la comprobación.

Se generaron `artifacts/m02-all-tests.json` y `artifacts/m02-query-demo.json`.
No se ejecutaron `make setup && make verify && make run` en esta sesión: Make y
Docker no estaban disponibles en la ruta de comandos. Queda pendiente validar
ese flujo completo en el entorno de entrega del equipo.


