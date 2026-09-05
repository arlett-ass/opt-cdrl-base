-- CDRL M01 — Contrato relacional de telemetría ambiental IoT
--
-- Autor de la propuesta:
-- Nicolás David Juarez Mendoza
--
-- Revisión del contrato:
-- Nicolás David Juarez Mendoza
-- Víctor Manuel Jiménez Suarez
-- Angelica Arlett Santiago Serrano
--
-- Este archivo define el esquema relacional propuesto por el equipo.
-- No sustituye las migraciones versionadas del proyecto.
--
-- Víctor Manuel Jiménez Suarez utilizará este contrato como fuente
-- para crear las migraciones y el seed sintético.
--
-- Angelica Arlett Santiago Serrano utilizará sus restricciones
-- como base para implementar las pruebas automáticas.
--
-- No deben incluirse credenciales, tokens, cadenas de conexión,
-- información personal ni datos provenientes de ambientes reales.

BEGIN;

CREATE TABLE IF NOT EXISTS locations (
    id BIGINT GENERATED ALWAYS AS IDENTITY,

    location_code VARCHAR(50) NOT NULL,
    name VARCHAR(120) NOT NULL,
    latitude NUMERIC(9,6) NOT NULL,
    longitude NUMERIC(9,6) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_locations
        PRIMARY KEY (id),

    CONSTRAINT uq_locations_location_code
        UNIQUE (location_code),

    CONSTRAINT ck_locations_code_not_blank
        CHECK (BTRIM(location_code) <> ''),

    CONSTRAINT ck_locations_name_not_blank
        CHECK (BTRIM(name) <> ''),

    CONSTRAINT ck_locations_latitude
        CHECK (latitude BETWEEN -90 AND 90),

    CONSTRAINT ck_locations_longitude
        CHECK (longitude BETWEEN -180 AND 180)
);

CREATE TABLE IF NOT EXISTS devices (
    id BIGINT GENERATED ALWAYS AS IDENTITY,

    location_id BIGINT NOT NULL,
    device_code VARCHAR(64) NOT NULL,
    name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    installed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_devices
        PRIMARY KEY (id),

    CONSTRAINT fk_devices_location
        FOREIGN KEY (location_id)
        REFERENCES locations (id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT uq_devices_device_code
        UNIQUE (device_code),

    CONSTRAINT ck_devices_code_not_blank
        CHECK (BTRIM(device_code) <> ''),

    CONSTRAINT ck_devices_name_not_blank
        CHECK (BTRIM(name) <> ''),

    CONSTRAINT ck_devices_status
        CHECK (status IN ('active', 'inactive', 'maintenance'))
);

CREATE TABLE IF NOT EXISTS telemetry_readings (
    id BIGINT GENERATED ALWAYS AS IDENTITY,

    device_id BIGINT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    temperature_c NUMERIC(5,2) NOT NULL,
    humidity_pct NUMERIC(5,2) NOT NULL,
    co2_ppm NUMERIC(8,2) NOT NULL,

    CONSTRAINT pk_telemetry_readings
        PRIMARY KEY (id),

    CONSTRAINT fk_telemetry_readings_device
        FOREIGN KEY (device_id)
        REFERENCES devices (id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT uq_telemetry_device_recorded_at
        UNIQUE (device_id, recorded_at),

    CONSTRAINT ck_telemetry_temperature
        CHECK (temperature_c BETWEEN -50.00 AND 80.00),

    CONSTRAINT ck_telemetry_humidity
        CHECK (humidity_pct BETWEEN 0.00 AND 100.00),

    CONSTRAINT ck_telemetry_co2
        CHECK (co2_ppm BETWEEN 0.00 AND 10000.00),

    CONSTRAINT ck_telemetry_timestamp_order
        CHECK (recorded_at <= received_at)
);

CREATE INDEX IF NOT EXISTS idx_devices_location_id
    ON devices (location_id);

CREATE INDEX IF NOT EXISTS idx_telemetry_recorded_at
    ON telemetry_readings (recorded_at);

COMMIT;