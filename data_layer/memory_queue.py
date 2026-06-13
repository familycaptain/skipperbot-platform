"""Data layer for memory_ingestion_queue.

Provides enqueue, dequeue_batch, and status helpers used by
memory sources (chat.py, app_platform/memory.py) and the
memory thinking domain worker (domain_memory.py).
"""

import json
import uuid

import psycopg2.extras

from data_layer.db import get_conn, fetch_one, execute

MAX_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

def enqueue(
    source_type: str,
    payload: dict,
    entity_key: str | None = None,
) -> str:
    """Insert a new item into the memory ingestion queue.

    If entity_key is provided and a pending item with the same key already
    exists, the payload is updated in-place (last-write wins). This prevents
    a rapid burst of updates to the same entity from stacking up duplicate
    digestion jobs — only the latest state is digested.

    Args:
        source_type:  'chat_turn' or 'app_record'
        payload:      The data dict to persist (will be JSON-serialised).
        entity_key:   Optional dedup key e.g. 'app:meals:ml-abc123:updated'

    Returns:
        The queue item id (mq-*).
    """
    item_id = f"mq-{uuid.uuid4().hex[:8]}"

    with get_conn() as conn:
        with conn.cursor() as cur:
            if entity_key:
                cur.execute(
                    """
                    INSERT INTO memory_ingestion_queue
                        (id, source_type, payload, entity_key, status, created_at)
                    VALUES (%s, %s, %s, %s, 'pending', now())
                    ON CONFLICT (entity_key)
                        WHERE entity_key IS NOT NULL AND status = 'pending'
                    DO UPDATE SET
                        payload    = EXCLUDED.payload,
                        created_at = now()
                    RETURNING id
                    """,
                    (item_id, source_type,
                     psycopg2.extras.Json(payload), entity_key),
                )
                row = cur.fetchone()
                if row:
                    item_id = row[0]
            else:
                cur.execute(
                    """
                    INSERT INTO memory_ingestion_queue
                        (id, source_type, payload, entity_key, status, created_at)
                    VALUES (%s, %s, %s, NULL, 'pending', now())
                    """,
                    (item_id, source_type, psycopg2.extras.Json(payload)),
                )
        conn.commit()

    return item_id


# ---------------------------------------------------------------------------
# Dequeue
# ---------------------------------------------------------------------------

def dequeue_batch(limit: int = 10) -> list[dict]:
    """Atomically claim a batch of pending items for processing.

    Uses SELECT ... FOR UPDATE SKIP LOCKED so multiple workers cannot
    claim the same item. Transitions claimed items to 'processing' and
    increments their attempt counter.

    Returns a list of item dicts ready for the domain worker to process.
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE memory_ingestion_queue
                SET status = 'processing', attempts = attempts + 1
                WHERE id IN (
                    SELECT id
                    FROM   memory_ingestion_queue
                    WHERE  status = 'pending'
                    ORDER  BY created_at
                    LIMIT  %s
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, source_type, payload, attempts, entity_key
                """,
                (limit,),
            )
            rows = cur.fetchall()
        conn.commit()

    result = []
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        result.append({
            "id":          row["id"],
            "source_type": row["source_type"],
            "payload":     payload,
            "attempts":    row["attempts"],
            "entity_key":  row["entity_key"],
        })
    return result


# ---------------------------------------------------------------------------
# Status updates
# ---------------------------------------------------------------------------

def mark_done(item_id: str) -> None:
    """Mark a processed item as done."""
    execute(
        "UPDATE memory_ingestion_queue "
        "SET status = 'done', processed_at = now() "
        "WHERE id = %s",
        (item_id,),
    )


def mark_failed(item_id: str, error: str, attempts: int) -> None:
    """Mark an item as failed.

    If attempts < MAX_ATTEMPTS, reset to 'pending' for automatic retry.
    If exhausted, mark permanently 'failed'.
    """
    next_status = "failed" if attempts >= MAX_ATTEMPTS else "pending"
    execute(
        "UPDATE memory_ingestion_queue "
        "SET status = %s, error = %s "
        "WHERE id = %s",
        (next_status, error[:500], item_id),
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_pending_count() -> int:
    """Return the number of items currently in 'pending' state."""
    row = fetch_one(
        "SELECT COUNT(*) AS n FROM memory_ingestion_queue WHERE status = 'pending'"
    )
    return int(row["n"]) if row else 0


def reset_stale_processing(stale_minutes: int = 10) -> int:
    """Reset 'processing' items stuck for too long back to 'pending'.

    Guards against items frozen in 'processing' after a server restart
    mid-cycle. Called once at the start of each domain cycle.

    The partial unique index ``idx_miq_entity_key`` allows only ONE 'pending' row
    per entity_key. So a stale 'processing' row whose entity already has a fresh
    'pending' row (or a newer stale 'processing' row) cannot simply be flipped to
    'pending' — that would violate the index and crash the whole cycle. Drop those
    superseded rows first (the surviving row already represents the work), then
    reset the rest. Rows with a NULL entity_key are exempt from the index and
    always reset safely.
    """
    # Remove stale 'processing' rows superseded by a same-entity 'pending' row or
    # a newer same-entity 'processing' row, so the reset below cannot collide.
    execute(
        "DELETE FROM memory_ingestion_queue mq "
        "WHERE mq.status = 'processing' "
        "  AND mq.created_at < now() - make_interval(mins => %s) "
        "  AND mq.entity_key IS NOT NULL "
        "  AND EXISTS (SELECT 1 FROM memory_ingestion_queue o "
        "              WHERE o.entity_key = mq.entity_key AND o.id <> mq.id "
        "                AND (o.status = 'pending' "
        "                     OR (o.status = 'processing' AND o.created_at > mq.created_at)))",
        (stale_minutes,),
    )
    # Reset the remaining (now collision-free) stale 'processing' rows.
    return execute(
        "UPDATE memory_ingestion_queue "
        "SET status = 'pending' "
        "WHERE status = 'processing' "
        "  AND created_at < now() - make_interval(mins => %s)",
        (stale_minutes,),
    )
