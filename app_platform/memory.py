"""App Memory Integration
=========================
Standard interface for app packages to generate memories from record CRUD
operations. Extracts meaningful facts using DUMB_MODEL and saves them as
searchable memories in the shared memory store.

**Pattern for app data.py files:**

    from app_platform.memory import digest_record

    _MEAL_HINT = (
        "Focus on: meal name, cuisine type, effort level (low/medium/high), "
        "tags, rating (1-5), and any notable notes about the meal."
    )

    def create_meal(meal_id, name, created_by, ...) -> dict:
        row = execute_returning_in_schema(...)
        meal = _meal_row(row)
        if meal:
            digest_record(
                app_id="meals",
                entity_type="meal",
                action="created",
                entity_id=meal["id"],
                record=meal,
                by=created_by,
                context_hint=_MEAL_HINT,
            )
        return meal

    def delete_meal(meal_id: str, by: str = "") -> bool:
        meal = get_meal(meal_id)          # fetch BEFORE deleting
        n = execute_in_schema(SCHEMA, "DELETE FROM meals WHERE id=%s", (meal_id,))
        if n > 0 and meal:
            digest_record(app_id="meals", entity_type="meal", action="deleted",
                          entity_id=meal_id, record=meal, by=by)
        return n > 0

**Rules:**
- Call AFTER a successful DB write (so IDs and timestamps exist)
- For deletes, fetch the record first, delete, then call with action="deleted"
- create/update/completed → LLM extraction in background thread
- deleted → single direct memory, no LLM (synchronous, fast)
- Never raises — all errors are logged and swallowed
"""

import json
import logging
import re
import threading
from datetime import date

logger = logging.getLogger("platform.memory")

# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a memory extraction assistant for a family AI assistant named Skipper.
Given a data record from one of Skipper's apps, extract key facts worth
remembering for future conversations. Facts are stored in a semantic memory
database and retrieved when the user asks questions about family data.

Rules:
- Extract concise, self-contained facts useful to recall in future conversations
- Include the record's name or title prominently in each fact
- Focus on specific meaningful values: names, categories, tags, ratings,
  frequencies, people, dates, locations, notes
- Skip bare internal fields (raw IDs, empty strings, null values)
- If action is "updated", focus on the current (new) state of the record
- If action is "completed", include when it was done and by whom if available
- Each fact should be short — 1-2 sentences maximum
- Return empty array [] if the record has nothing meaningful worth remembering

Respond ONLY with a JSON array of objects, each with:
- "fact": the concise factual statement (include the entity name in the fact text)
- "tags": array of 2-4 lowercase keyword tags for retrieval
- "about": the ENTITY ID provided in the prompt (e.g. "ml-abc12345") — always use
  the exact ID so memories can be looked up by entity later

