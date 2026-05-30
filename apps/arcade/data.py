"""Arcade — data layer (high-score board).

Schema-scoped CRUD for ``app_arcade.high_scores``.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from app_platform.db import (
    execute_in_schema,
    fetch_all_in_schema,
    scoped_conn,
)
from app_platform.time import utcnow

logger = logging.getLogger(__name__)

SCHEMA = "app_arcade"

VALID_GAMES = {"wardenfall", "aeldrift", "spinhazard"}

_SCORE_HINT = (
    "Focus on: which game was played, who played it, and the score. "
    "High scores answer 'what's the arcade leaderboard / my best run?'."
)

BACKFILL_ENTITIES = [
    {
        "entity_type": "high_score",
        "list_fn": lambda: top_scores(limit=1000),
        "context_hint": _SCORE_HINT,
    },
]


def _new_id() -> str:
    return f"hs-{os.urandom(4).hex()}"


def save_score(game: str, player: str, score: int) -> dict:
    """Insert a high-score row. Returns the saved record."""
    game = (game or "").strip().lower()
    if game not in VALID_GAMES:
        raise ValueError(f"unknown game '{game}'")
    rec = {
        "id": _new_id(),
        "game": game,
        "player": (player or "").strip().lower(),
        "score": max(0, int(score)),
        "created_at": utcnow(),
    }
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO high_scores (id, game, player, score, created_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (rec["id"], rec["game"], rec["player"], rec["score"], rec["created_at"]),
            )
        conn.commit()
    # Best-effort memory digest so chat can recall notable runs.
    try:
        from app_platform.memory import digest_record
        digest_record(app_id="arcade", entity_type="high_score", entity_id=rec["id"],
                      summary=f"{rec['player'] or 'someone'} scored {rec['score']} on {rec['game']}",
                      by=rec["player"])
    except Exception:
        pass
    return _row({**rec, "created_at": rec["created_at"]})


def top_scores(game: str = "", limit: int = 10) -> list[dict]:
    """Top scores overall or for one game, highest first."""
    limit = max(1, min(int(limit), 100))
    if game:
        rows = fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM high_scores WHERE game = %s ORDER BY score DESC, created_at ASC LIMIT %s",
            ((game or "").strip().lower(), limit),
        )
    else:
        rows = fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM high_scores ORDER BY score DESC, created_at ASC LIMIT %s",
            (limit,),
        )
    return [_row(r) for r in rows]


def _row(r: dict) -> dict:
    ca = r.get("created_at")
    return {
        "id": r["id"],
        "game": r["game"],
        "player": r.get("player") or "",
        "score": r.get("score", 0),
        "created_at": ca.isoformat() if hasattr(ca, "isoformat") else (ca or ""),
    }
