-- CDRL M03: roles separados y minimo privilegio.
-- Requiere 001_schema.sql y 002_relational_model.sql.
-- Esta migracion no contiene contrasenas, tokens ni cadenas de conexion.
-- Debe ejecutarse mediante una conexion administrativa controlada.

DO $$
DECLARE
    role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY[
        'cdrl_migrator',
        'cdrl_writer',
        'cdrl_reader',
        'cdrl_operator'
    ]
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_roles
            WHERE rolname = role_name
        ) THEN
            EXECUTE format(
                'CREATE ROLE %I WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
                role_name
            );
        ELSE
            EXECUTE format(
                'ALTER ROLE %I WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
                role_name
            );
        END IF;
    END LOOP;
END
$$;

-- Se elimina el acceso publico implicito al esquema.
REVOKE ALL PRIVILEGES ON SCHEMA public FROM PUBLIC;

REVOKE ALL PRIVILEGES
ON SCHEMA public
FROM cdrl_migrator, cdrl_writer, cdrl_reader, cdrl_operator;

-- Todos los roles definidos pueden utilizar el esquema.
GRANT USAGE
ON SCHEMA public
TO cdrl_migrator, cdrl_writer, cdrl_reader, cdrl_operator;

-- Solamente migrator puede crear objetos estructurales.
GRANT CREATE
ON SCHEMA public
TO cdrl_migrator;

-- Se eliminan privilegios previos para mantener la migracion repetible.
REVOKE ALL PRIVILEGES
ON TABLE
    public.locations,
    public.devices,
    public.telemetry_readings,
    public.v_telemetry_context
FROM PUBLIC;

REVOKE ALL PRIVILEGES
ON TABLE
    public.locations,
    public.devices,
    public.telemetry_readings,
    public.v_telemetry_context
FROM cdrl_migrator, cdrl_writer, cdrl_reader, cdrl_operator;

-- Lectura de tablas y vista para los cuatro roles.
GRANT SELECT
ON TABLE
    public.locations,
    public.devices,
    public.telemetry_readings,
    public.v_telemetry_context
TO cdrl_migrator, cdrl_writer, cdrl_reader, cdrl_operator;

-- Escritura de telemetria solamente para migrator y writer.
GRANT INSERT
ON TABLE public.telemetry_readings
TO cdrl_migrator, cdrl_writer;

-- El operador solo puede cambiar el estado del dispositivo.
GRANT UPDATE (status)
ON TABLE public.devices
TO cdrl_migrator, cdrl_operator;

-- La columna identity de telemetry_readings requiere USAGE sobre su secuencia.
DO $$
DECLARE
    sequence_name REGCLASS;
BEGIN
    SELECT pg_get_serial_sequence(
        'public.telemetry_readings',
        'id'
    )::REGCLASS
    INTO sequence_name;

    IF sequence_name IS NULL THEN
        RAISE EXCEPTION
            'No se encontro la secuencia identity de telemetry_readings.id';
    END IF;

    EXECUTE format(
        'REVOKE ALL PRIVILEGES ON SEQUENCE %s FROM PUBLIC, cdrl_migrator, cdrl_writer, cdrl_reader, cdrl_operator',
        sequence_name
    );

    EXECUTE format(
        'GRANT USAGE ON SEQUENCE %s TO cdrl_writer',
        sequence_name
    );
END
$$;

-- Migrator representa al propietario estructural de los objetos.
ALTER TABLE public.locations
OWNER TO cdrl_migrator;

ALTER TABLE public.devices
OWNER TO cdrl_migrator;

ALTER TABLE public.telemetry_readings
OWNER TO cdrl_migrator;

ALTER VIEW public.v_telemetry_context
OWNER TO cdrl_migrator;

-- La secuencia identity tambien queda bajo el rol migrator.
DO $$
DECLARE
    sequence_name REGCLASS;
BEGIN
    SELECT pg_get_serial_sequence(
        'public.telemetry_readings',
        'id'
    )::REGCLASS
    INTO sequence_name;

    IF sequence_name IS NULL THEN
        RAISE EXCEPTION
            'No se encontro la secuencia identity de telemetry_readings.id';
    END IF;

    EXECUTE format(
        'ALTER SEQUENCE %s OWNER TO cdrl_migrator',
        sequence_name
    );
END
$$;