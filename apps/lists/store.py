"""Lists — business logic.

Higher-level operations on top of ``apps.lists.data``: list creation
(with ID generation + Trello link bootstrap), rendering as text,
alias-resolution, write-through to Trello, sync orchestration.

Ported from ``list_store.py`` for sub-chunk 4c-part-2. Functionally
identical; the only changes are:

  - ``import data_layer.lists as _dl_lists`` is now
    ``from apps.lists import data as _dl_lists`` so the schema-scoped
    helpers in apps/lists/data.py do the persistence.
  - All ID generation, formatting, Trello write-through, and find-by-name
    logic is untouched.
"""

import uuid
from datetime import datetime

from config import logger
from app_platform.time import get_timezone
from auto_memory import log_entity_change
from apps.lists import data as _dl_lists


def _now_iso() -> str:
    return datetime.now(get_timezone()).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Persistence — Postgres via apps.lists.data
# ---------------------------------------------------------------------------

def _trello_enabled() -> bool:
    """Master Trello-sync switch for lists (Settings → Lists: trello_sync_enabled,
    default on). When off, no list↔Trello read/write happens."""
    try:
        from app_platform import settings as _settings
        return bool(_settings.get("trello_sync_enabled", scope="app:lists", default=True))
    except Exception:
        return True


def _load_list(list_id: str) -> dict | None:
    return _dl_lists.get_list(list_id)


def _save_list(lst: dict):
    """Save a list and its items to Postgres."""
    _dl_lists.save_list(lst)
    # Sync items: replace all items for this list
    _dl_lists.replace_items(lst["id"], lst.get("items", []))


def _load_all_lists() -> list[dict]:
    return _dl_lists.get_all_lists()


# ---------------------------------------------------------------------------
# List CRUD
# ---------------------------------------------------------------------------

def create_list(
    name: str,
    created_by: str,
    trello_board: str = "",
    trello_list_name: str = "",
    aliases: list[str] | None = None,
) -> dict:
    """Create a new list.

    Args:
        name: Display name of the list.
        created_by: Who created it.
        trello_board: Optional configured board name (Lists app Trello settings) for sync.
        trello_list_name: Optional Trello list name to link to.
        aliases: Optional list of nickname strings for matching.

    Returns:
        The created list dict.
    """
    lst = {
        "id": _new_id("l"),
        "name": name,
        "created_by": created_by.lower().strip(),
        "created_at": _now_iso(),
        "aliases": [a.strip().lower() for a in aliases] if aliases else [],
        "items": [],
        "trello": None,
    }

    if trello_board and trello_list_name:
        lst["trello"] = {
            "board": trello_board.lower().strip(),
            "list_name": trello_list_name.strip(),
            "last_sync": "",
        }

    _save_list(lst)

    trello_info = f" (Trello: {trello_board}/{trello_list_name})" if trello_board else ""
    log_entity_change("created", lst["id"], "list",
                      f"List '{name}'{trello_info}",
                      by=created_by)

    return lst


def get_list(list_id: str) -> dict | None:
    """Get a list by ID."""
    return _load_list(list_id)


def get_all_lists() -> list[dict]:
    """Get all lists."""
    return _load_all_lists()


def find_list_by_name(name: str) -> dict | None:
    """Find a list by name (case-insensitive).

    Match priority:
      1. Exact match on list name
      2. Board-qualified match ("board listname" or "listname board")
      3. Search term contained in list name
      4. Alias match
      5. List name contained in search term (longest first)
    """
    norm = name.strip().lower()
    lists = _load_all_lists()

    # Pass 1: exact match
    for lst in lists:
        if lst["name"].strip().lower() == norm:
            return lst

    # Pass 2: board-qualified match — e.g. "boardname Backlog" or "Backlog boardname"
    # Check if search term = "{board} {listname}" or "{listname} {board}"
    for lst in lists:
        trello = lst.get("trello") or {}
        board = trello.get("board", "").strip().lower()
        lname = lst["name"].strip().lower()
        if board and lname:
            if norm == f"{board} {lname}" or norm == f"{lname} {board}":
                return lst

    # Pass 2b: board-qualified substring — board name + list name both appear
    # in the search term (handles "boardname backlog list" or similar)
    board_matches = []
    for lst in lists:
        trello = lst.get("trello") or {}
        board = trello.get("board", "").strip().lower()
        lname = lst["name"].strip().lower()
        if board and lname and board in norm and lname in norm:
            board_matches.append(lst)
    if len(board_matches) == 1:
        return board_matches[0]

    # Pass 3: search term is contained in list name
    for lst in lists:
        if norm in lst["name"].strip().lower():
            return lst

    # Pass 4: alias match (exact or substring in either direction)
    for lst in lists:
        for alias in lst.get("aliases", []):
            if alias == norm or alias in norm or norm in alias:
                return lst

    # Pass 5: list name is contained in search term (longest name first to avoid
    # short names like "To-Do" stealing matches meant for "Weekend To-Do").
    # When multiple lists share the same name, prefer one whose board also
    # appears in the search term.
    sorted_lists = sorted(lists, key=lambda l: -len(l["name"]))
    fallback = None
    for lst in sorted_lists:
        lname = lst["name"].strip().lower()
        if lname in norm:
            trello = lst.get("trello") or {}
            board = trello.get("board", "").strip().lower()
            if board and board in norm:
                return lst
            if fallback is None:
                fallback = lst
    if fallback:
        return fallback

    return None


