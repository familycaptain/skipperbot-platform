"""Per-App Schema Migrator
==========================
Creates Postgres schemas for app packages and runs their migrations
in order, tracking applied files in public.app_migrations.

Each app gets its own schema: app_<id> (e.g., app_recipes).
Migrations run with search_path set to the app's schema + public,
so SQL can use unqualified table names.
"""

import hashlib
import logging
from pathlib import Path

from data_layer.db import get_conn
import psycopg2.extras

logger = logging.getLogger("platform.migrator")


def ensure_schema(app_id: str) -> str:
    """Create the app's Postgres schema if it doesn't exist.

    Returns the schema name.
    """
    schema = f"app_{app_id}"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        conn.commit()
    logger.info("MIGRATOR: Schema '%s' ensured", schema)
    return schema


def get_applied_migrations(app_id: str) -> set[str]:
    """Return set of migration filenames already applied for this app."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT filename FROM app_migrations WHERE app_id = %s",
                (app_id,),
            )
            return {row["filename"] for row in cur.fetchall()}


def _file_checksum(path: Path) -> str:
    """SHA256 hex digest of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_app_migrations(app_id: str, migrations_dir: Path) -> list[str]:
    """Run pending migrations for an app inside its schema.

    Migrations are .sql files sorted alphabetically. Each runs in its own
    transaction. On failure, the transaction rolls back and the error is raised.

    Args:
        app_id:         App identifier
        migrations_dir: Path to apps/<id>/migrations/

    Returns:
        List of newly applied migration filenames
    """
    if not migrations_dir.is_dir():
        return []

    schema = f"app_{app_id}"
    applied = get_applied_migrations(app_id)

    # Collect pending .sql files in sorted order
    sql_files = sorted(
        f for f in migrations_dir.iterdir()
        if f.suffix == ".sql" and f.name not in applied
    )

    if not sql_files:
        logger.info("MIGRATOR: %s — no pending migrations", app_id)
        return []

    newly_applied = []

    for sql_file in sql_files:
        sql = sql_file.read_text(encoding="utf-8")
        checksum = _file_checksum(sql_file)

        logger.info("MIGRATOR: %s — running %s", app_id, sql_file.name)

        with get_conn() as conn:
            try:
                with conn.cursor() as cur:
                    # Set search_path so unqualified tables go to app schema
                    cur.execute(f"SET LOCAL search_path TO {schema}, public")
                    cur.execute(sql)

                    # Record the migration
                    cur.execute(
                        "INSERT INTO app_migrations (app_id, filename, checksum) "
                        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (app_id, sql_file.name, checksum),
                    )
                conn.commit()
                newly_applied.append(sql_file.name)
                logger.info("MIGRATOR: %s — applied %s", app_id, sql_file.name)
            except Exception as e:
                conn.rollback()
                logger.error("MIGRATOR: %s — FAILED %s: %s", app_id, sql_file.name, e)
                raise RuntimeError(
                    f"Migration {sql_file.name} failed for app {app_id}: {e}"
                ) from e

    return newly_applied


def validate_no_cross_schema_fks(app_id: str) -> list[str]:
    """Check that the app's schema has no foreign keys pointing outside itself.

    Returns a list of violation descriptions (empty = clean).
    """
    schema = f"app_{app_id}"
    violations = []

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Find FKs from this schema referencing other schemas
            cur.execute("""
                SELECT
                    tc.table_schema AS from_schema,
                    tc.table_name AS from_table,
                    tc.constraint_name,
                    ccu.table_schema AS to_schema,
                    ccu.table_name AS to_table
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                    AND tc.constraint_schema = ccu.constraint_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_schema = %s
                    AND ccu.table_schema != %s
            """, (schema, schema))

            for row in cur.fetchall():
                violations.append(
                    f"FK {row['constraint_name']}: "
                    f"{row['from_schema']}.{row['from_table']} -> "
                    f"{row['to_schema']}.{row['to_table']}"
                )

            # Also check FKs FROM other schemas INTO this app's schema
            cur.execute("""
                SELECT
                    tc.table_schema AS from_schema,
                    tc.table_name AS from_table,
                    tc.constraint_name,
                    ccu.table_schema AS to_schema,
                    ccu.table_name AS to_table
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                    AND tc.constraint_schema = ccu.constraint_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_schema != %s
                    AND ccu.table_schema = %s
            """, (schema, schema))

            for row in cur.fetchall():
                violations.append(
                    f"External FK {row['constraint_name']}: "
                    f"{row['from_schema']}.{row['from_table']} -> "
                    f"{row['to_schema']}.{row['to_table']}"
                )

    if violations:
        logger.warning("MIGRATOR: %s has cross-schema FKs: %s", app_id, violations)

    return violations


def drop_app_schema(app_id: str, purge: bool = False):
    """Remove an app's schema and migration records.

    Args:
        purge: If True, drops the schema (RESTRICT — will fail if external deps exist).
               If False, only cleans up migration tracking.
    """
    schema = f"app_{app_id}"

    with get_conn() as conn:
        with conn.cursor() as cur:
            if purge:
                cur.execute(f"DROP SCHEMA IF EXISTS {schema} RESTRICT")
                logger.info("MIGRATOR: Dropped schema '%s'", schema)
            cur.execute(
                "DELETE FROM app_migrations WHERE app_id = %s", (app_id,),
            )
        conn.commit()
