"""Trello API Client
==================
Multi-account Trello REST client. Supports multiple credential sets
(e.g., a primary family account + a secondary project account).

Board configurations are stored in trello_boards.json.
Credentials are read from environment variables specified per-account.
"""

import json
import os
import re
from datetime import datetime, time as dtime
from typing import Any, Optional

import logging

import httpx
from dotenv import load_dotenv

from config import logger
from app_platform.time import get_timezone


def _normalize_due_date(due: str) -> str:
    """Normalize a due date to end-of-day (23:59:59) in the local timezone.

    Trello interprets bare dates as midnight UTC, which shows as 6 PM the
    previous day in Central time.  This ensures the due date lands on the
    correct calendar day at 11:59:59 PM local time.
    """
    due = due.strip()
    if not due:
        return due

    # Already has a full datetime with timezone — leave as-is
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}.*[+-]\d", due):
        return due

    # Extract just the date portion
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", due)
    if not m:
        return due  # unparseable, pass through

    date_str = m.group(1)
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        eod = datetime.combine(d.date(), dtime(23, 59, 59), tzinfo=get_timezone())
        return eod.isoformat()
    except ValueError:
        return due

# Suppress noisy httpx/httpcore debug logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

load_dotenv()

API_BASE = "https://api.trello.com/1"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOARDS_CONFIG_PATH = os.path.join(BASE_DIR, "data", "trello_boards.json")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    """Load trello_boards.json config."""
    if not os.path.exists(BOARDS_CONFIG_PATH):
        return {"accounts": {}, "boards": {}}
    try:
        with open(BOARDS_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"accounts": {}, "boards": {}}