def update_aliases(list_id: str, aliases: list[str]) -> str:
    """Set aliases (nicknames) on a list for fuzzy name matching.

    Args:
        list_id: Target list ID.
        aliases: List of alias strings (e.g. ["momma", "mom"]).

    Returns:
        Confirmation or error string.
    """
    lst = _load_list(list_id)
    if not lst:
        return f"Error: List '{list_id}' not found."

    lst["aliases"] = [a.strip().lower() for a in aliases if a.strip()]
    _save_list(lst)

    log_entity_change("updated", list_id, "list",
                      f"Aliases set on '{lst['name']}': {lst['aliases']}")

    return f"Aliases for '{lst['name']}' set to: {lst['aliases']}"


def set_track_items(list_id: str, enabled: bool = True) -> str:
    """Enable or disable item history tracking on a Trello-linked list.

    When enabled, every sync records card titles so the agent can later
    suggest the right board/list when re-adding items.

    Args:
        list_id: Target list ID.
        enabled: True to enable, False to disable.

    Returns:
        Confirmation or error string.
    """
    lst = _load_list(list_id)
    if not lst:
        return f"Error: List '{list_id}' not found."

    if not lst.get("trello"):
        return f"Error: List '{lst['name']}' is not linked to Trello."

    lst["trello"]["track_items"] = enabled
    _save_list(lst)

    state = "enabled" if enabled else "disabled"
    log_entity_change("updated", list_id, "list",
                      f"Item tracking {state} on '{lst['name']}'")

    return f"Item tracking {state} on '{lst['name']}' ({lst['trello']['board']}/{lst['trello']['list_name']})."


def delete_list(list_id: str) -> str:
    """Delete a list by ID.

    Returns:
        Confirmation or error string.
    """
    lst = _load_list(list_id)
    if not lst:
        return f"Error: List '{list_id}' not found."
    list_name = lst["name"]
    _dl_lists.delete_list(list_id)

    log_entity_change("deleted", list_id, "list", f"List '{list_name}' deleted")

    return f"List '{list_id}' deleted."


# ---------------------------------------------------------------------------
# Item CRUD
# ---------------------------------------------------------------------------

def add_item(
    list_id: str,
    text: str,
    added_by: str,
    position: int = -1,
) -> dict | str:
    """Add an item to a list.

    Args:
        list_id: Target list.
        text: Item text (single line).
        added_by: Who added it.
        position: Insert position (0-indexed). -1 = end.

    Returns:
        The created item dict, or error string.
    """
    lst = _load_list(list_id)
    if not lst:
        return f"Error: List '{list_id}' not found."

    item = {
        "id": _new_id("li"),
        "text": text.strip(),
        "added_by": added_by.lower().strip(),
        "added_at": _now_iso(),
        "archived": False,
        "trello_card_id": "",
    }

    items = lst.get("items", [])
    if position < 0 or position >= len(items):
        items.append(item)
    else:
        items.insert(position, item)

    lst["items"] = items
    _save_list(lst)

    # Write-through to Trello if linked
    if lst.get("trello") and _trello_enabled():
        try:
            from trello_client import add_card
            board = lst["trello"]["board"]
            trello_list = lst["trello"]["list_name"]
            trello_pos = "top" if position == 0 else ""
            result = add_card(board, trello_list, text.strip(), pos=trello_pos)
            item["trello_card_id"] = result.get("id", "")
            _save_list(lst)
        except Exception as e:
            logger.error("LIST: Trello write-through failed for add: %s", str(e))

    log_entity_change("added_item", item["id"], "list_item",
                      f"'{text.strip()}' added to list '{lst['name']}'",
                      by=added_by, related_entities=[list_id])

    return item


