"""Todo — business logic.

Higher-level operations that combine the per-user ``app_todo.todo_config``
table (owned here) with the underlying list + items (owned by the Lists
app). All cross-app reads go through ``apps.lists.data`` and
``apps.lists.store`` — never with raw SQL into ``app_lists.*``.

Ported from the helper functions that used to live in
``data_layer/todo.py`` for sub-chunk 5c-part-2.

A subtle fix lands here too: the legacy ``move_item_between_lists``
reached into ``public.list_items`` with raw SQL. After the lists app was
packaged in Chunk 4, that table moved to ``app_lists.list_items`` and
the raw query was silently broken. The replacement
``move_item_to_list`` delegates to ``apps.lists.store.move_item``, which
goes through the lists app's data layer (and so picks up the Trello
write-through path for free).
"""

from __future__ import annotations

import logging

from apps.todo import data as _dl_todo


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resolve the user's lists + items
# ---------------------------------------------------------------------------

def get_todo_items(user_id: str, include_archived: bool = False) -> dict | None:
    """Get the user's default to-do list with items.

    Returns ``{config, list_id, list_name, items, count}`` or ``None`` if
    no config / list is set up.
    """
    cfg = _dl_todo.get_config(user_id)
    if not cfg or not cfg["default_list_id"]:
        return None

    from apps.lists.data import get_list, get_items
    lst = get_list(cfg["default_list_id"])
    if not lst:
        return None

    items = get_items(cfg["default_list_id"], include_archived=include_archived)
    return {
        "config": cfg,
        "list_id": lst["id"],
        "list_name": lst["name"],
        "items": items,
        "count": len([i for i in items if not i.get("archived")]),
    }


def get_backlog_items(user_id: str, include_archived: bool = False) -> dict | None:
    """Get the user's backlog list with items.

    Returns ``{config, list_id, list_name, items, count}`` or ``None`` if
    no backlog is configured.
    """
    cfg = _dl_todo.get_config(user_id)
    if not cfg or not cfg.get("backlog_list_id"):
        return None

    from apps.lists.data import get_list, get_items
    lst = get_list(cfg["backlog_list_id"])
    if not lst:
        return None

    items = get_items(cfg["backlog_list_id"], include_archived=include_archived)
    return {
        "config": cfg,
        "list_id": lst["id"],
        "list_name": lst["name"],
        "items": items,
        "count": len([i for i in items if not i.get("archived")]),
    }


# ---------------------------------------------------------------------------
# Cross-list move (default <-> backlog)
# ---------------------------------------------------------------------------

def move_item_to_list(item_id: str, from_list_id: str, to_list_id: str) -> bool:
    """Move a list item from one list to another, placing it at the top.

    Delegates to ``apps.lists.store.move_item`` so the Lists app's data
    layer (and Trello write-through, if the destination is Trello-linked)
    runs. Returns ``True`` if the move succeeded.
    """
    from apps.lists.store import move_item
    result = move_item(from_list_id, item_id, to_list_id)
    # apps.lists.store.move_item returns a confirmation string on success
    # and an error string starting with "Error:" on failure.
    return isinstance(result, str) and not result.startswith("Error:")


# ---------------------------------------------------------------------------
# Default-list bootstrap
# ---------------------------------------------------------------------------

def ensure_default_list(user_id: str, display_name: str = "") -> dict:
    """Ensure the user has a default to-do list.

    Verifies the configured ``default_list_id`` still exists in the
    Lists app; if not (or no config at all), creates a fresh
    ``"<Name>'s To-Do"`` list via ``apps.lists.store.create_list`` and
    points ``default_list_id`` at it.

    Returns the (possibly freshly-created) config dict.
    """
    from apps.lists.data import get_list

    # Fast path: config already points at a live list — no lock, no writes.
    cfg = _dl_todo.get_config(user_id)
    if cfg and cfg["default_list_id"] and get_list(cfg["default_list_id"]):
        return cfg

    # Miss: bootstrap atomically. The To-Do UI opens /config and /items
    # concurrently (separate threads), so a plain create-here races and makes
    # two "<user>'s To-Do" lists. claim_default_list serializes bootstrappers
    # with a per-user advisory lock so exactly ONE list is created. The cross-app
    # calls are injected so apps/todo/data.py stays free of apps.lists imports.
    from apps.lists.store import create_list
    name = f"{display_name or user_id.title()}'s To-Do"
    return _dl_todo.claim_default_list(user_id, create_list, get_list, name)
