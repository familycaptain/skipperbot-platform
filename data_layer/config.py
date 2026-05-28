"""Config Key-Value Store — Postgres CRUD
=========================================
Drop-in replacement for misc config JSON files (discord_users, pushover_users,
trello_boards, pm_state, view_context).
"""

import logging

from psycopg2.extras import Json

from data_layer.db import get_conn, fetch_one, execute

logger = logging.getLogger(__name__)


def get_config(key: str) -> dict:
    """Get a config value by key. Returns empty dict if not found."""
    row = fetch_one("SELECT value FROM config WHERE key = %s", (key,))
    return row["value"] if row else {}


def set_config(key: str, value: dict):
    """Set a config value (upsert)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO config (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (key, Json(value)))
        conn.commit()


def delete_config(key: str) -> bool:
    return execute("DELETE FROM config WHERE key = %s", (key,)) > 0