def update_item_text(list_id: str, item_id: str, new_text: str) -> str:
    """Update the text of an existing list item.

    Returns:
        Confirmation or error string.
    """
    lst = _load_list(list_id)
    if not lst:
        return f"Error: List '{list_id}' not found."

    for item in lst.get("items", []):
        if item["id"] == item_id:
            old_text = item["text"]
            item["text"] = new_text.strip()
            _save_list(lst)

            # Write-through to Trello if linked
            if lst.get("trello") and item.get("trello_card_id") and _trello_enabled():
                try:
                    from trello_client import _board_request
                    board = lst["trello"]["board"]
                    _board_request(
                        "PUT", f"/cards/{item['trello_card_id']}", board,
                        {"name": new_text.strip()}
                    )
                except Exception as e:
                    logger.error("LIST: Trello write-through failed for edit: %s", str(e))

            log_entity_change("edited_item", item_id, "list_item",
                              f"'{old_text}' → '{new_text.strip()}' in list '{lst['name']}'",
                              related_entities=[list_id])

            return f"Item updated in list '{lst['name']}'."

    return f"Error: Item '{item_id}' not found in list '{list_id}'."


def remove_item(list_id: str, item_id: str) -> str:
    """Remove (archive) an item from a list.

    Returns:
        Confirmation or error string.
    """
    lst = _load_list(list_id)
    if not lst:
        return f"Error: List '{list_id}' not found."

    for item in lst.get("items", []):
        if item["id"] == item_id:
            item["archived"] = True
            from datetime import datetime, timezone
            item["archived_at"] = datetime.now(timezone.utc).isoformat()

            # Write-through to Trello if linked
            if lst.get("trello") and item.get("trello_card_id") and _trello_enabled():
                try:
                    from trello_client import _board_request
                    board = lst["trello"]["board"]
                    _board_request(
                        "PUT", f"/cards/{item['trello_card_id']}", board,
                        {"closed": "true"}
                    )
                except Exception as e:
                    logger.error("LIST: Trello write-through failed for archive: %s", str(e))

            _save_list(lst)

            log_entity_change("removed_item", item_id, "list_item",
                              f"'{item['text']}' removed from list '{lst['name']}'",
                              related_entities=[list_id])

            return f"Item '{item_id}' archived from list '{lst['name']}'."

    return f"Error: Item '{item_id}' not found in list '{list_id}'."


def move_item(
    from_list_id: str,
    item_id: str,
    to_list_id: str,
) -> str:
    """Move an item from one list to another.

    Returns:
        Confirmation or error string.
    """
    from_lst = _load_list(from_list_id)
    to_lst = _load_list(to_list_id)

    if not from_lst:
        return f"Error: Source list '{from_list_id}' not found."
    if not to_lst:
        return f"Error: Target list '{to_list_id}' not found."

    # Find and remove from source
    item = None
    new_items = []
    for i in from_lst.get("items", []):
        if i["id"] == item_id:
            item = i
        else:
            new_items.append(i)

    if not item:
        return f"Error: Item '{item_id}' not found in list '{from_list_id}'."

    from_lst["items"] = new_items
    to_lst.setdefault("items", []).insert(0, item)

    _save_list(from_lst)
    _save_list(to_lst)

    # Trello write-through for moves is complex (different boards possible).
    # Handle Trello move if both lists are on the same board.
    if (
        _trello_enabled()
        and from_lst.get("trello") and to_lst.get("trello")
        and from_lst["trello"]["board"] == to_lst["trello"]["board"]
        and item.get("trello_card_id")
    ):
        try:
            from trello_client import find_list_by_name, _board_request
            board = to_lst["trello"]["board"]
            to_trello_list = find_list_by_name(board, to_lst["trello"]["list_name"])
            _board_request(
                "PUT", f"/cards/{item['trello_card_id']}", board,
                {"idList": to_trello_list["id"], "pos": "top"}
            )
        except Exception as e:
            logger.error("LIST: Trello write-through failed for move: %s", str(e))

    log_entity_change("moved_item", item_id, "list_item",
                      f"'{item['text']}' moved from '{from_lst['name']}' to '{to_lst['name']}'",
                      related_entities=[from_list_id, to_list_id])

    return (
        f"Moved '{item['text']}' from '{from_lst['name']}' to '{to_lst['name']}'."
    )


