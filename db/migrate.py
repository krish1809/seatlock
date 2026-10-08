"""Apply db/migrations/*.sql in filename order, each exactly once.

Usage: python db/migrate.py   (`make migrate` runs it in the api container)

Each file runs in its own transaction together with the INSERT that records it
in schema_migrations. PostgreSQL DDL is transactional, so a failing migration
leaves no partial schema and no record; fix it and rerun. Running twice is a no-op.
"""
import os
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def main() -> None:
    # autocommit=True so that each `with conn.transaction()` below is a real
    # BEGIN ... COMMIT, not a savepoint inside one long transaction.
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename   TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        applied = {row[0] for row in conn.execute("SELECT filename FROM schema_migrations")}

        pending = [p for p in sorted(MIGRATIONS_DIR.glob("*.sql")) if p.name not in applied]
        for path in pending:
            with conn.transaction():
                # No parameters, so psycopg sends the file as-is and it may
                # contain several statements.
                conn.execute(path.read_text())
                conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,)
                )
            print(f"applied {path.name}")

        if not pending:
            print("nothing to apply")


if __name__ == "__main__":
    main()
