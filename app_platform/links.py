"""Platform Links Service
========================
Stable contract for the platform-level ``link`` entity type — soft, typed
references between any two entities **by ID** (not hard foreign keys). The data
lives in the baseline ``public.links`` table; this shim forwards to
``data_layer.links`` so apps use one short, stable import path (documented in
``APP_PACKAGES.md``). If the implementation ever moves, consumers don't change.

``link`` is platform **infrastructure** — any app can link entities — and is NOT
an app. (It has no viewer; compare ``image``/``document``, which are also
platform entity types but do ship viewer apps.) Mirrors the
``app_platform.documents`` / ``notifications`` / ``jobs`` shim pattern.

Usage from an app or platform module:

    from app_platform.links import ensure_edge, get_links

    ensure_edge(src_id, dst_id, "blocks", "blocked_by")
    links = get_links(entity_id)
"""

from __future__ import annotations

from data_layer.links import (
    create_link,
    ensure_edge,
    get_links,
    get_blast_radius,
    delete_link,
    delete_links_for_entity,
)

__all__ = [
    "create_link",
    "ensure_edge",
    "get_links",
    "get_blast_radius",
    "delete_link",
    "delete_links_for_entity",
]
