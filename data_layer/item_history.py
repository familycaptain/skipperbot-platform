"""Trello Item History — Postgres CRUD
======================================
Drop-in replacement for item_history.py's flat-file persistence.
Stores normalized card titles for sticky item learning / list suggestion.
"""

import logging
from datetime import datetime, timezone

from data_layer.db import get_conn, fetch_one, fetch_all, execute

logger = logging.getLogger(__name__)


def record_item(normalized_key: str, board: str, list_name: str, title: str):
    """Record or update a single item in the history."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO trello_item_history (normalized_key, board, list_name, title, last_seen)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (normalized_key) DO UPDATE SET
                    board = EXCLUDED.board,
                    list_name = EXCLUDED.list_name,
                    title = EXCLUDED.title,
                    last_seen = EXCLUDED.last_seen
            """, (
                normalized_key, board, list_name, title,
                datetime.now(timezone.utc).isoformat(),
            ))
        conn.commit()


def record_items_bulk(items: list[dict]):
    """Bulk record items. Each dict: {normalized_key, board, list_name, title}."""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        with conn.cursor() as cur:
            for item in items:
                cur.execute("""
                    INSERT INTO trello_item_history (normalized_key, board, list_name, title, last_seen)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (normalized_key) DO UPDATE SET
                        board = EXCLUDED.board,
                        list_name = EXCLUDED.list_name,
                        title = EXCLUDED.title,
                        last_seen = EXCLUDED.last_seen
                """, (
                    item["normalized_key"], item["board"],
                    item["list_name"], item["title"], now,
                ))
        conn.commit()


def get_all_history() -> dict:
    """Get the full history as a dict keyed by normalized_key."""
    rows = fetch_all("SELECT * FROM trello_item_history")
    return {
        r["normalized_key"]: {
            "board": r["board"],
            "list": r["list_name"],
            "title": r["title"],
            "last_seen": r["last_seen"].isoformat() if r.get("last_seen") else "",
        }
        for r in rows
    }


def suggest_list(query: str) -> dict | None:
    """Find the best matching item and return its board/list.

    Match priority: exact → substring → word overlap.
    """
    normalized = query.strip().lower()
    if not normalized:
        return None

    all_items = fetch_all("SELECT * FROM trello_item_history")

    # Pass 1: exact match
    for r in all_items:
        if r["normalized_key"] == normalized:
            return {"board": r["board"], "list": r["list_name"], "title": r["title"]}

    # Pass 2: substring match
    matches = []
    for r in all_items:
        if normalized in r["normalized_key"] or r["normalized_key"] in normalized:
            matches.append(r)
    if len(matches) == 1:
        r = matches[0]
        return {"board": r["board"], "list": r["list_name"], "title": r["title"]}

    # Pass 3: word overlap (ranked by overlap count)
    query_words = set(normalized.split())
    scored = []
    for r in all_items:
        item_words = set(r["normalized_key"].split())
        overlap = len(query_words & item_words)
        if overlap > 0:
            scored.append((overlap, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    if scored:
        r = scored[0][1]
        return {"board": r["board"], "list": r["list_name"], "title": r["title"]}

    return None


def get_history_stats() -> dict:
    """Return summary stats about the item history."""
    row = fetch_one("SELECT COUNT(*) AS cnt FROM trello_item_history")
    total = row["cnt"] if row else 0

    boards = fetch_all(
        "SELECT board, COUNT(*) AS cnt FROM trello_item_history GROUP BY board ORDER BY cnt DESC"
    )
    return {
        "total_items": total,
        "boards": {r["board"]: r["cnt"] for r in boards},
    }
