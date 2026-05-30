"""Item History Store
===================
Tracks where Trello card titles were last seen (board + list).
Used by the agent to auto-suggest the right board/list when re-adding items.

Data file: data/trello_item_history.json
Format:
    {
        "normalized_title": {
            "board": "walmart",
            "list": "Vegetable Aisle",
            "title": "Original Title Case",
            "last_seen": "2025-06-01T12:00:00"
        },
        ...
    }
"""

import json
import os
import re
from datetime import datetime

from app_platform.time import get_timezone
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_PATH = os.path.join(BASE_DIR, "data", "trello_item_history.json")

# Quantity patterns: leading digits ("4 light bulbs") or trailing digits ("head lettuce 1")
_LEADING_QTY_RE = re.compile(r"^\d+\s+")
_TRAILING_QTY_RE = re.compile(r"\s+\d+$")


def _normalize_key(title: str) -> str:
    """Normalize a card title for use as a history key.

    Strips leading and trailing quantity numbers so the same item with
    different quantities maps to one key:
        'Head lettuce 1' → 'head lettuce'
        '4 light bulbs'  → 'light bulbs'
    """
    key = title.strip().lower()
    key = _LEADING_QTY_RE.sub("", key)
    key = _TRAILING_QTY_RE.sub("", key)
    return key


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load() -> dict:
    if not os.path.exists(HISTORY_PATH):
        return {}
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save(data: dict):
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def record_items(board: str, list_name: str, card_titles: list[str]):
    """Record a batch of card titles as last seen on board/list.

    Called during Trello sync for boards with track_items enabled.

    Args:
        board: Board name (e.g. "walmart").
        list_name: Trello list name (e.g. "Vegetable Aisle").
        card_titles: List of card title strings.
    """
    if not card_titles:
        return

    data = _load()
    now = datetime.now(get_timezone()).isoformat()

    for title in card_titles:
        key = _normalize_key(title)
        if not key or not any(c.isalnum() for c in key):
            continue
        data[key] = {
            "board": board,
            "list": list_name,
            "title": title.strip(),
            "last_seen": now,
        }

    _save(data)


def record_items_bulk(board: str, cards_by_list: dict[str, list[str]]):
    """Record cards from multiple lists at once (single load/save).

    Args:
        board: Board name.
        cards_by_list: {list_name: [card_title, ...], ...}
    """
    data = _load()
    now = datetime.now(get_timezone()).isoformat()

    for list_name, titles in cards_by_list.items():
        for title in titles:
            key = _normalize_key(title)
            if not key or not any(c.isalnum() for c in key):
                continue
            data[key] = {
                "board": board,
                "list": list_name,
                "title": title.strip(),
                "last_seen": now,
            }

    _save(data)


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def suggest_list(query: str, limit: int = 5) -> list[dict]:
    """Find where an item was last seen, ranked by match quality.

    Match strategy (in priority order):
        1. Exact match on normalized title
        2. Query is a substring of a stored title
        3. Stored title is a substring of query
        4. Word overlap (any word in query appears in title or vice versa)

    Args:
        query: Search term (e.g. "lettuce", "dog food", "light bulbs").
        limit: Max results to return.

    Returns:
        List of {title, board, list, last_seen, match_type} dicts,
        best matches first.
    """
    data = _load()
    if not data:
        return []

    norm = _normalize_key(query)
    if not norm:
        return []

    query_words = set(norm.split())
    results = []

    for key, entry in data.items():
        # Priority 1: exact match
        if key == norm:
            results.append({**entry, "match_type": "exact", "_score": 0})
            continue

        # Priority 2: query is substring of stored title
        if norm in key:
            results.append({**entry, "match_type": "substring", "_score": 1})
            continue

        # Priority 3: stored title is substring of query
        if key in norm:
            results.append({**entry, "match_type": "contains", "_score": 2})
            continue

        # Priority 4: word overlap
        title_words = set(key.split())
        overlap = query_words & title_words
        if overlap:
            # Score by fraction of query words that matched (more = better)
            frac = len(overlap) / max(len(query_words), 1)
            results.append({**entry, "match_type": "word_overlap", "_score": 3 - frac})

    # Sort by score (lower = better), then by last_seen (newer = better)
    results.sort(key=lambda r: (r["_score"], r.get("last_seen", "") == ""))

    # Strip internal score
    for r in results:
        r.pop("_score", None)

    return results[:limit]


def get_history_stats() -> dict:
    """Return basic stats about the item history."""
    data = _load()
    boards = set()
    lists = set()
    for entry in data.values():
        boards.add(entry.get("board", ""))
        lists.add(f"{entry.get('board', '')}/{entry.get('list', '')}")

    return {
        "total_items": len(data),
        "boards": len(boards),
        "board_list_pairs": len(lists),
    }
