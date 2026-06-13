"""Trello item history — Postgres-backed.

Records normalized Trello card titles (board + list + last-seen) so the Lists
tools can suggest where an item usually goes ("sticky item learning"). This is
the DB-backed replacement for the old flat-file ``item_history.py``
(``data/trello_item_history.json``); it persists to ``public.trello_item_history``
and exposes the same public API the Lists app calls.
"""

import re
import logging
from datetime import datetime, timezone

from data_layer.db import get_conn, fetch_all, fetch_one

logger = logging.getLogger(__name__)

# Quantity patterns: leading ("4 light bulbs") or trailing ("head lettuce 1") digits,
# stripped so the same item at different quantities maps to one key.
_LEADING_QTY_RE = re.compile(r"^\d+\s+")
_TRAILING_QTY_RE = re.compile(r"\s+\d+$")


def _normalize_key(title: str) -> str:
    """Normalize a card title to a history key.

    'Head lettuce 1' -> 'head lettuce';  '4 light bulbs' -> 'light bulbs'
    """
    key = title.strip().lower()
    key = _LEADING_QTY_RE.sub("", key)
    key = _TRAILING_QTY_RE.sub("", key)
    return key


def _last_seen_str(value) -> str:
    """Coerce a last_seen value (timestamptz datetime, or str) to an ISO string."""
    if value is None:
        return ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _upsert(rows: list[tuple]) -> None:
    """Upsert (normalized_key, board, list_name, title) tuples with now() last_seen."""
    if not rows:
        return
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        with conn.cursor() as cur:
            for key, board, list_name, title in rows:
                cur.execute(
                    """
                    INSERT INTO trello_item_history
                        (normalized_key, board, list_name, title, last_seen)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (normalized_key) DO UPDATE SET
                        board = EXCLUDED.board,
                        list_name = EXCLUDED.list_name,
                        title = EXCLUDED.title,
                        last_seen = EXCLUDED.last_seen
                    """,
                    (key, board, list_name, title, now),
                )
        conn.commit()


def record_items(board: str, list_name: str, card_titles: list[str]) -> None:
    """Record a batch of card titles as last-seen on board/list (upsert)."""
    rows = []
    for title in card_titles or []:
        key = _normalize_key(title)
        if not key or not any(c.isalnum() for c in key):
            continue
        rows.append((key, board, list_name, title.strip()))
    _upsert(rows)


def record_items_bulk(board: str, cards_by_list: dict[str, list[str]]) -> None:
    """Record cards from multiple lists on a board at once."""
    rows = []
    for list_name, titles in (cards_by_list or {}).items():
        for title in titles:
            key = _normalize_key(title)
            if not key or not any(c.isalnum() for c in key):
                continue
            rows.append((key, board, list_name, title.strip()))
    _upsert(rows)


def suggest_list(query: str, limit: int = 5) -> list[dict]:
    """Find where an item was last seen, ranked by match quality.

    Priority: exact -> query-is-substring -> stored-is-substring -> word overlap.
    Returns up to ``limit`` ``{title, board, list, last_seen, match_type}`` dicts,
    best match first (empty list if nothing matches).
    """
    norm = _normalize_key(query or "")
    if not norm:
        return []

    rows = fetch_all(
        "SELECT normalized_key, board, list_name, title, last_seen "
        "FROM trello_item_history"
    )
    query_words = set(norm.split())
    results = []
    for r in rows:
        key = r["normalized_key"]
        entry = {
            "title": r["title"],
            "board": r["board"],
            "list": r["list_name"],
            "last_seen": _last_seen_str(r.get("last_seen")),
        }
        if key == norm:
            results.append({**entry, "match_type": "exact", "_score": 0})
        elif norm in key:
            results.append({**entry, "match_type": "substring", "_score": 1})
        elif key in norm:
            results.append({**entry, "match_type": "contains", "_score": 2})
        else:
            overlap = query_words & set(key.split())
            if overlap:
                frac = len(overlap) / max(len(query_words), 1)
                results.append({**entry, "match_type": "word_overlap", "_score": 3 - frac})

    # Best first: lower score wins, then prefer rows that have a last_seen.
    results.sort(key=lambda x: (x["_score"], x.get("last_seen", "") == ""))
    for r in results:
        r.pop("_score", None)
    return results[:limit]


def get_all_history() -> dict:
    """Full history keyed by normalized_key: {key: {board, list, title, last_seen}}."""
    rows = fetch_all("SELECT * FROM trello_item_history")
    return {
        r["normalized_key"]: {
            "board": r["board"],
            "list": r["list_name"],
            "title": r["title"],
            "last_seen": _last_seen_str(r.get("last_seen")),
        }
        for r in rows
    }


def get_history_stats() -> dict:
    """Summary stats: total items + per-board counts."""
    row = fetch_one("SELECT COUNT(*) AS cnt FROM trello_item_history")
    total = row["cnt"] if row else 0
    boards = fetch_all(
        "SELECT board, COUNT(*) AS cnt FROM trello_item_history "
        "GROUP BY board ORDER BY cnt DESC"
    )
    return {"total_items": total, "boards": {r["board"]: r["cnt"] for r in boards}}
