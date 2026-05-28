"""Trello ↔ Task Integration (v2)
=================================
Live-API integration between SkipperBot Tasks and Trello Cards.

When a Project has a trello config:
  project["trello"] = {
      "board": "project-alpha",
      "backlog_list": "Backlog",
      "done_list": "Done",
      "user_lists": {"bob": "Bob TODO", "dave": "Dave TODO"}
  }

Trello-linked tasks store only a skeleton in Skipper:
  task = {id, name, project_id, trello_card_id, trello_linked: True, ...}

All other data (description, checklists, status, due date, labels) is fetched
live from the Trello API on each read. No background sync needed.

Key operations:
  - create_trello_task: create skeleton + card
  - adopt_trello_card: link existing card to new skeleton
  - get_live_project_data: fetch + map all cards for project view
  - move_card_to_list: status/assignment changes
  - archive_trello_card: delete flow
"""

import json
from config import logger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_project_trello_config(project: dict) -> dict | None:
    """Get Trello config for a project, or None if not linked."""
    trello = project.get("trello")
    if not trello or not trello.get("board"):
        return None
    return trello


def get_boards_linked_to_projects() -> set[str]:
    """Return set of board names that are linked to a project.

    Used by list sync to skip these boards.
    """
    from apps.goals.store import _list_entities
    boards = set()
    for project in _list_entities("p-"):
        config = get_project_trello_config(project)
        if config:
            boards.add(config["board"].lower())
    return boards


def derive_status_from_list(list_name: str, config: dict) -> str:
    """Map a Trello list name to a Skipper status.

    Returns: "not_started", "in_progress", or "done"
    """
    backlog = config.get("backlog_list", "Backlog")
    done = config.get("done_list", "Done")
    if list_name.strip().lower() == backlog.strip().lower():
        return "not_started"
    if list_name.strip().lower() == done.strip().lower():
        return "done"
    return "in_progress"


def derive_assignee_from_list(list_name: str, config: dict) -> str | None:
    """Map a Trello list name to an assignee using user_lists config.

    Returns: username string or None if not a user list.
    """
    user_lists = config.get("user_lists", {})
    for user, ulist in user_lists.items():
        if list_name.strip().lower() == ulist.strip().lower():
            return user.lower()
    return None


def get_user_list(username: str, config: dict) -> str | None:
    """Look up a user's Trello list name from config.

    Returns: list name or None if user has no configured list.
    """
    user_lists = config.get("user_lists", {})
    for user, ulist in user_lists.items():
        if user.lower() == username.lower():
            return ulist
    return None


