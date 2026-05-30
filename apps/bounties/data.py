"""Bounties App — Schema-aware data layer
==========================================
All tables live in app_bounties schema. No cross-schema foreign keys.
User references stored as plain TEXT columns.
"""

import logging
import uuid
from datetime import datetime, timezone

from app_platform.db import (
    fetch_one_in_schema,
    fetch_all_in_schema,
    execute_in_schema,
    execute_returning_in_schema,
    scoped_conn,
)
from app_platform.memory import digest_record

logger = logging.getLogger(__name__)

SCHEMA = "app_bounties"

_BOUNTY_HINT = (
    "Focus on: bounty title, dollar value, category, status, who submitted it, "
    "who approved/rejected it, and any notes."
)
_TEMPLATE_HINT = (
    "Focus on: template title, dollar value, category, recurrence interval in days, "
    "and whether it is active or paused."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _template_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "description": row.get("description") or "",
        "value_cents": row.get("value_cents", 0),
        "created_by": row.get("created_by") or "",
        "category": row.get("category") or "",
        "recurrence_days": row.get("recurrence_days", 0),
        "is_active": bool(row.get("is_active", True)),
        "next_generate_at": row["next_generate_at"].isoformat() if row.get("next_generate_at") else "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def _bounty_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "template_id": row.get("template_id") or "",
        "title": row.get("title") or "",
        "description": row.get("description") or "",
        "value_cents": row.get("value_cents", 0),
        "category": row.get("category") or "",
        "status": row.get("status") or "open",
        "created_by": row.get("created_by") or "",
        "submitted_by": row.get("submitted_by") or "",
        "submitted_at": row["submitted_at"].isoformat() if row.get("submitted_at") else "",
        "submission_note": row.get("submission_note") or "",
        "reviewed_by": row.get("reviewed_by") or "",
        "reviewed_at": row["reviewed_at"].isoformat() if row.get("reviewed_at") else "",
        "review_note": row.get("review_note") or "",
        "expires_at": row["expires_at"].isoformat() if row.get("expires_at") else "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def _balance_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "user_id": row["user_id"],
        "balance_cents": row.get("balance_cents", 0),
        "lifetime_earned_cents": row.get("lifetime_earned_cents", 0),
        "lifetime_paid_out_cents": row.get("lifetime_paid_out_cents", 0),
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def _txn_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "user_id": row.get("user_id") or "",
        "type": row.get("type") or "",
        "amount_cents": row.get("amount_cents", 0),
        "balance_after_cents": row.get("balance_after_cents", 0),
        "bounty_id": row.get("bounty_id") or "",
        "payment_method": row.get("payment_method") or "",
        "note": row.get("note") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }


def _category_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "icon": row.get("icon") or "",
        "sort_order": row.get("sort_order", 0),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }


# ---------------------------------------------------------------------------
# Bounty Templates
# ---------------------------------------------------------------------------

def create_template(template: dict) -> dict | None:
    tpl_id = template.get("id") or _gen_id("bt")
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO bounty_templates (id, title, description, value_cents,
                                         created_by, category, recurrence_days,
                                         is_active, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (
            tpl_id,
            template.get("title", ""),
            template.get("description", ""),
            template.get("value_cents", 0),
            template.get("created_by", ""),
            template.get("category", ""),
            template.get("recurrence_days", 7),
            template.get("is_active", True),
            template.get("created_at", _now()),
            template.get("updated_at", _now()),
        ),
    )
    result = _template_row(row) if row else None
    if result:
        digest_record(app_id="bounties", entity_type="bounty template", action="created",
                      entity_id=result["id"], record=result,
                      by=template.get("created_by", ""), context_hint=_TEMPLATE_HINT)
    return result


