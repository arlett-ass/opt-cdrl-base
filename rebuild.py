import psycopg2
import subprocess
import os

def rebuild_database():
    print("Iniciando pruebas de base de datos...")
    
    try:
        conn = psycopg2.connect(
            dbname=os.environ.get("POSTGRES_DB", "postgres"),
            user=os.environ.get("POSTGRES_USER", "postgres"),
            password=os.environ.get("POSTGRES_PASSWORD", "postgres"),
            host=os.environ.get("DB_HOST", "127.0.0.1"),
            port=os.environ.get("DB_PORT", "5432")
        )
        conn.autocommit = True
        cur = conn.cursor()
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        return

    print("5. Probando creación desde cero (ejecutando migraciones)...")
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        migrations_dir = os.path.join(base_dir, "db", "migrations")

        migration_files = sorted(
            filename for filename in os.listdir(migrations_dir) if filename.endswith(".sql")
        )

        for migration_file in migration_files:
            migration_path = os.path.join(migrations_dir, migration_file)
            with open(migration_path, 'r', encoding='utf-8') as file:
                cur.execute(file.read())
        print("✓ Migraciones creadas correctamente.")
    except Exception as e:
        print(f"❌ Error en migraciones: {e}")
        return
    finally:
        cur.close()
        conn.close()

    print("6. Probando carga de seed sintético...")
    try:
        subprocess.run(["python3", "db/seed/seed.py"], check=True)
        print("✓ Carga de seed probada con éxito.")
    except Exception as e:
        print(f"❌ Error en el seed: {e}")

if __name__ == "__main__":
    rebuild_database()