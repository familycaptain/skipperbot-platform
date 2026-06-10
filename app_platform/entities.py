"""Platform Entity Query Service
=================================
Read-only cross-app entity queries. Apps use this to read entities from
other apps without importing their code or knowing their schema.

Usage:
    from app_platform.entities import query_entities

    recipes = query_entities(
        prefix="re",
        filters={"category": "dinner"},
        fields=["id", "title", "category"],
        limit=50,
    )
"""

import logging
import re

from data_layer.db import get_conn
from data_layer.entity_types import get_all as get_all_entity_types
import psycopg2.extras

logger = logging.getLogger("platform.entities")

# Cache: prefix -> (table_name, schema_name)
_schema_cache: dict[str, tuple[str, str]] = {}


def _resolve_prefix(prefix: str) -> tuple[str, str]:
    """Resolve an entity prefix to (table_name, schema_name).

    Checks app_registry first for packaged apps (schema = app_<id>),
    falls back to public schema for legacy entities.
    """
    if prefix in _schema_cache:
        return _schema_cache[prefix]

    entity_types = get_all_entity_types()
    et = None
    for e in entity_types:
        if e["prefix"] == prefix:
            et = e
            break

    if not et:
        raise ValueError(f"Unknown entity prefix: {prefix}")

    table_name = et["table_name"]

    # Check if this table belongs to a packaged app
    from data_layer.db import fetch_one
    app_row = fetch_one(
        "SELECT app_id FROM app_registry WHERE status = 'active' "
        "AND manifest->'entity_types' @> %s::jsonb",
        (f'[{{"prefix": "{prefix}"}}]',),
    )

    if app_row:
        schema = f"app_{app_row['app_id']}"
    else:
        schema = "public"

    _schema_cache[prefix] = (table_name, schema)
    return table_name, schema


def invalidate_cache():
    """Clear the schema resolution cache (call after app install/uninstall)."""
    _schema_cache.clear()


# Valid identifier pattern for SQL injection prevention
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def _safe_ident(name: str) -> str:
    """Validate and return a safe SQL identifier."""
    if not _IDENT_RE.match(name):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


def query_entities(
    prefix: str,
    filters: dict | None = None,
    fields: list[str] | None = None,
    limit: int = 100,
    order_by: str = "created_at",
    order_dir: str = "DESC",
) -> list[dict]:
    """Query entities by prefix with optional filters.

    This is read-only. No mutations allowed.

    Args:
        prefix:    Entity type prefix (e.g., "re" for recipes)
        filters:   Column=value equality filters
        fields:    Columns to return (None = all)
        limit:     Max rows (capped at 500)
        order_by:  Column to sort by
        order_dir: ASC or DESC

    Returns:
        List of entity dicts
    """
    table_name, schema = _resolve_prefix(prefix)
    safe_schema = _safe_ident(schema)
    safe_table = _safe_ident(table_name)

    # Build field list
    if fields:
        cols = ", ".join(_safe_ident(f) for f in fields)
    else:
        cols = "*"

    # Build WHERE clause
    where_parts = []
    params = []
    if filters:
        for col, val in filters.items():
            where_parts.append(f"{_safe_ident(col)} = %s")
            params.append(val)

    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    # Validate order
    safe_order = _safe_ident(order_by)
    if order_dir.upper() not in ("ASC", "DESC"):
        order_dir = "DESC"

    limit = min(limit, 500)
    params.append(limit)

    query = (
        f"SELECT {cols} FROM {safe_schema}.{safe_table}"
        f"{where_sql} ORDER BY {safe_order} {order_dir} LIMIT %s"
    )

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, tuple(params))
            return [dict(row) for row in cur.fetchall()]


def get_entity(prefix: str, entity_id: str) -> dict | None:
    """Get a single entity by its full ID (e.g., 're-a1b2c3d4').

    Returns the entity dict or None if not found.
    """
    table_name, schema = _resolve_prefix(prefix)
    safe_schema = _safe_ident(schema)
    safe_table = _safe_ident(table_name)

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"SELECT * FROM {safe_schema}.{safe_table} WHERE id = %s",
                (entity_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
