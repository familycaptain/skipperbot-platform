"""Database Connection Pool & Query Helpers
==========================================
Thread-safe connection pool using psycopg2.pool.
All data_layer modules import `get_conn` and use it as a context manager.

Usage:
    from data_layer.db import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM goals WHERE id = %s", (goal_id,))
            row = cur.fetchone()
        conn.commit()
"""

import os
import re
import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.pool
import psycopg2.extras

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------

# DSN resolution + redaction live in a dependency-free module so scripts
# can reuse them without importing this pool (and psycopg2). Re-exported
# here for backward compatibility with existing imports.
from data_layer.dsn import resolve_dsn, redact_dsn  # noqa: E402

_DSN = resolve_dsn()


_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Lazy-init the connection pool on first use."""
    global _pool
    if _pool is None or _pool.closed:
        logger.info("DB: Creating connection pool (%s)", redact_dsn(_DSN))
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=_DSN,
        )
    return _pool


@contextmanager
def get_conn():
    """Yield a connection from the pool. Auto-returns on exit.

    The caller is responsible for calling conn.commit() or conn.rollback().
    If the block exits without committing, changes are rolled back.
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def close_pool():
    """Shut down the connection pool (call on app exit)."""
    global _pool
    if _pool and not _pool.closed:
        _pool.closeall()
        _pool = None
        logger.info("DB: Connection pool closed")


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def fetch_one(query: str, params: tuple = ()) -> dict | None:
    """Execute a query and return a single row as a dict, or None."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            return dict(row) if row else None


def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    """Execute a query and return all rows as a list of dicts."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]


# Default IVFFlat probe count. Every embedding-indexed table in this DB was
# created with `lists=10`; pgvector's default `probes=1` only scans 1/10th
# of the rows, silently dropping high-similarity matches that happen to live
# in other partitions. We pin probes=lists for every cosine search so the
# top-k results are exact. If a future migration rebuilds the indexes with
# more lists (e.g. lists=N/1000), bump this in sync.
VECTOR_SEARCH_PROBES = 10


def fetch_all_vector(query: str, params: tuple = (), *, probes: int = VECTOR_SEARCH_PROBES) -> list[dict]:
    """Like `fetch_all`, but raises `ivfflat.probes` so pgvector returns the
    true top-k by cosine similarity instead of an approximate subset.

    Use this for any SELECT whose ORDER BY touches an embedding column. The
    `SET LOCAL` lives in the same transaction as the SELECT, so it doesn't
    leak across pool checkouts.
    """
    probes_int = int(probes)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SET LOCAL ivfflat.probes = {probes_int}")
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]


def execute(query: str, params: tuple = ()) -> int:
    """Execute a write query and return the number of affected rows."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rowcount = cur.rowcount
        conn.commit()
        return rowcount


def execute_returning(query: str, params: tuple = ()) -> dict | None:
    """Execute a write query with RETURNING and return the row as a dict."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None
