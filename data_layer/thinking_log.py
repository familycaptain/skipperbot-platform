"""
Data layer for thinking_log — audit trail of every thinking cycle.
"""

import uuid
import json
from datetime import datetime

import psycopg2

from app_platform.time import get_timezone
from data_layer.db import fetch_one, fetch_all, execute


def _new_id() -> str:
    # Full uuid4 hex (128-bit). Widened from hex[:8] (32-bit), whose birthday-paradox
    # collisions (~50% by ~77k rows) at production volume made log_cycle's INSERT raise a
    # duplicate-key error that marked SUCCESSFUL thinking cycles as failed. tl- ids are
    # opaque with no external joins, so longer ids are safe for new rows; existing short
    # ids remain valid (no migration).
    return f"tl-{uuid.uuid4().hex}"


def _row_to_dict(row) -> dict | None:
    if not row:
        return None
    d = dict(row)
    if isinstance(d.get("cycle_at"), datetime):
        d["cycle_at"] = d["cycle_at"].isoformat()
    return d


def log_cycle(
    domain: str,
    trigger: str,
    input_summary: str = "",
    context_snapshot: dict | None = None,
    reasoning: str = "",
    actions_taken: list | None = None,
    memories_extracted: list | None = None,
    model_used: str = "",
    tokens_used: int = 0,
) -> dict:
    """Record a thinking cycle to the log."""
    now = datetime.now(get_timezone())

    def _insert(row_id: str) -> None:
        execute("""
            INSERT INTO thinking_log
                (id, cycle_at, domain, trigger, input_summary, context_snapshot,
                 reasoning, actions_taken, memories_extracted, model_used, tokens_used)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s, %s)
        """, (
            row_id, now, domain, trigger, input_summary,
            json.dumps(context_snapshot or {}),
            reasoning,
            json.dumps(actions_taken or []),
            json.dumps(memories_extracted or []),
            model_used, tokens_used,
        ))

    log_id = _new_id()
    try:
        _insert(log_id)
    except psycopg2.errors.UniqueViolation:
        # A primary-key collision on the id must never surface as a FAILED cycle:
        # thinking_scheduler._run_cycle logs this success-path write inside the try whose
        # `except` records the cycle as failed and skips the digest bookkeeping. Regenerate
        # a fresh id and retry the INSERT exactly once via a new execute() (a clean pooled
        # connection — the first attempt's transaction was already rolled back). Catch ONLY
        # the unique-violation; any other DB error propagates so genuine failures still
        # surface. With 128-bit ids this retry is defense-in-depth that effectively never
        # fires. If the retry also collides, it raises (bounded — exactly one retry).
        log_id = _new_id()
        _insert(log_id)
    return get_log_entry(log_id)


def get_log_entry(log_id: str) -> dict | None:
    """Get a single log entry by ID."""
    row = fetch_one("SELECT * FROM thinking_log WHERE id = %s", (log_id,))
    return _row_to_dict(row)


def list_log_entries(
    domain: str | None = None,
    trigger: str | None = None,
    date: str | None = None,
    days: int = 1,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Query log entries with optional filters."""
    clauses = []
    params: list = []

    if domain:
        clauses.append("domain = %s")
        params.append(domain)
    if trigger:
        clauses.append("trigger = %s")
        params.append(trigger)
    if date:
        clauses.append("cycle_at::date = %s")
        params.append(date)
    elif days:
        clauses.append("cycle_at >= now() - interval '%s days'")
        params.append(days)

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.extend([limit, offset])

    rows = fetch_all(f"""
        SELECT * FROM thinking_log
        {where}
        ORDER BY cycle_at DESC
        LIMIT %s OFFSET %s
    """, tuple(params))
    return [_row_to_dict(r) for r in rows]


def get_today_usage_by_domain() -> list[dict]:
    """Get today's token usage grouped by domain."""
    rows = fetch_all("""
        SELECT
            domain,
            COALESCE(SUM(tokens_used), 0) as total_tokens,
            COUNT(*) as cycle_count
        FROM thinking_log
        WHERE cycle_at::date = CURRENT_DATE
        GROUP BY domain
        ORDER BY total_tokens DESC
    """)
    return [dict(r) for r in rows]


def get_today_token_usage(domain: str | None = None) -> dict:
    """Get today's token usage, optionally by domain."""
    domain_clause = ""
    params: list = []
    if domain:
        domain_clause = "AND domain = %s"
        params.append(domain)

    row = fetch_one(f"""
        SELECT
            COALESCE(SUM(tokens_used), 0) as total_tokens,
            COUNT(*) as cycle_count,
            COALESCE(SUM(CASE WHEN model_used = 'cheap' THEN tokens_used ELSE 0 END), 0) as cheap_tokens,
            COALESCE(SUM(CASE WHEN model_used = 'standard' THEN tokens_used ELSE 0 END), 0) as standard_tokens,
            COALESCE(SUM(CASE WHEN model_used = 'expensive' THEN tokens_used ELSE 0 END), 0) as expensive_tokens
        FROM thinking_log
        WHERE cycle_at::date = CURRENT_DATE
          {domain_clause}
    """, tuple(params))
    return dict(row) if row else {"total_tokens": 0, "cycle_count": 0}
