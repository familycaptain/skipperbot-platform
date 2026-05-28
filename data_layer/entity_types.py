"""Entity Types — master registry of all entity ID prefixes.

Provides lookup functions for resolving entity IDs to types and source tables.
Replaces the hardcoded ENTITY_TYPE_NAMES / ENTITY_PREFIXES in link_registry.py.
"""

import logging
from functools import lru_cache
from data_layer.db import fetch_all, fetch_one, execute

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _load_all() -> list[dict]:
    """Load all entity types from the database."""
    return fetch_all("SELECT prefix, name, id_format, table_name FROM entity_types ORDER BY prefix")


@lru_cache(maxsize=1)
def _prefix_map() -> dict[str, dict]:
    """Build a prefix → row dict, cached until invalidated."""
    rows = _load_all()
    return {r["prefix"]: r for r in rows}


@lru_cache(maxsize=1)
def _id_format_list() -> tuple[str, ...]:
    """Return all id_format values sorted longest-first (for prefix matching).

    Longest-first ensures 'sch-' matches before 'sc-', 'li-' before 'l-', etc.
    """
    rows = _load_all()
    formats = sorted([r["id_format"] for r in rows], key=len, reverse=True)
    return tuple(formats)


@lru_cache(maxsize=1)
def _id_format_to_prefix() -> dict[str, str]:
    """Map id_format → prefix for reverse lookups."""
    rows = _load_all()
    return {r["id_format"]: r["prefix"] for r in rows}


def invalidate_cache():
    """Clear all caches. Call after inserting/updating entity_types rows."""
    _prefix_map.cache_clear()
    _id_format_list.cache_clear()
    _id_format_to_prefix.cache_clear()


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_all() -> list[dict]:
    """Return all entity type rows."""
    return _load_all()


def get_by_prefix(prefix: str) -> dict | None:
    """Look up an entity type by its prefix moniker (e.g., 'g', 'sch', 'veh')."""
    return _prefix_map().get(prefix)


def resolve_entity_id(entity_id: str) -> dict | None:
    """Given an entity ID like 'g-abc123', return its entity type record.

    Matches the longest id_format prefix first to handle overlapping prefixes
    (e.g., 'sch-' before 'sc-', 'li-' before 'l-').
    """
    fmt_to_prefix = _id_format_to_prefix()
    for fmt in _id_format_list():
        if entity_id.startswith(fmt):
            prefix = fmt_to_prefix[fmt]
            return _prefix_map().get(prefix)
    return None


def entity_type_name(entity_id: str) -> str:
    """Return the human-readable type name for an entity ID, or 'unknown'."""
    rec = resolve_entity_id(entity_id)
    return rec["name"] if rec else "unknown"


def entity_table_name(entity_id: str) -> str | None:
    """Return the source table name for an entity ID, or None."""
    rec = resolve_entity_id(entity_id)
    return rec["table_name"] if rec else None


def is_valid_entity_id(entity_id: str) -> bool:
    """Check if a string starts with a known entity ID prefix."""
    return resolve_entity_id(entity_id) is not None


def get_all_id_formats() -> tuple[str, ...]:
    """Return all known id_format prefixes (e.g., ('g-', 'p-', 't-', ...))."""
    return _id_format_list()


# ---------------------------------------------------------------------------
# Write operations (for future self-extension by Skipper)
# ---------------------------------------------------------------------------

def register_entity_type(prefix: str, name: str, id_format: str, table_name: str | None = None) -> dict | None:
    """Register a new entity type. Returns the row, or None if prefix already exists."""
    row = fetch_one(
        """INSERT INTO entity_types (prefix, name, id_format, table_name)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (prefix) DO NOTHING
           RETURNING *""",
        (prefix, name, id_format, table_name),
    )
    if row:
        invalidate_cache()
    return dict(row) if row else None