def get_template(tpl_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM bounty_templates WHERE id = %s", (tpl_id,))
    return _template_row(row) if row else None


def get_all_templates(active_only: bool = True) -> list[dict]:
    if active_only:
        rows = fetch_all_in_schema(SCHEMA, "SELECT * FROM bounty_templates WHERE is_active = TRUE ORDER BY title")
    else:
        rows = fetch_all_in_schema(SCHEMA, "SELECT * FROM bounty_templates ORDER BY title")
    return [_template_row(r) for r in rows]


def update_template(tpl_id: str, updates: dict) -> bool:
    allowed = {"title", "description", "value_cents", "category", "recurrence_days", "is_active", "next_generate_at"}
    sets, vals = [], []
    for key, val in updates.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        vals.append(val)
    if not sets:
        return False
    sets.append("updated_at = %s")
    vals.append(_now())
    vals.append(tpl_id)
    return execute_in_schema(
        SCHEMA, f"UPDATE bounty_templates SET {', '.join(sets)} WHERE id = %s", tuple(vals)
    ) > 0


def delete_template(tpl_id: str, by: str = "") -> bool:
    tpl = get_template(tpl_id)
    ok = execute_in_schema(SCHEMA, "DELETE FROM bounty_templates WHERE id = %s", (tpl_id,)) > 0
    if ok and tpl:
        digest_record(app_id="bounties", entity_type="bounty template", action="deleted",
                      entity_id=tpl_id, record=tpl, by=by)
    return ok


# ---------------------------------------------------------------------------
# Bounties
# ---------------------------------------------------------------------------

def create_bounty(bounty: dict) -> dict | None:
    bnt_id = bounty.get("id") or _gen_id("bnt")
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO bounties (id, template_id, title, description, value_cents,
                                  category, status, created_by, expires_at,
                                  created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (
            bnt_id,
            bounty.get("template_id") or None,
            bounty.get("title", ""),
            bounty.get("description", ""),
            bounty.get("value_cents", 0),
            bounty.get("category", ""),
            bounty.get("status", "open"),
            bounty.get("created_by", ""),
            bounty.get("expires_at") or None,
            bounty.get("created_at", _now()),
            bounty.get("updated_at", _now()),
        ),
    )
    result = _bounty_row(row) if row else None
    if result:
        digest_record(app_id="bounties", entity_type="bounty", action="created",
                      entity_id=result["id"], record=result,
                      by=bounty.get("created_by", ""), context_hint=_BOUNTY_HINT)
    return result


def get_bounty(bounty_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM bounties WHERE id = %s", (bounty_id,))
    return _bounty_row(row) if row else None


def get_all_bounties(status: str = "", category: str = "", limit: int = 200) -> list[dict]:
    clauses, params = [], []
    if status:
        clauses.append("status = %s")
        params.append(status)
    if category:
        clauses.append("category ILIKE %s")
        params.append(category)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    rows = fetch_all_in_schema(
        SCHEMA,
        f"""SELECT * FROM bounties {where}
            ORDER BY
                CASE WHEN status = 'open' THEN 0
                     WHEN status = 'submitted' THEN 1
                     ELSE 2 END,
                created_at DESC
            LIMIT %s""",
        tuple(params),
    )
    return [_bounty_row(r) for r in rows]


def update_bounty(bounty_id: str, updates: dict) -> bool:
    allowed = {
        "title", "description", "value_cents", "category", "status",
        "submitted_by", "submitted_at", "submission_note",
        "reviewed_by", "reviewed_at", "review_note", "expires_at",
    }
    sets, vals = [], []
    for key, val in updates.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        vals.append(val)
    if not sets:
        return False
    sets.append("updated_at = %s")
    vals.append(_now())
    vals.append(bounty_id)
    return execute_in_schema(
        SCHEMA, f"UPDATE bounties SET {', '.join(sets)} WHERE id = %s", tuple(vals)
    ) > 0


def delete_bounty(bounty_id: str, by: str = "") -> bool:
    bounty = get_bounty(bounty_id)
    ok = execute_in_schema(SCHEMA, "DELETE FROM bounties WHERE id = %s", (bounty_id,)) > 0
    if ok and bounty:
        digest_record(app_id="bounties", entity_type="bounty", action="deleted",
                      entity_id=bounty_id, record=bounty, by=by)
    return ok


def set_template_cooldown(tpl_id: str, recurrence_days: int) -> bool:
    """Set next_generate_at = now + recurrence_days on a template."""
    return execute_in_schema(
        SCHEMA,
        "UPDATE bounty_templates SET next_generate_at = now() + interval '1 day' * %s, updated_at = %s WHERE id = %s",
        (recurrence_days, _now(), tpl_id),
    ) > 0


def get_due_templates() -> list[dict]:
    """Return active templates where next_generate_at <= now and no open bounty exists."""
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT t.* FROM bounty_templates t
           WHERE t.is_active = TRUE
             AND t.next_generate_at IS NOT NULL
             AND t.next_generate_at <= now()
             AND NOT EXISTS (
                 SELECT 1 FROM bounties b
                 WHERE b.template_id = t.id AND b.status IN ('open', 'submitted')
             )
           ORDER BY t.next_generate_at""",
    )
    return [_template_row(r) for r in rows]


def get_open_bounties() -> list[dict]:
    """Return all open bounties (for digest and board view)."""
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM bounties WHERE status = 'open' ORDER BY value_cents DESC, created_at DESC",
    )
    return [_bounty_row(r) for r in rows]


def get_submitted_bounties() -> list[dict]:
    """Return all bounties awaiting approval."""
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM bounties WHERE status = 'submitted' ORDER BY submitted_at DESC",
    )
    return [_bounty_row(r) for r in rows]


def get_recent_approved(days: int = 7, limit: int = 5) -> list[dict]:
    """Recent approved bounties for digest."""
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT * FROM bounties
           WHERE status = 'approved'
             AND reviewed_at >= now() - interval '%s days'
           ORDER BY reviewed_at DESC
           LIMIT %s""",
        (days, limit),
    )
    return [_bounty_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------

def get_balance(user_id: str) -> dict:
    row = fetch_one_in_schema(
        SCHEMA, "SELECT * FROM bounty_balances WHERE user_id = %s", (user_id,)
    )
    if row:
        return _balance_row(row)
    return {
        "user_id": user_id,
        "balance_cents": 0,
        "lifetime_earned_cents": 0,
        "lifetime_paid_out_cents": 0,
        "updated_at": "",
    }


def get_all_balances() -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA, "SELECT * FROM bounty_balances ORDER BY balance_cents DESC"
    )
    return [_balance_row(r) for r in rows]


def _ensure_balance(user_id: str) -> None:
    """Create balance row if it doesn't exist."""
    execute_in_schema(
        SCHEMA,
        """INSERT INTO bounty_balances (user_id, balance_cents, lifetime_earned_cents,
                                         lifetime_paid_out_cents, updated_at)
           VALUES (%s, 0, 0, 0, %s)
           ON CONFLICT (user_id) DO NOTHING""",
        (user_id, _now()),
    )


def credit_balance(user_id: str, amount_cents: int, bounty_id: str = "",
                   note: str = "", created_by: str = "system") -> dict:
    """Credit a user's balance (bounty approved). Returns the transaction."""
    _ensure_balance(user_id)
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE bounty_balances
                   SET balance_cents = balance_cents + %s,
                       lifetime_earned_cents = lifetime_earned_cents + %s,
                       updated_at = %s
                   WHERE user_id = %s
                   RETURNING balance_cents""",
                (amount_cents, amount_cents, _now(), user_id),
            )
            new_balance = cur.fetchone()[0]

            txn_id = _gen_id("btx")
            cur.execute(
                """INSERT INTO bounty_transactions
                   (id, user_id, type, amount_cents, balance_after_cents,
                    bounty_id, note, created_by, created_at)
                   VALUES (%s, %s, 'credit', %s, %s, %s, %s, %s, %s)""",
                (txn_id, user_id, amount_cents, new_balance,
                 bounty_id or None, note, created_by, _now()),
            )
        conn.commit()

    return {
        "id": txn_id, "user_id": user_id, "type": "credit",
        "amount_cents": amount_cents, "balance_after_cents": new_balance,
        "bounty_id": bounty_id, "note": note,
    }


def debit_payment(user_id: str, amount_cents: int, payment_method: str = "",
                  note: str = "", created_by: str = "") -> dict:
    """Record an external payment (debit). amount_cents should be positive."""
    _ensure_balance(user_id)
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE bounty_balances
                   SET balance_cents = balance_cents - %s,
                       lifetime_paid_out_cents = lifetime_paid_out_cents + %s,
                       updated_at = %s
                   WHERE user_id = %s
                   RETURNING balance_cents""",
                (amount_cents, amount_cents, _now(), user_id),
            )
            new_balance = cur.fetchone()[0]

            txn_id = _gen_id("btx")
            cur.execute(
                """INSERT INTO bounty_transactions
                   (id, user_id, type, amount_cents, balance_after_cents,
                    payment_method, note, created_by, created_at)
                   VALUES (%s, %s, 'debit_payment', %s, %s, %s, %s, %s, %s)""",
                (txn_id, user_id, -amount_cents, new_balance,
                 payment_method or None, note, created_by, _now()),
            )
        conn.commit()

    return {
        "id": txn_id, "user_id": user_id, "type": "debit_payment",
        "amount_cents": -amount_cents, "balance_after_cents": new_balance,
        "payment_method": payment_method, "note": note,
    }