def ensure_user_list(username: str, project: dict) -> str | None:
    """Ensure a user has a TODO list on the linked Trello board.

    If the user already has a list in user_lists config, returns it.
    Otherwise, scans the board for an existing list matching the user's name.
    If none found, creates a new "{DisplayName} TODO" list on the board.
    Updates the project's trello config and saves.

    Returns: list name, or None if project is not Trello-linked.
    """
    config = get_project_trello_config(project)
    if not config:
        return None

    # Already configured?
    existing = get_user_list(username, config)
    if existing:
        return existing

    board_name = config["board"]

    # Look up display name for the list title
    display_name = username.capitalize()
    try:
        from data_layer.users import get_user
        user_data = get_user(username)
        if user_data and user_data.get("display_name"):
            display_name = user_data["display_name"]
    except Exception:
        pass

    # Scan board for existing list matching this user
    try:
        from trello_client import get_lists, ensure_list
        board_lists = get_lists(board_name)
        uname_lower = username.lower()
        display_lower = display_name.lower()

        target_list = None
        for bl in board_lists:
            ln = bl["name"].strip().lower()
            if (ln.startswith(display_lower + " ") or ln.startswith(uname_lower + " ")
                    or ln == display_lower or ln == uname_lower):
                target_list = bl["name"]
                break

        # Create if not found
        if not target_list:
            new_list_name = f"{display_name} TODO"
            result = ensure_list(board_name, new_list_name, pos="top")
            target_list = result["name"]
            logger.info("TRELLO_TASK: Created list '%s' on board '%s' for user '%s'",
                        target_list, board_name, username)

        # Update project config
        from apps.goals.store import _load_entity, _save_entity
        config.setdefault("user_lists", {})[username.lower()] = target_list
        project["trello"] = config
        _save_entity(project)
        logger.info("TRELLO_TASK: Added user_list mapping %s → '%s' on project %s",
                    username, target_list, project["id"])

        return target_list
    except Exception as e:
        logger.warning("TRELLO_TASK: ensure_user_list failed for '%s': %s", username, e)
        return None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def link_project_to_trello(
    project_id: str,
    board_name: str,
    backlog_list: str = "Backlog",
    done_list: str = "Done",
    user_lists_json: str = "",
    linked_by: str = "",
) -> str:
    """Link a Skipper project to a Trello board.

    Args:
        project_id: Skipper project ID (p-xxx).
        board_name: Trello board name.
        backlog_list: List for new/unassigned cards (default: "Backlog").
        done_list: List for completed cards (default: "Done").
        user_lists_json: JSON mapping users to their lists,
                         e.g. '{"bob": "Bob TODO"}'.
        linked_by: Who is performing the link.

    Returns:
        Confirmation or error string.
    """
    from apps.goals.store import _load_entity, _save_entity, _add_history
    from trello_client import get_board_config, get_lists

    project = _load_entity(project_id)
    if not project or not project_id.startswith("p-"):
        return f"Error: Project '{project_id}' not found."

    try:
        get_board_config(board_name)
    except ValueError as e:
        return f"Error: {e}"

    try:
        lists = get_lists(board_name)
        list_names = [l["name"] for l in lists]
    except Exception as e:
        return f"Error checking board lists: {e}"

    # --- Validate backlog list ---
    norm = backlog_list.strip().lower()
    match = next((n for n in list_names if n.strip().lower() == norm), None)
    if not match:
        return (
            f"Error: Backlog list '{backlog_list}' not found on board '{board_name}'. "
            f"Available: {', '.join(list_names)}"
        )
    backlog_list = match

    # --- Validate done list ---
    norm = done_list.strip().lower()
    match = next((n for n in list_names if n.strip().lower() == norm), None)
    if not match:
        return (
            f"Error: Done list '{done_list}' not found on board '{board_name}'. "
            f"Available: {', '.join(list_names)}"
        )
    done_list = match

    # --- Parse and validate user_lists ---
    user_lists = {}
    if user_lists_json and user_lists_json.strip():
        try:
            user_lists = json.loads(user_lists_json.strip())
        except json.JSONDecodeError as e:
            return f"Error: Invalid user_lists_json: {e}"

        for user, ulist in list(user_lists.items()):
            norm = ulist.strip().lower()
            match = next((n for n in list_names if n.strip().lower() == norm), None)
            if not match:
                return (
                    f"Error: User list '{ulist}' for user '{user}' not found. "
                    f"Available: {', '.join(list_names)}"
                )
            user_lists[user] = match  # exact casing
    else:
        # Auto-detect user lists by matching board lists to known users
        try:
            from data_layer.users import get_all_users
            all_users = get_all_users()
            user_names = {u["name"].lower(): u for u in all_users}
            for list_name in list_names:
                ln = list_name.strip().lower()
                # Skip system lists
                if ln in (backlog_list.strip().lower(), done_list.strip().lower()):
                    continue
                # Match patterns: "Name TODO", "Name Tasks", or exact "Name"
                for uname, udata in user_names.items():
                    display = (udata.get("display_name") or uname).lower()
                    if (ln.startswith(display + " ") or ln.startswith(uname + " ")
                            or ln == display or ln == uname):
                        user_lists[uname] = list_name
                        break
            if user_lists:
                logger.info("TRELLO_TASK: Auto-detected user_lists: %s", user_lists)
        except Exception as e:
            logger.warning("TRELLO_TASK: Auto-detect user_lists failed: %s", e)

    project["trello"] = {
        "board": board_name,
        "backlog_list": backlog_list,
        "done_list": done_list,
        "user_lists": user_lists,
    }
    _add_history(project, linked_by or "system",
                 f"Linked to Trello board '{board_name}' "
                 f"(backlog: {backlog_list}, done: {done_list})")
    _save_entity(project)

    logger.info("TRELLO_TASK: Linked project %s to board '%s'", project_id, board_name)

    ul_summary = ""
    if user_lists:
        ul_lines = [f"    {u} → {l}" for u, l in user_lists.items()]
        ul_summary = "\n  User lists:\n" + "\n".join(ul_lines)

    return (
        f"Project '{project['name']}' linked to Trello board '{board_name}'.\n"
        f"  Backlog list: {backlog_list}\n"
        f"  Done list: {done_list}{ul_summary}\n"
        f"  Board lists: {', '.join(list_names)}"
    )