def reorder_item(list_id: str, item_id: str, new_position: int) -> str:
    """Move an item to a new position within the same list.

    Returns:
        Confirmation or error string.
    """
    lst = _load_list(list_id)
    if not lst:
        return f"Error: List '{list_id}' not found."

    items = lst.get("items", [])
    item = None
    old_pos = -1
    for i, it in enumerate(items):
        if it["id"] == item_id:
            item = it
            old_pos = i
            break

    if not item:
        return f"Error: Item '{item_id}' not found."

    items.pop(old_pos)
    new_pos = max(0, min(new_position, len(items)))
    items.insert(new_pos, item)
    lst["items"] = items
    _save_list(lst)

    # Write-through to Trello if linked
    if lst.get("trello") and item.get("trello_card_id") and _trello_enabled():
        try:
            from trello_client import _board_request, get_cards
            board = lst["trello"]["board"]
            trello_list = lst["trello"]["list_name"]
            # Fetch current Trello card positions to compute a valid pos value
            cards = get_cards(board, trello_list)
            # Build ordered pos list (excluding the card being moved)
            other_positions = [
                c["pos"] for c in cards
                if c["id"] != item["trello_card_id"] and not c.get("closed")
            ]
            other_positions.sort()
            # Calculate new pos: between neighbors, or top/bottom
            if not other_positions:
                target_pos = 16384.0
            elif new_pos == 0:
                target_pos = other_positions[0] / 2.0
            elif new_pos >= len(other_positions):
                target_pos = other_positions[-1] + 16384.0
            else:
                target_pos = (other_positions[new_pos - 1] + other_positions[new_pos]) / 2.0
            _board_request(
                "PUT", f"/cards/{item['trello_card_id']}", board,
                {"pos": str(target_pos)}
            )
        except Exception as e:
            logger.error("LIST: Trello write-through failed for reorder: %s", str(e))

    return f"Moved '{item['text']}' to position {new_pos} in '{lst['name']}'."


def move_items_by_text(
    from_list_name: str,
    to_list_name: str,
    item_texts: list[str] | None = None,
    move_all: bool = False,
) -> str:
    """Move items between lists by text match. Convenience function.

    Args:
        from_list_name: Source list name.
        to_list_name: Target list name.
        item_texts: Specific items to move (fuzzy match). None + move_all=True moves everything.
        move_all: If True, moves all non-archived items.

    Returns:
        Summary of moves.
    """
    from_lst = find_list_by_name(from_list_name)
    to_lst = find_list_by_name(to_list_name)

    if not from_lst:
        return f"Error: List '{from_list_name}' not found."
    if not to_lst:
        return f"Error: List '{to_list_name}' not found."

    active_items = [i for i in from_lst.get("items", []) if not i.get("archived")]

    if move_all:
        to_move = active_items
    elif item_texts:
        to_move = []
        for text in item_texts:
            norm = text.strip().lower()
            match = None
            for item in active_items:
                if item["text"].strip().lower() == norm:
                    match = item
                    break
            if not match:
                for item in active_items:
                    if norm in item["text"].strip().lower():
                        match = item
                        break
            if match:
                to_move.append(match)
    else:
        return "Error: Specify item_texts or set move_all=True."

    moved = []
    for item in to_move:
        result = move_item(from_lst["id"], item["id"], to_lst["id"])
        moved.append(item["text"])
        # Reload from_lst as it was modified
        from_lst = _load_list(from_lst["id"])

    if not moved:
        return "No matching items found to move."

    return f"Moved {len(moved)} item(s) from '{from_lst['name']}' to '{to_lst['name']}':\n" + \
           "\n".join(f"  - {t}" for t in moved)


# ---------------------------------------------------------------------------
# Query / display
# ---------------------------------------------------------------------------

def show_list(list_id: str, include_archived: bool = False) -> str:
    """Format a list for display.

    Returns:
        Formatted string showing all items.
    """
    lst = _load_list(list_id)
    if not lst:
        return f"Error: List '{list_id}' not found."

    items = lst.get("items", [])
    active = [i for i in items if not i.get("archived")]
    archived = [i for i in items if i.get("archived")]

    lines = [f"📋 {lst['name']} [{lst['id']}]"]
    if lst.get("trello"):
        lines.append(f"  (synced with Trello: {lst['trello']['board']} / {lst['trello']['list_name']})")

    if not active:
        lines.append("  (empty)")
    else:
        for idx, item in enumerate(active):
            lines.append(f"  {idx + 1}. {item['text']}  [{item['id']}]")

    if include_archived and archived:
        lines.append(f"\n  Archived ({len(archived)}):")
        for item in archived:
            lines.append(f"    ✕ {item['text']}")

    return "\n".join(lines)