Example:
[
  {"fact": "Tacos Al Pastor is a Mexican meal rated 5/5 with medium effort.",
   "tags": ["tacos", "mexican", "dinner", "rating"],
   "about": "ml-abc12345"},
  {"fact": "Tacos Al Pastor is tagged quick, weeknight, and family-friendly.",
   "tags": ["tacos", "tags", "weeknight"],
   "about": "ml-abc12345"}
]
"""

# Internal metadata fields — stripped before sending to LLM to reduce noise
_SKIP_FIELDS = frozenset({
    "created_at",
    "updated_at",
    "recipe_doc_id",
    "sort_order",
})

# Volatile bookkeeping/sync-clock keys that must never reach a memory — stripped by
# NAME at ANY depth so a memory never contains a sync clock (issue #24). App-agnostic:
# the rule is purely key-name based (no app-specific block names like 'trello').
_VOLATILE_FIELDS = _SKIP_FIELDS | frozenset({
    "last_sync",
    "synced_at",
    "last_synced",
})


def _strip_for_digest(record: dict) -> dict:
    """Recursively drop volatile bookkeeping fields (by name) from a record before it is
    digested, so per-write sync clocks (e.g. a nested ``trello.last_sync``) can't churn
    memory. Returns a cleaned copy; empty/None pruning + the skip-trivial guard run after
    (in _run_digest), unchanged."""
    def _clean(value):
        if isinstance(value, dict):
            return {k: _clean(v) for k, v in value.items() if k not in _VOLATILE_FIELDS}
        if isinstance(value, list):
            return [_clean(v) for v in value]
        return value
    return _clean(record)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def digest_record(
    app_id: str,
    entity_type: str,
    action: str,
    entity_id: str,
    record: dict,
    by: str = "",
    context_hint: str = "",
    blocking: bool = False,
) -> None:
    """Extract facts from an app record and save as memories.

    Call this from app data.py after a successful CRUD operation.
    For create/update/completed: runs LLM extraction (background thread by default).
    For deleted: writes one direct memory synchronously (no LLM needed).

    Args:
        app_id:       App package ID (e.g. "meals", "home", "recipes").
        entity_type:  Human label (e.g. "meal", "home maintenance task").
        action:       "created", "updated", "deleted", "completed", etc.
        entity_id:    The entity's ID (e.g. "ml-abc123").
        record:       Full record dict as returned from the data layer.
        by:           Who performed the action (user_id or "system").
        context_hint: Optional extraction focus hint — what attributes matter
                      most for this entity type. Helps the LLM prioritize.
        blocking:     If True, run synchronously (no thread). Use for scripts
                      and backfill operations where you need to control rate.
    """
    if not record:
        return

    if blocking:
        # Direct execution path — used by tests and explicit callers.
        # Bypasses the queue entirely and runs synchronously.
        if action == "deleted":
            _write_delete_memory(app_id, entity_type, entity_id, record, by)
        else:
            _run_digest(app_id, entity_type, action, entity_id, record, by, context_hint)
        return

    # Post to the author's personal activity feed (fire-and-forget, no LLM).
    try:
        from app_platform.activity import log_activity
        log_activity(app_id, entity_type, action, entity_id, record, by)
    except Exception as exc:
        logger.warning("APP_MEMORY[%s]: activity log failed for %s: %s", app_id, entity_id, exc)

    # Normal path: enqueue to the durable memory ingestion queue.
    # The memory thinking domain will process this within ~30 seconds.
    try:
        from data_layer.memory_queue import enqueue as _enqueue
        entity_key = (
            f"app:{app_id}:{entity_id}:{action}"
            if action not in ("created", "deleted")
            else None
        )
        _enqueue(
            source_type="app_record",
            payload={
                "app_id":       app_id,
                "entity_type":  entity_type,
                "action":       action,
                "entity_id":    entity_id,
                "record":       record,
                "by":           by,
                "context_hint": context_hint,
            },
            entity_key=entity_key,
        )
    except Exception as exc:
        # Fallback: if queue is unavailable, run in background thread
        logger.warning(
            "APP_MEMORY[%s]: Queue unavailable for %s, falling back to thread: %s",
            app_id, entity_id, exc,
        )
        threading.Thread(
            target=_background_digest,
            args=(app_id, entity_type, action, entity_id, record, by, context_hint),
            daemon=True,
        ).start()


# ---------------------------------------------------------------------------
# Delete path — synchronous, no LLM
# ---------------------------------------------------------------------------

def _write_delete_memory(
    app_id: str,
    entity_type: str,
    entity_id: str,
    record: dict,
    by: str,
) -> None:
    """Write a single memory noting the deletion. Fast, no LLM needed."""
    try:
        name = (
            record.get("name")
            or record.get("title")
            or record.get("summary")
            or entity_id
        )
        content = (
            f"[deleted] {entity_type} '{name}' ({entity_id}) was removed "
            f"from the {app_id} app on {date.today().isoformat()}"
        )
        if by:
            content += f" by {by}"

        from memory_store import save_memory
        save_memory(
            content=content,
            tags=[app_id, entity_type, "deleted", "app_memory"],
            about=entity_id,
            saved_by=by or "system",
            related_entities=[entity_id],
        )
        logger.debug("APP_MEMORY[%s]: wrote delete memory for %s", app_id, entity_id)
    except Exception as exc:
        logger.error(
            "APP_MEMORY[%s]: delete memory failed for %s: %s", app_id, entity_id, exc
        )


# ---------------------------------------------------------------------------
# LLM extraction path — runs in a background thread
# ---------------------------------------------------------------------------

_ENTITY_RE = re.compile(r"\b([a-z]{1,5}-[0-9a-f]{8})\b")


def _background_digest(
    app_id: str,
    entity_type: str,
    action: str,
    entity_id: str,
    record: dict,
    by: str,
    context_hint: str,
) -> None:
    """Thread target — wraps _run_digest with full error isolation."""
    try:
        _run_digest(app_id, entity_type, action, entity_id, record, by, context_hint)
    except Exception as exc:
        logger.error(
            "APP_MEMORY[%s]: background digest failed for %s: %s",
            app_id,
            entity_id,
            exc,
        )


def _run_digest(
    app_id: str,
    entity_type: str,
    action: str,
    entity_id: str,
    record: dict,
    by: str,
    context_hint: str,
) -> None:
    """Core: build prompt → call LLM → parse facts → save memories."""
    # Strip volatile bookkeeping/sync-clock fields recursively (issue #24), THEN prune
    # empties — so a record whose only non-skip content was a sync clock falls below the
    # skip-trivial threshold and yields no memory.
    stripped = _strip_for_digest(record)
    clean = {
        k: v
        for k, v in stripped.items()
        if v is not None
        and v != ""
        and v != []
        and v != {}
    }

    # Skip records that have nothing meaningful beyond their ID
    meaningful = {k: v for k, v in clean.items() if k not in {"id", "created_by"}}
    if len(meaningful) < 2:
        logger.debug(
            "APP_MEMORY[%s]: skipping trivial record %s (%d meaningful fields)",
            app_id,
            entity_id,
            len(meaningful),
        )
        return

    record_text = json.dumps(clean, indent=2, default=str)

    prompt_lines = [
        f"APP: {app_id}",
        f"ENTITY TYPE: {entity_type}",
        f"ACTION: {action}",
        f"ENTITY ID: {entity_id}",
        f"DATE: {date.today().isoformat()}",
    ]
    if by:
        prompt_lines.append(f"BY: {by}")
    if context_hint:
        prompt_lines.append(f"EXTRACTION FOCUS: {context_hint}")
    prompt_lines.append(f"\nRECORD:\n{record_text}")

    user_prompt = "\n".join(prompt_lines)

    # Late import to avoid circular imports at module load time
    from config import openai_client, DUMB_MODEL

    try:
        completion = openai_client.chat.completions.create(
            model=DUMB_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=4000,
        )
        raw = (completion.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.error(
            "APP_MEMORY[%s]: LLM call failed for %s: %s", app_id, entity_id, exc
        )
        return

    if not raw:
        return

    # Strip markdown code fences if the model wrapped its output
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        facts = json.loads(raw)
        if not isinstance(facts, list):
            return
    except json.JSONDecodeError as exc:
        logger.error(
            "APP_MEMORY[%s]: JSON parse failed for %s: %s — raw: %s",
            app_id,
            entity_id,
            exc,
            raw[:200],
        )
        return

    if not facts:
        return

    from memory_store import save_memory

    saved = 0
    for item in facts:
        fact = item.get("fact", "").strip()
        if not fact:
            continue

        tags = item.get("tags", [])
        if not isinstance(tags, list):
            tags = []

        # Always stamp with: source marker, app, entity type, action
        for marker in ("app_memory", app_id, entity_type, action):
            if marker not in tags:
                tags.append(marker)

        about = entity_id  # always use entity_id so memories are retrievable by ID

        # Merge LLM-provided related entities with regex-extracted IDs from the fact
        llm_related = item.get("related_entities", [])
        if not isinstance(llm_related, list):
            llm_related = []
        regex_related = _ENTITY_RE.findall(fact)
        related = list(set(llm_related + regex_related + [entity_id]))

        save_memory(
            content=fact,
            tags=tags,
            about=about,
            saved_by=by or "system",
            related_entities=related,
        )
        saved += 1

    logger.info(
        "APP_MEMORY[%s]: saved %d fact(s) for %s %s (%s)",
        app_id,
        saved,
        action,
        entity_type,
        entity_id,
    )