def unlink_project_from_trello(project_id: str, unlinked_by: str = "") -> str:
    """Remove the Trello board link from a project.

    Existing task skeletons are preserved but no longer live-linked.
    """
    from apps.goals.store import _load_entity, _save_entity, _add_history

    project = _load_entity(project_id)
    if not project or not project_id.startswith("p-"):
        return f"Error: Project '{project_id}' not found."

    if not project.get("trello"):
        return f"Project '{project['name']}' is not linked to any Trello board."

    old_board = project["trello"].get("board", "?")
    del project["trello"]
    _add_history(project, unlinked_by or "system",
                 f"Unlinked from Trello board '{old_board}'")
    _save_entity(project)

    logger.info("TRELLO_TASK: Unlinked project %s from board '%s'",
                project_id, old_board)

    return (
        f"Project '{project['name']}' unlinked from Trello board '{old_board}'.\n"
        f"  Existing task skeletons are preserved but no longer live-linked."
    )


# ---------------------------------------------------------------------------
# Create / Adopt
# ---------------------------------------------------------------------------

def create_trello_task(
    project_id: str,
    name: str,
    created_by: str,
    description: str = "",
    checklist_items: list[str] | None = None,
    assigned_to: str = "",
) -> dict | str:
    """Create a Trello-linked task: skeleton in Skipper + card in Trello.

    Returns:
        Task dict on success, or error string.
    """
    from apps.goals.store import (
        _load_entity, _save_entity, _new_id, _now_iso, _add_history,
        _rerank_project, _refresh_project_nag, _get_tasks_for_project,
    )
    from link_registry import create_link
    from auto_memory import log_entity_change
    from trello_client import add_card, set_checklist

    project = _load_entity(project_id)
    if not project or not project_id.startswith("p-"):
        return f"Error: Project '{project_id}' not found."

    config = get_project_trello_config(project)
    if not config:
        return f"Error: Project '{project['name']}' is not linked to a Trello board."

    board = config["board"]
    backlog = config.get("backlog_list", "Backlog")

    # Determine target list: user's TODO list if assigned, else backlog
    target_list = backlog
    effective_assignee = assigned_to.strip().lower() if assigned_to else ""
    if effective_assignee:
        user_list = get_user_list(effective_assignee, config)
        if not user_list:
            user_list = ensure_user_list(effective_assignee, project)
        if user_list:
            target_list = user_list
            logger.info("TRELLO_TASK: Routing new card to '%s' for assignee '%s'",
                        target_list, effective_assignee)

    # Create card in Trello
    try:
        card = add_card(board, target_list, name, desc=description)
        card_id = card["id"]
    except Exception as e:
        return f"Error creating Trello card: {e}"

    # Set checklist if provided
    if checklist_items:
        try:
            set_checklist(board, title="", checklist_name="Checklist",
                          items=checklist_items, card_id=card_id)
        except Exception as e:
            logger.warning("TRELLO_TASK: Failed to set checklist on card %s: %s",
                           card_id, e)

    # Next stack rank
    all_project_tasks = _get_tasks_for_project(project_id)
    max_rank = max((t.get("stack_rank", 0) for t in all_project_tasks), default=0)

    # Create task skeleton
    task = {
        "id": _new_id("t"),
        "name": name,
        "project_id": project_id,
        "parent_task_id": None,
        "subtasks": [],
        "assigned_to": [effective_assignee or created_by],
        "due_date": "",
        "priority": "medium",
        "status": "not_started",
        "stack_rank": max_rank + 1,
        "depends_on": [],
        "trello_card_id": card_id,
        "trello_linked": True,
        "created_at": _now_iso(),
        "created_by": created_by,
        "history": [],
    }
    _add_history(task, created_by, "Trello-linked task created")
    _save_entity(task)

    # Register on project
    project.setdefault("tasks", []).append(task["id"])
    _save_entity(project)
    create_link(project_id, task["id"], relation="has_task", created_by=created_by)
    log_entity_change("created", task["id"], "task",
                      f"{name} (Trello-linked) under {project_id}",
                      by=created_by, related_entities=[project_id])

    _rerank_project(project_id)
    _refresh_project_nag(project_id, reason=f"new trello task {task['id']}")

    logger.info("TRELLO_TASK: Created task %s with card %s on %s/%s",
                task["id"], card_id, board, backlog)

    return task


