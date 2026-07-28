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


def _literal_prefix(id_format: str) -> str:
    """The part of an id_format that a real id actually starts with.

    An app may declare its format either way:

        id_format: "g-"            -> ids look like "g-abc123"
        id_format: "img-{hex8}"    -> ids look like "img-1a2b3c4d"

    The placeholder is documentation, not a template anything expands, so matching an id
    against the RAW value made every app that spelled one out match nothing: no id begins
    with the literal text "{hex8}". Those apps' ids were rejected as invalid and generic
    entity links to their records could not be created at all — silently, because an
    unmatched id is indistinguishable from an unknown one.

    Truncating at the first brace handles both spellings, and is done at READ time so
    existing rows are repaired without a migration or a re-registration pass.
    """
    return (id_format or "").split("{", 1)[0]


@lru_cache(maxsize=1)
def _id_format_list() -> tuple[str, ...]:
    """Matchable id prefixes, longest-first.

    Longest-first ensures 'sch-' matches before 'sc-', 'li-' before 'l-', etc.
    """
    rows = _load_all()
    formats = {_literal_prefix(r["id_format"]) for r in rows}
    return tuple(sorted((f for f in formats if f), key=len, reverse=True))


@lru_cache(maxsize=1)
def _id_format_to_prefix() -> dict[str, str]:
    """Map matchable id prefix → prefix moniker for reverse lookups.

    Two apps resolving to the same literal prefix would be a registry conflict rather
    than something to silently pick a winner for, so it is logged.
    """
    mapping: dict[str, str] = {}
    for r in _load_all():
        lit = _literal_prefix(r["id_format"])
        if not lit:
            continue
        if lit in mapping and mapping[lit] != r["prefix"]:
            logger.warning(
                "ENTITY_TYPES: id prefix %r is claimed by both %r and %r — ids starting "
                "with it will resolve to %r", lit, mapping[lit], r["prefix"], mapping[lit])
            continue
        mapping[lit] = r["prefix"]
    return mapping


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
