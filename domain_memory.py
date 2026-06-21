"""
Memory Thinking Domain
======================
Drains the memory_ingestion_queue in batches, delegating each item to the
appropriate digester (chat_digest or app_platform.memory).

Observe → act contract (no LLM reasoning at the domain level):
  - OBSERVE: count pending items, reset any stale 'processing' rows
  - ACT:     dequeue a batch, process each item, mark done/failed
  - REPORT:  return result dict to the thinking scheduler

The domain never calls an LLM itself — it delegates to:
  - chat_digest.digest_turn()         for source_type='chat_turn'
  - app_platform.memory._run_digest() for source_type='app_record'

These digesters handle their own LLM calls using DUMB_MODEL.

Runs 24/7 on the thinking scheduler. Returns next_check_seconds=5 when
the queue still has items (scheduler MIN_SLEEP_SECONDS clamps this to 30),
and next_check_seconds=30 when idle.
"""

import asyncio

from config import logger

BATCH_SIZE = 10          # items processed per domain cycle
STALE_MINUTES = 10       # 'processing' items older than this are reset to 'pending'


# ---------------------------------------------------------------------------
# Domain handler (observe → act)
# ---------------------------------------------------------------------------

async def memory_domain_handler(domain: dict, budget_status: dict) -> dict:
    """Run one memory ingestion cycle.

    Called by the thinking scheduler on its timer loop.
    Returns a result dict following the standard domain contract.
    """
    from data_layer import memory_queue as _mq
    from data_layer.skipper_state import upsert_focus

    # --- Reset stale 'processing' items from any previous crash/restart ---
    stale = await asyncio.to_thread(_mq.reset_stale_processing, STALE_MINUTES)
    if stale:
        logger.info("MEMORY_DOMAIN: Reset %d stale processing item(s) to pending", stale)

    # --- OBSERVE: how many items are waiting? ---
    pending = await asyncio.to_thread(_mq.get_pending_count)

    if pending == 0:
        await asyncio.to_thread(
            upsert_focus, "memory", "queue", "queue",
            "Memory ingestion queue is empty — idle.",
        )
        return {
            "trigger":           "timer",
            "input_summary":     "Queue empty — nothing to process.",
            "context_snapshot":  {"pending": 0},
            "reasoning":         "No items in the memory ingestion queue.",
            "actions_taken":     [],
            "memories_extracted": [],
            "model_used":        "skip",
            "tokens_used":       0,
            "next_check_seconds": 30,
        }

    # --- Update focus so the Mind tab shows current activity ---
    await asyncio.to_thread(
        upsert_focus, "memory", "queue", "queue",
        f"Processing memory ingestion queue — {pending} item(s) pending.",
    )

    # --- ACT: claim and process a batch ---
    items = await asyncio.to_thread(_mq.dequeue_batch, BATCH_SIZE)

    actions = []
    total_facts = 0

    for item in items:
        item_id     = item["id"]
        source_type = item["source_type"]
        payload     = item["payload"]
        attempts    = item["attempts"]

        try:
            facts = await asyncio.to_thread(
                _process_item, source_type, payload
            )
            await asyncio.to_thread(_mq.mark_done, item_id)
            total_facts += facts
            actions.append({
                "type":        "processed",
                "item_id":     item_id,
                "source_type": source_type,
                "facts":       facts,
            })
            logger.debug("MEMORY_DOMAIN: %s processed → %d fact(s)", item_id, facts)
        except Exception as exc:
            logger.error("MEMORY_DOMAIN: Failed %s: %s", item_id, exc)
            await asyncio.to_thread(_mq.mark_failed, item_id, str(exc), attempts)
            actions.append({
                "type":        "failed",
                "item_id":     item_id,
                "source_type": source_type,
                "error":       str(exc)[:200],
            })

    remaining = await asyncio.to_thread(_mq.get_pending_count)

    # Update focus with outcome
    await asyncio.to_thread(
        upsert_focus, "memory", "queue", "queue",
        f"Processed {len(items)} item(s), extracted {total_facts} fact(s). "
        f"{remaining} item(s) remaining in queue.",
    )

    return {
        "trigger":      "timer",
        "input_summary": (
            f"Processed {len(items)} item(s) from memory ingestion queue "
            f"({pending} were pending, {remaining} still pending)."
        ),
        "context_snapshot": {
            "pending_before": pending,
            "processed":      len(items),
            "pending_after":  remaining,
            "facts_extracted": total_facts,
        },
        "reasoning": (
            f"Drained {len(items)} item(s) from the memory ingestion queue. "
            f"Extracted {total_facts} total fact(s)."
        ),
        "actions_taken":     actions,
        "memories_extracted": [],   # saved directly by digesters
        "model_used":        "cheap" if actions else "skip",
        "tokens_used":       0,     # tracked inside each digester, not here
        "digest_reasoning":  False, # "Drained N items…" is operational status, never a memory
        "next_check_seconds": 5 if remaining > 0 else 30,
    }


# ---------------------------------------------------------------------------
# Item processor — routes by source_type to the appropriate digester
# ---------------------------------------------------------------------------

def _process_item(source_type: str, payload: dict) -> int:
    """Process one queue item synchronously. Returns number of facts saved.

    Called via asyncio.to_thread so it is safe to do blocking I/O here.
    """
    if source_type == "chat_turn":
        return _process_chat_turn(payload)
    elif source_type == "app_record":
        return _process_app_record(payload)
    else:
        raise ValueError(f"Unknown source_type: {source_type!r}")


def _process_chat_turn(payload: dict) -> int:
    """Delegate to chat_digest.digest_turn(). Returns number of memories saved."""
    from chat_digest import digest_turn
    memories = digest_turn(
        user_message=payload.get("user_message", ""),
        assistant_response=payload.get("assistant_response", ""),
        user_id=payload.get("user_id", ""),
        turn_id=payload.get("turn_id", ""),
    )
    return len(memories) if memories else 0


def _process_app_record(payload: dict) -> int:
    """Delegate to app_platform.memory._run_digest(). Returns 0 (saves directly)."""
    action = payload.get("action", "")

    if action == "deleted":
        # Deletions skip the LLM — write a single direct memory
        from app_platform.memory import _write_delete_memory
        _write_delete_memory(
            app_id=payload.get("app_id", ""),
            entity_type=payload.get("entity_type", ""),
            entity_id=payload.get("entity_id", ""),
            record=payload.get("record", {}),
            by=payload.get("by", ""),
        )
        return 1

    from app_platform.memory import _run_digest
    _run_digest(
        app_id=payload.get("app_id", ""),
        entity_type=payload.get("entity_type", ""),
        action=action,
        entity_id=payload.get("entity_id", ""),
        record=payload.get("record", {}),
        by=payload.get("by", ""),
        context_hint=payload.get("context_hint", ""),
    )
    return 0   # _run_digest saves its own memories and doesn't return a count