def adopt_trello_card(
    project_id: str,
    board_name: str,
    created_by: str,
    card_title: str = "",
    card_id: str = "",
) -> dict | str:
    """Adopt an existing Trello card into a Skipper project as a linked task.

    The card is NOT moved — it stays on whatever list it's currently on.
    Skipper simply starts tracking it.

    Returns:
        Task dict on success, or error string.
    """
    from apps.goals.store import (
        _load_entity, _save_entity, _new_id, _now_iso, _add_history,
        _list_entities, _rerank_project, _refresh_project_nag,
        _get_tasks_for_project,
    )
    from link_registry import create_link
    from auto_memory import log_entity_change
    from trello_client import _find_card

    project = _load_entity(project_id)
    if not project or not project_id.startswith("p-"):
        return f"Error: Project '{project_id}' not found."

    config = get_project_trello_config(project)
    if not config:
        return f"Error: Project '{project['name']}' is not linked to a Trello board."

    if not card_title and not card_id:
        return "Error: Provide either card_title or card_id."

    # Find the card
    try:
        card = _find_card(board_name, card_title or "", card_id=card_id or "")
    except Exception as e:
        return f"Error finding card: {e}"

    found_card_id = card["id"]

    # Check not already adopted
    for t in _list_entities("t-"):
        if t.get("trello_card_id") == found_card_id and t.get("project_id") == project_id:
            return f"Error: Card '{card['name']}' is already linked to task {t['id']}."

    list_name = card.get("list_name", "")

    # Next stack rank
    all_project_tasks = _get_tasks_for_project(project_id)
    max_rank = max((t.get("stack_rank", 0) for t in all_project_tasks), default=0)

    # Create task skeleton
    task = {
        "id": _new_id("t"),
        "name": card["name"],
        "project_id": project_id,
        "parent_task_id": None,
        "subtasks": [],
        "assigned_to": [created_by],
        "due_date": "",
        "priority": "medium",
        "status": "not_started",
        "stack_rank": max_rank + 1,
        "depends_on": [],
        "trello_card_id": found_card_id,
        "trello_linked": True,
        "created_at": _now_iso(),
        "created_by": created_by,
        "history": [],
    }

    # Derive assignee from list
    assignee = derive_assignee_from_list(list_name, config)
    if assignee:
        task["assigned_to"] = [assignee]

    _add_history(task, created_by,
                 f"Adopted from Trello card '{card['name']}' (list: {list_name})")
    _save_entity(task)

    # Register on project
    project.setdefault("tasks", []).append(task["id"])
    _save_entity(project)
    create_link(project_id, task["id"], relation="has_task", created_by=created_by)
    log_entity_change("created", task["id"], "task",
                      f"{card['name']} (adopted from Trello) under {project_id}",
                      by=created_by, related_entities=[project_id])

    _rerank_project(project_id)
    _refresh_project_nag(project_id, reason=f"adopted trello card as {task['id']}")

    logger.info("TRELLO_TASK: Adopted card '%s' (%s) as task %s",
                card["name"], found_card_id, task["id"])

    return task


# ---------------------------------------------------------------------------
# Live reads
# ---------------------------------------------------------------------------