def show_all_lists(user_id: str = "") -> str:
    """Show a summary of all lists.

    Args:
        user_id: Optional filter by creator.
    """
    lists = _load_all_lists()
    if not lists:
        return "No lists found."

    user = user_id.lower().strip() if user_id else ""

    lines = [f"Lists ({len(lists)}):\n"]
    for lst in lists:
        if user and lst.get("created_by", "") != user:
            continue

        active_count = len([i for i in lst.get("items", []) if not i.get("archived")])
        sync_tag = ""
        if lst.get("trello"):
            sync_tag = f" ↔ Trello:{lst['trello']['board']}/{lst['trello']['list_name']}"

        lines.append(f"  [{lst['id']}] {lst['name']} ({active_count} items){sync_tag}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trello sync (pull from Trello → update local cache)
# ---------------------------------------------------------------------------

def sync_from_trello(list_id: str) -> str:
    """Pull latest cards from Trello and replace local items.

    Only works for Trello-linked lists. Trello is source of truth.

    Returns:
        Summary of sync results.
    """
    if not _trello_enabled():
        return "Trello sync is disabled (Settings → Lists → Sync lists to Trello)."
    lst = _load_list(list_id)
    if not lst:
        return f"Error: List '{list_id}' not found."

    if not lst.get("trello"):
        return f"Error: List '{lst['name']}' is not linked to Trello."

    try:
        from trello_client import get_cards

        board = lst["trello"]["board"]
        trello_list = lst["trello"]["list_name"]
        cards = get_cards(board, trello_list)

        # Build lookup of existing items by trello_card_id to reuse IDs
        existing_by_card = {
            item["trello_card_id"]: item
            for item in lst.get("items", [])
            if item.get("trello_card_id")
        }

        # Replace local items with Trello cards, reusing IDs where possible
        new_items = []
        for card in cards:
            if card.get("closed"):
                continue
            existing = existing_by_card.get(card["id"])
            new_items.append({
                "id": existing["id"] if existing else _new_id("li"),
                "text": card["name"],
                "added_by": "trello_sync",
                "added_at": card.get("dateLastActivity", _now_iso()),
                "archived": False,
                "trello_card_id": card["id"],
            })

        old_count = len([i for i in lst.get("items", []) if not i.get("archived")])
        lst["items"] = new_items
        lst["trello"]["last_sync"] = _now_iso()
        _save_list(lst)

        # Record card titles in item history if tracking is enabled
        if lst["trello"].get("track_items"):
            try:
                from data_layer.item_history import record_items
                titles = [item["text"] for item in new_items]
                record_items(board, trello_list, titles)
            except Exception as e:
                logger.error("LIST: Item history recording failed for '%s': %s", lst["name"], str(e))

        return (
            f"Synced '{lst['name']}' from Trello ({board}/{trello_list}).\n"
            f"  Before: {old_count} items → After: {len(new_items)} items.\n"
            f"  Last sync: {lst['trello']['last_sync'][:16]}"
        )

    except Exception as e:
        return f"Error syncing from Trello: {str(e)}"


def sync_all_trello_lists() -> str:
    """Sync all Trello-linked lists. Called by background poller.

    Skips boards that are linked to a project (those use task sync via
    trello_task_sync instead).

    Returns:
        Summary of all syncs.
    """
    if not _trello_enabled():
        return "Trello list sync is disabled (Settings → Lists)."
    lists = _load_all_lists()
    linked = [lst for lst in lists if lst.get("trello")]

    if not linked:
        return "No Trello-linked lists to sync."

    # Skip boards that are linked to a project (they use task sync)
    try:
        from trello_task_sync import get_boards_linked_to_projects
        project_boards = get_boards_linked_to_projects()
    except Exception:
        project_boards = set()

    results = []
    for lst in linked:
        board = lst["trello"].get("board", "").lower()
        if board in project_boards:
            continue
        result = sync_from_trello(lst["id"])
        results.append(result)

    if not results:
        return "No Trello-linked lists to sync (project boards use task sync)."

    return "\n".join(results)
