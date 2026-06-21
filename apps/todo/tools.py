"""Todo — MCP tools.

Three thin tools layered over the per-user default-list config:

- ``get_todo_list(user_id)``                — show what's on the user's to-do.
- ``add_todo_item(user_id, text, top=False)`` — add a line.
- ``mark_todo_done(user_id, item_text)``    — archive an item by fuzzy text match.

Each tool resolves the user's ``default_list_id`` (from
``app_todo.todo_config``) and then operates on it via the Lists app's
data + store layers. If the user has no config / list yet, the tools
bootstrap one via ``apps.todo.store.ensure_default_list``.

Moved here in sub-chunk 5e from ``apps/lists/tools.py``, where they
temporarily lived during the lists packaging in Chunk 4.
"""

from __future__ import annotations

import os
import sys

# Make sure the platform root is on sys.path so this module is importable
# both as ``apps.todo.tools`` and (rarely, for ad-hoc scripts) directly.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app_platform.memory import digest_record
from apps.lists.data import archive_item, get_list
from apps.lists.store import add_item as _add_item
from apps.todo.data import get_config
from apps.todo.store import ensure_default_list, get_todo_items, get_backlog_items


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


def get_backlog_list(user_id: str) -> str:
    """Show the user's BACKLOG list (the to-do app's optional 'someday/later' second list).

    RESERVED REFERENCE: "my backlog" (and an unqualified "backlog") ALWAYS means the speaking
    user's own to-do-app backlog. Use THIS tool for it — do NOT search for a list named
    "backlog", which could match a different family member's list. (Likewise "my to-do" →
    get_todo_list.) Only when the user explicitly names someone else ("Sarah's backlog") would
    you look up that other person's backlog.

    Use when the user says: "show my backlog", "what's on my backlog?", "my backlog items".

    Args:
        user_id: The person whose backlog to show.

    Returns:
        Formatted backlog list, or a note that no backlog is set up.
    """
    try:
        if not user_id or not user_id.strip():
            return "Error: user_id is required."
        uid = user_id.strip().lower()
        result = get_backlog_items(uid)
        if not result:
            return ("You don't have a backlog list set up yet — it's an optional second to-do "
                    "list for 'someday/later' items. Want me to create one?")
        active = [i for i in result["items"] if not i.get("archived")]
        if not active:
            return f"📋 {result['list_name']} is empty."
        lines = [f"📋 {result['list_name']} ({len(active)} item{'s' if len(active) != 1 else ''}):"]
        for idx, item in enumerate(active):
            lines.append(f"  {idx + 1}. {item['text']}")
        lines.append(f"\n  List ID: {result['list_id']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error in get_backlog_list: {str(e)}"


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
            digest_record(
                app_id="todo",
                entity_type="to-do item",
                action="created",
                entity_id=result["id"],
                record={"name": result["text"]},
                by=uid,
            )
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

        archive_item(match["id"])

        # If this item is synced from Trello, archive the Trello card too.
        # Otherwise the next Trello sync will replace local items and bring it back.
        trello_card_id = match.get("trello_card_id", "")
        if trello_card_id:
            try:
                lst = get_list(result["list_id"])
                trello_cfg = lst.get("trello") if lst else None
                board = trello_cfg.get("board") if trello_cfg else None
                if board:
                    from trello_client import _board_request
                    _board_request("PUT", f"/cards/{trello_card_id}", board, {"closed": "true"})
            except Exception:
                pass

        try:
            digest_record(
                app_id="todo",
                entity_type="to-do item",
                action="completed",
                entity_id=match["id"],
                record={"name": match["text"]},
                by=uid,
            )
        except Exception:
            pass
        return f"✓ Done: {match['text']}"

    except Exception as e:
        return f"Error in mark_todo_done: {str(e)}"
