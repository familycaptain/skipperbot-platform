"""Live mission-control projection (EVOLVE.md §9) — what the engine is doing, now.

Two tables (migration 004): `run` is one row per process-instance (the list + current
status/agent); `activity` is an append-only event stream (the per-agent scrolling log).
Box 1 is the only writer (service principal); the Evolve app polls these for the live
view. This is a display projection — discardable, never the source of truth.
"""
from app_platform.db import (execute_in_schema, fetch_all_in_schema,
                             fetch_one_in_schema)

SCHEMA = "app_evolve"


def upsert_run(instance_id: str, *, title: str = "", source: str = "", phase: str = "",
               status: str = "", current_agent: str = "", current_node: str = "",
               cost_usd: float | None = None) -> None:
    """Create/refresh the run row. Empty string fields are treated as 'leave unchanged'
    on update (COALESCE-by-NULLIF) so a progress ping needn't resend the title etc.
    cost_usd (when given) is the run's cumulative spend; None leaves it unchanged."""
    execute_in_schema(SCHEMA, """
        INSERT INTO run (instance_id, title, source, phase, status, current_agent, current_node, cost_usd)
        VALUES (%s, %s, %s, COALESCE(NULLIF(%s,''),''), COALESCE(NULLIF(%s,''),'running'), %s, %s, COALESCE(%s,0))
        ON CONFLICT (instance_id) DO UPDATE SET
            title         = COALESCE(NULLIF(EXCLUDED.title,''), run.title),
            source        = COALESCE(NULLIF(EXCLUDED.source,''), run.source),
            phase         = COALESCE(NULLIF(EXCLUDED.phase,''), run.phase),
            status        = COALESCE(NULLIF(EXCLUDED.status,''), run.status),
            current_agent = EXCLUDED.current_agent,
            current_node  = COALESCE(NULLIF(EXCLUDED.current_node,''), run.current_node),
            cost_usd      = COALESCE(%s, run.cost_usd),
            updated_at    = now()
    """, (instance_id, title[:200], source[:80], phase, status, current_agent[:60],
          current_node[:60], cost_usd, cost_usd))


def add_events(instance_id: str, events: list[dict]) -> int:
    """Append a batch of activity events: each {agent, kind, message}. Also bumps the
    run's current_agent/updated_at to the last event so the list stays live."""
    n = 0
    for e in events:
        execute_in_schema(SCHEMA, """
            INSERT INTO activity (instance_id, agent, kind, message)
            VALUES (%s, %s, %s, %s)
        """, (instance_id, (e.get("agent") or "")[:60], (e.get("kind") or "info")[:20],
              (e.get("message") or "")[:20000]))   # never clip agent output (TEXT col); high safety bound only
        n += 1
    if events:
        last = events[-1]
        execute_in_schema(SCHEMA,
            "UPDATE run SET current_agent = %s, updated_at = now() WHERE instance_id = %s",
            ((last.get("agent") or "")[:60], instance_id))
    return n


def list_runs(limit: int = 50, archived: bool = False) -> list[dict]:
    """Runs, most-recently-active first (active ones float up). Archived rows are hidden by
    default; pass archived=True for the archived view."""
    return fetch_all_in_schema(SCHEMA, """
        SELECT instance_id, title, source, phase, status, current_agent, current_node,
               archived, cost_usd, created_at, updated_at
        FROM run
        WHERE archived = %s
        ORDER BY (status IN ('running','building')) DESC, updated_at DESC
        LIMIT %s
    """, (archived, limit))


def total_cost() -> float:
    """Cumulative Evolve spend across ALL runs (the running total shown at the top)."""
    rows = fetch_all_in_schema(SCHEMA, "SELECT COALESCE(SUM(cost_usd),0) AS t FROM run", ())
    return round(float(rows[0]["t"]) if rows else 0.0, 4)


def set_archived(instance_id: str, archived: bool) -> int:
    """Archive (hide from the default list) or unarchive a run. The record is kept."""
    return execute_in_schema(SCHEMA,
                             "UPDATE run SET archived = %s WHERE instance_id = %s",
                             (archived, instance_id))


def get_run(instance_id: str) -> dict | None:
    return fetch_one_in_schema(SCHEMA, "SELECT * FROM run WHERE instance_id = %s",
                               (instance_id,))


def events(instance_id: str, since_id: int = 0, limit: int = 500) -> list[dict]:
    """Events newer than `since_id` (for the UI to tail). Ascending, so append-in-order."""
    return fetch_all_in_schema(SCHEMA, """
        SELECT id, agent, kind, message, ts FROM activity
        WHERE instance_id = %s AND id > %s
        ORDER BY id ASC LIMIT %s
    """, (instance_id, since_id, limit))
