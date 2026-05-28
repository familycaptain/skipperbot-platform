"""
List & Trello Tools — Manage Trello-style vertical lists.
Lists can be standalone (local only) or linked to a Trello board/list.
For Trello-linked lists, Trello is the source of truth.
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app_platform.memory import digest_record
from list_store import (
    create_list as _create_list,
    get_list as _get_list,
    get_all_lists as _get_all_lists,
    find_list_by_name as _find_list_by_name,
    delete_list as _delete_list,
    update_aliases as _update_aliases,
    add_item as _add_item,
    remove_item as _remove_item,
    move_item as _move_item,
    reorder_item as _reorder_item,
    move_items_by_text as _move_items_by_text,
    show_list as _show_list,
    show_all_lists as _show_all_lists,
    sync_from_trello as _sync_from_trello,
)


def _try_trello_match(name: str) -> tuple[str, str] | None:
    """Try to match a user-provided name to a Trello board + list.

    Handles inputs like:
      'vegetable aisle walmart' -> ('walmart', 'Vegetable Aisle')
      'walmart vegetable aisle' -> ('walmart', 'Vegetable Aisle')
      'mom walmart'             -> ('walmart', "Mom's List")
      'bob todo myproject'      -> ('myproject', 'Bob TODO')

    Returns:
        (board_name, trello_list_name) or None if no match.
    """
    try:
        from trello_client import _load_config, get_lists

        config = _load_config()
        boards = config.get("boards", {})
        norm = name.strip().lower()

        # For each configured board, check if the board name appears in the input
        for board_key, board_cfg in boards.items():
            board_names = [board_key]
            if board_cfg.get("board_name"):
                board_names.append(board_cfg["board_name"].lower())

            for bname in board_names:
                if bname in norm:
                    # Board name found in input; strip it and match the remainder to a list
                    remainder = norm.replace(bname, "").strip()
                    if not remainder:
                        continue

                    # Check list_aliases — exact matches first, then substrings
                    aliases = board_cfg.get("list_aliases", {})
                    # Pass 1: exact alias key or name match
                    for alias_key, alias_name in aliases.items():
                        if remainder == alias_key or remainder == alias_name.lower():
                            return (board_key, alias_name)
                    # Pass 2: substring (longest alias first to avoid 'veg' stealing 'nonveg')
                    for alias_key, alias_name in sorted(aliases.items(), key=lambda x: -len(x[0])):
                        if alias_key in remainder or remainder in alias_key:
                            return (board_key, alias_name)
                        if remainder in alias_name.lower():
                            return (board_key, alias_name)

                    # Then check actual Trello list names
                    try:
                        lists = get_lists(board_key)
                        for lst in lists:
                            ln = lst["name"].lower()
                            if remainder in ln or ln in remainder:
                                return (board_key, lst["name"])
                            # Also try word overlap
                            remainder_words = set(remainder.split())
                            list_words = set(ln.split())
                            if remainder_words and remainder_words.issubset(list_words):
                                return (board_key, lst["name"])
                    except Exception:
                        pass

        return None
    except Exception:
        return None


def get_todo_list(user_id: str) -> str:
    """Show the user's default to-do list. Resolves "my to-do list" automatically.

    Use this when the user says things like:
      - "show my to-do list"
      - "what's on my to-do?"
      - "my to-do items"

    Args:
        user_id: The person whose to-do list to show.

    Returns:
        Formatted to-do list with items in stack-rank order.
    """
    try:
        if not user_id or not user_id.strip():
            return "Error: user_id is required."

        from data_layer.todo import get_todo_items, ensure_default_list

        uid = user_id.strip().lower()

        # Ensure config exists
        ensure_default_list(uid)

        result = get_todo_items(uid)
        if not result or not result.get("items"):
            return f"Your to-do list is empty. Use add_todo_item to add something!"

        active = [i for i in result["items"] if not i.get("archived")]
        archived = [i for i in result["items"] if i.get("archived")]

        lines = [f"📋 {result['list_name']} ({len(active)} item{'s' if len(active) != 1 else ''}):"]
        if not active:
            lines.append("  (empty — all items completed!)")
        else:
            for idx, item in enumerate(active):
                lines.append(f"  {idx + 1}. {item['text']}")

        if archived:
            lines.append(f"\n  ✓ {len(archived)} completed item{'s' if len(archived) != 1 else ''}")

        lines.append(f"\n  List ID: {result['list_id']}")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in get_todo_list: {str(e)}"


def add_todo_item(user_id: str, text: str, top: bool = False) -> str:
    """Add an item to the user's default to-do list.

    Use this when the user says things like:
      - "add X to my to-do list"
      - "put X on my to-do"
      - "I need to do X"
      - "add X to the TOP of my to-do list" (set top=True)

    Args:
        user_id: The person whose to-do list to add to.
        text: The item to add (single line).
        top: If True, insert at the top of the list. Default is bottom.

    Returns:
        Confirmation.
    """
    try:
        if not user_id or not user_id.strip():
            return "Error: user_id is required."
        if not text or not text.strip():
            return "Error: text is required."

        from data_layer.todo import get_config, ensure_default_list

        uid = user_id.strip().lower()
        cfg = get_config(uid)
        if not cfg or not cfg.get("default_list_id"):
            cfg = ensure_default_list(uid)

        list_id = cfg["default_list_id"]
        position = 0 if top else -1
        result = _add_item(list_id, text.strip(), uid, position=position)
        if isinstance(result, str):
            return result
        try:
            digest_record("todo", "to-do item", "created", result["id"], {"name": result["text"]}, by=uid)
        except Exception:
            pass
        where = " (at the top)" if top else ""
        return f"Added to your to-do list{where}: {result['text']}"

    except Exception as e:
        return f"Error in add_todo_item: {str(e)}"


def mark_todo_done(user_id: str, item_text: str) -> str:
    """Mark a to-do item as done (archive it).

    Use this when the user says things like:
      - "mark X as done on my to-do"
      - "I finished X on my to-do"
      - "check off X"

    Args:
        user_id: The person whose to-do list to update.
        item_text: The item text to mark done (fuzzy match).

    Returns:
        Confirmation.
    """
    try:
        if not user_id or not user_id.strip():
            return "Error: user_id is required."
        if not item_text or not item_text.strip():
            return "Error: item_text is required."

        from data_layer.todo import get_todo_items

        uid = user_id.strip().lower()
        result = get_todo_items(uid)
        if not result or not result.get("items"):
            return "Your to-do list is empty."

        active = [i for i in result["items"] if not i.get("archived")]
        norm = item_text.strip().lower()

        # Exact match first, then substring
        match = None
        for item in active:
            if item["text"].strip().lower() == norm:
                match = item
                break
        if not match:
            for item in active:
                if norm in item["text"].strip().lower():
                    match = item
                    break

        if not match:
            available = [i["text"] for i in active[:10]]
            return f"Item '{item_text}' not found. Items: {', '.join(available)}"

        from data_layer.lists import archive_item
        archive_item(match["id"])

        # If this item is synced from Trello, archive the Trello card too.
        # Otherwise the next Trello sync will replace local items and bring it back.
        trello_card_id = match.get("trello_card_id", "")
        if trello_card_id:
            try:
                from data_layer.lists import get_list as _get_list
                lst = _get_list(result["list_id"])
                trello_cfg = lst.get("trello") if lst else None
                board = trello_cfg.get("board") if trello_cfg else None
                if board:
                    from trello_client import _board_request
                    _board_request("PUT", f"/cards/{trello_card_id}", board, {"closed": "true"})
            except Exception:
                pass

        try:
            digest_record("todo", "to-do item", "completed", match["id"], {"name": match["text"]}, by=uid)
        except Exception:
            pass
        return f"✓ Done: {match['text']}"

    except Exception as e:
        return f"Error in mark_todo_done: {str(e)}"


def create_list(
    name: str,
    created_by: str,
    trello_board: str = "",
    trello_list_name: str = "",
) -> str:
    """Create a new list.

    Most lists the family uses already exist (shopping, walmart, project-alpha boards).
    Only use this to create a brand-new standalone list (e.g. "Weekend To-Do").

    Args:
        name: Display name for the list (e.g. "Weekend To-Do", "Packing List").
        created_by: Who is creating this list (person name).
        trello_board: Optional. Board key to link to ("shopping", "walmart", "project-alpha").
        trello_list_name: Optional. List name on that board (e.g. "Momma's List").

    Returns:
        Confirmation with list ID.
    """
    try:
        if not name or not name.strip():
            return "Error: name is required."
        if not created_by or not created_by.strip():
            return "Error: created_by is required."
        if trello_board and not trello_list_name:
            return "Error: trello_list_name is required when trello_board is set."

        result = _create_list(
            name=name.strip(),
            created_by=created_by.strip(),
            trello_board=trello_board.strip() if trello_board else "",
            trello_list_name=trello_list_name.strip() if trello_list_name else "",
        )

        try:
            digest_record("lists", "list", "created", result["id"], result, by=created_by.strip())
        except Exception:
            pass
        out = f"List created (ID: {result['id']}).\n"
        out += f"  Name: {result['name']}\n"
        if result.get("trello"):
            out += f"  Trello: {result['trello']['board']} / {result['trello']['list_name']}\n"
            out += "  (Trello is source of truth — will sync automatically)\n"
        else:
            out += "  Mode: standalone (local only)\n"

        # If Trello-linked, do an initial sync
        if result.get("trello"):
            sync_result = _sync_from_trello(result["id"])
            out += f"  Initial sync: {sync_result}\n"

        return out

    except Exception as e:
        return f"Error in create_list: {str(e)}"


def set_list_aliases(
    list_name: str,
    aliases: str,
) -> str:
    """Set nicknames/aliases on a list so it can be found by those names.

    For example, setting alias "mom" on "Mom's List" means the user can say
    "add milk to mom" and it will resolve to that list.

    Args:
        list_name: The list to update (name or ID).
        aliases: Comma-separated alias strings (e.g. "mom, mother").

    Returns:
        Confirmation with new aliases.

    Ack: Setting aliases...
    """
    try:
        if not list_name or not list_name.strip():
            return "Error: list_name is required."
        if not aliases or not aliases.strip():
            return "Error: aliases is required (comma-separated)."

        name = list_name.strip()
        lst = _get_list(name) if name.startswith("l-") else _find_list_by_name(name)
        if not lst:
            return f"Error: List '{name}' not found."

        alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
        if not alias_list:
            return "Error: at least one alias is required."

        return _update_aliases(lst["id"], alias_list)

    except Exception as e:
        return f"Error in set_list_aliases: {str(e)}"


def show_list(list_name: str, include_archived: str = "false") -> str:
    """Show items in a list.

    Accepts list names in any natural form. Examples:
      - 'walmart vegetable aisle' or 'vegetable aisle walmart'
      - 'myproject backlog'
      - 'shopping grocerystore'
      - 'Weekend To-Do' (a standalone list the user created)

    Args:
        list_name: The list name. Use 'board listname' or 'listname board' format
                   for board-backed lists, or just the list name for standalone lists.
        include_archived: "true" to also show archived items. Default "false".

    Returns:
        Formatted list with items.
    """
    try:
        if not list_name or not list_name.strip():
            return "Error: list_name is required."

        name = list_name.strip()
        archived = include_archived.strip().lower() == "true"

        # Try as ID first
        if name.startswith("l-"):
            lst = _get_list(name)
            if lst:
                return _show_list(name, archived)

        # Try by name
        lst = _find_list_by_name(name)
        if lst:
            return _show_list(lst["id"], archived)

        # Fallback: try to match against Trello boards
        trello_match = _try_trello_match(name)
        if trello_match:
            board, trello_list = trello_match
            from trello_client import get_cards
            cards = get_cards(board, trello_list)
            lines = [f"Trello: {board} / {trello_list} ({len(cards)} items):"]
            if not cards:
                lines.append("  (empty)")
            else:
                for idx, c in enumerate(cards):
                    lines.append(f"  {idx + 1}. {c['name']}")
            return "\n".join(lines)

        return f"Error: List '{name}' not found (checked local lists and Trello boards)."

    except Exception as e:
        return f"Error in show_list: {str(e)}"


def show_all_lists(user_id: str = "") -> str:
    """Show all available lists. This includes board-backed lists (walmart,
    shopping, project-alpha) and any standalone lists the user has created.

    Args:
        user_id: Optional. Filter to lists created by this person.

    Returns:
        Unified summary of every list the user can interact with.
    """
    try:
        lines = []

        # Gather board-backed lists
        try:
            from trello_client import list_configured_boards, get_lists
            boards = list_configured_boards()
            for b in boards:
                try:
                    trello_lists = get_lists(b["name"])
                    for tl in trello_lists:
                        lines.append(f"  {b['name']} / {tl['name']}")
                except Exception:
                    lines.append(f"  {b['name']}: (could not fetch)")
        except Exception:
            pass

        # Gather standalone (user-created) lists
        standalone = []
        try:
            from list_store import get_all_lists
            all_local = get_all_lists()
            for lst in all_local:
                if not lst.get("trello"):
                    count = len([i for i in lst.get("items", []) if not i.get("archived")])
                    standalone.append(f"  {lst['name']} ({count} items)")
        except Exception:
            pass

        if not lines and not standalone:
            return "No lists available."

        out = f"Available lists ({len(lines) + len(standalone)}):"
        if lines:
            out += "\n" + "\n".join(lines)
        if standalone:
            out += "\n" + "\n".join(standalone)
        return out

    except Exception as e:
        return f"Error in show_all_lists: {str(e)}"


def add_list_item(
    list_name: str,
    text: str,
    added_by: str,
) -> str:
    """Add an item to a list.

    Examples:
      add_list_item('walmart vegetable aisle', 'lettuce', 'alice')
      add_list_item('shopping grocerystore', 'milk', 'carol')
      add_list_item('myproject backlog', 'Lighting overhaul', 'bob')
      add_list_item('Weekend To-Do', 'mow the lawn', 'alice')

    Args:
        list_name: The list to add to. Use 'board listname' format for
                   board-backed lists (e.g. 'walmart vegetable aisle').
        text: The item to add (single line).
        added_by: Who is adding this item.

    Returns:
        Confirmation.
    """
    try:
        if not list_name or not list_name.strip():
            return "Error: list_name is required."
        if not text or not text.strip():
            return "Error: text is required."
        if not added_by or not added_by.strip():
            return "Error: added_by is required."

        name = list_name.strip()
        lst = _get_list(name) if name.startswith("l-") else _find_list_by_name(name)

        if lst:
            result = _add_item(lst["id"], text.strip(), added_by.strip())
            if isinstance(result, str):
                return result
            try:
                digest_record("lists", "list item", "created", result["id"],
                              {"name": result["text"], "list": lst["name"]}, by=added_by.strip())
            except Exception:
                pass
            out = f"Added to '{lst['name']}': {result['text']}  [ID: {result['id']}]\n"
            if result.get("trello_card_id"):
                out += f"  (also added to Trello)\n"
            return out

        # Fallback: try to match against Trello boards
        trello_match = _try_trello_match(name)
        if trello_match:
            board, trello_list = trello_match
            from trello_client import add_card
            result = add_card(board, trello_list, text.strip())
            return (
                f"Added to Trello ({board} / {trello_list}): {result['name']}\n"
                f"  Card ID: {result['id']}\n"
            )

        return f"Error: List '{name}' not found (checked local lists and Trello boards)."

    except Exception as e:
        return f"Error in add_list_item: {str(e)}"


def remove_list_item(
    list_name: str,
    item_text: str,
) -> str:
    """Remove/archive an item from a list.

    For board-backed lists, also use trello_archive_card as a fallback.

    Args:
        list_name: The list name (e.g. 'walmart vegetable aisle').
        item_text: The item text to remove (fuzzy match).

    Returns:
        Confirmation.
    """
    try:
        if not list_name or not list_name.strip():
            return "Error: list_name is required."
        if not item_text or not item_text.strip():
            return "Error: item_text is required."

        name = list_name.strip()
        lst = _get_list(name) if name.startswith("l-") else _find_list_by_name(name)
        if not lst:
            return f"Error: List '{name}' not found."

        # Find item by text
        norm = item_text.strip().lower()
        active = [i for i in lst.get("items", []) if not i.get("archived")]

        match = None
        for item in active:
            if item["text"].strip().lower() == norm:
                match = item
                break
        if not match:
            for item in active:
                if norm in item["text"].strip().lower():
                    match = item
                    break

        if not match:
            available = [i["text"] for i in active[:10]]
            return f"Error: Item '{item_text}' not found. Items: {', '.join(available)}"

        result = _remove_item(lst["id"], match["id"])
        try:
            digest_record("lists", "list item", "deleted", match["id"],
                          {"name": match["text"], "list": lst["name"]}, by="")
        except Exception:
            pass
        return result

    except Exception as e:
        return f"Error in remove_list_item: {str(e)}"


def move_list_items(
    from_list: str,
    to_list: str,
    items: str = "",
    move_all: str = "false",
) -> str:
    """Move items between lists. Works by text match.

    Args:
        from_list: Source list name (fuzzy match).
        to_list: Target list name (fuzzy match). Will NOT create a new list.
        items: Comma-separated item texts to move (fuzzy match each).
               Leave empty and set move_all="true" to move everything.
        move_all: "true" to move all remaining items. Default "false".

    Returns:
        Summary of moved items.
    """
    try:
        if not from_list or not from_list.strip():
            return "Error: from_list is required."
        if not to_list or not to_list.strip():
            return "Error: to_list is required."

        do_all = move_all.strip().lower() == "true"
        item_texts = None
        if items and items.strip():
            item_texts = [t.strip() for t in items.split(",") if t.strip()]

        if not do_all and not item_texts:
            return "Error: Specify items to move, or set move_all='true'."

        return _move_items_by_text(
            from_list_name=from_list.strip(),
            to_list_name=to_list.strip(),
            item_texts=item_texts,
            move_all=do_all,
        )

    except Exception as e:
        return f"Error in move_list_items: {str(e)}"


def sync_list(list_name: str) -> str:
    """Force a sync of a Trello-linked list from Trello (source of truth).

    Args:
        list_name: List name (fuzzy match) or list ID.

    Returns:
        Sync results.
    """
    try:
        if not list_name or not list_name.strip():
            return "Error: list_name is required."

        name = list_name.strip()
        lst = _get_list(name) if name.startswith("l-") else _find_list_by_name(name)
        if not lst:
            return f"Error: List '{name}' not found."

        return _sync_from_trello(lst["id"])

    except Exception as e:
        return f"Error in sync_list: {str(e)}"


def trello_show_board(board_name: str, list_name: str = "") -> str:
    """Show all lists and cards on a board. Use this to see an entire board at once.
    For a single list, prefer show_list instead.
    Card IDs are shown in parentheses — use them with trello_get_card(card_id=...) for details.

    Args:
        board_name: Board name ("shopping", "walmart", "project-alpha").
        list_name: Optional. Show only one list on the board.

    Returns:
        Board view with lists and cards (including card IDs).
    """
    try:
        if not board_name or not board_name.strip():
            return "Error: board_name is required."

        from trello_client import get_lists, get_cards, get_all_cards_on_board

        board = board_name.strip().lower()

        if list_name and list_name.strip():
            cards = get_cards(board, list_name.strip())
            lines = [f"Trello: {board} / {list_name.strip()} ({len(cards)} cards):"]
            for c in cards:
                labels = f" [{', '.join(c['labels'])}]" if c.get("labels") and any(c["labels"]) else ""
                lines.append(f"  - {c['name']}{labels} (id:{c['id']})")
            return "\n".join(lines)
        else:
            all_cards = get_all_cards_on_board(board)
            lists = get_lists(board)
            cards_by_list = {}
            for c in all_cards:
                lid = c.get("list_id", "")
                cards_by_list.setdefault(lid, []).append(c)

            lines = [f"Trello board: {board} ({len(lists)} lists):"]
            for lst in lists:
                lst_cards = cards_by_list.get(lst["id"], [])
                lines.append(f"\n  {lst['name']} ({len(lst_cards)} cards):")
                if not lst_cards:
                    lines.append("    (empty)")
                else:
                    for c in lst_cards:
                        labels = f" [{', '.join(c['labels'])}]" if c.get("labels") and any(c["labels"]) else ""
                        lines.append(f"    - {c['name']}{labels} (id:{c['id']})")
            return "\n".join(lines)

    except Exception as e:
        return f"Error in trello_show_board: {str(e)}"


def trello_add_card(
    board_name: str,
    list_name: str,
    title: str,
    desc: str = "",
) -> str:
    """Add a card to a board list. Prefer add_list_item for normal use.
    Use this only when you need to set a card description.

    Args:
        board_name: Board name ("shopping", "walmart", "project-alpha").
        list_name: List name on that board.
        title: Card title.
        desc: Optional card description.

    Returns:
        Confirmation.
    """
    try:
        if not board_name or not board_name.strip():
            return "Error: board_name is required."
        if not list_name or not list_name.strip():
            return "Error: list_name is required."
        if not title or not title.strip():
            return "Error: title is required."

        from trello_client import add_card

        result = add_card(
            board_name.strip().lower(),
            list_name.strip(),
            title.strip(),
            desc.strip() if desc else "",
        )

        out = f"Card added to Trello ({board_name}/{list_name}).\n"
        out += f"  Title: {result['name']}\n"
        out += f"  ID: {result['id']}\n"
        if result.get("url"):
            out += f"  URL: {result['url']}\n"
        return out

    except Exception as e:
        return f"Error in trello_add_card: {str(e)}"


def trello_move_card(
    board_name: str,
    title: str,
    to_list: str,
    from_list: str = "",
) -> str:
    """Move a card between lists on a Trello board.

    Args:
        board_name: Board name from config.
        title: Card title (fuzzy match).
        to_list: Destination list name.
        from_list: Optional source list name to narrow search.

    Returns:
        Confirmation.
    """
    try:
        if not board_name or not board_name.strip():
            return "Error: board_name is required."
        if not title or not title.strip():
            return "Error: title is required."
        if not to_list or not to_list.strip():
            return "Error: to_list is required."

        from trello_client import move_card

        result = move_card(
            board_name.strip().lower(),
            title.strip(),
            to_list.strip(),
            from_list.strip() if from_list else "",
        )

        return (
            f"Moved on Trello: '{result['name']}'\n"
            f"  From: {result.get('from_list', '?')}\n"
            f"  To: {result['to_list']}\n"
        )

    except Exception as e:
        return f"Error in trello_move_card: {str(e)}"


def trello_archive_card(
    board_name: str,
    title: str,
    list_name: str = "",
) -> str:
    """Archive a card on a Trello board.

    Args:
        board_name: Board name from config.
        title: Card title (fuzzy match).
        list_name: Optional list name to narrow search.

    Returns:
        Confirmation.
    """
    try:
        if not board_name or not board_name.strip():
            return "Error: board_name is required."
        if not title or not title.strip():
            return "Error: title is required."

        from trello_client import archive_card

        result = archive_card(
            board_name.strip().lower(),
            title.strip(),
            list_name.strip() if list_name else "",
        )

        return f"Archived on Trello: '{result['name']}' (board: {board_name})"

    except Exception as e:
        return f"Error in trello_archive_card: {str(e)}"


def trello_list_boards() -> str:
    """Show all configured Trello boards and their settings.

    Returns:
        List of configured boards with accounts and default lists.
    """
    try:
        from trello_client import list_configured_boards

        boards = list_configured_boards()
        if not boards:
            return "No Trello boards configured."

        lines = [f"Configured Trello boards ({len(boards)}):"]
        for b in boards:
            lines.append(f"  [{b['name']}] account: {b['account']}, board_id: {b['board_id'] or '(not set)'}")
            if b.get("default_list"):
                lines.append(f"    default list: {b['default_list']}")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in trello_list_boards: {str(e)}"


def trello_suggest_list(query: str) -> str:
    """Look up where an item was last seen on Trello.

    Uses item history (populated automatically from tracked boards) to suggest
    the right board and list for re-adding an item. Call this BEFORE
    trello_add_card or add_list_item when the user wants to add something
    that might have been on a board before.

    Args:
        query: Item name or keyword to search for (e.g. "lettuce", "dog food").

    Returns:
        Suggested board/list or "no history found".

    Ack: Checking item history...
    """
    try:
        if not query or not query.strip():
            return "Error: query is required."

        from item_history import suggest_list

        results = suggest_list(query.strip())
        if not results:
            return f"No item history found for '{query.strip()}'."

        lines = [f"Item history matches for '{query.strip()}':"]
        for r in results:
            lines.append(
                f"  - \"{r['title']}\" → {r['board']} / {r['list']}"
                f" (last seen: {r['last_seen'][:10]}, match: {r['match_type']})"
            )

        # Highlight the best match
        best = results[0]
        lines.append(
            f"\nSuggested: board=\"{best['board']}\", list=\"{best['list']}\""
        )

        return "\n".join(lines)

    except Exception as e:
        return f"Error in trello_suggest_list: {str(e)}"


def trello_get_card(
    board_name: str,
    title: str = "",
    list_name: str = "",
    card_id: str = "",
) -> str:
    """Get full details of a Trello card — description, checklists, labels, comments, attachments.

    Prefer card_id when available (from trello_show_board output) for reliable lookup.
    Falls back to fuzzy title matching if no card_id provided.

    Args:
        board_name: Board name ("shopping", "walmart", "project-alpha").
        title: Card title (fuzzy match). Not needed if card_id is provided.
        card_id: Trello card ID for direct lookup (from trello_show_board output).
        list_name: Optional list name to narrow search.

    Returns:
        Full card details formatted as text.

    Ack: Loading Trello card details...
    """
    try:
        if not board_name or not board_name.strip():
            return "Error: board_name is required."
        if (not title or not title.strip()) and (not card_id or not card_id.strip()):
            return "Error: provide either title or card_id."

        from trello_client import get_card_details

        card = get_card_details(
            board_name.strip().lower(),
            title.strip() if title else "",
            list_name.strip() if list_name else "",
            card_id=card_id.strip() if card_id else "",
        )

        lines = [f"Card: {card['name']}"]
        if card.get("list_name"):
            lines.append(f"  List: {card['list_name']}")
        if card.get("url"):
            lines.append(f"  URL: {card['url']}")
        if card.get("desc"):
            lines.append(f"  Description:\n    {card['desc']}")
        if card.get("due"):
            done = " (complete)" if card.get("dueComplete") else ""
            lines.append(f"  Due: {card['due']}{done}")
        if card.get("labels"):
            lbl_strs = [f"{lb['name']} ({lb['color']})" if lb.get("name") else lb.get("color", "?") for lb in card["labels"]]
            lines.append(f"  Labels: {', '.join(lbl_strs)}")

        if card.get("checklists"):
            for cl in card["checklists"]:
                done_count = sum(1 for i in cl["items"] if i["state"] == "complete")
                lines.append(f"  Checklist: {cl['name']} ({done_count}/{len(cl['items'])})")
                for item in cl["items"]:
                    mark = "x" if item["state"] == "complete" else " "
                    lines.append(f"    [{mark}] {item['name']}")

        if card.get("comments"):
            lines.append(f"  Comments ({len(card['comments'])}):")
            for cm in card["comments"]:
                lines.append(f"    [{cm['date'][:10]}] {cm['author']}: {cm['text'][:200]}")

        if card.get("attachments"):
            lines.append(f"  Attachments ({len(card['attachments'])}):")
            for att in card["attachments"]:
                lines.append(f"    - {att['name']}: {att['url']}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error in trello_get_card: {str(e)}"


def trello_update_card(
    board_name: str,
    title: str = "",
    list_name: str = "",
    new_title: str = "",
    desc: str = "",
    due: str = "",
    card_id: str = "",
) -> str:
    """Update an existing Trello card's title, description, and/or due date.

    Args:
        board_name: Board name ("shopping", "walmart", "project-alpha").
        title: Current card title (fuzzy match). Not needed if card_id provided.
        card_id: Trello card ID for direct lookup.
        list_name: Optional list name to narrow search.
        new_title: New title for the card. Leave empty to keep current title.
        desc: New description. Leave empty to keep current. Use " " (space) to clear.
        due: New due date (ISO format or natural like "2025-03-15"). Leave empty to keep.

    Returns:
        Confirmation of what was changed.

    Ack: Updating Trello card...
    """
    try:
        if not board_name or not board_name.strip():
            return "Error: board_name is required."
        if (not title or not title.strip()) and (not card_id or not card_id.strip()):
            return "Error: provide either title or card_id."
        if not new_title and not desc and not due:
            return "Error: provide at least one field to update (new_title, desc, or due)."

        from trello_client import update_card

        result = update_card(
            board_name.strip().lower(),
            title.strip() if title else "",
            list_name.strip() if list_name else "",
            new_name=new_title.strip() if new_title else "",
            desc=desc if desc else "",
            due=due.strip() if due else "",
            card_id=card_id.strip() if card_id else "",
        )

        if not result.get("changed"):
            return f"No changes made to card '{title}'."

        changes = []
        if new_title:
            changes.append(f"title → '{new_title.strip()}'")
        if desc:
            changes.append("description updated")
        if due:
            changes.append(f"due → {due.strip()}")

        return (
            f"Updated Trello card: '{result['name']}'\n"
            f"  Changes: {', '.join(changes)}\n"
            f"  URL: {result.get('url', '')}"
        )

    except Exception as e:
        return f"Error in trello_update_card: {str(e)}"


def trello_card_checklist(
    board_name: str,
    title: str = "",
    checklist_name: str = "",
    items: str = "",
    list_name: str = "",
    card_id: str = "",
) -> str:
    """View or set a checklist on a Trello card.

    To VIEW checklists: call with just board_name + title (or card_id).
    To SET a checklist: also provide checklist_name and items (newline-separated).
    Setting replaces any existing checklist with the same name.

    Args:
        board_name: Board name ("shopping", "walmart", "project-alpha").
        title: Card title (fuzzy match). Not needed if card_id provided.
        card_id: Trello card ID for direct lookup.
        checklist_name: Name for the checklist (e.g. "Steps to Reproduce", "Subtasks").
        items: Newline-separated checklist items. If empty, shows existing checklists.
        list_name: Optional list name to narrow search.

    Returns:
        Checklist view or confirmation.

    Ack: Working on Trello checklist...
    """
    try:
        if not board_name or not board_name.strip():
            return "Error: board_name is required."
        if (not title or not title.strip()) and (not card_id or not card_id.strip()):
            return "Error: provide either title or card_id."

        board = board_name.strip().lower()
        card_title = title.strip() if title else ""
        ln = list_name.strip() if list_name else ""
        cid = card_id.strip() if card_id else ""

        # VIEW mode
        if not items or not items.strip():
            from trello_client import get_checklists

            checklists = get_checklists(board, card_title, ln, card_id=cid)
            if not checklists:
                return f"Card '{card_title or cid}' has no checklists."

            lines = [f"Checklists on '{card_title or cid}':"]
            for cl in checklists:
                done_count = sum(1 for i in cl["items"] if i["state"] == "complete")
                lines.append(f"\n  {cl['name']} ({done_count}/{len(cl['items'])})")
                for item in cl["items"]:
                    mark = "x" if item["state"] == "complete" else " "
                    lines.append(f"    [{mark}] {item['name']}")
            return "\n".join(lines)

        # SET mode
        if not checklist_name or not checklist_name.strip():
            return "Error: checklist_name is required when setting items."

        from trello_client import set_checklist

        item_list = [i.strip() for i in items.strip().split("\n") if i.strip()]
        if not item_list:
            return "Error: no valid items provided."

        result = set_checklist(
            board, card_title,
            checklist_name.strip(), item_list, ln, card_id=cid,
        )

        verb = "Replaced" if result["replaced"] else "Created"
        return (
            f"{verb} checklist '{result['name']}' on card '{card_title}'.\n"
            f"  Items: {result['items_count']}"
        )

    except Exception as e:
        return f"Error in trello_card_checklist: {str(e)}"


def trello_add_comment(
    board_name: str,
    title: str = "",
    text: str = "",
    list_name: str = "",
    card_id: str = "",
) -> str:
    """Add a comment to a Trello card.

    Args:
        board_name: Board name ("shopping", "walmart", "project-alpha").
        title: Card title (fuzzy match). Not needed if card_id provided.
        card_id: Trello card ID for direct lookup.
        text: Comment text.
        list_name: Optional list name to narrow search.

    Returns:
        Confirmation.

    Ack: Adding comment to Trello card...
    """
    try:
        if not board_name or not board_name.strip():
            return "Error: board_name is required."
        if (not title or not title.strip()) and (not card_id or not card_id.strip()):
            return "Error: provide either title or card_id."
        if not text or not text.strip():
            return "Error: text is required."

        from trello_client import add_comment

        result = add_comment(
            board_name.strip().lower(),
            title.strip() if title else "",
            text.strip(),
            list_name.strip() if list_name else "",
            card_id=card_id.strip() if card_id else "",
        )

        return (
            f"Comment added to '{result['card_name']}' on Trello.\n"
            f"  Text: {result['text'][:100]}{'...' if len(result['text']) > 100 else ''}"
        )

    except Exception as e:
        return f"Error in trello_add_comment: {str(e)}"


def trello_card_labels(
    board_name: str,
    title: str = "",
    action: str = "list",
    label_name: str = "",
    label_color: str = "sky",
    list_name: str = "",
    card_id: str = "",
) -> str:
    """Manage labels on a Trello card — list, add, or remove.

    Args:
        board_name: Board name ("shopping", "walmart", "project-alpha").
        title: Card title (fuzzy match). Not needed if card_id provided.
        card_id: Trello card ID for direct lookup.
        action: "list" to view labels, "add" to add one, "remove" to remove one.
        label_name: Label name (required for add/remove).
        label_color: Label color for new labels (default "sky"). Trello colors:
            green, yellow, orange, red, purple, blue, sky, lime, pink, black.
        list_name: Optional list name to narrow search.

    Returns:
        Label info or confirmation.

    Ack: Managing Trello card labels...
    """
    try:
        if not board_name or not board_name.strip():
            return "Error: board_name is required."
        if (not title or not title.strip()) and (not card_id or not card_id.strip()):
            return "Error: provide either title or card_id."

        board = board_name.strip().lower()
        card_title = title.strip() if title else ""
        ln = list_name.strip() if list_name else ""
        cid = card_id.strip() if card_id else ""
        act = action.strip().lower() if action else "list"

        if act == "list":
            from trello_client import get_card_details
            card = get_card_details(board, card_title, ln, card_id=cid)
            if not card.get("labels"):
                return f"Card '{card['name']}' has no labels."
            lbl_strs = [f"{lb['name']} ({lb['color']})" if lb.get("name") else lb.get("color", "?") for lb in card["labels"]]
            return f"Labels on '{card['name']}': {', '.join(lbl_strs)}"

        elif act == "add":
            if not label_name or not label_name.strip():
                return "Error: label_name is required for 'add' action."
            from trello_client import add_label_to_card
            result = add_label_to_card(board, card_title, label_name.strip(), label_color.strip(), ln, card_id=cid)
            return f"Label '{result['label']['name']}' added to card '{result['card_name']}'."

        elif act == "remove":
            if not label_name or not label_name.strip():
                return "Error: label_name is required for 'remove' action."
            from trello_client import remove_label_from_card
            result = remove_label_from_card(board, card_title, label_name.strip(), ln, card_id=cid)
            return f"Label '{result['removed_label']}' removed from card '{result['card_name']}'."

        else:
            return f"Error: unknown action '{action}'. Use 'list', 'add', or 'remove'."

    except Exception as e:
        return f"Error in trello_card_labels: {str(e)}"


def trello_board_labels(
    board_name: str,
    action: str = "list",
    label_name: str = "",
    label_color: str = "sky",
    new_name: str = "",
    new_color: str = "",
) -> str:
    """Manage labels at the board level — list, create, update, or delete.

    Args:
        board_name: Board name ("shopping", "walmart", "project-alpha").
        action: "list" to view all labels, "create" to add a new one,
                "update" to rename/recolor, "delete" to remove.
        label_name: Label name (required for create/update/delete).
        label_color: Color for new/updated labels. Trello colors:
            green, yellow, orange, red, purple, blue, sky, lime, pink, black.
        new_name: New name when updating (empty = keep current).
        new_color: New color when updating (empty = keep current).

    Returns:
        Label info or confirmation.

    Ack: Managing Trello board labels...
    """
    try:
        if not board_name or not board_name.strip():
            return "Error: board_name is required."

        board = board_name.strip().lower()
        act = action.strip().lower() if action else "list"

        if act == "list":
            from trello_client import get_labels
            labels = get_labels(board)
            if not labels:
                return f"No labels on board '{board}'."
            lines = [f"Labels on board '{board}':"]
            for lb in labels:
                name = lb["name"] or "(unnamed)"
                lines.append(f"  - {name} ({lb['color']})")
            return "\n".join(lines)

        elif act == "create":
            if not label_name or not label_name.strip():
                return "Error: label_name is required for 'create' action."
            from trello_client import ensure_label
            label = ensure_label(board, label_name.strip(), label_color.strip())
            return f"Label '{label['name']}' ({label['color']}) ready on board '{board}'."

        elif act == "update":
            if not label_name or not label_name.strip():
                return "Error: label_name is required for 'update' action."
            from trello_client import update_label
            result = update_label(board, label_name.strip(), new_name.strip() if new_name else "", new_color.strip() if new_color else "")
            return f"Label updated: '{result['name']}' ({result['color']})."

        elif act == "delete":
            if not label_name or not label_name.strip():
                return "Error: label_name is required for 'delete' action."
            from trello_client import delete_label
            result = delete_label(board, label_name.strip())
            return f"Label '{result['deleted']}' deleted from board '{board}'."

        else:
            return f"Error: unknown action '{action}'. Use 'list', 'create', 'update', or 'delete'."

    except Exception as e:
        return f"Error in trello_board_labels: {str(e)}"


def connect_trello_board(
    board_name: str,
    connected_by: str,
    board_id: str = "",
    account: str = "",
) -> str:
    """Connect a Trello board — register it, scan all lists, create local l-* files, and sync cards.

    If the board is not yet in trello_boards.json, it will be added automatically.
    You need the Trello board ID (from the board URL or Trello settings).

    Account auto-detection uses board name matching (configured in trello_boards.json).
    If the correct account is unclear from context, ask the user which account to use.

    After connecting, every list on the board becomes a local list that the user
    can reference by name (e.g. "add screws to hobby lobby"). Write-through to
    Trello happens automatically on add/remove.

    Args:
        board_name: Short name/key for the board (e.g. "shopping", "walmart", "project-alpha").
            Used as the lookup key in trello_boards.json.
        connected_by: Who is connecting this board (person name).
        board_id: Trello board ID. Required for new boards not yet in trello_boards.json.
            Found in the board URL: https://trello.com/b/{board_id}/...
        account: Which Trello account credentials to use (matches account keys in config).
            If empty, auto-detects based on board name.

    Returns:
        Summary of board registration, lists created, and cards synced.

    Ack: Connecting to Trello board {board_name}...
    """
    try:
        if not board_name or not board_name.strip():
            return "Error: board_name is required."
        if not connected_by or not connected_by.strip():
            return "Error: connected_by is required."

        board = board_name.strip().lower()
        user = connected_by.strip().lower()

        from trello_client import _load_config, _save_config, get_lists, check_board

        config = _load_config()
        boards = config.get("boards", {})
        registered_new = False

        # If board not in config, register it
        if board not in boards:
            if not board_id or not board_id.strip():
                return (
                    f"Board '{board}' is not yet configured. "
                    f"Please provide the Trello board ID (found in the board URL: "
                    f"https://trello.com/b/BOARD_ID/board-name)."
                )

            # Auto-detect account from config
            acct = account.strip().lower() if account else ""
            if not acct:
                board_cfg = boards.get(board, {})
                acct = board_cfg.get("account", config.get("default_account", ""))
                if not acct:
                    # Fall back to first account in config
                    accounts = config.get("accounts", {})
                    acct = next(iter(accounts), "") if accounts else ""

            # Verify the account exists in config
            if acct not in config.get("accounts", {}):
                available = ", ".join(config.get("accounts", {}).keys())
                return (
                    f"Account '{acct}' not found in trello_boards.json. "
                    f"Available accounts: {available}. "
                    f"Specify the correct account name."
                )

            boards[board] = {
                "account": acct,
                "board_id": board_id.strip(),
                "board_name": board_name.strip(),
                "default_list": "",
            }
            config["boards"] = boards
            _save_config(config)
            registered_new = True

        # Verify board access
        try:
            check_board(board)
        except Exception as e:
            return f"Error: Cannot access board '{board}': {str(e)}"

        # Get all lists on the board
        trello_lists = get_lists(board)
        if not trello_lists:
            return f"Board '{board}' registered but has no lists."

        # Check which lists already have local l-* files
        existing = _get_all_lists()
        linked_names = set()
        for lst in existing:
            t = lst.get("trello")
            if t and t.get("board") == board:
                linked_names.add(t["list_name"].strip().lower())

        # Build alias map from board config (list_aliases maps alias → Trello list name)
        # Reverse it to: trello_list_name_lower → [alias1, alias2, ...]
        board_cfg = boards[board]
        alias_map: dict[str, list[str]] = {}
        for alias_key, alias_target in board_cfg.get("list_aliases", {}).items():
            target_lower = alias_target.strip().lower()
            alias_map.setdefault(target_lower, []).append(alias_key.strip().lower())

        created = []
        skipped = []
        synced = []

        for tlist in trello_lists:
            tname = tlist["name"]
            if tname.strip().lower() in linked_names:
                skipped.append(tname)
                continue

            # Look up aliases for this list from board config
            list_aliases = alias_map.get(tname.strip().lower(), [])

            # Create local list linked to this Trello list
            new_list = _create_list(
                name=tname,
                created_by=user,
                trello_board=board,
                trello_list_name=tname,
                aliases=list_aliases if list_aliases else None,
            )
            alias_note = f" (aliases: {', '.join(list_aliases)})" if list_aliases else ""
            created.append(f"{new_list['id']} — {tname}{alias_note}")

            # Sync existing cards from Trello
            sync_result = _sync_from_trello(new_list["id"])
            synced.append(f"  {tname}: {sync_result}")

        lines = []
        if registered_new:
            acct_used = boards[board]["account"]
            lines.append(f"Registered new board '{board}' (account: {acct_used}, id: {board_id.strip()})")
        lines.append(f"Connected to Trello board '{board}':")
        if created:
            lines.append(f"\nCreated {len(created)} local lists:")
            for c in created:
                lines.append(f"  {c}")
        if skipped:
            lines.append(f"\nSkipped {len(skipped)} already-connected lists:")
            for s in skipped:
                lines.append(f"  {s}")
        if synced:
            lines.append(f"\nSync results:")
            for s in synced:
                lines.append(s)
        lines.append(f"\nAll lists on '{board}' are now available by name.")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in connect_trello_board: {str(e)}"


def disconnect_trello_board(
    board_name: str,
) -> str:
    """Disconnect a Trello board — remove local l-* files and the board entry from trello_boards.json.

    This does NOT delete anything on Trello. It removes:
    1. All local l-* list files linked to this board
    2. The board entry from trello_boards.json

    The board can be re-connected later with connect_trello_board.

    Args:
        board_name: Board key (e.g. "shopping", "walmart", "project-alpha").

    Returns:
        Summary of lists and config removed.

    Ack: Disconnecting Trello board {board_name}...
    """
    try:
        if not board_name or not board_name.strip():
            return "Error: board_name is required."

        board = board_name.strip().lower()

        # Remove local l-* files
        existing = _get_all_lists()
        removed = []
        for lst in existing:
            t = lst.get("trello")
            if t and t.get("board") == board:
                _delete_list(lst["id"])
                removed.append(f"{lst['id']} — {lst['name']}")

        # Remove from trello_boards.json
        from trello_client import _load_config, _save_config
        config = _load_config()
        config_removed = False
        if board in config.get("boards", {}):
            del config["boards"][board]
            _save_config(config)
            config_removed = True

        if not removed and not config_removed:
            return f"Board '{board}' not found in config or local lists."

        lines = [f"Disconnected board '{board}':"]
        if removed:
            lines.append(f"  Removed {len(removed)} local lists:")
            for r in removed:
                lines.append(f"    {r}")
        if config_removed:
            lines.append(f"  Removed '{board}' from trello_boards.json")
        lines.append("\nTrello board and cards are untouched.")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in disconnect_trello_board: {str(e)}"


def set_item_tracking(
    list_name: str,
    enabled: bool = True,
) -> str:
    """Enable or disable item history tracking on a Trello-linked list.

    When enabled, each sync records card titles so the agent can suggest
    the right board/list when re-adding items via trello_suggest_list.

    Args:
        list_name: List name (fuzzy match).
        enabled: True to enable tracking, False to disable.

    Returns:
        Confirmation.

    Ack: Updating item tracking...
    """
    try:
        if not list_name or not list_name.strip():
            return "Error: list_name is required."

        from list_store import find_list_by_name, set_track_items

        lst = find_list_by_name(list_name.strip())
        if not lst:
            return f"Error: List '{list_name}' not found."

        return set_track_items(lst["id"], enabled)

    except Exception as e:
        return f"Error in set_item_tracking: {str(e)}"
