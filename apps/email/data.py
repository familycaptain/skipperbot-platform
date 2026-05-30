"""Email Data Layer — Schema-aware CRUD for email accounts, rules, and processing log.

Uses the app_email schema via app_platform.db helpers.
"""

import uuid
import logging
from psycopg2.extras import Json
from app_platform.db import (
    fetch_one_in_schema,
    fetch_all_in_schema,
    execute_in_schema,
    execute_returning_in_schema,
    scoped_conn,
)
from data_layer.links import ensure_edge
from app_platform.memory import digest_record

logger = logging.getLogger(__name__)

SCHEMA = "app_email"

_ACCOUNT_HINT = (
    "Focus on: user, email address, display name, and active status."
)
_RULE_HINT = (
    "Focus on: rule name, email account, match conditions (sender/subject/keywords), "
    "actions taken (label/archive/forward/skip), priority order, and active status."
)


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
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO email_accounts (id, user_id, email_address, display_name, credentials, scopes)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (_new_id("ea"), user_id, email_address, display_name or "",
         Json(credentials or {}), scopes or []),
    )
    saved = _row(row)
    if saved:
        safe_record = {k: v for k, v in saved.items() if k != "credentials"}
        digest_record(app_id="email", entity_type="email account", action="created",
                      entity_id=saved["id"], record=safe_record,
                      by=user_id, context_hint=_ACCOUNT_HINT)
    return saved


def get_account(account_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM email_accounts WHERE id = %s", (account_id,))
    return _row(row)


def get_all_accounts() -> list[dict]:
    return [_row(r) for r in fetch_all_in_schema(
        SCHEMA, "SELECT * FROM email_accounts ORDER BY created_at"
    )]


def get_all_rules() -> list[dict]:
    return [_row(r) for r in fetch_all_in_schema(
        SCHEMA, "SELECT * FROM email_rules ORDER BY priority, created_at"
    )]


def list_accounts(user_id: str) -> list[dict]:
    return [_row(r) for r in fetch_all_in_schema(
        SCHEMA,
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
    row = execute_returning_in_schema(
        SCHEMA,
        f"UPDATE email_accounts SET {', '.join(sets)} WHERE id = %s RETURNING *",
        tuple(params),
    )
    return _row(row)


def delete_account(account_id: str) -> bool:
    account = get_account(account_id)
    n = execute_in_schema(SCHEMA, "DELETE FROM email_accounts WHERE id = %s", (account_id,))
    if n > 0 and account:
        safe_record = {k: v for k, v in account.items() if k != "credentials"}
        digest_record(app_id="email", entity_type="email account", action="deleted",
                      entity_id=account_id, record=safe_record, by="")
    return n > 0


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def create_rule(account_id: str, name: str, conditions: dict, actions: dict,
                priority: int = 100, stop_processing: bool = True) -> dict:
    rule_id = _new_id("er")
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO email_rules (id, account_id, name, conditions, actions, priority, stop_processing)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (rule_id, account_id, name, Json(conditions), Json(actions), priority, stop_processing),
    )
    ensure_edge(rule_id, account_id, "child_of", "parent_of")
    saved = _row(row)
    if saved:
        digest_record(app_id="email", entity_type="email rule", action="created",
                      entity_id=rule_id, record=saved, by="", context_hint=_RULE_HINT)
    return saved


def get_rule(rule_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM email_rules WHERE id = %s", (rule_id,))
    return _row(row)


def list_rules(account_id: str) -> list[dict]:
    return [_row(r) for r in fetch_all_in_schema(
        SCHEMA,
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
    row = execute_returning_in_schema(
        SCHEMA,
        f"UPDATE email_rules SET {', '.join(sets)} WHERE id = %s RETURNING *",
        tuple(params),
    )
    saved = _row(row)
    if saved:
        digest_record(app_id="email", entity_type="email rule", action="updated",
                      entity_id=rule_id, record=saved, by="", context_hint=_RULE_HINT)
    return saved


def delete_rule(rule_id: str) -> bool:
    rule = get_rule(rule_id)
    n = execute_in_schema(SCHEMA, "DELETE FROM email_rules WHERE id = %s", (rule_id,))
    if n > 0 and rule:
        digest_record(app_id="email", entity_type="email rule", action="deleted",
                      entity_id=rule_id, record=rule, by="")
    return n > 0


def reorder_rules(rule_ids_in_order: list[str]) -> int:
    """Bulk update priorities based on list order. Returns count updated."""
    updated = 0
    with scoped_conn(SCHEMA) as conn:
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
    execute_in_schema(SCHEMA, "UPDATE email_rules SET match_count = match_count + 1 WHERE id = %s", (rule_id,))


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

def log_processed(account_id: str, gmail_msg_id: str, thread_id: str = "",
                  subject: str = "", sender: str = "", received_at=None,
                  rule_id: str = None, actions_taken: list = None) -> dict | None:
    """Log a processed email. Returns None if gmail_msg_id already exists (dedup)."""
    try:
        row = execute_returning_in_schema(
            SCHEMA,
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
        return [_row(r) for r in fetch_all_in_schema(
            SCHEMA,
            """SELECT l.*, r.name as rule_name
               FROM email_log l LEFT JOIN email_rules r ON l.rule_id = r.id
               WHERE l.account_id = %s ORDER BY l.received_at DESC LIMIT %s OFFSET %s""",
            (account_id, limit, offset),
        )]
    elif user_id:
        return [_row(r) for r in fetch_all_in_schema(
            SCHEMA,
            """SELECT l.*, r.name as rule_name, a.email_address
               FROM email_log l
               JOIN email_accounts a ON l.account_id = a.id
               LEFT JOIN email_rules r ON l.rule_id = r.id
               WHERE a.user_id = %s ORDER BY l.received_at DESC LIMIT %s OFFSET %s""",
            (user_id, limit, offset),
        )]
    return []


def was_processed(gmail_msg_id: str) -> bool:
    row = fetch_one_in_schema(SCHEMA, "SELECT 1 FROM email_log WHERE gmail_msg_id = %s", (gmail_msg_id,))
    return row is not None


def get_unmatched_log_entries(account_id: str) -> list[dict]:
    """Get log entries that had no rule match — candidates for re-evaluation."""
    return [_row(r) for r in fetch_all_in_schema(
        SCHEMA,
        """SELECT * FROM email_log
           WHERE account_id = %s AND rule_id IS NULL
           ORDER BY received_at DESC""",
        (account_id,),
    )]


def update_log_entry_match(log_id: str, rule_id: str, actions_taken: list):
    """Update a log entry with a newly matched rule and actions."""
    execute_in_schema(
        SCHEMA,
        "UPDATE email_log SET rule_id = %s, actions_taken = %s WHERE id = %s",
        (rule_id, Json(actions_taken), log_id),
    )


# ---------------------------------------------------------------------------
# Backfill registry — consumed by backfill_app_memories.py via discover_apps()
# Defining this list has no side effects; list_fn callables are only invoked
# by the CLI backfill script, never on app load.
# ---------------------------------------------------------------------------
def _accounts_without_credentials():
    return [{k: v for k, v in a.items() if k != "credentials"}
            for a in get_all_accounts()]


BACKFILL_ENTITIES = [
    {"entity_type": "email account",
     "list_fn": _accounts_without_credentials,
     "context_hint": _ACCOUNT_HINT},
    {"entity_type": "email rule",
     "list_fn": get_all_rules, "context_hint": _RULE_HINT},
]