def adjust_balance(user_id: str, amount_cents: int, note: str = "",
                   created_by: str = "") -> dict:
    """Manual adjustment (positive or negative)."""
    _ensure_balance(user_id)
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE bounty_balances
                   SET balance_cents = balance_cents + %s,
                       updated_at = %s
                   WHERE user_id = %s
                   RETURNING balance_cents""",
                (amount_cents, _now(), user_id),
            )
            new_balance = cur.fetchone()[0]

            txn_id = _gen_id("btx")
            cur.execute(
                """INSERT INTO bounty_transactions
                   (id, user_id, type, amount_cents, balance_after_cents,
                    note, created_by, created_at)
                   VALUES (%s, %s, 'adjustment', %s, %s, %s, %s, %s)""",
                (txn_id, user_id, amount_cents, new_balance,
                 note, created_by, _now()),
            )
        conn.commit()

    return {
        "id": txn_id, "user_id": user_id, "type": "adjustment",
        "amount_cents": amount_cents, "balance_after_cents": new_balance,
        "note": note,
    }


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def get_transactions(user_id: str, limit: int = 50) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM bounty_transactions WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
        (user_id, limit),
    )
    return [_txn_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

def get_all_categories() -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA, "SELECT * FROM bounty_categories ORDER BY sort_order, name"
    )
    return [_category_row(r) for r in rows]


def create_category(name: str, icon: str = "") -> dict | None:
    cat_id = _gen_id("bcat")
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO bounty_categories (id, name, icon, sort_order)
           VALUES (%s, %s, %s, COALESCE((SELECT MAX(sort_order)+1 FROM bounty_categories), 0))
           RETURNING *""",
        (cat_id, name, icon),
    )
    return _category_row(row) if row else None


