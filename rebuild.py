import psycopg2
import os
from pathlib import Path
from db.seed.seed import run_seed

MIGRATIONS_DIR = Path(__file__).parent / "db" / "migrations"

def get_connection():
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB", "cdrl"),
        user=os.getenv("POSTGRES_USER", "cdrl_dev"),
        password=os.getenv("POSTGRES_PASSWORD", "cdrl_dev_only"),
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("POSTGRES_PORT", "5432"),
    )

def ensure_migration_table(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMPTZ
                    NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

    conn.commit()

def migration_was_applied(conn, version):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM schema_migrations
                WHERE version = %s
            );
            """,
            (version,),
        )

        return cur.fetchone()[0]

def apply_migration(conn, migration_path):
    version = migration_path.name

    if migration_was_applied(conn, version):
        print(f"Migración ya aplicada: {version}")
        return

    print(f"Aplicando migración: {version}")

    sql = migration_path.read_text(encoding="utf-8")

    try:
        with conn.cursor() as cur:
            cur.execute(sql)

            cur.execute(
                """
                INSERT INTO schema_migrations (version)
                VALUES (%s);
                """,
                (version,),
            )

        conn.commit()

        print(
            f"Migración aplicada correctamente: {version}"
        )

    except Exception:
        conn.rollback()
        raise


def run_migrations():
    conn = get_connection()

    try:
        ensure_migration_table(conn)

        migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))

        if not migrations:
            raise RuntimeError("No se encontraron migraciones SQL.")

        for migration in migrations:
            apply_migration(conn, migration)

    finally:
        conn.close()


def main():
    print("Preparando base de datos...")
    run_migrations()
    print("Ejecutando seed...")
    run_seed()
    print("Base preparada correctamente.")

if __name__ == "__main__":
    main()