def get_live_project_data(project: dict) -> dict | str:
    """Fetch live Trello data for a project's linked tasks.

    Returns dict with:
        cards_by_list: {list_name: [card_dicts...]} ordered by card pos
        list_order: [list_names...] in left-to-right board order
        task_card_map: {trello_card_id: card_dict}
        config: project trello config
    Or error string.
    """
    config = get_project_trello_config(project)
    if not config:
        return "Error: Project not linked to Trello."

    from trello_client import get_all_cards_on_board, get_lists

    board = config["board"]

    try:
        cards = get_all_cards_on_board(board)
        lists = get_lists(board)
    except Exception as e:
        return f"Error fetching Trello data: {e}"

    # Build list order (left-to-right from board)
    list_order = [l["name"] for l in sorted(lists, key=lambda x: x.get("pos", 0))]

    # Build card lookup (open cards only)
    task_card_map = {c["id"]: c for c in cards if not c.get("closed")}

    # Group cards by list, preserving card position within each list
    cards_by_list = {ln: [] for ln in list_order}
    for c in sorted(cards, key=lambda x: x.get("pos", 0)):
        if c.get("closed"):
            continue
        ln = c.get("list_name", "")
        if ln not in cards_by_list:
            cards_by_list[ln] = []
        cards_by_list[ln].append(c)

    return {
        "cards_by_list": cards_by_list,
        "list_order": list_order,
        "task_card_map": task_card_map,
        "config": config,
    }


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def get_card_description(task: dict, project: dict) -> str | None:
    """Fetch the Trello card description for a linked task.

    Returns description string, or None on error.
    """
    config = get_project_trello_config(project)
    if not config:
        return None
    card_id = task.get("trello_card_id")
    if not card_id:
        return None
    try:
        from trello_client import _find_card
        card = _find_card(config["board"], "", card_id=card_id)
        return card.get("desc", "")
    except Exception as e:
        logger.warning("TRELLO_TASK: get_card_description failed for %s: %s", task.get("id"), e)
        return None


def update_card_description(task: dict, project: dict, description: str) -> str:
    """Update the Trello card description for a linked task.

    Returns confirmation or error string.
    """
    config = get_project_trello_config(project)
    if not config:
        return "Error: Project not linked to Trello."
    card_id = task.get("trello_card_id")
    if not card_id:
        return "Error: Task has no linked Trello card."
    try:
        from trello_client import _board_request
        board = config["board"]
        _board_request("PUT", f"/cards/{card_id}", board, {"desc": description})
        logger.info("TRELLO_TASK: Updated description on card %s", card_id)
        return "Card description updated."
    except Exception as e:
        return f"Error updating card description: {e}"


def move_card_to_list(task: dict, project: dict, target_list_name: str) -> str:
    """Move a Trello-linked task's card to a specific list.

    Returns confirmation or error string.
    """
    config = get_project_trello_config(project)
    if not config:
        return "Error: Project not linked to Trello."

    card_id = task.get("trello_card_id")
    if not card_id:
        return "Error: Task has no linked Trello card."

    try:
        from trello_client import find_list_by_name, _board_request

        board = config["board"]
        target = find_list_by_name(board, target_list_name)
        _board_request("PUT", f"/cards/{card_id}", board, {"idList": target["id"]})

        logger.info("TRELLO_TASK: Moved card %s to '%s' on %s",
                     card_id, target_list_name, board)
        return f"Moved card to '{target_list_name}'."
    except Exception as e:
        return f"Error moving card: {e}"


def archive_trello_card(task: dict, project: dict) -> str:
    """Archive a Trello card when its task is deleted.

    Returns confirmation or error string.
    """
    config = get_project_trello_config(project)
    if not config:
        return "Error: Project not linked to Trello."

    card_id = task.get("trello_card_id")
    if not card_id:
        return "Error: Task has no linked Trello card."

    try:
        from trello_client import _board_request

        board = config["board"]
        _board_request("PUT", f"/cards/{card_id}", board, {"closed": "true"})

        logger.info("TRELLO_TASK: Archived card %s on %s for task %s",
                     card_id, board, task["id"])
        return "Archived Trello card."
    except Exception as e:
        return f"Error archiving card: {e}"


# ---------------------------------------------------------------------------
# Compatibility (used by goal_store.py)
# ---------------------------------------------------------------------------