def delete_category(cat_id: str) -> bool:
    return execute_in_schema(SCHEMA, "DELETE FROM bounty_categories WHERE id = %s", (cat_id,)) > 0


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def get_config() -> dict:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM bounty_config WHERE id = 1")
    if row:
        return {
            "min_payout_cents": row.get("min_payout_cents", 2000),
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
        }
    return {"min_payout_cents": 2000, "updated_at": ""}


def update_config(updates: dict) -> bool:
    allowed = {"min_payout_cents"}
    sets, vals = [], []
    for key, val in updates.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        vals.append(val)
    if not sets:
        return False
    sets.append("updated_at = %s")
    vals.append(_now())
    return execute_in_schema(
        SCHEMA, f"UPDATE bounty_config SET {', '.join(sets)} WHERE id = 1", tuple(vals)
    ) > 0


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def get_leaderboard(period: str = "all") -> list[dict]:
    """Return leaderboard data. period: 'all', 'month', 'week'."""
    if period == "month":
        rows = fetch_all_in_schema(
            SCHEMA,
            """SELECT submitted_by AS user_id,
                      COUNT(*) AS bounties_completed,
                      SUM(value_cents) AS total_earned_cents,
                      MAX(reviewed_at) AS last_completed_at
               FROM bounties
               WHERE status = 'approved'
                 AND reviewed_at >= date_trunc('month', CURRENT_DATE)
               GROUP BY submitted_by
               ORDER BY total_earned_cents DESC, last_completed_at DESC""",
        )
    elif period == "week":
        rows = fetch_all_in_schema(
            SCHEMA,
            """SELECT submitted_by AS user_id,
                      COUNT(*) AS bounties_completed,
                      SUM(value_cents) AS total_earned_cents,
                      MAX(reviewed_at) AS last_completed_at
               FROM bounties
               WHERE status = 'approved'
                 AND reviewed_at >= date_trunc('week', CURRENT_DATE)
               GROUP BY submitted_by
               ORDER BY total_earned_cents DESC, last_completed_at DESC""",
        )
    else:
        rows = fetch_all_in_schema(
            SCHEMA,
            """SELECT b.submitted_by AS user_id,
                      COUNT(*) AS bounties_completed,
                      bal.lifetime_earned_cents AS total_earned_cents,
                      bal.balance_cents,
                      MAX(b.reviewed_at) AS last_completed_at
               FROM bounties b
               JOIN bounty_balances bal ON bal.user_id = b.submitted_by
               WHERE b.status = 'approved'
               GROUP BY b.submitted_by, bal.lifetime_earned_cents, bal.balance_cents
               ORDER BY bal.lifetime_earned_cents DESC, MAX(b.reviewed_at) DESC""",
        )
    result = []
    for r in rows:
        entry = {
            "user_id": r.get("user_id") or "",
            "bounties_completed": r.get("bounties_completed", 0),
            "total_earned_cents": r.get("total_earned_cents", 0),
        }
        if "balance_cents" in r:
            entry["balance_cents"] = r["balance_cents"]
        result.append(entry)
    return result