def _save_config(config: dict):
    """Save trello_boards.json config."""
    with open(BOARDS_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.flush()
        os.fsync(f.fileno())


def _get_account_creds(account_name: str) -> tuple[str, str]:
    """Get (key, token) for a named account from env vars.

    Returns:
        (api_key, api_token) tuple.

    Raises:
        ValueError if credentials not found.
    """
    config = _load_config()
    account = config.get("accounts", {}).get(account_name)
    if not account:
        raise ValueError(f"Trello account '{account_name}' not found in config.")

    key_env = account.get("key_env", "")
    token_env = account.get("token_env", "")

    key = os.getenv(key_env, "")
    token = os.getenv(token_env, "")

    if not key or not token:
        raise ValueError(
            f"Trello credentials missing for account '{account_name}'. "
            f"Expected env vars: {key_env}, {token_env}"
        )
    return (key, token)


def get_board_config(board_name: str) -> dict:
    """Get config for a named board.

    Returns:
        Board config dict with account, board_id, etc.

    Raises:
        ValueError if board not configured.
    """
    config = _load_config()
    board = config.get("boards", {}).get(board_name.lower())
    if not board:
        available = list(config.get("boards", {}).keys())
        raise ValueError(
            f"Board '{board_name}' not configured. "
            f"Available: {', '.join(available) if available else '(none)'}"
        )
    return board


def list_configured_boards() -> list[dict]:
    """List all configured boards with their settings."""
    config = _load_config()
    result = []
    for name, board in config.get("boards", {}).items():
        result.append({
            "name": name,
            "account": board.get("account"),
            "board_id": board.get("board_id"),
            "default_list": board.get("default_list", ""),
        })
    return result


# ---------------------------------------------------------------------------
# Low-level API
# ---------------------------------------------------------------------------

def _request(
    method: str,
    path: str,
    account_name: str,
    params: dict | None = None,
    body: dict | None = None,
) -> Any:
    """Make a Trello API request.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE).
        path: API path (e.g., /boards/{id}/lists).
        account_name: Which credential set to use.
        params: Query parameters (merged with auth).
        body: JSON body for POST/PUT.

    Returns:
        Parsed JSON response.

    Raises:
        httpx.HTTPStatusError on API errors.
    """
    key, token = _get_account_creds(account_name)

    all_params = {"key": key, "token": token}
    if params:
        all_params.update(params)

    url = f"{API_BASE}{path}"

    with httpx.Client(timeout=30.0) as client:
        if method.upper() in ("POST", "PUT") and body:
            resp = client.request(
                method, url, params=all_params, json=body
            )
        else:
            resp = client.request(method, url, params=all_params)

        resp.raise_for_status()

        ct = resp.headers.get("content-type", "")
        if "application/json" in ct:
            return resp.json()
        return resp.text


def _board_request(
    method: str,
    path: str,
    board_name: str,
    params: dict | None = None,
    body: dict | None = None,
) -> Any:
    """Make a Trello API request using a named board's account."""
    board_cfg = get_board_config(board_name)
    return _request(method, path, board_cfg["account"], params, body)


# ---------------------------------------------------------------------------
# Board operations
# ---------------------------------------------------------------------------

def check_board(board_name: str) -> dict:
    """Verify board access and return board info."""
    board_cfg = get_board_config(board_name)
    board_id = board_cfg["board_id"]
    result = _board_request("GET", f"/boards/{board_id}", board_name, {"fields": "name,url"})
    return {"ok": True, "board": result}


# ---------------------------------------------------------------------------
# List operations
# ---------------------------------------------------------------------------

def get_lists(board_name: str) -> list[dict]:
    """Get all open lists on a board.

    Returns:
        List of {id, name} dicts.
    """
    board_cfg = get_board_config(board_name)
    board_id = board_cfg["board_id"]
    lists = _board_request("GET", f"/boards/{board_id}/lists", board_name, {"fields": "name,pos"})
    return [{"id": l["id"], "name": l["name"], "pos": l.get("pos", 0)} for l in lists]


def find_list_by_name(board_name: str, list_name: str) -> dict:
    """Find a list by name (exact then substring match).

    Returns:
        {id, name} dict.

    Raises:
        ValueError if not found.
    """
    lists = get_lists(board_name)
    norm = list_name.strip().lower()

    # Exact match
    for l in lists:
        if l["name"].strip().lower() == norm:
            return l

    # Substring match
    for l in lists:
        if norm in l["name"].strip().lower():
            return l

    available = [l["name"] for l in lists]
    raise ValueError(f"List '{list_name}' not found on {board_name}. Available: {', '.join(available)}")


def ensure_list(board_name: str, list_name: str, pos: str = "bottom") -> dict:
    """Get or create a list on a board.

    Returns:
        {id, name} dict.
    """
    try:
        return find_list_by_name(board_name, list_name)
    except ValueError:
        pass

    board_cfg = get_board_config(board_name)
    board_id = board_cfg["board_id"]
    created = _board_request(
        "POST", "/lists", board_name,
        {"idBoard": board_id, "name": list_name, "pos": pos}
    )
    return {"id": created["id"], "name": created["name"]}


# ---------------------------------------------------------------------------
# Card operations
# ---------------------------------------------------------------------------

def get_cards(board_name: str, list_name: str) -> list[dict]:
    """Get all open cards in a list.

    Returns:
        List of {id, name, desc, pos, labels, due, closed} dicts.
    """
    lst = find_list_by_name(board_name, list_name)
    cards = _board_request(
        "GET", f"/lists/{lst['id']}/cards", board_name,
        {"fields": "name,desc,pos,labels,due,closed,idList,dateLastActivity"}
    )
    return [
        {
            "id": c["id"],
            "name": c["name"],
            "desc": c.get("desc", ""),
            "pos": c.get("pos", 0),
            "labels": [lb.get("name", "") for lb in c.get("labels", [])],
            "due": c.get("due"),
            "closed": c.get("closed", False),
            "dateLastActivity": c.get("dateLastActivity"),
        }
        for c in cards
    ]


def get_all_cards_on_board(board_name: str) -> list[dict]:
    """Get all open cards across all lists on a board.

    Uses single /boards/{id}/cards call (1 API request) instead of
    fetching per-list (N+1 requests). Resolves list names via a
    separate get_lists call.

    Returns:
        List of {id, name, list_id, list_name, ...} dicts.
    """
    board_cfg = get_board_config(board_name)
    board_id = board_cfg["board_id"]

    # Single API call for all cards on the board
    cards = _board_request(
        "GET", f"/boards/{board_id}/cards", board_name,
        {"fields": "name,desc,pos,labels,due,closed,idList,dateLastActivity,badges"}
    )

    # Build list_id -> list_name map
    lists = get_lists(board_name)
    list_map = {l["id"]: l["name"] for l in lists}

    return [
        {
            "id": c["id"],
            "name": c["name"],
            "desc": c.get("desc", ""),
            "pos": c.get("pos", 0),
            "labels": [lb.get("name", "") for lb in c.get("labels", [])],
            "due": c.get("due"),
            "closed": c.get("closed", False),
            "list_id": c.get("idList", ""),
            "list_name": list_map.get(c.get("idList", ""), "(unknown)"),
            "dateLastActivity": c.get("dateLastActivity"),
            "check_total": c.get("badges", {}).get("checkItems", 0),
            "check_done": c.get("badges", {}).get("checkItemsChecked", 0),
        }
        for c in cards
    ]


def _find_card(board_name: str, title: str, list_name: str = "", card_id: str = "") -> dict:
    """Find a card by ID or title (exact then substring match).

    Args:
        board_name: Board to search.
        title: Card title to find.
        list_name: Optional list to narrow search.
        card_id: Optional Trello card ID for direct lookup (skips title matching).

    Returns:
        Card dict with list_name added.

    Raises:
        ValueError if not found or ambiguous.
    """
    # Direct ID lookup — single API call, no fuzzy matching needed
    if card_id and card_id.strip():
        account = get_board_config(board_name)["account"]
        try:
            c = _request(
                "GET", f"/cards/{card_id.strip()}", account,
                {"fields": "name,desc,pos,labels,due,closed,idList,dateLastActivity"}
            )
            lists = get_lists(board_name)
            list_map = {l["id"]: l["name"] for l in lists}
            return {
                "id": c["id"],
                "name": c["name"],
                "desc": c.get("desc", ""),
                "pos": c.get("pos", 0),
                "labels": [lb.get("name", "") for lb in c.get("labels", [])],
                "due": c.get("due"),
                "closed": c.get("closed", False),
                "list_id": c.get("idList", ""),
                "list_name": list_map.get(c.get("idList", ""), "(unknown)"),
                "dateLastActivity": c.get("dateLastActivity"),
            }
        except Exception as e:
            raise ValueError(f"Card not found by ID '{card_id}': {e}")

    norm = title.strip().lower()

    if list_name:
        cards = get_cards(board_name, list_name)
        for c in cards:
            c["list_name"] = list_name
    else:
        cards = get_all_cards_on_board(board_name)

    # Exact match
    exact = [c for c in cards if c["name"].strip().lower() == norm]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        names = [f"{c['name']} (list: {c.get('list_name', '?')})" for c in exact[:5]]
        raise ValueError(f"Ambiguous card title '{title}'. Matches:\n" + "\n".join(names))

    # Substring match
    contains = [c for c in cards if norm in c["name"].strip().lower()]
    if len(contains) == 1:
        return contains[0]
    if len(contains) > 1:
        names = [f"{c['name']} (list: {c.get('list_name', '?')})" for c in contains[:5]]
        raise ValueError(f"Ambiguous card title '{title}'. Matches:\n" + "\n".join(names))

    # Include available card names in error for debugging
    available = [c["name"] for c in cards[:10]]
    suffix = f" Available cards: {available}" if available else " (no cards found on board)"
    raise ValueError(f"Card not found: '{title}' on board '{board_name}'.{suffix}")


def get_card_details(
    board_name: str,
    title: str,
    list_name: str = "",
    card_id: str = "",
) -> dict:
    """Get full card details including checklists, comments, labels, attachments.

    Args:
        board_name: Board name.
        title: Card title (fuzzy match). Ignored if card_id is provided.
        list_name: Optional list to narrow search.
        card_id: Optional Trello card ID for direct lookup.

    Returns:
        Dict with card fields, checklists, comments, attachments.
    """
    card = _find_card(board_name, title, list_name, card_id=card_id)
    account = get_board_config(board_name)["account"]

    # Fetch full card data with nested resources
    full = _request(
        "GET", f"/cards/{card['id']}", account,
        {
            "fields": "name,desc,due,dueComplete,closed,labels,url,idList,dateLastActivity,pos",
            "checklists": "all",
            "checkItemStates": "true",
            "attachments": "true",
            "attachment_fields": "name,url,date",
        }
    )

    # Fetch comments (card actions of type commentCard)
    actions = _request(
        "GET", f"/cards/{card['id']}/actions", account,
        {"filter": "commentCard", "fields": "data,date,memberCreator", "limit": "20"}
    )
    comments = [
        {
            "id": a["id"],
            "text": a.get("data", {}).get("text", ""),
            "date": a.get("date", ""),
            "author": a.get("memberCreator", {}).get("fullName", ""),
        }
        for a in actions
    ]

    # Structure checklists
    checklists = [
        {
            "id": cl["id"],
            "name": cl["name"],
            "items": [
                {"id": ci["id"], "name": ci["name"], "state": ci["state"]}
                for ci in cl.get("checkItems", [])
            ],
        }
        for cl in full.get("checklists", [])
    ]

    # Structure attachments
    attachments = [
        {"id": att["id"], "name": att.get("name", ""), "url": att.get("url", ""), "date": att.get("date", "")}
        for att in full.get("attachments", [])
    ]

    return {
        "id": full["id"],
        "name": full["name"],
        "desc": full.get("desc", ""),
        "due": full.get("due"),
        "dueComplete": full.get("dueComplete", False),
        "closed": full.get("closed", False),
        "url": full.get("url", ""),
        "labels": [{"id": lb["id"], "name": lb.get("name", ""), "color": lb.get("color", "")} for lb in full.get("labels", [])],
        "list_name": card.get("list_name", ""),
        "dateLastActivity": full.get("dateLastActivity", ""),
        "checklists": checklists,
        "comments": comments,
        "attachments": attachments,
    }


def add_card(
    board_name: str,
    list_name: str,
    title: str,
    desc: str = "",
    due: str = "",
    pos: str = "",
) -> dict:
    """Add a card to a list.

    Args:
        pos: Card position — "top", "bottom", or empty (Trello default = bottom).

    Returns:
        Created card {id, name, url, list_name}.
    """
    lst = find_list_by_name(board_name, list_name)
    params = {"idList": lst["id"], "name": title}
    if desc:
        params["desc"] = desc
    if due:
        params["due"] = _normalize_due_date(due)
    if pos:
        params["pos"] = pos

    card = _board_request("POST", "/cards", board_name, params)
    return {
        "id": card["id"],
        "name": card["name"],
        "url": card.get("url", ""),
        "list_name": lst["name"],
    }


def move_card(
    board_name: str,
    title: str,
    to_list: str,
    from_list: str = "",
) -> dict:
    """Move a card to a different list.

    Returns:
        Updated card {id, name, url, from_list, to_list}.
    """
    card = _find_card(board_name, title, from_list)
    to = find_list_by_name(board_name, to_list)

    updated = _board_request(
        "PUT", f"/cards/{card['id']}", board_name,
        {"idList": to["id"]}
    )
    return {
        "id": updated["id"],
        "name": updated["name"],
        "url": updated.get("url", ""),
        "from_list": card.get("list_name", ""),
        "to_list": to["name"],
    }


def archive_card(
    board_name: str,
    title: str,
    list_name: str = "",
) -> dict:
    """Archive (close) a card.

    Returns:
        {id, name, archived: True}.
    """
    card = _find_card(board_name, title, list_name)
    _board_request("PUT", f"/cards/{card['id']}", board_name, {"closed": "true"})
    return {"id": card["id"], "name": card["name"], "archived": True}


def update_card(
    board_name: str,
    title: str,
    list_name: str = "",
    new_name: str = "",
    desc: str = "",
    due: str = "",
    card_id: str = "",
) -> dict:
    """Update card fields.

    Returns:
        Updated card dict.
    """
    card = _find_card(board_name, title, list_name, card_id=card_id)
    params = {}
    if new_name:
        params["name"] = new_name
    if desc is not None and desc != "":
        params["desc"] = desc
    if due:
        params["due"] = _normalize_due_date(due)

    if not params:
        return {"id": card["id"], "name": card["name"], "changed": False}

    updated = _board_request("PUT", f"/cards/{card['id']}", board_name, params)
    return {
        "id": updated["id"],
        "name": updated["name"],
        "url": updated.get("url", ""),
        "changed": True,
    }


def add_comment(
    board_name: str,
    title: str,
    text: str,
    list_name: str = "",
    card_id: str = "",
) -> dict:
    """Add a comment to a card.

    Returns:
        {card_id, comment_id, text}.
    """
    card = _find_card(board_name, title, list_name, card_id=card_id)
    account = get_board_config(board_name)["account"]
    result = _request(
        "POST", f"/cards/{card['id']}/actions/comments", account,
        {"text": text}
    )
    return {
        "card_id": card["id"],
        "card_name": card["name"],
        "comment_id": result["id"],
        "text": text,
    }


def add_label_to_card(
    board_name: str,
    title: str,
    label_name: str,
    label_color: str = "sky",
    list_name: str = "",
    card_id: str = "",
) -> dict:
    """Add a label to a card (creates the label on the board if needed).

    Returns:
        {card_id, card_name, label}.
    """
    card = _find_card(board_name, title, list_name, card_id=card_id)
    label = ensure_label(board_name, label_name, label_color)
    account = get_board_config(board_name)["account"]
    _request("POST", f"/cards/{card['id']}/idLabels", account, {"value": label["id"]})
    return {
        "card_id": card["id"],
        "card_name": card["name"],
        "label": label,
    }


def remove_label_from_card(
    board_name: str,
    title: str,
    label_name: str,
    list_name: str = "",
    card_id: str = "",
) -> dict:
    """Remove a label from a card.

    Returns:
        {card_id, card_name, removed_label}.

    Raises:
        ValueError if label not found on card.
    """
    card = _find_card(board_name, title, list_name, card_id=card_id)
    account = get_board_config(board_name)["account"]

    # Get current labels on the card
    card_data = _request("GET", f"/cards/{card['id']}", account, {"fields": "labels"})
    norm = label_name.strip().lower()
    target = next(
        (lb for lb in card_data.get("labels", []) if lb.get("name", "").strip().lower() == norm),
        None
    )
    if not target:
        available = [lb.get("name", "(unnamed)") for lb in card_data.get("labels", [])]
        raise ValueError(
            f"Label '{label_name}' not found on card '{card['name']}'. "
            f"Current labels: {', '.join(available) if available else '(none)'}"
        )

    _request("DELETE", f"/cards/{card['id']}/idLabels/{target['id']}", account)
    return {
        "card_id": card["id"],
        "card_name": card["name"],
        "removed_label": target["name"],
    }


# ---------------------------------------------------------------------------
# Checklist operations
# ---------------------------------------------------------------------------

def get_checklists(board_name: str, title: str, list_name: str = "", card_id: str = "") -> list[dict]:
    """Get checklists on a card.

    Returns:
        List of {id, name, items: [{id, name, state}]}.
    """
    card = _find_card(board_name, title, list_name, card_id=card_id)
    checklists = _board_request(
        "GET", f"/cards/{card['id']}/checklists", board_name,
        {"fields": "name", "checkItem_fields": "name,state"}
    )
    return [
        {
            "id": cl["id"],
            "name": cl["name"],
            "items": [
                {"id": ci["id"], "name": ci["name"], "state": ci["state"]}
                for ci in cl.get("checkItems", [])
            ],
        }
        for cl in checklists
    ]


def update_check_item(
    board_name: str,
    card_id: str,
    check_item_id: str,
    state: str = "complete",
) -> dict:
    """Update a checklist item's state on a card.

    Args:
        board_name: Board name (for credential lookup).
        card_id: Trello card ID.
        check_item_id: Trello checkItem ID.
        state: 'complete' or 'incomplete'.

    Returns:
        {card_id, check_item_id, name, state}.
    """
    account = get_board_config(board_name)["account"]
    result = _request(
        "PUT", f"/cards/{card_id}/checkItem/{check_item_id}", account,
        {"state": state}
    )
    return {
        "card_id": card_id,
        "check_item_id": check_item_id,
        "name": result.get("name", ""),
        "state": result.get("state", state),
    }


def set_checklist(
    board_name: str,
    title: str,
    checklist_name: str,
    items: list[str],
    list_name: str = "",
    card_id: str = "",
) -> dict:
    """Replace a checklist on a card (delete existing + recreate).

    Returns:
        {card_id, checklist_id, name, items_count, replaced}.
    """
    card = _find_card(board_name, title, list_name, card_id=card_id)
    account = get_board_config(board_name)["account"]

    # Find and delete existing checklist with same name
    checklists = _request("GET", f"/cards/{card['id']}/checklists", account, {"fields": "name"})
    norm = checklist_name.strip().lower()
    existing = next((c for c in checklists if c["name"].strip().lower() == norm), None)
    replaced = False
    if existing:
        _request("DELETE", f"/checklists/{existing['id']}", account)
        replaced = True

    # Create new checklist
    created = _request("POST", "/checklists", account, {"idCard": card["id"], "name": checklist_name})

    # Add items
    for item_text in items:
        _request("POST", f"/checklists/{created['id']}/checkItems", account, {"name": item_text})

    return {
        "card_id": card["id"],
        "checklist_id": created["id"],
        "name": created["name"],
        "items_count": len(items),
        "replaced": replaced,
    }


# ---------------------------------------------------------------------------
# Label operations
# ---------------------------------------------------------------------------

def get_labels(board_name: str) -> list[dict]:
    """Get all labels on a board."""
    board_cfg = get_board_config(board_name)
    board_id = board_cfg["board_id"]
    labels = _board_request("GET", f"/boards/{board_id}/labels", board_name, {"fields": "name,color"})
    return [{"id": l["id"], "name": l["name"], "color": l["color"]} for l in labels]


def ensure_label(board_name: str, name: str, color: str) -> dict:
    """Get or create a label on a board."""
    labels = get_labels(board_name)
    norm = name.strip().lower()
    existing = next((l for l in labels if l["name"].strip().lower() == norm), None)
    if existing:
        return existing

    board_cfg = get_board_config(board_name)
    board_id = board_cfg["board_id"]
    created = _board_request(
        "POST", "/labels", board_name,
        {"idBoard": board_id, "name": name, "color": color}
    )
    return {"id": created["id"], "name": created["name"], "color": created["color"]}


def update_label(board_name: str, label_name: str, new_name: str = "", new_color: str = "") -> dict:
    """Update an existing label on a board (rename and/or recolor).

    Args:
        board_name: Board name.
        label_name: Current label name to find.
        new_name: New name (empty = keep current).
        new_color: New color (empty = keep current).

    Returns:
        Updated {id, name, color}.

    Raises:
        ValueError if label not found.
    """
    labels = get_labels(board_name)
    norm = label_name.strip().lower()
    existing = next((l for l in labels if l["name"].strip().lower() == norm), None)
    if not existing:
        available = [l["name"] or f"(unnamed {l['color']})" for l in labels]
        raise ValueError(
            f"Label '{label_name}' not found on board '{board_name}'. "
            f"Available: {', '.join(available) if available else '(none)'}"
        )
    params = {}
    if new_name:
        params["name"] = new_name
    if new_color:
        params["color"] = new_color
    if not params:
        return existing
    updated = _board_request("PUT", f"/labels/{existing['id']}", board_name, params)
    return {"id": updated["id"], "name": updated["name"], "color": updated["color"]}


def delete_label(board_name: str, label_name: str) -> dict:
    """Delete a label from a board.

    Returns:
        {deleted: label_name}.

    Raises:
        ValueError if label not found.
    """
    labels = get_labels(board_name)
    norm = label_name.strip().lower()
    existing = next((l for l in labels if l["name"].strip().lower() == norm), None)
    if not existing:
        available = [l["name"] or f"(unnamed {l['color']})" for l in labels]
        raise ValueError(
            f"Label '{label_name}' not found on board '{board_name}'. "
            f"Available: {', '.join(available) if available else '(none)'}"
        )
    _board_request("DELETE", f"/labels/{existing['id']}", board_name)
    return {"deleted": existing["name"]}


# ---------------------------------------------------------------------------
# Batch/maintenance operations
# ---------------------------------------------------------------------------

def archive_done_cards(board_name: str, list_name: str = "Done", days: int = 30) -> dict:
    """Archive cards in a list that haven't been active for N days.

    Returns:
        {list_name, days, archived_count, archived: [{id, name}]}.
    """
    from datetime import datetime, timezone

    lst = find_list_by_name(board_name, list_name)
    cards = _board_request(
        "GET", f"/lists/{lst['id']}/cards", board_name,
        {"fields": "name,dateLastActivity"}
    )

    cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
    archived = []
    for c in cards:
        last = c.get("dateLastActivity", "")
        if not last:
            continue
        try:
            ts = datetime.fromisoformat(last.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            continue
        if ts < cutoff:
            _board_request("PUT", f"/cards/{c['id']}", board_name, {"closed": "true"})
            archived.append({"id": c["id"], "name": c["name"]})

    return {
        "list_name": lst["name"],
        "days": days,
        "archived_count": len(archived),
        "archived": archived,
    }