def sync_task_to_trello(task: dict, project: dict) -> tuple[str, str] | None:
    """Create a Trello card for a newly created task.

    When a project is Trello-linked, auto-creates a card on the appropriate
    list: the assignee's TODO list if assigned, otherwise the backlog list.

    Returns:
        Tuple of (card_id, list_name) on success, or None.
    """
    config = get_project_trello_config(project)
    if not config:
        return None

    if task.get("trello_card_id"):
        return task["trello_card_id"], task.get("trello_list", "")

    board = config["board"]
    backlog = config.get("backlog_list", "Backlog")

    # Determine target list: user's TODO list if assigned, else backlog
    target_list = backlog
    assignees = task.get("assigned_to", [])
    if assignees and len(assignees) > 0:
        primary_assignee = assignees[0].strip().lower()
        if primary_assignee:
            user_list = get_user_list(primary_assignee, config)
            if not user_list:
                user_list = ensure_user_list(primary_assignee, project)
            if user_list:
                target_list = user_list
                logger.info("TRELLO_TASK: Routing auto-synced card to '%s' for assignee '%s'",
                            target_list, primary_assignee)

    try:
        from trello_client import add_card
        desc = task.get("notes", "")
        due = task.get("due_date", "")
        card = add_card(board, target_list, task.get("name", "Untitled"), desc=desc, due=due)
        card_id = card["id"]
        logger.info("TRELLO_TASK: Auto-created card %s for task %s on board '%s' list '%s'",
                     card_id, task.get("id"), board, target_list)
        return card_id, target_list
    except Exception as e:
        logger.warning("TRELLO_TASK: Failed to auto-create card for task %s: %s",
                       task.get("id"), e)
        return None


def check_trello_item(
    task_id: str,
    item_number: int,
    checked: bool = True,
) -> str:
    """Check or uncheck a checklist item on a Trello-linked task.

    Args:
        task_id: Task ID or rank reference (resolved by caller).
        item_number: 1-based index matching the ☐/☑ display order.
        checked: True to check, False to uncheck.

    Returns:
        Confirmation string or error.
    """
    from apps.goals.store import _load_entity

    task = _load_entity(task_id)
    if not task:
        return f"Error: Task '{task_id}' not found."

    if not task.get("trello_linked") or not task.get("trello_card_id"):
        return f"Error: Task '{task_id}' is not Trello-linked."

    project = _load_entity(task.get("project_id", ""))
    if not project:
        return f"Error: Project not found for task '{task_id}'."

    config = get_project_trello_config(project)
    if not config:
        return "Error: Project is not Trello-linked."

    card_id = task["trello_card_id"]
    board = config["board"]

    try:
        from trello_client import _request, get_board_config, update_check_item
        account = get_board_config(board)["account"]

        # Fetch all checklists for this card
        raw_cls = _request("GET", f"/cards/{card_id}/checklists", account, {})

        # Flatten all items across checklists in order (matches display)
        all_items = []
        for cl in raw_cls:
            for ci in cl.get("checkItems", []):
                all_items.append({
                    "id": ci["id"],
                    "name": ci["name"],
                    "state": ci.get("state", "incomplete"),
                    "checklist_name": cl.get("name", "Checklist"),
                })

        if not all_items:
            return "Error: This card has no checklist items."

        if item_number < 1 or item_number > len(all_items):
            return f"Error: Item number {item_number} out of range (1–{len(all_items)})."

        target = all_items[item_number - 1]
        new_state = "complete" if checked else "incomplete"

        if target["state"] == new_state:
            mark = "☑" if checked else "☐"
            return f"Already {mark}: {target['name']}"

        result = update_check_item(board, card_id, target["id"], state=new_state)

        mark = "☑" if checked else "☐"
        logger.info("TRELLO_TASK: %s item %d on %s: %s",
                     "checked" if checked else "unchecked",
                     item_number, task_id, target["name"])
        return f"{mark} {target['name']}"

    except Exception as e:
        logger.error("TRELLO_TASK: check_trello_item failed for %s item %d: %s",
                     task_id, item_number, e)
        return f"Error: Failed to update checklist item: {e}"


def sync_task_completion_to_trello(task: dict, project: dict):
    """Move a task's Trello card to the Done list when completed."""
    config = get_project_trello_config(project)
    if not config:
        return

    card_id = task.get("trello_card_id")
    if not card_id:
        return

    done_list_name = config.get("done_list", "Done")
    result = move_card_to_list(task, project, done_list_name)
    if result.startswith("Error"):
        logger.error("TRELLO_TASK: completion sync failed for %s: %s",
                     task["id"], result)


def sync_all_project_tasks() -> str:
    """Legacy: no-op in v2. Background sync replaced by live API reads."""
    return ""
