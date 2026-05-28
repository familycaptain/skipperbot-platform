"""DEPRECATED — Moved to apps/email/data.py (app package).
This file is no longer imported. Safe to delete.

Email Data Layer — CRUD for email accounts, rules, and processing log."""

import uuid
import logging
from psycopg2.extras import Json
from data_layer.db import get_conn, fetch_one, fetch_all, execute, execute_returning
from data_layer.links import ensure_edge

logger = logging.getLogger(__name__)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _row(r: dict | None) -> dict | None:
    if not r:
        return None
    out = dict(r)
    # Serialize datetimes to ISO strings for JSON responses
    for k in ("created_at", "updated_at", "last_synced_at", "received_at"):
        if k in out and out[k] is not None:
            out[k] = out[k].isoformat()
    return out


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def create_account(user_id: str, email_address: str, display_name: str = "",
                   credentials: dict = None, scopes: list = None) -> dict:
    row = execute_returning(
        """INSERT INTO email_accounts (id, user_id, email_address, display_name, credentials, scopes)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (_new_id("ea"), user_id, email_address, display_name or "",
         Json(credentials or {}), scopes or []),
    )
    return _row(row)


def get_account(account_id: str) -> dict | None:
    row = fetch_one("SELECT * FROM email_accounts WHERE id = %s", (account_id,))
    return _row(row)


def list_accounts(user_id: str) -> list[dict]:
    return [_row(r) for r in fetch_all(
        "SELECT * FROM email_accounts WHERE user_id = %s ORDER BY created_at", (user_id,)
    )]


def update_account(account_id: str, **kwargs) -> dict | None:
    allowed = {"display_name", "active", "credentials", "scopes", "last_synced_at", "history_id"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_account(account_id)
    sets = []
    params = []
    for k, v in updates.items():
        if k == "credentials":
            sets.append(f"{k} = %s")
            params.append(Json(v))
        else:
            sets.append(f"{k} = %s")
            params.append(v)
    params.append(account_id)
    row = execute_returning(
        f"UPDATE email_accounts SET {', '.join(sets)} WHERE id = %s RETURNING *",
        tuple(params),
    )
    return _row(row)


def delete_account(account_id: str) -> bool:
    n = execute("DELETE FROM email_accounts WHERE id = %s", (account_id,))
    return n > 0


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def create_rule(account_id: str, name: str, conditions: dict, actions: dict,
                priority: int = 100, stop_processing: bool = True) -> dict:
    rule_id = _new_id("er")
    row = execute_returning(
        """INSERT INTO email_rules (id, account_id, name, conditions, actions, priority, stop_processing)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (rule_id, account_id, name, Json(conditions), Json(actions), priority, stop_processing),
    )
    ensure_edge(rule_id, account_id, "child_of", "parent_of")
    return _row(row)


def get_rule(rule_id: str) -> dict | None:
    row = fetch_one("SELECT * FROM email_rules WHERE id = %s", (rule_id,))
    return _row(row)


def list_rules(account_id: str) -> list[dict]:
    return [_row(r) for r in fetch_all(
        "SELECT * FROM email_rules WHERE account_id = %s ORDER BY priority, created_at",
        (account_id,),
    )]


def update_rule(rule_id: str, **kwargs) -> dict | None:
    allowed = {"name", "conditions", "actions", "priority", "active", "stop_processing"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_rule(rule_id)
    sets = []
    params = []
    for k, v in updates.items():
        if k in ("conditions", "actions"):
            sets.append(f"{k} = %s")
            params.append(Json(v))
        else:
            sets.append(f"{k} = %s")
            params.append(v)
    sets.append("updated_at = now()")
    params.append(rule_id)
    row = execute_returning(
        f"UPDATE email_rules SET {', '.join(sets)} WHERE id = %s RETURNING *",
        tuple(params),
    )
    return _row(row)


def delete_rule(rule_id: str) -> bool:
    n = execute("DELETE FROM email_rules WHERE id = %s", (rule_id,))
    return n > 0


def reorder_rules(rule_ids_in_order: list[str]) -> int:
    """Bulk update priorities based on list order. Returns count updated."""
    updated = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for i, rule_id in enumerate(rule_ids_in_order):
                cur.execute(
                    "UPDATE email_rules SET priority = %s, updated_at = now() WHERE id = %s",
                    (i * 10, rule_id),
                )
                updated += cur.rowcount
        conn.commit()
    return updated


def increment_match_count(rule_id: str):
    execute("UPDATE email_rules SET match_count = match_count + 1 WHERE id = %s", (rule_id,))


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

def log_processed(account_id: str, gmail_msg_id: str, thread_id: str = "",
                  subject: str = "", sender: str = "", received_at=None,
                  rule_id: str = None, actions_taken: list = None) -> dict | None:
    """Log a processed email. Returns None if gmail_msg_id already exists (dedup)."""
    try:
        row = execute_returning(
            """INSERT INTO email_log (id, account_id, gmail_msg_id, thread_id, subject, sender,
                                     received_at, rule_id, actions_taken)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (gmail_msg_id) DO NOTHING
               RETURNING *""",
            (_new_id("el"), account_id, gmail_msg_id, thread_id or "",
             subject or "", sender or "", received_at, rule_id,
             Json(actions_taken or [])),
        )
        if row:
            ensure_edge(row["id"], account_id, "child_of", "parent_of")
            if rule_id:
                ensure_edge(row["id"], rule_id, "triggered_by", "triggered")
        return _row(row)
    except Exception as e:
        logger.error("EMAIL_DL: Failed to log message %s: %s", gmail_msg_id, e)
        return None


def list_log(account_id: str = None, user_id: str = None, limit: int = 50, offset: int = 0) -> list[dict]:
    if account_id:
        return [_row(r) for r in fetch_all(
            """SELECT l.*, r.name as rule_name
               FROM email_log l LEFT JOIN email_rules r ON l.rule_id = r.id
               WHERE l.account_id = %s ORDER BY l.received_at DESC LIMIT %s OFFSET %s""",
            (account_id, limit, offset),
        )]
    elif user_id:
        return [_row(r) for r in fetch_all(
            """SELECT l.*, r.name as rule_name, a.email_address
               FROM email_log l
               JOIN email_accounts a ON l.account_id = a.id
               LEFT JOIN email_rules r ON l.rule_id = r.id
               WHERE a.user_id = %s ORDER BY l.received_at DESC LIMIT %s OFFSET %s""",
            (user_id, limit, offset),
        )]
    return []


def was_processed(gmail_msg_id: str) -> bool:
    row = fetch_one("SELECT 1 FROM email_log WHERE gmail_msg_id = %s", (gmail_msg_id,))
    return row is not None
