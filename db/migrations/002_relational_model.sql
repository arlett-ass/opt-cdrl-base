-- CDRL M02: modelo relacional operativo.
-- Requiere 001_schema.sql.
--
-- Las PK, FK, UNIQUE, NOT NULL y CHECK se conservan desde M01.
-- UNIQUE (device_id, recorded_at) ya proporciona un índice
-- para consultar lecturas por dispositivo y rango temporal.
--
-- Esta migración no elimina tablas ni modifica registros.
-- CREATE OR REPLACE VIEW permite repetir su ejecución.
-- La transacción la administra rebuild.py.

CREATE OR REPLACE VIEW public.v_telemetry_context AS
SELECT
    tr.id AS reading_id,
    tr.device_id,
    d.device_code,
    d.name AS device_name,
    d.status AS device_status,
    d.location_id,
    l.location_code,
    l.name AS location_name,
    l.latitude,
    l.longitude,
    tr.recorded_at,
    tr.received_at,
    tr.temperature_c,
    tr.humidity_pct,
    tr.co2_ppm
FROM public.telemetry_readings AS tr
INNER JOIN public.devices AS d
    ON d.id = tr.device_id
INNER JOIN public.locations AS l
    ON l.id = d.location_id;

COMMENT ON VIEW public.v_telemetry_context IS
    'Lecturas relacionadas con el dispositivo y su ubicacion actual. '
    'No representa un historial de cambios de ubicacion.';

COMMENT ON CONSTRAINT uq_telemetry_device_recorded_at
ON public.telemetry_readings IS
    'Impide dos lecturas del mismo dispositivo en el mismo instante. '
    'Su indice UNIQUE permite buscar por dispositivo y fecha.';

COMMENT ON CONSTRAINT ck_telemetry_timestamp_order
ON public.telemetry_readings IS
    'La recepcion debe ocurrir en el mismo instante o despues del registro.';

COMMENT ON CONSTRAINT fk_devices_location
ON public.devices IS
    'Cada dispositivo pertenece a una ubicacion existente. '
    'No permite borrar ubicaciones que conservan dispositivos.';

COMMENT ON CONSTRAINT fk_telemetry_readings_device
ON public.telemetry_readings IS
    'Cada lectura pertenece a un dispositivo existente. '
    'No permite borrar dispositivos que conservan lecturas.';