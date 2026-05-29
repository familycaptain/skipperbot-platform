"""Platform Database Service
============================
Thin wrapper around data_layer.db that app packages import.
Adds schema-aware helpers for app-scoped queries.

Usage from an app package:
    from app_platform.db import fetch_one, fetch_all, execute, get_conn
"""

from data_layer.db import (
    fetch_one,
    fetch_all,
    execute,
    execute_returning,
    get_conn,
)


def fetch_one_in_schema(schema: str, query: str, params: tuple = ()) -> dict | None:
    """Execute a query with search_path set to the given schema + public."""
    import psycopg2.extras
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SET LOCAL search_path TO {schema}, public")
            cur.execute(query, params)
            row = cur.fetchone()
            return dict(row) if row else None


def fetch_all_in_schema(schema: str, query: str, params: tuple = ()) -> list[dict]:
    """Execute a query with search_path set to the given schema + public."""
    import psycopg2.extras
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SET LOCAL search_path TO {schema}, public")
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]


def execute_in_schema(schema: str, query: str, params: tuple = ()) -> int:
    """Execute a write query with search_path set to the given schema + public."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL search_path TO {schema}, public")
            cur.execute(query, params)
            rowcount = cur.rowcount
        conn.commit()
        return rowcount


def execute_returning_in_schema(schema: str, query: str, params: tuple = ()) -> dict | None:
    """Execute a RETURNING query with search_path set to the given schema + public."""
    import psycopg2.extras
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SET LOCAL search_path TO {schema}, public")
            cur.execute(query, params)
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None


def fetch_all_vector_in_schema(schema: str, query: str, params: tuple = (), *, probes: int | None = None) -> list[dict]:
    """Like ``fetch_all_in_schema`` but also raises ``ivfflat.probes`` so
    pgvector returns the true top-k by cosine similarity instead of an
    approximate subset.

    Use this for any SELECT whose ORDER BY touches an embedding column.
    Both ``SET LOCAL`` calls live in the same transaction as the SELECT
    so they don't leak across pool checkouts.

    ``probes`` defaults to the platform-wide value from data_layer.db
    (``VECTOR_SEARCH_PROBES``) if not supplied.
    """
    import psycopg2.extras
    from data_layer.db import VECTOR_SEARCH_PROBES
    probes_int = int(probes if probes is not None else VECTOR_SEARCH_PROBES)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SET LOCAL search_path TO {schema}, public")
            cur.execute(f"SET LOCAL ivfflat.probes = {probes_int}")
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]


def scoped_conn(schema: str):
    """Get a DB connection with search_path set to schema + public.

    Usage::

        with scoped_conn("app_timeline") as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO timeline_posts ...")
            conn.commit()

    SET LOCAL lasts for the transaction, so the search_path automatically
    resets when the connection is returned to the pool.
    """
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL search_path TO {schema}, public")
            yield conn

    return _ctx()
